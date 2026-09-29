"""Filesystem content-addressed store for reusable evaluation runs.

Layout under ``root``::

    runs/<dd>/<digest>/                     canonical successful run (reusable)
    imports/<dd>/<digest>/<native-id>/      successful import of specific native content
    attempts/<dd>/<digest>/<attempt-id>/    every terminal attempt, any status
    attempts/_unkeyed/<attempt-id>/         attempts whose identity is not reusable
    quarantine/<name>-<stamp>/              published runs that later failed validation
    locks/<dd>/<key>.lock                   single-flight acquisition locks

Only a validated successful attempt is ever promoted to ``runs/`` or
``imports/``. Failed, cancelled, or incomplete attempts stay inspectable under
``attempts/`` and can neither occupy nor hide a published slot. Each attempt
is a separate bundle, so retries never merge or inflate sample records.

The canonical run answers "the result of this measurement": the first valid
result, executed or imported. An import is also published under its native
content identity (ADR-0011), so importing different native artifacts for the
same measurement never silently returns the earlier ones.

``acquisition_lock`` makes acquiring one reusable measurement single-flight
across threads and processes sharing the store (ADR-0011): concurrent callers
wait for the one that executes and then reuse its result.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import os
import secrets
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, AsyncIterator, Mapping

from magnet_evals.artifacts import RunBundle, publish_run
from magnet_evals.contracts import (
    EvaluationResult,
    ExecutionContext,
    ResolvedEvaluation,
)
from magnet_evals.errors import ArtifactError, PublicationError

_UNKEYED = '_unkeyed'
# POSIX: cross-process flock. Elsewhere only in-process exclusion applies.
fcntl: ModuleType | None = importlib.import_module('fcntl') if os.name == 'posix' else None
_LINK_NOTE_KEYS = (
    'excluded_external_symlinks', 'followed_external_symlinks', 'skipped_non_regular_files',
)


def _stamp() -> str:
    # Sortable UTC time with microseconds: attempt directories list in order.
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')


def _check_digest(digest: str) -> str:
    if len(digest) < 8 or any(ch not in '0123456789abcdef' for ch in digest.lower()):
        raise ValueError(f'invalid measurement digest {digest!r}')
    return digest.lower()


# Lock files held by this process. flock() already excludes a second open file
# description in the same process on local filesystems; this set also covers
# filesystems that emulate flock with per-process POSIX locks (e.g. NFS).
_HELD_LOCKS: set[str] = set()
_HELD_GUARD = threading.Lock()
LOCK_POLL_SECONDS = 0.05


def _try_lock(path: Path) -> int | None:
    with _HELD_GUARD:
        if str(path) in _HELD_LOCKS:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        if fcntl is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                return None
            except BaseException:
                os.close(fd)
                raise
        _HELD_LOCKS.add(str(path))
    # Who holds it, for a human looking at a stuck acquisition. Best-effort: a
    # failed write (e.g. a full disk) must not leave the lock held forever.
    try:
        holder = json.dumps({'pid': os.getpid(), 'host': socket.gethostname(), 'since': _stamp()})
        os.ftruncate(fd, 0)
        os.write(fd, holder.encode() + b'\n')
    except OSError:
        pass
    return fd


def _unlock(path: Path, fd: int) -> None:
    with _HELD_GUARD:
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
            _HELD_LOCKS.discard(str(path))


@dataclass(frozen=True)
class ReuseDecision:
    """Why a canonical run was or was not reusable."""

    bundle: RunBundle | None
    reason: str


@dataclass(frozen=True)
class Acquisition:
    """A held acquisition lock; ``waited`` if another holder had it first."""

    path: Path
    waited: bool


@dataclass(frozen=True)
class ResultStore:
    root: Path

    def __init__(self, root: str | Path):
        object.__setattr__(self, 'root', Path(root).expanduser().resolve())

    def run_path(self, digest: str) -> Path:
        digest = _check_digest(digest)
        return self.root / 'runs' / digest[:2] / digest

    def new_attempt_path(self, resolved: ResolvedEvaluation) -> Path:
        """A fresh, unique attempt directory (not yet created)."""
        attempt_id = f'{_stamp()}-{secrets.token_hex(4)}'
        if not resolved.identity.reusable:
            return self.root / 'attempts' / _UNKEYED / attempt_id
        digest = _check_digest(resolved.identity.digest)
        return self.root / 'attempts' / digest[:2] / digest / attempt_id

    def attempts(self, digest: str) -> list[RunBundle]:
        """All loadable terminal attempts for a measurement, oldest first."""
        digest = _check_digest(digest)
        root = self.root / 'attempts' / digest[:2] / digest
        bundles = []
        for path in sorted(root.iterdir()) if root.is_dir() else []:
            try:
                bundles.append(RunBundle.load(path, verify_checksums=False))
            except ArtifactError:
                continue
        return bundles

    def import_path(self, digest: str, native_identity: str) -> Path:
        digest = _check_digest(digest)
        return self.root / 'imports' / digest[:2] / digest / _check_digest(native_identity)

    def lock_path(self, digest: str, *qualifiers: str) -> Path:
        """Lock file for a measurement digest, optionally qualified (an import's content)."""
        parts = [_check_digest(digest), *(_check_digest(q) for q in qualifiers)]
        return self.root / 'locks' / parts[0][:2] / ('-'.join(parts) + '.lock')

    @contextlib.asynccontextmanager
    async def acquisition_lock(self, digest: str, *qualifiers: str) -> AsyncIterator['Acquisition']:
        """Hold the single-flight lock for one acquisition key (ADR-0011).

        The key is a measurement digest, qualified by the native content
        identity for an import. The lock is an ``flock`` on a file under
        ``locks/``, so it spans processes sharing the store and is released by
        the kernel if its holder dies. Waiting polls, so it stays cancellable.
        The yielded ``Acquisition.waited`` says whether another holder came
        first, i.e. whether the caller should look for its result again.
        """
        path = self.lock_path(digest, *qualifiers)
        waited = False
        while (fd := _try_lock(path)) is None:
            waited = True
            await asyncio.sleep(LOCK_POLL_SECONDS)
        try:
            yield Acquisition(path, waited)
        finally:
            _unlock(path, fd)

    def check_reuse(self, resolved: ResolvedEvaluation, *, verify_checksums: bool = True) -> ReuseDecision:
        if not resolved.identity.reusable:
            return ReuseDecision(None, f'identity not reusable: {list(resolved.identity.unknown_reasons)}')
        return self._check_published(
            self.run_path(resolved.identity.digest), resolved, verify_checksums,
            missing='no canonical run for this measurement identity', label='canonical run',
        )

    def check_import_reuse(
        self, resolved: ResolvedEvaluation, native_identity: str, *, verify_checksums: bool = True,
    ) -> ReuseDecision:
        """Reuse only an import of exactly this native content for this measurement."""
        if not resolved.identity.reusable:
            return ReuseDecision(None, f'identity not reusable: {list(resolved.identity.unknown_reasons)}')
        decision = self._check_published(
            self.import_path(resolved.identity.digest, native_identity), resolved, verify_checksums,
            missing='these native artifacts have not been imported for this measurement',
            label='stored import',
        )
        if decision.bundle is not None and decision.bundle.manifest.get('native_artifact_identity') != native_identity:
            return ReuseDecision(None, 'stored import holds different native content')
        return decision

    def _check_published(
        self, path: Path, resolved: ResolvedEvaluation, verify_checksums: bool, *, missing: str, label: str,
    ) -> ReuseDecision:
        if not path.exists():
            return ReuseDecision(None, missing)
        try:
            bundle = RunBundle.load(path, verify_checksums=verify_checksums)
        except ArtifactError as ex:
            return ReuseDecision(None, f'{label} failed validation: {ex}')
        if not bundle.complete:
            return ReuseDecision(None, f'{label} lacks RUN_COMPLETE')
        if bundle.result.status != 'succeeded':
            return ReuseDecision(None, f'{label} status is {bundle.result.status!r}')
        if bundle.resolved.identity != resolved.identity:
            return ReuseDecision(None, f'{label} identity differs from the resolved identity')
        if not bundle.manifest.get('reusable'):
            return ReuseDecision(None, f'{label} manifest is not marked reusable')
        return ReuseDecision(bundle, f'validated {label}')

    def lookup(self, resolved: ResolvedEvaluation, *, verify_checksums: bool = True) -> RunBundle | None:
        return self.check_reuse(resolved, verify_checksums=verify_checksums).bundle

    def publish(
        self,
        *,
        resolved: ResolvedEvaluation,
        result: EvaluationResult,
        context: ExecutionContext,
        native_dir: str | Path | None = None,
        attempt_metadata: Mapping[str, Any] | None = None,
        manifest_notes: Mapping[str, Any] | None = None,
    ) -> RunBundle:
        """Publish a successful reusable result as the canonical run.

        Returns the existing canonical run when one already validates (e.g. a
        concurrent ensure won the race).
        """
        if not resolved.identity.reusable:
            raise ValueError(
                'cannot publish a non-reusable measurement to the content-addressed store; '
                f'unknown identity facts: {resolved.identity.unknown_reasons}'
            )
        if result.status != 'succeeded':
            raise ValueError(
                f'only succeeded results become canonical; got {result.status!r} '
                '(publish the attempt under attempts/ instead)'
            )
        return self._publish_at(
            self.run_path(resolved.identity.digest),
            lambda: self.lookup(resolved),
            resolved=resolved, result=result, context=context, native_dir=native_dir,
            attempt_metadata=attempt_metadata, manifest_notes=manifest_notes,
        )

    def _publish_at(self, path: Path, existing_valid, **publish_kwargs: Any) -> RunBundle:
        existing = existing_valid()
        if existing is not None:
            return existing
        if path.exists() and existing_valid() is None:
            # Re-checked: a concurrent publisher may have just written a valid run.
            self._quarantine(path)
        try:
            return publish_run(path, **publish_kwargs)
        except PublicationError:
            existing = existing_valid()
            if existing is None:
                raise
            return existing

    def _quarantine(self, path: Path) -> Path:
        """Move an invalid published run aside; never delete evidence."""
        target = self.root / 'quarantine' / f'{path.name}-{_stamp()}-{secrets.token_hex(4)}'
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.rename(target)
        except FileNotFoundError:
            pass  # a concurrent publisher already moved or replaced it
        return target

    def _promotion_kwargs(self, attempt: RunBundle, destination: Path) -> dict[str, Any]:
        return {
            'resolved': attempt.resolved,
            'result': attempt.result,
            'context': ExecutionContext(output_dir=destination),
            'native_dir': attempt.path / 'native',
            'attempt_metadata': {
                'execution_context': attempt.attempt.get('execution_context'),
                'source_attempt': {
                    'path': str(attempt.path),
                    'relative_path': _relative_or_none(attempt.path, self.root),
                    'native_artifact_identity': attempt.manifest.get('native_artifact_identity'),
                    'normalized_artifact_identity': attempt.manifest.get('normalized_artifact_identity'),
                },
            },
            'manifest_notes': {key: attempt.manifest.get(key) for key in _LINK_NOTE_KEYS},
        }

    def promote(self, attempt: RunBundle) -> RunBundle:
        """Promote a successful attempt bundle to the canonical run.

        The canonical bundle keeps the producing attempt's sanitized execution
        context and symlink notes, plus a ``source_attempt`` pointer, rather
        than a context synthesized at promotion time.
        """
        path = self.run_path(attempt.resolved.identity.digest)
        return self.publish(**self._promotion_kwargs(attempt, path))

    def promote_import(self, attempt: RunBundle) -> RunBundle:
        """Publish a successful import under its native content identity.

        Returns the import of *this* content, never an earlier one. Seeding the
        measurement's canonical run from it is :meth:`seed_canonical`, which
        ``ensure`` calls under the measurement's own acquisition lock.
        """
        resolved = attempt.resolved
        if not resolved.identity.reusable or attempt.result.status != 'succeeded':
            raise ValueError('only a succeeded, reusable import can be published')
        native_identity = str(attempt.manifest['native_artifact_identity'])
        path = self.import_path(resolved.identity.digest, native_identity)
        return self._publish_at(
            path,
            lambda: self.check_import_reuse(resolved, native_identity).bundle,
            **self._promotion_kwargs(attempt, path),
        )

    def seed_canonical(self, attempt: RunBundle) -> RunBundle | None:
        """Make a successful attempt the canonical run if the measurement has none.

        The first valid result of a measurement, executed or imported, becomes
        canonical, so an import can satisfy later execute-or-reuse requests. An
        existing valid canonical run is kept. Returns the canonical run, or
        ``None`` if publication lost a race it could not resolve.
        """
        try:
            return self.promote(attempt)
        except PublicationError:
            return self.lookup(attempt.resolved)


def _relative_or_none(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return None
