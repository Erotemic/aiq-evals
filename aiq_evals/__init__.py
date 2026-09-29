"""Backend-agnostic evaluation runtime and artifact interface."""

from aiq_evals._version import __version__
from aiq_evals.contracts import (
    EvaluationRequest,
    EvaluationResult,
    ExecutionContext,
    MeasurementIdentity,
    ModelBinding,
    ResolvedEvaluation,
)
from aiq_evals.engines import ENGINE_SPECS, EngineSpec
from aiq_evals.ensure import EnsureOutcome, ensure_evaluation, ensure_evaluation_async
from aiq_evals.outputs import load_run
from aiq_evals.runner import (
    import_evaluation,
    import_evaluation_async,
    resolve_evaluation,
    resolve_evaluation_async,
    run_evaluation,
    run_evaluation_async,
    validate_request,
)
from aiq_evals.store import ResultStore

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
    'resolve_evaluation',
    'resolve_evaluation_async',
    'run_evaluation',
    'run_evaluation_async',
    'validate_request',
]
