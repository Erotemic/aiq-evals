"""Filesystem content-addressed store for reusable evaluation runs.

Layout under ``root``::

    runs/<dd>/<digest>/                     canonical successful run (reusable)
    attempts/<dd>/<digest>/<attempt-id>/    every terminal attempt, any status
    attempts/_unkeyed/<attempt-id>/         attempts whose identity is not reusable
    quarantine/<digest>-<stamp>/            canonical runs that later failed validation

Only a validated successful attempt is ever promoted to ``runs/``. Failed,
cancelled, or incomplete attempts stay inspectable under ``attempts/`` and
can neither occupy nor hide the canonical slot. Each attempt is a separate
bundle, so retries never merge or inflate sample records.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from magnet_evals.artifacts import RunBundle, publish_run
from magnet_evals.contracts import (
    EvaluationResult,
    ExecutionContext,
    ResolvedEvaluation,
)
from magnet_evals.errors import ArtifactError, PublicationError

_UNKEYED = '_unkeyed'
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


@dataclass(frozen=True)
class ReuseDecision:
    """Why a canonical run was or was not reusable."""

    bundle: RunBundle | None
    reason: str


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

    def check_reuse(self, resolved: ResolvedEvaluation, *, verify_checksums: bool = True) -> ReuseDecision:
        if not resolved.identity.reusable:
            return ReuseDecision(None, f'identity not reusable: {list(resolved.identity.unknown_reasons)}')
        path = self.run_path(resolved.identity.digest)
        if not path.exists():
            return ReuseDecision(None, 'no canonical run for this measurement identity')
        try:
            bundle = RunBundle.load(path, verify_checksums=verify_checksums)
        except ArtifactError as ex:
            return ReuseDecision(None, f'canonical run failed validation: {ex}')
        if not bundle.complete:
            return ReuseDecision(None, 'canonical run lacks RUN_COMPLETE')
        if bundle.result.status != 'succeeded':
            return ReuseDecision(None, f'canonical run status is {bundle.result.status!r}')
        if bundle.resolved.identity != resolved.identity:
            return ReuseDecision(None, 'canonical run identity differs from the resolved identity')
        if not bundle.manifest.get('reusable'):
            return ReuseDecision(None, 'canonical run manifest is not marked reusable')
        return ReuseDecision(bundle, 'validated canonical run')

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
        existing = self.lookup(resolved)
        if existing is not None:
            return existing
        path = self.run_path(resolved.identity.digest)
        if path.exists():
            self._quarantine(path)
        try:
            return publish_run(
                path, resolved=resolved, result=result, context=context, native_dir=native_dir,
                attempt_metadata=attempt_metadata, manifest_notes=manifest_notes,
            )
        except PublicationError:
            existing = self.lookup(resolved)
            if existing is None:
                raise
            return existing

    def _quarantine(self, path: Path) -> Path:
        """Move an invalid canonical run aside; never delete evidence."""
        target = self.root / 'quarantine' / f'{path.name}-{_stamp()}-{secrets.token_hex(4)}'
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.rename(target)
        except FileNotFoundError:
            pass  # a concurrent publisher already moved or replaced it
        return target

    def promote(self, attempt: RunBundle) -> RunBundle:
        """Promote a successful attempt bundle to the canonical run.

        The canonical bundle keeps the producing attempt's sanitized execution
        context and symlink notes, plus a ``source_attempt`` pointer, rather
        than a context synthesized at promotion time.
        """
        return self.publish(
            resolved=attempt.resolved,
            result=attempt.result,
            context=ExecutionContext(output_dir=self.run_path(attempt.resolved.identity.digest)),
            native_dir=attempt.path / 'native',
            attempt_metadata={
                'execution_context': attempt.attempt.get('execution_context'),
                'source_attempt': {
                    'path': str(attempt.path),
                    'relative_path': _relative_or_none(attempt.path, self.root),
                    'native_artifact_identity': attempt.manifest.get('native_artifact_identity'),
                    'normalized_artifact_identity': attempt.manifest.get('normalized_artifact_identity'),
                },
            },
            manifest_notes={key: attempt.manifest.get(key) for key in _LINK_NOTE_KEYS},
        )


def _relative_or_none(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return None
