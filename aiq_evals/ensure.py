"""Resolve -> reuse/import or execute -> publish (ADR-0002).

``ensure_evaluation`` obtains the result of one fully specified evaluation. It
reuses a validated canonical run when the measurement identity is reusable and
already stored. Otherwise it imports caller-supplied native artifacts or
executes the native engine into a fresh attempt, and promotes a successful
attempt atomically. It schedules nothing and never retries: campaign
scheduling and retry policy belong to the caller (kwdagger/MAGNET, ADR-0006).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from aiq_evals.artifacts import RunBundle
from aiq_evals.contracts import EvaluationRequest, ExecutionContext, ResolvedEvaluation
from aiq_evals.errors import ActiveEventLoopError
from aiq_evals.runner import (
    import_evaluation,
    resolve_evaluation_async,
    run_evaluation_async,
)
from aiq_evals.store import ResultStore

EnsureAction = Literal['reused', 'executed', 'imported']


@dataclass(frozen=True)
class EnsureOutcome:
    """What ``ensure`` did and the run it returns.

    ``run`` is the canonical bundle when the result is reusable and succeeded;
    otherwise it is the attempt bundle, which stays inspectable but is never
    reused. ``attempt`` is the new attempt bundle (``None`` on reuse).
    """

    action: EnsureAction
    run: RunBundle
    resolved: ResolvedEvaluation
    attempt: RunBundle | None
    reuse_reason: str

    @property
    def reused(self) -> bool:
        return self.action == 'reused'


async def ensure_evaluation_async(
    request: EvaluationRequest | ResolvedEvaluation,
    store: ResultStore | str | Path,
    *,
    env: Mapping[str, str] | None = None,
    worker_python: str | None = None,
    timeout_seconds: float | None = None,
    import_source: str | Path | None = None,
    allow_external_symlinks: bool = False,
    verify_checksums: bool = True,
) -> EnsureOutcome:
    store = store if isinstance(store, ResultStore) else ResultStore(store)
    # Operational context; output_dir is replaced by the attempt location.
    base = ExecutionContext(
        output_dir=store.root,
        env=dict(env or {}),
        worker_python=worker_python,
        timeout_seconds=timeout_seconds,
    )
    resolved = (
        request
        if isinstance(request, ResolvedEvaluation)
        else await resolve_evaluation_async(request, base)
    )

    decision = store.check_reuse(resolved, verify_checksums=verify_checksums)
    if decision.bundle is not None:
        return EnsureOutcome('reused', decision.bundle, resolved, None, decision.reason)

    attempt_dir = store.new_attempt_path(resolved)
    context = ExecutionContext(
        output_dir=attempt_dir,
        env=base.env,
        worker_python=base.worker_python,
        timeout_seconds=base.timeout_seconds,
    )
    if import_source is not None:
        action: EnsureAction = 'imported'
        attempt = await asyncio.to_thread(
            import_evaluation, resolved, import_source, context,
            allow_external_symlinks=allow_external_symlinks,
        )
    else:
        action = 'executed'
        attempt = await run_evaluation_async(resolved, context)

    run = attempt
    if resolved.identity.reusable and attempt.result.status == 'succeeded':
        run = await asyncio.to_thread(store.promote, attempt)
    return EnsureOutcome(action, run, resolved, attempt, decision.reason)


def ensure_evaluation(
    request: EvaluationRequest | ResolvedEvaluation,
    store: ResultStore | str | Path,
    **kwargs,
) -> EnsureOutcome:
    """Synchronous facade; use ``ensure_evaluation_async`` inside an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(ensure_evaluation_async(request, store, **kwargs))
    raise ActiveEventLoopError(
        'ensure_evaluation() cannot be called from an active event loop; '
        'await ensure_evaluation_async() instead'
    )
