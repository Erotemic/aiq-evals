"""Backend-agnostic evaluation runtime and artifact interface."""

from magnet_evals._version import __version__
from magnet_evals.artifacts import native_source_identity
from magnet_evals.contracts import (
    EvaluationRequest,
    EvaluationResult,
    ExecutionContext,
    MeasurementIdentity,
    ModelBinding,
    ResolvedEvaluation,
)
from magnet_evals.engines import ENGINE_SPECS, EngineSpec
from magnet_evals.ensure import (
    EnsureOutcome,
    ensure_evaluation,
    ensure_evaluation_async,
)
from magnet_evals.outputs import load_run
from magnet_evals.runner import (
    import_evaluation,
    import_evaluation_async,
    resolve_evaluation,
    resolve_evaluation_async,
    run_evaluation,
    run_evaluation_async,
    validate_request,
)
from magnet_evals.store import ResultStore

__all__ = [
    'ENGINE_SPECS',
    'EngineSpec',
    'EnsureOutcome',
    'EvaluationRequest',
    'EvaluationResult',
    'ExecutionContext',
    'MeasurementIdentity',
    'ModelBinding',
    'ResolvedEvaluation',
    'ResultStore',
    '__version__',
    'ensure_evaluation',
    'ensure_evaluation_async',
    'import_evaluation',
    'import_evaluation_async',
    'load_run',
    'native_source_identity',
    'resolve_evaluation',
    'resolve_evaluation_async',
    'run_evaluation',
    'run_evaluation_async',
    'validate_request',
]
