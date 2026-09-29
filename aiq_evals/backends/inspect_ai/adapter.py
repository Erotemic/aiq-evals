"""Inspect AI adapter using only the public evaluation and log APIs.

The adapter targets the public surface documented for Inspect 0.3.272. It is
experimental until the native phase-4 acceptance smokes are recorded. Native
imports remain lazy so core :mod:`aiq_evals` and published run readers do not
require Inspect.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

from aiq_evals.backends.inspect_ai.normalize import (
    native_log_model,
    native_log_task,
    native_log_task_args,
    normalize_inspect_logs,
)
from aiq_evals.contracts import (
    EvaluationRequest,
    EvaluationResult,
    ExecutionContext,
    ModelBinding,
    ResolvedEvaluation,
)
from aiq_evals.errors import (
    ArtifactError,
    EngineCompatibilityError,
    MissingDependencyError,
    RequestValidationError,
)
from aiq_evals.identity import adapter_source_digest, build_measurement_identity
from aiq_evals.jsonutil import normalize_json, sha256_file
from aiq_evals.probes.source import verify_engine_revision

# 0.2.0: native phase-1 fixes (worker registration, task paths, coverage of
# results-less logs, native log locations). adapter_source_sha256 also enters
# identity, so reuse never spans unversioned edits.
ADAPTER_VERSION = '0.2.0'
CANDIDATE_INSPECT_VERSION = '0.3.272'
_FULL_GIT_SHA = re.compile(r'^[0-9a-fA-F]{40}$')

_ALLOWED_ENGINE_OPTIONS = {
    'eval_options',
    'log_format',
    'registration_modules',
    'upstream_revision',
}
_PROTECTED_EVAL_OPTIONS = {
    'tasks',
    'model',
    'model_args',
    'model_roles',
    'task_args',
    'log_dir',
    'log_format',
    'display',
    'metadata',
    # JSON requests cannot safely serialize callbacks. aiq-evals owns the
    # task/run boundary and does not let callbacks enqueue hidden extra work.
    'sample_complete',
    'task_complete',
    'sample_abandoned',
}


def _distribution_version(module: Any | None = None) -> str | None:
    try:
        return importlib.metadata.version('inspect-ai')
    except importlib.metadata.PackageNotFoundError:
        value = getattr(module, '__version__', None) if module is not None else None
        return None if value is None else str(value)


def _native_symbols() -> tuple[Any, Any, Any, Any]:
    """Load the narrow public Inspect API used by this adapter."""
    try:
        api = importlib.import_module('inspect_ai')
        log_api = importlib.import_module('inspect_ai.log')
    except ImportError as ex:
        raise MissingDependencyError(
            'Inspect execution/import requires the optional inspect_ai runtime. '
            'Install aiq-evals[inspect] in the native worker; engine-free result '
            'reading does not require Inspect.'
        ) from ex
    eval_fn = getattr(api, 'eval', None)
    list_logs = getattr(log_api, 'list_eval_logs', None)
    read_log = getattr(log_api, 'read_eval_log', None)
    if not callable(eval_fn):
        raise EngineCompatibilityError('Inspect public inspect_ai.eval() is required')
    if not callable(list_logs) or not callable(read_log):
        raise EngineCompatibilityError(
            'Inspect public list_eval_logs()/read_eval_log() APIs are required'
        )
    return api, eval_fn, list_logs, read_log


def _qualify_model(binding: ModelBinding) -> str:
    model = binding.model
    provider = binding.provider
    if provider is None:
        return model
    prefix = provider + '/'
    if model.startswith(prefix):
        return model
    if '/' in model:
        raise RequestValidationError(
            f'Inspect model binding {binding.role!r} declares provider {provider!r} '
            f'but model is already qualified as {model!r}'
        )
    return prefix + model


def _import_python_task(reference: str) -> tuple[Any, dict[str, Any]]:
    """Resolve ``python:module:attribute`` to an Inspect task callable/class."""
    raw = reference[len('python:') :]
    module_name, sep, attribute = raw.partition(':')
    if not sep or not module_name or not attribute:
        raise RequestValidationError(
            'python task references must use python:package.module:attribute'
        )
    try:
        module = importlib.import_module(module_name)
    except Exception as ex:
        raise RequestValidationError(
            f'cannot import Inspect task module {module_name!r}: {ex}'
        ) from ex
    value: Any = module
    try:
        for part in attribute.split('.'):
            value = getattr(value, part)
    except AttributeError as ex:
        raise RequestValidationError(
            f'Inspect task reference {reference!r} does not resolve to {attribute!r}'
        ) from ex
    if not callable(value):
        raise RequestValidationError(
            f'Inspect task reference {reference!r} must resolve to a callable task factory/class'
        )
    facts: dict[str, Any] = {
        'task_reference_kind': 'python_factory',
        'task_python_module': module_name,
        'task_python_attribute': attribute,
    }
    source = getattr(module, '__file__', None)
    if source:
        path = Path(source).resolve()
        if path.is_file():
            facts['task_source_path'] = str(path)
            facts['task_source_sha256'] = sha256_file(path)
    return value, facts


def _resolve_task_reference(reference: str) -> dict[str, Any]:
    if reference.startswith('python:'):
        _value, facts = _import_python_task(reference)
        return facts

    facts: dict[str, Any] = {
        'task_reference_kind': 'inspect_native',
        'task_native_reference': reference,
    }
    # Inspect's documented file reference is ``file.py@task``. Hash a concrete
    # local task file when available; otherwise the request's explicit
    # task_revision remains the immutable identity source.
    file_part = reference.split('@', 1)[0]
    path = Path(file_part).expanduser()
    if path.suffix == '.py' and path.is_file():
        path = path.resolve()
        facts['task_source_path'] = str(path)
        facts['task_source_sha256'] = sha256_file(path)
    return facts


def _materialize_task_reference(reference: str) -> Any:
    if reference.startswith('python:'):
        value, _facts = _import_python_task(reference)
        return value
    if Path(reference).is_absolute() and Path(reference).is_file():
        # Inspect's public file loader passes this to Path.glob(), which
        # rejects absolute patterns on Python 3.11.
        return os.path.relpath(reference, Path.cwd())
    return reference


def _load_registration_modules(modules: list[str]) -> dict[str, str | None]:
    digests: dict[str, str | None] = {}
    for name in modules:
        try:
            module = importlib.import_module(name)
        except Exception as ex:
            raise RequestValidationError(f'cannot import Inspect registration module {name!r}: {ex}') from ex
        source = getattr(module, '__file__', None)
        path = Path(source).resolve() if source else None
        digests[name] = sha256_file(path) if path is not None and path.is_file() else None
    return digests


def _merge_native_config(request: EvaluationRequest) -> dict[str, Any]:
    options = dict(request.engine_options)
    unknown = set(options) - _ALLOWED_ENGINE_OPTIONS
    if unknown:
        raise RequestValidationError(
            f'unknown inspect_ai engine_options: {sorted(unknown)}; '
            f'allowed: {sorted(_ALLOWED_ENGINE_OPTIONS)}'
        )
    upstream_revision = options.get('upstream_revision')
    if upstream_revision is not None and not _FULL_GIT_SHA.fullmatch(str(upstream_revision)):
        raise RequestValidationError(
            'inspect_ai engine_options.upstream_revision must be a full 40-character git SHA'
        )
    log_format = str(options.get('log_format', 'eval'))
    if log_format not in {'eval', 'json'}:
        raise RequestValidationError("inspect_ai log_format must be 'eval' or 'json'")
    registration_modules = options.get('registration_modules', [])
    if not isinstance(registration_modules, list) or any(
        not isinstance(module, str) or not module.strip() for module in registration_modules
    ):
        raise RequestValidationError('inspect_ai registration_modules must be a list of importable module names')

    raw_eval_options = options.get('eval_options') or {}
    if not isinstance(raw_eval_options, Mapping):
        raise RequestValidationError('inspect_ai engine_options.eval_options must be an object')
    eval_options = dict(raw_eval_options)
    protected = set(eval_options) & _PROTECTED_EVAL_OPTIONS
    if protected:
        raise RequestValidationError(
            'Inspect eval options are owned by aiq-evals and cannot be overridden: '
            f'{sorted(protected)}'
        )
    for key, value in request.generation.items():
        if key in eval_options and eval_options[key] != value:
            raise RequestValidationError(
                f'conflicting Inspect generation/eval option {key!r}: '
                f'{value!r} vs {eval_options[key]!r}'
            )
        eval_options[key] = value
    # Normalization requires sample detail for trajectories. A caller may still
    # explicitly disable it, in which case aggregate results remain valid and
    # sample/trajectory access is simply unavailable.
    eval_options.setdefault('log_samples', True)

    primary = request.primary_model
    model_roles: dict[str, str] = {}
    for binding in request.models:
        if binding.role == 'primary':
            continue
        if binding.provider_options:
            raise RequestValidationError(
                'phase-4 Inspect auxiliary model roles support model/provider binding '
                'but not per-role provider_options; encode native role configuration '
                'inside the task until the public ModelRoles construction is covered '
                'by a native fixture'
            )
        model_roles[binding.role] = _qualify_model(binding)

    return {
        'task_reference': request.task,
        'task_args': dict(request.task_options),
        'model': _qualify_model(primary),
        'model_args': dict(primary.provider_options),
        'model_roles': model_roles,
        'eval_options': eval_options,
        'log_format': log_format,
        'registration_modules': registration_modules,
    }


def _coerce_logs(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _read_native_logs(source: Path, list_logs: Any, read_log: Any) -> list[Any]:
    if source.is_file():
        return [read_log(str(source))]
    if not source.is_dir():
        raise ArtifactError(f'Inspect native source does not exist: {source}')
    try:
        infos = list(list_logs(str(source), recursive=True))
    except TypeError:
        infos = list(list_logs(str(source)))
    logs = [read_log(info) for info in infos]
    return logs


def _validate_native_logs(
    resolved: ResolvedEvaluation,
    logs: Sequence[Any],
    result: EvaluationResult,
) -> EvaluationResult:
    expected_model = str(resolved.native_config['model'])
    models = sorted(
        {
            model
            for model in (native_log_model(log) for log in logs)
            if model not in (None, '')
        }
    )
    mismatched = [model for model in models if model != expected_model]
    if mismatched:
        raise ArtifactError(
            'Inspect native log model does not match the resolved request: '
            f'{mismatched} != {expected_model!r}'
        )

    expected_args = dict(resolved.request.task_options)
    for log in logs:
        native_args = native_log_task_args(log)
        if native_args is None:
            continue
        differing = {
            key: (value, native_args.get(key))
            for key, value in expected_args.items()
            if native_args.get(key) != value
        }
        if differing:
            raise ArtifactError(
                'Inspect native log task arguments do not match the resolved request: '
                f'{differing}'
            )

    diagnostics = dict(result.diagnostics)
    diagnostics['import_validation'] = {
        'expected_model': expected_model,
        'native_models': models,
        'model_verified': bool(models),
        'native_tasks': sorted(
            task for task in (native_log_task(log) for log in logs) if task is not None
        ),
        'task_args_checked': bool(expected_args),
        'revision_provenance': (
            'task/data/model revision tokens are caller-supplied identity inputs; '
            'Inspect logs preserve native task/package/revision facts separately'
        ),
    }
    return EvaluationResult(
        engine=result.engine,
        identity=result.identity,
        status=result.status,
        records=result.records,
        samples=result.samples,
        artifacts=result.artifacts,
        diagnostics=normalize_json(diagnostics),
    )


class InspectAIBackend:
    key = 'inspect_ai'
    adapter_version = ADAPTER_VERSION

    def capabilities(self) -> Mapping[str, Any]:
        return {
            'experimental': True,
            # Experimental until the phase-8 release gate; phase-1 native acceptance
            # passed only for the combinations in docs/planning/phase1-capabilities.md.
            'implementation_status': 'phase1-native-accepted',
            # Inspect's public evaluation entry point is synchronous. Running it
            # in an owned process gives aiq-evals hard cancellation semantics.
            'requires_worker_process': True,
            'capability_scope': 'request/task/model/solver combination; validate natively',
            'candidate_version': CANDIDATE_INSPECT_VERSION,
            'features': {
                'generation': {'implemented': True, 'native_verified': False},
                'agentic': {'implemented': True, 'native_verified': False},
                'tools': {'implemented': True, 'native_verified': False},
                'trajectories': {'implemented': True, 'native_verified': False},
                'native_import': {'implemented': True, 'native_verified': False},
                'model_roles': {'implemented': True, 'native_verified': False},
                'epochs': {'implemented': True, 'native_verified': False},
                'sandboxing': {'implemented': 'native-pass-through', 'native_verified': False},
                'native_resume': {'implemented': False, 'native_verified': False},
                'native_rescore': {'implemented': False, 'native_verified': False},
            },
        }

    def validate_request(self, request: EvaluationRequest) -> None:
        if request.engine != self.key:
            raise RequestValidationError(
                f'InspectAIBackend cannot handle engine {request.engine!r}'
            )
        _merge_native_config(request)
        # Validate the explicit importable-factory syntax without requiring the
        # Inspect package itself. Native Inspect string references are resolved by
        # Inspect in the preflight/runtime worker.
        if request.task.startswith('python:'):
            raw = request.task[len('python:') :]
            module_name, sep, attribute = raw.partition(':')
            if not sep or not module_name or not attribute:
                raise RequestValidationError(
                    'python task references must use python:package.module:attribute'
                )

    def resolve(self, request: EvaluationRequest) -> ResolvedEvaluation:
        self.validate_request(request)
        api, _eval_fn, _list_logs, _read_log = _native_symbols()
        native_config = _merge_native_config(request)
        registration_digests = _load_registration_modules(native_config['registration_modules'])
        task_facts = _resolve_task_reference(request.task)
        engine_version = _distribution_version(api)
        engine_revision, revision_facts, revision_reasons = verify_engine_revision(
            request.engine_options.get('upstream_revision'),
            module_file=getattr(sys.modules.get('inspect_ai'), '__file__', None),
            distribution='inspect-ai',
        )
        resolved_facts = {
            **revision_facts,
            **task_facts,
            'engine_version': engine_version,
            'engine_revision': engine_revision,
            'native_api': 'inspect_ai.eval + inspect_ai.log public APIs',
            'candidate_version': CANDIDATE_INSPECT_VERSION,
            'candidate_version_match': engine_version == CANDIDATE_INSPECT_VERSION,
            'registration_module_digests': registration_digests,
        }
        identity_facts = {
            'adapter_source_sha256': adapter_source_digest(__package__),
            'task_source_sha256': task_facts.get('task_source_sha256'),
            'registration_module_digests': registration_digests,
        }
        unhashed = sorted(name for name, digest in registration_digests.items() if digest is None)
        unknown_reasons = list(revision_reasons)
        if unhashed:
            unknown_reasons.append(f'registration modules have no hashable source: {unhashed}')
        if unknown_reasons:
            resolved_facts['identity_unknown_reasons'] = unknown_reasons
        identity = build_measurement_identity(
            request,
            adapter_version=self.adapter_version,
            engine_version=engine_version,
            native_config=native_config,
            resolved_facts=resolved_facts,
            identity_facts=identity_facts,
        )
        return ResolvedEvaluation(
            request=request,
            adapter_version=self.adapter_version,
            engine_version=engine_version,
            native_config=native_config,
            identity=identity,
            resolved_facts=resolved_facts,
        )

    def execute_blocking(
        self,
        resolved: ResolvedEvaluation,
        context: ExecutionContext,
    ) -> EvaluationResult:
        """Run Inspect's synchronous public ``eval()`` on the calling thread.

        The owned worker calls this on its main thread so that the runner's
        cancellation SIGINT reaches Inspect's own interruption handling, which
        cleans up sandboxes and writes a ``cancelled`` log.
        """
        _api, eval_fn, list_logs, read_log = _native_symbols()
        if context.env:
            raise RequestValidationError(
                'Inspect execution must run in an owned worker process when '
                'ExecutionContext.env is used; process-global environment mutation '
                'is intentionally not performed in the adapter'
            )
        native_root = context.output_dir / 'native' / 'inspect_ai'
        log_dir = native_root / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        config = dict(resolved.native_config)
        _load_registration_modules(list(config.get('registration_modules') or []))
        task = _materialize_task_reference(str(config['task_reference']))
        kwargs = dict(config.get('eval_options') or {})
        try:
            returned = eval_fn(
                tasks=task,
                model=str(config['model']),
                model_args=dict(config.get('model_args') or {}),
                model_roles=dict(config.get('model_roles') or {}) or None,
                task_args=dict(config.get('task_args') or {}),
                log_dir=str(log_dir),
                log_format=str(config.get('log_format', 'eval')),
                display='none',
                metadata={
                    'aiq_evals_measurement_identity': resolved.identity.digest,
                    'aiq_evals_adapter_version': self.adapter_version,
                },
                **kwargs,
            )
            logs = _coerce_logs(returned)
            if not logs:
                # Be conservative: an empty return can still leave native logs.
                logs = _read_native_logs(log_dir, list_logs, read_log)
            return normalize_inspect_logs(
                logs,
                identity=resolved.identity,
                fallback_task=resolved.request.task,
                location_root=log_dir,
                location_prefix='native/inspect_ai/logs',
            )
        except Exception as ex:
            if isinstance(ex, (KeyboardInterrupt, SystemExit)):
                raise
            failure = f'{type(ex).__name__}: {ex}'
            try:
                logs = _read_native_logs(log_dir, list_logs, read_log)
            except Exception:
                logs = []
            result = normalize_inspect_logs(
                logs,
                identity=resolved.identity,
                fallback_task=resolved.request.task,
                forced_status='failed',
                failure=failure,
                location_root=log_dir,
                location_prefix='native/inspect_ai/logs',
            )
            diagnostics = dict(result.diagnostics)
            diagnostics['traceback'] = ''.join(
                traceback.format_exception(type(ex), ex, ex.__traceback__)
            )
            return EvaluationResult(
                engine=result.engine,
                identity=result.identity,
                status=result.status,
                records=result.records,
                samples=result.samples,
                artifacts=result.artifacts,
                diagnostics=normalize_json(diagnostics),
            )

    async def execute(
        self,
        resolved: ResolvedEvaluation,
        context: ExecutionContext,
    ) -> EvaluationResult:
        if resolved.request.engine != self.key:
            raise RequestValidationError('resolved evaluation belongs to another engine')
        # Inspect exposes a synchronous public eval API at the candidate release.
        # The shared runner executes this adapter in an owned process; to_thread
        # keeps that worker's asyncio protocol responsive while the native call runs.
        return await asyncio.to_thread(self.execute_blocking, resolved, context)

    def import_results(
        self,
        resolved: ResolvedEvaluation,
        source: str,
        context: ExecutionContext,
    ) -> EvaluationResult:
        del context
        _api, _eval_fn, list_logs, read_log = _native_symbols()
        root = Path(source).expanduser().resolve()
        logs = _read_native_logs(root, list_logs, read_log)
        if not logs:
            raise ArtifactError(f'Inspect source contains no evaluation logs: {root}')
        result = normalize_inspect_logs(
            logs,
            identity=resolved.identity,
            fallback_task=resolved.request.task,
            location_root=root if root.is_dir() else root.parent,
        )
        result = _validate_native_logs(resolved, logs, result)
        diagnostics = dict(result.diagnostics)
        diagnostics['import_source'] = str(root)
        diagnostics['import_provenance'] = 'inspect-public-log-api'
        return EvaluationResult(
            engine=result.engine,
            identity=result.identity,
            status=result.status,
            records=result.records,
            samples=result.samples,
            artifacts=result.artifacts,
            diagnostics=normalize_json(diagnostics),
        )
