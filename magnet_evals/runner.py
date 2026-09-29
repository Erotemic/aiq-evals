"""Shared resolve/execute/import facades."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from magnet_evals import errors as errors_module
from magnet_evals.artifacts import RunBundle, publish_run
from magnet_evals.backends.registry import get_backend
from magnet_evals.contracts import (
    EvaluationRequest,
    EvaluationResult,
    ExecutionContext,
    ResolvedEvaluation,
    as_execution_status,
)
from magnet_evals.errors import (
    ActiveEventLoopError,
    ExecutionError,
    RequestValidationError,
)
from magnet_evals.jsonutil import (
    MIN_REDACTED_VALUE_LENGTH,
    redact_values,
    required_secret_names,
)


def validate_request(request: EvaluationRequest) -> None:
    """Perform engine-specific static validation without importing the engine."""
    get_backend(request.engine).validate_request(request)


def resolve_evaluation(request: EvaluationRequest) -> ResolvedEvaluation:
    """Resolve native configuration and measurement identity in the engine runtime."""
    backend = get_backend(request.engine)
    backend.validate_request(request)
    return backend.resolve(request)


# Seconds a worker gets after SIGINT to run native cleanup (sandbox teardown,
# cancelled logs) before escalation to SIGTERM and then SIGKILL.
CANCEL_GRACE_SECONDS = 15.0
_TERM_GRACE_SECONDS = 5.0


async def _terminate_process_tree(
    process: asyncio.subprocess.Process,
    *,
    grace_seconds: float = CANCEL_GRACE_SECONDS,
) -> None:
    """Interrupt, then terminate, then kill the worker's process group.

    SIGINT first gives the engine its own interruption path (Inspect handles it
    and runs sandbox cleanup; OLMo's runner sees task cancellation through
    asyncio.run). Escalation keeps cancellation bounded if the engine hangs.
    """
    if process.returncode is not None:
        return
    if os.name != 'posix':
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=_TERM_GRACE_SECONDS)
        except TimeoutError:
            process.kill()
            await process.wait()
        return
    for sig, wait in (
        (signal.SIGINT, grace_seconds),
        (signal.SIGTERM, _TERM_GRACE_SECONDS),
        (signal.SIGKILL, None),
    ):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        try:
            await asyncio.wait_for(process.wait(), timeout=wait)
            break
        except TimeoutError:
            continue
    # The leader may have exited while other group members linger.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


def _redact_file(path: Path, env: Any) -> None:
    if not path.is_file():
        return
    data = path.read_bytes()
    for key, value in dict(env).items():
        if value:
            data = data.replace(value.encode(), f'<redacted:{key}>'.encode())
    path.write_bytes(data)


def _worker_result_path(work_dir: Path) -> Path:
    return work_dir / '.aiq-evals-worker' / 'result.json'


def _worker_env(context: ExecutionContext) -> dict[str, str]:
    env = os.environ.copy()
    env.update(context.env)
    # Make source-tree execution work without requiring an editable install in
    # the worker environment. Installed distributions also work with this path.
    package_parent = str(Path(__file__).resolve().parent.parent)
    old_pythonpath = env.get('PYTHONPATH')
    env['PYTHONPATH'] = package_parent if not old_pythonpath else package_parent + os.pathsep + old_pythonpath
    return env


async def _run_worker(
    arguments: list[str],
    context: ExecutionContext,
    stdout_path: Path,
    stderr_path: Path,
    secrets: Mapping[str, str],
) -> int:
    """Run ``python -m magnet_evals.worker ...`` in its own process group.

    Output goes to files rather than pipes, so a worker that keeps writing
    during the cancellation grace period can never block on an unread pipe.
    Cancellation and timeout terminate the whole group (SIGINT first).
    """
    assert context.worker_python is not None
    try:
        with stdout_path.open('wb') as stdout_file, stderr_path.open('wb') as stderr_file:
            process = await asyncio.create_subprocess_exec(
                context.worker_python, '-m', 'magnet_evals.worker', *arguments,
                stdout=stdout_file,
                stderr=stderr_file,
                env=_worker_env(context),
                start_new_session=(os.name == 'posix'),
            )
            try:
                if context.timeout_seconds is None:
                    await process.wait()
                else:
                    await asyncio.wait_for(process.wait(), context.timeout_seconds)
            except (asyncio.CancelledError, TimeoutError):
                await _terminate_process_tree(process)
                raise
    finally:
        _redact_file(stdout_path, secrets)
        _redact_file(stderr_path, secrets)
    assert process.returncode is not None
    return process.returncode


async def _execute_in_worker(
    resolved: ResolvedEvaluation,
    context: ExecutionContext,
    work_dir: Path,
) -> EvaluationResult:
    protocol_dir = work_dir / '.aiq-evals-worker'
    protocol_dir.mkdir(parents=True, exist_ok=True)
    resolved_path = protocol_dir / 'resolved.json'
    result_path = _worker_result_path(work_dir)
    # Worker diagnostics must survive publication, especially when a native
    # runner fails after writing partial artifacts.
    worker_log_dir = work_dir / 'native' / 'aiq_worker'
    worker_log_dir.mkdir(parents=True, exist_ok=True)
    stderr_path = worker_log_dir / 'stderr.log'
    resolved_path.write_text(json.dumps(resolved.to_dict(), indent=2, sort_keys=True) + '\n')
    returncode = await _run_worker(
        [
            'execute',
            '--resolved', str(resolved_path),
            '--output-dir', str(work_dir),
            '--result', str(result_path),
            '--model-endpoints', json.dumps(dict(context.model_endpoints)),
        ],
        context,
        worker_log_dir / 'stdout.log',
        stderr_path,
        effective_secrets(resolved.request, context),
    )
    if returncode != 0:
        detail = stderr_path.read_text(errors='replace')[-4000:]
        raise ExecutionError(f'evaluation worker exited with code {returncode}: {detail}')
    try:
        payload = json.loads(result_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as ex:
        raise ExecutionError('evaluation worker did not produce a valid result protocol file') from ex
    return EvaluationResult.from_dict(payload)


async def resolve_evaluation_async(
    request: EvaluationRequest,
    context: ExecutionContext | None = None,
) -> ResolvedEvaluation:
    """Resolve in ``context.worker_python`` when given, else in this process.

    Resolution imports the native engine (and task/plugin code), so it belongs
    in the engine's worker environment (ADR-0002). Errors raised there keep
    their aiq-evals error type.
    """
    if context is not None:
        # Before any task/plugin code runs, in-process or in the worker.
        check_required_secrets(request, context)
    if context is None or context.worker_python is None:
        return resolve_evaluation(request)
    validate_request(request)
    with tempfile.TemporaryDirectory(prefix='aiq-evals-resolve-') as scratch:
        scratch_dir = Path(scratch)
        request_path = scratch_dir / 'request.json'
        result_path = scratch_dir / 'resolved.json'
        request_path.write_text(json.dumps(request.to_dict(), sort_keys=True))
        stderr_path = scratch_dir / 'stderr.log'
        returncode = await _run_worker(
            ['resolve', '--request', str(request_path), '--result', str(result_path)],
            context,
            scratch_dir / 'stdout.log',
            stderr_path,
            effective_secrets(request, context),
        )
        try:
            payload = json.loads(result_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError) as ex:
            detail = stderr_path.read_text(errors='replace')[-4000:]
            raise ExecutionError(
                f'resolution worker exited with code {returncode} without a result: {detail}'
            ) from ex
    _raise_worker_error(payload)
    return ResolvedEvaluation.from_dict(payload['resolved'])


def _raise_worker_error(payload: Mapping[str, Any]) -> None:
    if 'error' not in payload:
        return
    error_cls = getattr(errors_module, str(payload['error'].get('type')), None)
    if not (isinstance(error_cls, type) and issubclass(error_cls, errors_module.AiqEvalsError)):
        error_cls = ExecutionError
    raise error_cls(str(payload['error'].get('message')))


def _cancelled_result(resolved: ResolvedEvaluation, work_dir: Path, detail: str) -> EvaluationResult:
    """Terminal cancelled result, keeping native facts a worker wrote while interrupted."""
    fallback = _terminal_error_result(resolved, status='cancelled', kind='cancelled', detail=detail)
    try:
        native = EvaluationResult.from_dict(json.loads(_worker_result_path(work_dir).read_text()))
    except (OSError, ValueError, KeyError, TypeError):
        return fallback
    diagnostics = dict(native.diagnostics)
    diagnostics.update(fallback.diagnostics)
    # Whatever the engine reported, this attempt was cancelled by its caller.
    diagnostics['worker_reported_status'] = native.status
    return EvaluationResult(
        engine=native.engine,
        identity=resolved.identity,
        status='cancelled',
        records=native.records,
        samples=native.samples,
        artifacts=native.artifacts,
        diagnostics=diagnostics,
    )


async def _execute_resolved(
    resolved: ResolvedEvaluation,
    context: ExecutionContext,
    work_dir: Path,
) -> EvaluationResult:
    backend = get_backend(resolved.request.engine)
    capabilities = dict(backend.capabilities())
    requires_worker = bool(capabilities.get('requires_worker_process'))
    if context.worker_python is not None or requires_worker:
        worker_context = ExecutionContext(
            output_dir=context.output_dir,
            env=context.env,
            worker_python=context.worker_python or sys.executable,
            timeout_seconds=context.timeout_seconds,
            model_endpoints=context.model_endpoints,
        )
        return await _execute_in_worker(resolved, worker_context, work_dir)
    direct_context = ExecutionContext(
        output_dir=work_dir,
        env=context.env,
        worker_python=None,
        timeout_seconds=context.timeout_seconds,
        model_endpoints=context.model_endpoints,
    )
    if context.timeout_seconds is None:
        return await backend.execute(resolved, direct_context)
    # Same semantics as the worker path: on expiry the adapter task is
    # cancelled (running its cleanup) and TimeoutError becomes a failed run.
    return await asyncio.wait_for(backend.execute(resolved, direct_context), context.timeout_seconds)


def _redacted_exception_text(ex: BaseException, env: Mapping[str, str]) -> str:
    text = f'{type(ex).__name__}: {ex}'
    for key, value in dict(env).items():
        if value:
            text = text.replace(value, f'<redacted:{key}>')
    return text


def effective_secrets(request: EvaluationRequest, context: ExecutionContext) -> dict[str, str]:
    """Secret values to scrub: ``ExecutionContext.env`` plus declared secrets inherited.

    Workers inherit the parent environment, so a ``required_secrets`` name set
    only in ``os.environ`` is as sensitive as one passed explicitly.
    """
    secrets = {name: value for name, value in context.env.items() if value}
    for name in required_secret_names(request.to_dict()):
        if name not in secrets and os.environ.get(name):
            secrets[name] = os.environ[name]
    return secrets


def check_required_secrets(request: EvaluationRequest, context: ExecutionContext) -> None:
    """Fail before any worker starts when a declared secret is unavailable.

    Names come from ``required_secrets`` lists in the request; values must be
    supplied through ``ExecutionContext.env`` or the inherited environment.
    """
    missing = [
        name for name in required_secret_names(request.to_dict())
        if not (context.env.get(name) or os.environ.get(name))
    ]
    if missing:
        raise RequestValidationError(
            f'required secrets are not set in ExecutionContext.env or the environment: {missing}'
        )


def _redact_result(result: EvaluationResult, secrets: Mapping[str, str]) -> EvaluationResult:
    # Adapters retain native exception text/tracebacks, which can quote
    # credentials supplied through the environment; never publish those values.
    if not any(secrets.values()):
        return result
    redacted = EvaluationResult.from_dict(redact_values(result.to_dict(), secrets))
    diagnostics = dict(redacted.diagnostics)
    short = sorted(
        name for name, value in secrets.items()
        if value and len(value) < MIN_REDACTED_VALUE_LENGTH
    )
    if short:
        diagnostics['env_values_not_redacted_as_too_short'] = short
    return EvaluationResult(
        engine=redacted.engine,
        identity=result.identity,
        status=redacted.status,
        records=redacted.records,
        samples=redacted.samples,
        artifacts=redacted.artifacts,
        diagnostics=diagnostics,
    )


def _terminal_error_result(
    resolved: ResolvedEvaluation,
    *,
    status: str,
    kind: str,
    detail: str,
) -> EvaluationResult:
    return EvaluationResult(
        engine=resolved.request.engine,
        identity=resolved.identity,
        status=as_execution_status(status),
        records=(),
        diagnostics={
            'runner_failure_kind': kind,
            'runner_error': detail,
        },
    )


async def run_evaluation_async(
    request_or_resolved: EvaluationRequest | ResolvedEvaluation,
    context: ExecutionContext,
) -> RunBundle:
    """Execute once and atomically publish the run bundle at ``context.output_dir``.

    Always executes; use ``ensure_evaluation`` for store lookup and reuse. A
    request is resolved in ``context.worker_python`` when given.
    """
    if isinstance(request_or_resolved, EvaluationRequest):
        resolved = await resolve_evaluation_async(request_or_resolved, context)
    else:
        resolved = request_or_resolved
        check_required_secrets(resolved.request, context)
    secrets = effective_secrets(resolved.request, context)
    destination = context.output_dir
    destination.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix='.aiq-evals-work-', dir=destination.parent))
    try:
        try:
            result = _redact_result(await _execute_resolved(resolved, context, work_dir), secrets)
        except asyncio.CancelledError as ex:
            # Preserve an inspectable terminal attempt, but do not consume task
            # cancellation: callers still receive CancelledError.
            cancelled = _redact_result(
                _cancelled_result(resolved, work_dir, _redacted_exception_text(ex, secrets)),
                secrets,
            )
            try:
                publish_run(
                    destination,
                    resolved=resolved,
                    result=cancelled,
                    context=context,
                    native_dir=work_dir / 'native',
                )
            except Exception:
                # Cancellation semantics take precedence over a secondary
                # publication failure. There may simply be no terminal bundle.
                pass
            raise
        except (ExecutionError, TimeoutError, OSError) as ex:
            result = _terminal_error_result(
                resolved,
                status='failed',
                kind='execution',
                detail=_redacted_exception_text(ex, secrets),
            )
        return publish_run(
            destination,
            resolved=resolved,
            result=result,
            context=context,
            native_dir=work_dir / 'native',
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def run_evaluation(
    request_or_resolved: EvaluationRequest | ResolvedEvaluation,
    context: ExecutionContext,
) -> RunBundle:
    """Synchronous facade; use ``run_evaluation_async`` inside an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_evaluation_async(request_or_resolved, context))
    raise ActiveEventLoopError(
        'run_evaluation() cannot be called from an active event loop; '
        'await run_evaluation_async() instead'
    )


