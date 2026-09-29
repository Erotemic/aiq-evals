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
from typing import Any

from aiq_evals.artifacts import RunBundle, publish_run
from aiq_evals.backends.registry import get_backend
from aiq_evals.contracts import (
    EvaluationRequest,
    EvaluationResult,
    ExecutionContext,
    ResolvedEvaluation,
)
from aiq_evals.errors import ActiveEventLoopError, ExecutionError
from aiq_evals.jsonutil import MIN_REDACTED_VALUE_LENGTH, redact_values


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


async def _execute_in_worker(
    resolved: ResolvedEvaluation,
    context: ExecutionContext,
    work_dir: Path,
) -> EvaluationResult:
    assert context.worker_python is not None
    protocol_dir = work_dir / '.aiq-evals-worker'
    protocol_dir.mkdir(parents=True, exist_ok=True)
    resolved_path = protocol_dir / 'resolved.json'
    result_path = _worker_result_path(work_dir)
    # Worker diagnostics must survive publication, especially when a native
    # runner fails after writing partial artifacts.
    worker_log_dir = work_dir / 'native' / 'aiq_worker'
    worker_log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = worker_log_dir / 'stdout.log'
    stderr_path = worker_log_dir / 'stderr.log'
    resolved_path.write_text(json.dumps(resolved.to_dict(), indent=2, sort_keys=True) + '\n')
    command = [
        context.worker_python,
        '-m',
        'aiq_evals.worker',
        'execute',
        '--resolved',
        str(resolved_path),
        '--output-dir',
        str(work_dir),
        '--result',
        str(result_path),
    ]
    env = os.environ.copy()
    env.update(context.env)
    # Make source-tree execution work without requiring an editable install in
    # the worker environment. Installed distributions also work with this path.
    package_parent = str(Path(__file__).resolve().parent.parent)
    old_pythonpath = env.get('PYTHONPATH')
    env['PYTHONPATH'] = package_parent if not old_pythonpath else package_parent + os.pathsep + old_pythonpath
    # Files rather than pipes: a worker that keeps writing during the
    # cancellation grace period can never block on an unread pipe.
    try:
        with stdout_path.open('wb') as stdout_file, stderr_path.open('wb') as stderr_file:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=stdout_file,
                stderr=stderr_file,
                env=env,
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
        _redact_file(stdout_path, context.env)
        _redact_file(stderr_path, context.env)
    if process.returncode != 0:
        detail = stderr_path.read_text(errors='replace')[-4000:]
        raise ExecutionError(
            f'evaluation worker exited with code {process.returncode}: {detail}'
        )
    try:
        payload = json.loads(result_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as ex:
        raise ExecutionError('evaluation worker did not produce a valid result protocol file') from ex
    return EvaluationResult.from_dict(payload)


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
        )
        return await _execute_in_worker(resolved, worker_context, work_dir)
    direct_context = ExecutionContext(
        output_dir=work_dir,
        env=context.env,
        worker_python=None,
        timeout_seconds=context.timeout_seconds,
    )
    return await backend.execute(resolved, direct_context)


def _redacted_exception_text(ex: BaseException, env: dict[str, str] | Any) -> str:
    text = f'{type(ex).__name__}: {ex}'
    for key, value in dict(env).items():
        if value:
            text = text.replace(value, f'<redacted:{key}>')
    return text


def _redact_result(result: EvaluationResult, context: ExecutionContext) -> EvaluationResult:
    # Adapters retain native exception text/tracebacks, which can quote
    # credentials supplied through the environment; never publish those values.
    if not any(context.env.values()):
        return result
    redacted = EvaluationResult.from_dict(redact_values(result.to_dict(), context.env))
    diagnostics = dict(redacted.diagnostics)
    short = sorted(
        name for name, value in context.env.items()
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
        status=status,  # type: ignore[arg-type]
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
    """Execute and atomically publish one evaluation run.

    This is intentionally *not* ``ensure`` yet: phase 6 owns cache lookup/reuse
    semantics. Phase 2 provides the content-addressed store primitives separately.
    """
    resolved = (
        resolve_evaluation(request_or_resolved)
        if isinstance(request_or_resolved, EvaluationRequest)
        else request_or_resolved
    )
    destination = context.output_dir
    destination.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix='.aiq-evals-work-', dir=destination.parent))
    try:
        try:
            result = _redact_result(await _execute_resolved(resolved, context, work_dir), context)
        except asyncio.CancelledError as ex:
            # Preserve an inspectable terminal attempt, but do not consume task
            # cancellation: callers still receive CancelledError.
            cancelled = _redact_result(
                _cancelled_result(resolved, work_dir, _redacted_exception_text(ex, context.env)),
                context,
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
                detail=_redacted_exception_text(ex, context.env),
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


def import_evaluation(
    request_or_resolved: EvaluationRequest | ResolvedEvaluation,
    source: str | Path,
    context: ExecutionContext,
) -> RunBundle:
    """Import native artifacts and atomically publish an engine-free run bundle."""
    resolved = (
        resolve_evaluation(request_or_resolved)
        if isinstance(request_or_resolved, EvaluationRequest)
        else request_or_resolved
    )
    backend = get_backend(resolved.request.engine)
    result = backend.import_results(resolved, str(Path(source).expanduser().resolve()), context)
    return publish_run(
        context.output_dir,
        resolved=resolved,
        result=result,
        context=context,
        native_dir=source,
    )
