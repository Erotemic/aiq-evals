"""Filesystem content-addressed store for reusable evaluation runs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aiq_evals.artifacts import RunBundle, publish_run
from aiq_evals.contracts import EvaluationResult, ExecutionContext, ResolvedEvaluation
from aiq_evals.errors import ArtifactError


@dataclass(frozen=True)
class ResultStore:
    root: Path

    def __init__(self, root: str | Path):
        object.__setattr__(self, 'root', Path(root).expanduser().resolve())

    def run_path(self, digest: str) -> Path:
        if len(digest) < 8 or any(ch not in '0123456789abcdef' for ch in digest.lower()):
            raise ValueError(f'invalid measurement digest {digest!r}')
        digest = digest.lower()
        return self.root / 'runs' / digest[:2] / digest

    def lookup(self, resolved: ResolvedEvaluation, *, verify_checksums: bool = True) -> RunBundle | None:
        if not resolved.identity.reusable:
            return None
        path = self.run_path(resolved.identity.digest)
        if not path.exists():
            return None
        try:
            bundle = RunBundle.load(path, verify_checksums=verify_checksums)
        except ArtifactError:
            return None
        if not bundle.complete:
            return None
        if bundle.result.status != 'succeeded':
            return None
        if bundle.resolved.identity.digest != resolved.identity.digest:
            return None
        return bundle

    def publish(
        self,
        *,
        resolved: ResolvedEvaluation,
        result: EvaluationResult,
        context: ExecutionContext,
        native_dir: str | Path | None = None,
    ) -> RunBundle:
        if not resolved.identity.reusable:
            raise ValueError(
                'cannot publish a non-reusable measurement to the content-addressed store; '
                f'unknown identity facts: {resolved.identity.unknown_reasons}'
            )
        path = self.run_path(resolved.identity.digest)
        existing = self.lookup(resolved)
        if existing is not None:
            return existing
        return publish_run(
            path,
            resolved=resolved,
            result=result,
            context=context,
            native_dir=native_dir,
        )