async def import_evaluation_async(
    request_or_resolved: EvaluationRequest | ResolvedEvaluation,
    source: str | Path,
    context: ExecutionContext,
    *,
    allow_external_symlinks: bool = False,
) -> RunBundle:
    """Import native artifacts and atomically publish an engine-free run bundle.

    Resolution and native reading happen in ``context.worker_python`` when given,
    so an engine-free caller can import, e.g., Inspect ``.eval`` logs. Symlinks in
    ``source`` that leave it are refused unless ``allow_external_symlinks`` is set
    for a trusted source; followed links are listed in the manifest.
    """
    if isinstance(request_or_resolved, EvaluationRequest):
        resolved = await resolve_evaluation_async(request_or_resolved, context)
    else:
        resolved = request_or_resolved
        check_required_secrets(resolved.request, context)
    secrets = effective_secrets(resolved.request, context)
    source_path = Path(source).expanduser().resolve()
    if context.worker_python is None:
        backend = get_backend(resolved.request.engine)
        result = backend.import_results(resolved, str(source_path), context)
    else:
        result = await _import_in_worker(resolved, source_path, context, secrets)
    return publish_run(
        context.output_dir,
        resolved=resolved,
        result=_redact_result(result, secrets),
        context=context,
        native_dir=source,
        external_symlinks='follow' if allow_external_symlinks else 'raise',
    )


