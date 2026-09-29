"""HELM adapter (phase 5, experimental).

Resolution uses HELM's own run-entry expansion (``run_entries_to_run_specs``)
so the canonical ``RunSpec`` objects, not the caller's shorthand, enter the
measurement identity. Execution runs HELM's public CLI module
(``python -m helm.benchmark.run``) with the worker's interpreter, and locates
outputs by exact ``RunSpec.name`` under ``runs/<suite>/``. Native imports read
run directories without importing HELM.

This is a MAGNET-independent reimplementation of the generic compute/import
behavior. MAGNET's name-matching reuse and predictor APIs stay in MAGNET.
Engine imports stay lazy.
"""
from __future__ import annotations

import asyncio
import dataclasses
import importlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from aiq_evals.backends.helm.normalize import (
    find_run_dirs,
    normalize_helm_runs,
    normalize_run_dir,
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
from aiq_evals.jsonutil import normalize_json_object, sha256_file
from aiq_evals.probes.source import verify_engine_revision

# 0.1.0: first adapter; verified against crfm-helm 0.5.14 (phase-1 fixtures).
ADAPTER_VERSION = '0.1.0'
VERIFIED_HELM_VERSION = '0.5.14'
# Fixed so output locations never depend on caller-chosen names.
SUITE = 'aiq-evals'

_FULL_GIT_SHA = re.compile(r'^[0-9a-fA-F]{40}$')
# required_secrets is engine-independent: names checked by the runner, never passed to HELM.
_ALLOWED_ENGINE_OPTIONS = {'upstream_revision', 'plugins', 'required_secrets'}
_ALLOWED_TASK_OPTIONS = {'max_eval_instances', 'num_train_trials'}
_MODEL_ARG = re.compile(r'(^|[:,])model(_deployment)?=')

_CONFIGS_REGISTERED = False


def _distribution_version() -> str | None:
    try:
        return importlib.metadata.version('crfm-helm')
    except importlib.metadata.PackageNotFoundError:
        return None


def _native_symbols() -> dict[str, Any]:
    try:
        run_mod = importlib.import_module('helm.benchmark.run')
        run_entry_mod = importlib.import_module('helm.benchmark.presentation.run_entry')
        registry_mod = importlib.import_module('helm.benchmark.config_registry')
        runner_mod = importlib.import_module('helm.benchmark.runner')
    except ImportError as ex:
        raise MissingDependencyError(
            'HELM resolution/execution requires crfm-helm in the worker environment; '
            'install it in an isolated worker (see dev/environments/phase1/)'
        ) from ex
    try:
        return {
            'run_entries_to_run_specs': run_mod.run_entries_to_run_specs,
            'import_user_plugins': run_mod.import_user_plugins,
            'load_entry_point_plugins': run_mod.load_entry_point_plugins,
            'RunEntry': run_entry_mod.RunEntry,
            'register_builtin_configs': registry_mod.register_builtin_configs_from_helm_package,
            'set_benchmark_output_path': runner_mod.set_benchmark_output_path,
        }
    except AttributeError as ex:
        raise EngineCompatibilityError(
            f'installed HELM lacks the run-entry/run-spec API seam used at {VERIFIED_HELM_VERSION}: {ex}'
        ) from ex


def build_run_entry(request: EvaluationRequest) -> str:
    """HELM run-entry description: the task entry plus the bound primary model."""
    task = request.task.strip()
    if _MODEL_ARG.search(task):
        raise RequestValidationError(
            'the HELM task must not name model/model_deployment; bind the model through '
            f'EvaluationRequest.models instead: {task!r}'
        )
    return f"{task}{',' if ':' in task else ':'}model={request.primary_model.model}"


def _task_options(request: EvaluationRequest) -> dict[str, int]:
    unknown = set(request.task_options) - _ALLOWED_TASK_OPTIONS
    if unknown:
        raise RequestValidationError(
            f'unknown helm task_options: {sorted(unknown)}; allowed: {sorted(_ALLOWED_TASK_OPTIONS)}'
        )
    options: dict[str, int] = {}
    for key, value in request.task_options.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise RequestValidationError(f'helm task_options.{key} must be a positive integer')
        options[key] = value
    return options


def _merge_native_config(request: EvaluationRequest) -> dict[str, Any]:
    options = dict(request.engine_options)
    unknown = set(options) - _ALLOWED_ENGINE_OPTIONS
    if unknown:
        raise RequestValidationError(
            f'unknown helm engine_options: {sorted(unknown)}; allowed: {sorted(_ALLOWED_ENGINE_OPTIONS)}'
        )
    upstream_revision = options.get('upstream_revision')
    if upstream_revision is not None and not _FULL_GIT_SHA.fullmatch(str(upstream_revision)):
        raise RequestValidationError('helm engine_options.upstream_revision must be a full 40-character git SHA')
    plugins = options.get('plugins', [])
    if not isinstance(plugins, list) or any(not isinstance(item, str) or not item.strip() for item in plugins):
        raise RequestValidationError('helm plugins must be a list of importable module names')
    if any('/' in item or item.endswith('.py') for item in plugins):
        raise RequestValidationError('helm plugins must be module names, not paths, so they can be hashed')
    if request.generation:
        raise RequestValidationError(
            'HELM generation settings belong to the RunSpec; encode them in the run entry '
            '(e.g. "task:temperature=0.0") rather than EvaluationRequest.generation'
        )
    if len(request.models) != 1:
        raise RequestValidationError('the HELM adapter supports exactly one (primary) model binding')
    primary = request.primary_model
    if primary.provider not in (None, 'helm'):
        raise RequestValidationError(
            "HELM model deployments come from HELM's registry; provider must be unset or 'helm'"
        )
    if primary.provider_options:
        raise RequestValidationError('HELM provider_options are not supported; configure deployments natively')
    return {
        'run_entry': build_run_entry(request),
        'task_options': _task_options(request),
        'plugins': list(plugins),
        'suite': SUITE,
    }


def _load_plugins(symbols: Mapping[str, Any], plugins: list[str]) -> dict[str, str | None]:
    digests: dict[str, str | None] = {}
    if plugins:
        try:
            symbols['import_user_plugins'](plugins)
        except Exception as ex:
            raise RequestValidationError(f'cannot import HELM plugins {plugins}: {ex}') from ex
    for name in plugins:
        module = sys.modules.get(name) or importlib.import_module(name)
        source = getattr(module, '__file__', None)
        path = Path(source).resolve() if source else None
        digests[name] = sha256_file(path) if path is not None and path.is_file() else None
    return digests


def _resolve_run_specs(symbols: Mapping[str, Any], native_config: Mapping[str, Any]) -> list[dict[str, Any]]:
    global _CONFIGS_REGISTERED
    if not _CONFIGS_REGISTERED:
        symbols['register_builtin_configs']()
        symbols['load_entry_point_plugins']()
        _CONFIGS_REGISTERED = True
    options = native_config['task_options']
    # Run spec functions may use the benchmark output path for caching; keep
    # resolution side effects out of any real output directory.
    with tempfile.TemporaryDirectory(prefix='aiq-helm-resolve-') as scratch:
        symbols['set_benchmark_output_path'](scratch)
        try:
            specs = symbols['run_entries_to_run_specs'](
                run_entries=[symbols['RunEntry'](description=native_config['run_entry'], priority=1, groups=None)],
                max_eval_instances=options.get('max_eval_instances'),
                num_train_trials=options.get('num_train_trials'),
            )
        except Exception as ex:
            raise RequestValidationError(
                f"HELM cannot resolve run entry {native_config['run_entry']!r}: {ex}"
            ) from ex
    if not specs:
        raise RequestValidationError(f"HELM run entry {native_config['run_entry']!r} resolved to no run specs")
    return [json.loads(json.dumps(dataclasses.asdict(spec), default=str)) for spec in specs]


def _validate_import(
    resolved: ResolvedEvaluation, result: EvaluationResult, run_dirs: list[Path]
) -> EvaluationResult:
    expected = set(resolved.native_config.get('run_spec_names') or [])
    present = {record.task for record in result.records}
    unexpected = sorted(present - expected)
    if unexpected:
        raise ArtifactError(
            f'HELM artifact contains run specs outside the resolved request: {unexpected}; '
            f'expected {sorted(expected)}'
        )
    model = resolved.request.primary_model.model
    for summary in result.diagnostics.get('native_runs') or []:
        if summary.get('model') not in (None, model):
            raise ArtifactError(
                f"HELM run {summary.get('task')!r} used model {summary.get('model')!r}, "
                f'not the resolved {model!r}'
            )
    missing = sorted(expected - present)
    status = result.status if not missing else 'incomplete'
    diagnostics = dict(result.diagnostics)
    diagnostics['missing_run_specs'] = missing
    return dataclasses.replace(result, status=status, diagnostics=normalize_json_object(diagnostics))


class HelmBackend:
    key = 'helm'
    adapter_version = ADAPTER_VERSION

    def capabilities(self) -> Mapping[str, Any]:
        return {
            'experimental': True,
            'implementation_status': 'phase5-implemented',
            'requires_worker_process': True,
            'capability_scope': 'run entry/model combination; validate natively',
            'verified_version': VERIFIED_HELM_VERSION,
            'features': {
                'generation': {'implemented': True, 'native_verified': 'local simple model'},
                'native_import': {'implemented': True, 'native_verified': True},
                'trajectories': {'implemented': 'prompt/completion from scenario_state', 'native_verified': True},
                'multiple_metrics': {'implemented': True, 'native_verified': True},
                'repetitions': {'implemented': 'train trials as epochs', 'native_verified': True},
                'agentic': {'implemented': False, 'native_verified': False},
                'tools': {'implemented': False, 'native_verified': False},
                'log_probabilities': {'implemented': False, 'native_verified': False},
                'sandboxing': {'implemented': False, 'native_verified': False},
                'native_resume': {'implemented': False, 'native_verified': False},
                'native_rescore': {'implemented': False, 'native_verified': False},
            },
        }

    def validate_request(self, request: EvaluationRequest) -> None:
        if request.engine != self.key:
            raise RequestValidationError(f'request engine {request.engine!r} is not {self.key!r}')
        _merge_native_config(request)

    def resolve(self, request: EvaluationRequest) -> ResolvedEvaluation:
        self.validate_request(request)
        symbols = _native_symbols()
        native_config = _merge_native_config(request)
        plugin_digests = _load_plugins(symbols, native_config['plugins'])
        run_specs = _resolve_run_specs(symbols, native_config)
        native_config = {
            **native_config,
            'run_specs': run_specs,
            'run_spec_names': [spec['name'] for spec in run_specs],
        }
        engine_version = _distribution_version()
        helm_module = importlib.import_module('helm')
        engine_revision, revision_facts, revision_reasons = verify_engine_revision(
            request.engine_options.get('upstream_revision'),
            module_file=getattr(helm_module, '__file__', None),
            distribution='crfm-helm',
        )
        resolved_facts = {
            **revision_facts,
            'engine_version': engine_version,
            'engine_revision': engine_revision,
            'native_api': 'helm.benchmark.run (run_entries_to_run_specs + CLI module)',
            'verified_version': VERIFIED_HELM_VERSION,
            'verified_version_match': engine_version == VERIFIED_HELM_VERSION,
            'plugin_digests': plugin_digests,
        }
        identity_facts = {
            'adapter_source_sha256': adapter_source_digest(__package__),
            'plugin_digests': plugin_digests,
        }
        unknown_reasons = list(revision_reasons)
        unhashed = sorted(name for name, digest in plugin_digests.items() if digest is None)
        if unhashed:
            unknown_reasons.append(f'HELM plugins have no hashable source: {unhashed}')
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

    def execute_blocking(self, resolved: ResolvedEvaluation, context: ExecutionContext) -> EvaluationResult:
        """Run HELM's CLI module as a child of the calling (worker) process.

        The child inherits the worker's process group, so the runner's
        SIGINT-first cancellation reaches HELM directly.
        """
        if resolved.request.engine != self.key:
            raise RequestValidationError('resolved evaluation belongs to another engine')
        if context.model_endpoints:
            raise RequestValidationError(
                'HELM model deployments come from its registry; endpoint overrides are unsupported'
            )
        config = dict(resolved.native_config)
        native_root = (context.output_dir / 'native' / 'helm').resolve()
        output_path = native_root / 'benchmark_output'
        # A per-run local path keeps HELM's request cache and any credentials
        # hermetic; a shared cache would be operational state outside identity.
        local_path = native_root / 'prod_env'
        local_path.mkdir(parents=True, exist_ok=True)
        options = config.get('task_options') or {}
        command = [
            sys.executable, '-m', 'helm.benchmark.run',
            '--run-entries', str(config['run_entry']),
            '--suite', SUITE,
            '--output-path', str(output_path),
            '--local-path', str(local_path),
            '--num-threads', '1',
            '--exit-on-error',
        ]
        if 'max_eval_instances' in options:
            command += ['--max-eval-instances', str(options['max_eval_instances'])]
        if 'num_train_trials' in options:
            command += ['--num-train-trials', str(options['num_train_trials'])]
        if config.get('plugins'):
            command += ['--plugins', *config['plugins']]
        env = dict(os.environ)
        env.update(context.env)
        with (native_root / 'helm-run.stdout.log').open('wb') as out, (
            native_root / 'helm-run.stderr.log'
        ).open('wb') as err:
            completed = subprocess.run(command, cwd=native_root, stdout=out, stderr=err, env=env, check=False)
        run_root = output_path / 'runs' / SUITE
        expected = [run_root / str(name) for name in config.get('run_spec_names') or []]
        present = [path for path in expected if path.is_dir()]
        failure = None
        if completed.returncode != 0:
            tail = (native_root / 'helm-run.stderr.log').read_text(errors='replace')[-4000:]
            failure = f'helm-run exited with code {completed.returncode}: {tail}'
        elif len(present) != len(expected):
            missing = [path.name for path in expected if not path.is_dir()]
            failure = f'helm-run exited 0 but wrote no run directory for {missing}'
        result = normalize_helm_runs(
            present,
            identity=resolved.identity,
            forced_status='failed' if failure else None,
            failure=failure,
            # HELM names each run directory exactly after its resolved RunSpec.
            expected_tasks=True,
        )
        diagnostics = dict(result.diagnostics)
        diagnostics['command'] = command[1:]  # interpreter path is operational
        return dataclasses.replace(result, diagnostics=normalize_json_object(diagnostics))

    async def execute(self, resolved: ResolvedEvaluation, context: ExecutionContext) -> EvaluationResult:
        return await asyncio.to_thread(self.execute_blocking, resolved, context)

    def import_results(
        self,
        resolved: ResolvedEvaluation,
        source: str,
        context: ExecutionContext,
    ) -> EvaluationResult:
        del context
        root = Path(source).expanduser().resolve()
        run_dirs = find_run_dirs(root)
        if not run_dirs:
            raise ArtifactError(f'no HELM run directory (run_spec.json) under {root}')
        result = normalize_helm_runs(run_dirs, identity=resolved.identity)
        result = _validate_import(resolved, result, run_dirs)
        diagnostics = dict(result.diagnostics)
        diagnostics['import_source'] = str(root)
        diagnostics['import_provenance'] = 'caller-supplied-native-artifact'
        return dataclasses.replace(result, diagnostics=normalize_json_object(diagnostics))


__all__ = ['ADAPTER_VERSION', 'HelmBackend', 'build_run_entry', 'normalize_run_dir']
