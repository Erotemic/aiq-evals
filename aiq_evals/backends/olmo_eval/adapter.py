"""OLMo Eval adapter for the inspected AsyncEvalRunner API seam.

Native imports are lazy. Importing :mod:`aiq_evals` or reading a published run
never requires OLMo Eval to be installed.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import re
import sys
import traceback
from dataclasses import fields, is_dataclass
from functools import partial
from pathlib import Path
from typing import Any, Mapping

from aiq_evals.backends.olmo_eval.normalize import (
    attach_prediction_files,
    load_native_metrics,
    normalize_olmo_results,
)
from aiq_evals.backends.olmo_eval.worker_bootstrap import (
    inference_worker_with_registration,
)
from aiq_evals.contracts import (
    EvaluationRequest,
    EvaluationResult,
    ExecutionContext,
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
_FULL_GIT_SHA = re.compile(r'^[0-9a-fA-F]{40}$')

_ALLOWED_ENGINE_OPTIONS = {
    'harness_config',
    'save_predictions',
    'save_requests',
    'shuffle_seed',
    'upstream_revision',
    'task_modules',
}


def _distribution_version() -> str | None:
    try:
        return importlib.metadata.version('olmo-eval')
    except importlib.metadata.PackageNotFoundError:
        # Some editable/source environments may expose the module without
        # distribution metadata. The exact upstream git revision can still be
        # supplied explicitly in engine_options.
        return None


def _native_symbols() -> tuple[type, type, type, type, Any]:
    """Load the narrow upstream API surface phase 3 supports."""
    try:
        config_mod = importlib.import_module('olmo_eval.harness.config')
        runner_mod = importlib.import_module('olmo_eval.runners.asynq.runner')
        types_mod = importlib.import_module('olmo_eval.common.types')
        task_mod = importlib.import_module('olmo_eval.evals.tasks.common.base')
        configs_mod = importlib.import_module('olmo_eval.common.configs')
    except ImportError as ex:
        raise MissingDependencyError(
            'OLMo Eval execution requires the optional olmo_eval runtime. '
            'Install/use a supported OLMo worker environment; engine-free result '
            'reading does not require it.'
        ) from ex
    try:
        harness_cls = config_mod.HarnessConfig
        runner_cls = runner_mod.AsyncEvalRunner
        sampling_cls = types_mod.SamplingParams
        task_config_cls = task_mod.TaskConfig
        expand_tasks = configs_mod.expand_tasks
    except AttributeError as ex:
        raise EngineCompatibilityError(
            'installed OLMo Eval does not expose the supported HarnessConfig / '
            'AsyncEvalRunner / SamplingParams / TaskConfig API seam'
        ) from ex
    if not callable(getattr(harness_cls, 'from_dict', None)):
        raise EngineCompatibilityError('OLMo HarnessConfig.from_dict() is required')
    if not callable(getattr(runner_cls, 'validate', None)):
        raise EngineCompatibilityError('OLMo AsyncEvalRunner.validate() is required')
    if not callable(getattr(runner_cls, 'run_async', None)):
        raise EngineCompatibilityError('OLMo AsyncEvalRunner.run_async() is required')
    return harness_cls, runner_cls, sampling_cls, task_config_cls, expand_tasks


def _merge_native_config(request: EvaluationRequest) -> dict[str, Any]:
    options = dict(request.engine_options)
    unknown = set(options) - _ALLOWED_ENGINE_OPTIONS
    if unknown:
        raise RequestValidationError(
            f'unknown olmo_eval engine_options: {sorted(unknown)}; '
            f'allowed: {sorted(_ALLOWED_ENGINE_OPTIONS)}'
        )
    upstream_revision = options.get('upstream_revision')
    if upstream_revision is not None and not _FULL_GIT_SHA.fullmatch(str(upstream_revision)):
        raise RequestValidationError(
            'olmo_eval engine_options.upstream_revision must be a full 40-character git SHA'
        )
    task_modules = options.get('task_modules', [])
    if not isinstance(task_modules, list) or any(
        not isinstance(module, str) or not module.strip() for module in task_modules
    ):
        raise RequestValidationError('olmo_eval task_modules must be a list of importable module names')
    raw_harness = options.get('harness_config') or {}
    if not isinstance(raw_harness, Mapping):
        raise RequestValidationError('olmo_eval engine_options.harness_config must be an object')
    harness = dict(raw_harness)
    # HarnessConfig.from_dict serializes tools under ``tool_names`` even though
    # the dataclass field is named ``tools``. Accept the intuitive JSON spelling
    # but canonicalize it before calling upstream so it cannot be silently ignored.
    if 'tools' in harness:
        if 'tool_names' in harness and harness['tool_names'] != harness['tools']:
            raise RequestValidationError('conflicting OLMo harness tools and tool_names')
        harness['tool_names'] = harness.pop('tools')
    provider = harness.get('provider') or {}
    if not isinstance(provider, Mapping):
        raise RequestValidationError('olmo_eval harness_config.provider must be an object')
    provider = dict(provider)
    primary = request.primary_model
    if provider.get('model') not in (None, primary.model):
        raise RequestValidationError(
            'conflicting model declarations: primary model binding is '
            f'{primary.model!r}, harness provider.model is {provider.get("model")!r}'
        )
    provider['model'] = primary.model
    if primary.provider is not None:
        if provider.get('kind') not in (None, primary.provider):
            raise RequestValidationError(
                'conflicting provider declarations: primary provider is '
                f'{primary.provider!r}, harness provider.kind is {provider.get("kind")!r}'
            )
        provider['kind'] = primary.provider
    for key, value in primary.provider_options.items():
        if key in provider and provider[key] != value:
            raise RequestValidationError(
                f'conflicting provider option {key!r}: model binding and harness_config differ'
            )
        provider[key] = value
    if primary.revision is not None:
        if provider.get('revision') not in (None, primary.revision):
            raise RequestValidationError('conflicting primary model revision in harness_config')
        provider['revision'] = primary.revision
    harness['provider'] = provider
    harness.setdefault('name', 'aiq-evals')

    task_override = dict(request.task_options)
    for key, value in request.generation.items():
        if key in task_override and task_override[key] != value:
            raise RequestValidationError(
                f'conflicting task/generation override for {key!r}: '
                f'{task_override[key]!r} vs {value!r}'
            )
        task_override[key] = value

    return {
        'harness_config': harness,
        'task_specs': [request.task],
        'task_overrides': {request.task: task_override},
        'save_predictions': bool(options.get('save_predictions', True)),
        'save_requests': bool(options.get('save_requests', True)),
        'shuffle_seed': int(options.get('shuffle_seed', 42)),
        'task_modules': task_modules,
    }


def _load_task_modules(modules: list[str]) -> dict[str, str | None]:
    """Import explicit task/tool registration modules in this process."""
    digests: dict[str, str | None] = {}
    for name in modules:
        try:
            module = importlib.import_module(name)
        except Exception as ex:
            raise RequestValidationError(f'cannot import OLMo registration module {name!r}: {ex}') from ex
        source = getattr(module, '__file__', None)
        path = Path(source).resolve() if source else None
        digests[name] = sha256_file(path) if path is not None and path.is_file() else None
    return digests


def _expected_tasks(resolved: ResolvedEvaluation) -> set[str]:
    values = resolved.native_config.get('resolved_task_specs') or resolved.native_config.get('task_specs') or []
    return {str(value) for value in values}


def _validate_import_source(
    resolved: ResolvedEvaluation,
    raw: Mapping[str, Any],
    result: EvaluationResult,
) -> EvaluationResult:
    """Validate the native artifact against facts that OLMo actually records.

    Native metrics do not prove every revision in an EvaluationRequest, so the
    diagnostics distinguish facts verified from the artifact from caller-supplied
    provenance. Task/model/provider mismatches are never silently relabeled as the
    requested measurement.
    """
    expected = _expected_tasks(resolved)
    present = {record.task for record in result.records}
    unexpected = sorted(present - expected) if expected else []
    missing = sorted(expected - present) if expected else []
    if unexpected:
        raise ArtifactError(
            'OLMo native artifact contains tasks outside the resolved request: '
            f'{unexpected}; expected {sorted(expected)}'
        )

    primary = resolved.request.primary_model
    native_model_path = raw.get('model_path')
    if native_model_path is not None and str(native_model_path) != primary.model:
        raise ArtifactError(
            'OLMo native artifact model_path does not match the resolved request: '
            f'{native_model_path!r} != {primary.model!r}'
        )
    native_provider = raw.get('provider')
    if (
        primary.provider is not None
        and native_provider is not None
        and str(native_provider) != primary.provider
    ):
        raise ArtifactError(
            'OLMo native artifact provider does not match the resolved request: '
            f'{native_provider!r} != {primary.provider!r}'
        )

    diagnostics = dict(result.diagnostics)
    diagnostics['import_validation'] = {
        'expected_tasks': sorted(expected),
        'present_tasks': sorted(present),
        'missing_tasks': missing,
        'model_path_verified': native_model_path is not None,
        'provider_verified': primary.provider is None or native_provider is not None,
        'revision_provenance': 'caller-supplied; native metrics do not prove task/data/engine revisions',
    }
    status = 'incomplete' if result.status == 'succeeded' and missing else result.status
    if missing:
        diagnostics['import_incomplete_reason'] = 'resolved tasks are missing from native artifact'
    return EvaluationResult(
        engine=result.engine,
        identity=result.identity,
        status=status,
        records=result.records,
        samples=result.samples,
        artifacts=result.artifacts,
        diagnostics=normalize_json(diagnostics),
    )


class OlmoEvalBackend:
    key = 'olmo_eval'
    adapter_version = ADAPTER_VERSION

    def capabilities(self) -> Mapping[str, Any]:
        # These describe the adapter surface, not a claim that every native
        # task/provider combination supports each feature.
        return {
            'experimental': True,
            # Experimental until the phase-8 release gate; phase-1 native acceptance
            # passed only for the combinations in docs/planning/phase1-capabilities.md.
            'implementation_status': 'phase1-native-accepted',
            'capability_scope': 'request/task/provider combination; validate during resolution',
            'features': {
                'generation': {'implemented': True, 'native_verified': False},
                'agentic': {'implemented': True, 'native_verified': False},
                'tools': {'implemented': True, 'native_verified': False},
                'trajectories': {'implemented': True, 'native_verified': False},
                'native_import': {'implemented': True, 'native_verified': False},
                'log_probabilities': {'implemented': False, 'native_verified': False},
                'sandboxing': {'implemented': 'harness-pass-through', 'native_verified': False},
                'native_resume': {'implemented': False, 'native_verified': False},
                'native_rescore': {'implemented': False, 'native_verified': False},
            },
        }

    def validate_request(self, request: EvaluationRequest) -> None:
        if request.engine != self.key:
            raise RequestValidationError(
                f'OlmoEvalBackend cannot handle engine {request.engine!r}'
            )
        if len(request.models) != 1:
            raise RequestValidationError(
                'phase-3 OLMo adapter supports one primary model binding per request; '
                'auxiliary judge/provider models belong in harness_config until a shared '
                'role mapping is proven against native fixtures'
            )
        _merge_native_config(request)

    def resolve(self, request: EvaluationRequest) -> ResolvedEvaluation:
        self.validate_request(request)
        harness_cls, _runner_cls, sampling_cls, task_config_cls, expand_tasks = _native_symbols()
        native_config = _merge_native_config(request)
        task_module_digests = _load_task_modules(native_config['task_modules'])

        task_fields = {item.name for item in fields(task_config_cls)}
        sampling_fields = {item.name for item in fields(sampling_cls)}
        override_keys = set(native_config['task_overrides'][request.task])
        unknown_overrides = override_keys - task_fields - sampling_fields
        if unknown_overrides:
            raise RequestValidationError(
                'OLMo task/generation overrides are not recognized by the selected '
                f'upstream API: {sorted(unknown_overrides)}'
            )

        if is_dataclass(harness_cls):
            harness_fields = {item.name for item in fields(harness_cls)}
            # from_dict supports these compatibility/serialized names in addition
            # to dataclass fields. Unknown keys would otherwise be silently ignored.
            harness_allowed = harness_fields | {'tool_names', 'backend', 'backend_kwargs'}
            harness_unknown = set(native_config['harness_config']) - harness_allowed
            if harness_unknown:
                raise RequestValidationError(
                    f'unknown OLMo harness_config fields: {sorted(harness_unknown)}'
                )
        try:
            harness = harness_cls.from_dict(dict(native_config['harness_config']))
            canonical_harness = harness.to_dict()
        except Exception as ex:
            raise RequestValidationError(f'invalid OLMo harness configuration: {ex}') from ex

        try:
            expanded = list(expand_tasks(list(native_config['task_specs'])))
        except Exception as ex:
            raise RequestValidationError(f'cannot resolve OLMo task/suite {request.task!r}: {ex}') from ex
        if not expanded:
            raise RequestValidationError(
                f'OLMo task/suite {request.task!r} resolved to no native tasks'
            )

        native_config = {
            **native_config,
            'harness_config': canonical_harness,
            'resolved_task_specs': expanded,
        }
        engine_version = _distribution_version()
        engine_revision, revision_facts, revision_reasons = verify_engine_revision(
            request.engine_options.get('upstream_revision'),
            module_file=getattr(sys.modules.get('olmo_eval'), '__file__', None),
            distribution='olmo-eval',
        )
        resolved_facts = {
            **revision_facts,
            'engine_version': engine_version,
            'engine_revision': engine_revision,
            'resolved_task_specs': expanded,
            'native_api': 'AsyncEvalRunner/HarnessConfig',
            'task_module_digests': task_module_digests,
        }
        identity_facts = {
            'adapter_source_sha256': adapter_source_digest(__package__),
            'task_module_digests': task_module_digests,
        }
        unhashed = sorted(name for name, digest in task_module_digests.items() if digest is None)
        unknown_reasons = list(revision_reasons)
        if unhashed:
            unknown_reasons.append(f'task modules have no hashable source: {unhashed}')
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

    async def execute(
        self,
        resolved: ResolvedEvaluation,
        context: ExecutionContext,
    ) -> EvaluationResult:
        if resolved.request.engine != self.key:
            raise RequestValidationError('resolved evaluation belongs to another engine')
        if context.env:
            raise RequestValidationError(
                'in-process OLMo execution does not mutate process-global environment; '
                'use ExecutionContext.worker_python for isolated credentials/environment '
                'or inherit credentials in the current process environment'
            )
        harness_cls, runner_cls, _sampling_cls, _task_config_cls, _expand_tasks = _native_symbols()
        native_dir = context.output_dir / 'native'
        native_dir.mkdir(parents=True, exist_ok=True)
        config = dict(resolved.native_config)
        _load_task_modules(list(config.get('task_modules') or []))
        modules = tuple(config.get('task_modules') or [])
        try:
            harness = harness_cls.from_dict(dict(config['harness_config']))
            runner = runner_cls(
                harness_config=harness,
                task_specs=list(config['task_specs']),
                task_overrides={
                    str(key): dict(value)
                    for key, value in dict(config.get('task_overrides') or {}).items()
                },
                output_dir=str(native_dir),
                save_predictions=bool(config.get('save_predictions', True)),
                save_requests=bool(config.get('save_requests', True)),
                shuffle_seed=int(config.get('shuffle_seed', 42)),
            )
            # Explicit validation is part of the supported adapter contract.
            runner.validate()
            if modules:
                worker_module = importlib.import_module('olmo_eval.runners.asynq.workers')
                original_worker = worker_module.inference_worker
                worker_module.inference_worker = partial(
                    inference_worker_with_registration, modules
                )
                try:
                    raw = await runner.run_async()
                finally:
                    worker_module.inference_worker = original_worker
            else:
                raw = await runner.run_async()
            if not isinstance(raw, Mapping):
                raise EngineCompatibilityError(
                    f'OLMo AsyncEvalRunner.run_async() returned {type(raw).__name__}, expected mapping'
                )
            result = normalize_olmo_results(raw, identity=resolved.identity)
            return attach_prediction_files(result, native_dir)
        except asyncio.CancelledError:
            # AsyncEvalRunner owns native cleanup in its finally block. Preserve
            # caller cancellation instead of converting it into a normal result.
            raise
        except Exception as ex:
            # OLMo intentionally writes diagnostic metrics before its hard-failure
            # gate raises. Capture those artifacts, but mark this attempt failed.
            failure = f'{type(ex).__name__}: {ex}'
            try:
                raw = load_native_metrics(native_dir)
            except Exception:
                raw = {'tasks': {}, 'errors': []}
            result = normalize_olmo_results(
                raw,
                identity=resolved.identity,
                status='failed',
                failure=failure,
            )
            result = attach_prediction_files(result, native_dir)
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

    def import_results(
        self,
        resolved: ResolvedEvaluation,
        source: str,
        context: ExecutionContext,
    ) -> EvaluationResult:
        root = Path(source).expanduser().resolve()
        raw = load_native_metrics(root)
        result = normalize_olmo_results(raw, identity=resolved.identity)
        result = attach_prediction_files(result, root)
        result = _validate_import_source(resolved, raw, result)
        diagnostics = dict(result.diagnostics)
        diagnostics['import_source'] = str(root)
        diagnostics['import_provenance'] = 'caller-supplied-native-artifact'
        return EvaluationResult(
            engine=result.engine,
            identity=result.identity,
            status=result.status,
            records=result.records,
            samples=result.samples,
            artifacts=result.artifacts,
            diagnostics=diagnostics,
        )