async def _import_in_worker(
    resolved: ResolvedEvaluation,
    source: Path,
    context: ExecutionContext,
    secrets: Mapping[str, str],
) -> EvaluationResult:
    with tempfile.TemporaryDirectory(prefix='aiq-evals-import-') as scratch:
        scratch_dir = Path(scratch)
        resolved_path = scratch_dir / 'resolved.json'
        result_path = scratch_dir / 'result.json'
        stderr_path = scratch_dir / 'stderr.log'
        resolved_path.write_text(json.dumps(resolved.to_dict(), sort_keys=True))
        returncode = await _run_worker(
            [
                'import',
                '--resolved', str(resolved_path),
                '--source', str(source),
                '--output-dir', str(context.output_dir),
                '--result', str(result_path),
            ],
            context,
            scratch_dir / 'stdout.log',
            stderr_path,
            secrets,
        )
        try:
            payload = json.loads(result_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError) as ex:
            detail = stderr_path.read_text(errors='replace')[-4000:]
            raise ExecutionError(f'import worker exited with code {returncode} without a result: {detail}') from ex
    _raise_worker_error(payload)
    return EvaluationResult.from_dict(payload['result'])


def import_evaluation(
    request_or_resolved: EvaluationRequest | ResolvedEvaluation,
    source: str | Path,
    context: ExecutionContext,
    *,
    allow_external_symlinks: bool = False,
) -> RunBundle:
    """Synchronous facade for :func:`import_evaluation_async`."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            import_evaluation_async(
                request_or_resolved, source, context, allow_external_symlinks=allow_external_symlinks
            )
        )
    raise ActiveEventLoopError(
        'import_evaluation() cannot be called from an active event loop; '
        'await import_evaluation_async() instead'
    )
