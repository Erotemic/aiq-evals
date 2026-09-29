"""Resolve -> reuse/import or execute -> publish (ADR-0002, ADR-0011).

``ensure_evaluation`` obtains the result of one fully specified evaluation.

* Without ``import_source`` it reuses a validated canonical run when the
  measurement identity is reusable and already stored; otherwise it executes
  the native engine into a fresh attempt and promotes a success atomically.
* With ``import_source`` the caller names specific native artifacts, so the
  result is keyed by the measurement *and* the artifacts' content: the same
  content is reused, different content (even at the same path) is imported.
  An import never returns results imported from other artifacts.

Acquisition of a reusable identity is single-flight: concurrent callers for
the same key wait under the store's lock and then reuse what the first caller
published, instead of executing the engine again. It schedules nothing and
never retries: campaign scheduling and retry policy belong to the caller
(kwdagger/MAGNET, ADR-0006). A caller that waited for a failed acquisition
performs its own attempt, exactly as if it had arrived afterwards.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from magnet_evals.artifacts import RunBundle, native_source_identity
from magnet_evals.contracts import (
    EvaluationRequest,
    ExecutionContext,
    ResolvedEvaluation,
)
from magnet_evals.errors import ActiveEventLoopError
from magnet_evals.runner import (
    import_evaluation_async,
    resolve_evaluation_async,
    run_evaluation_async,
)
from magnet_evals.store import ResultStore

EnsureAction = Literal['reused', 'executed', 'imported']


@dataclass(frozen=True)
class EnsureOutcome:
    """What ``ensure`` did and the run it returns.

    ``run`` is the published bundle when the result is reusable and succeeded
    (the canonical run, or for an import the import of that content);
    otherwise it is the attempt bundle, which stays inspectable but is never
    reused. ``attempt`` is the new attempt bundle (``None`` on reuse).
    ``import_identity`` is the native content identity of ``import_source``.
    ``waited`` is true when another caller held the acquisition lock first.
    """

    action: EnsureAction
    run: RunBundle
    resolved: ResolvedEvaluation
    attempt: RunBundle | None
    reuse_reason: str
    import_identity: str | None = None
    waited: bool = False

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
    model_endpoints: Mapping[str, str] | None = None,
    verify_checksums: bool = True,
) -> EnsureOutcome:
    store = store if isinstance(store, ResultStore) else ResultStore(store)
    # Operational context; output_dir is replaced by the attempt location.
    base = ExecutionContext(
        output_dir=store.root,
        env=dict(env or {}),
        worker_python=worker_python,
        timeout_seconds=timeout_seconds,
        model_endpoints=dict(model_endpoints or {}),
    )
    resolved = (
        request
        if isinstance(request, ResolvedEvaluation)
        else await resolve_evaluation_async(request, base)
    )

    if import_source is not None:
        return await _ensure_import(
            resolved, store, base, import_source, allow_external_symlinks, verify_checksums,
        )

    decision = store.check_reuse(resolved, verify_checksums=verify_checksums)
    if decision.bundle is not None:
        return EnsureOutcome('reused', decision.bundle, resolved, None, decision.reason)
    if not resolved.identity.reusable:
        attempt = await run_evaluation_async(resolved, _attempt_context(base, store, resolved))
        return EnsureOutcome('executed', attempt, resolved, attempt, decision.reason)

    async with store.acquisition_lock(resolved.identity.digest) as lock:
        # Another caller may have published between the check and the lock.
        decision = store.check_reuse(resolved, verify_checksums=verify_checksums)
        if decision.bundle is not None:
            return EnsureOutcome('reused', decision.bundle, resolved, None, decision.reason, waited=lock.waited)
        attempt = await run_evaluation_async(resolved, _attempt_context(base, store, resolved))
        run = attempt
        if attempt.result.status == 'succeeded':
            run = await _finish_in_thread(store.promote, attempt)
    return EnsureOutcome('executed', run, resolved, attempt, decision.reason, waited=lock.waited)


async def _ensure_import(
    resolved: ResolvedEvaluation,
    store: ResultStore,
    base: ExecutionContext,
    import_source: str | Path,
    allow_external_symlinks: bool,
    verify_checksums: bool,
) -> EnsureOutcome:
    source_identity = await asyncio.to_thread(
        native_source_identity, import_source, allow_external_symlinks=allow_external_symlinks,
    )

    async def import_attempt() -> RunBundle:
        return await import_evaluation_async(
            resolved, import_source, _attempt_context(base, store, resolved),
            allow_external_symlinks=allow_external_symlinks,
        )

    if not resolved.identity.reusable:
        attempt = await import_attempt()
        reason = f'identity not reusable: {list(resolved.identity.unknown_reasons)}'
        return EnsureOutcome('imported', attempt, resolved, attempt, reason, source_identity)
    digest = resolved.identity.digest
    decision = store.check_import_reuse(resolved, source_identity, verify_checksums=verify_checksums)
    if decision.bundle is not None:
        return EnsureOutcome('reused', decision.bundle, resolved, None, decision.reason, source_identity)
    async with store.acquisition_lock(digest, source_identity) as lock:
        decision = store.check_import_reuse(resolved, source_identity, verify_checksums=verify_checksums)
        if decision.bundle is not None:
            return EnsureOutcome(
                'reused', decision.bundle, resolved, None, decision.reason, source_identity, lock.waited,
            )
        attempt = await import_attempt()
        run = attempt
        if attempt.result.status == 'succeeded':
            run = await _finish_in_thread(store.promote_import, attempt)
            # The first valid result also seeds the canonical run; canonical
            # publication always happens under the measurement's own lock.
            async with store.acquisition_lock(digest):
                await _finish_in_thread(store.seed_canonical, attempt)
    # The files may have changed between hashing and copying; report what was
    # actually imported.
    imported_identity = str(attempt.manifest.get('native_artifact_identity') or source_identity)
    return EnsureOutcome('imported', run, resolved, attempt, decision.reason, imported_identity, lock.waited)


async def _finish_in_thread(func, attempt: RunBundle):
    """Run a publication step to completion even if the caller is cancelled.

    Publication runs in a thread that cancellation cannot stop. Returning
    early would release the acquisition lock while the thread is still
    publishing, and a waiter would then find nothing and execute again. On
    cancellation, wait for the thread, then re-raise.
    """
    task = asyncio.ensure_future(asyncio.to_thread(func, attempt))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.wait({task})
            except asyncio.CancelledError:
                continue
        raise


def _attempt_context(base: ExecutionContext, store: ResultStore, resolved: ResolvedEvaluation) -> ExecutionContext:
    return ExecutionContext(
        output_dir=store.new_attempt_path(resolved),
        env=base.env,
        worker_python=base.worker_python,
        timeout_seconds=base.timeout_seconds,
        model_endpoints=base.model_endpoints,
    )


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
