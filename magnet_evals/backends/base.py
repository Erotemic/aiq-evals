"""Backend protocol implemented by native evaluation adapters."""
from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from magnet_evals.contracts import (
    EvaluationRequest,
    EvaluationResult,
    ExecutionContext,
    ResolvedEvaluation,
)


@runtime_checkable
class EvaluationBackend(Protocol):
    """One native evaluation engine integration."""

    key: str
    adapter_version: str

    def capabilities(self) -> Mapping[str, Any]: ...

    def validate_request(self, request: EvaluationRequest) -> None: ...

    def resolve(self, request: EvaluationRequest) -> ResolvedEvaluation: ...

    async def execute(
        self,
        resolved: ResolvedEvaluation,
        context: ExecutionContext,
    ) -> EvaluationResult: ...

    def import_results(
        self,
        resolved: ResolvedEvaluation,
        source: str,
        context: ExecutionContext,
    ) -> EvaluationResult: ...
