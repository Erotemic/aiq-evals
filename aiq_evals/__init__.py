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
from aiq_evals.outputs import load_run
from aiq_evals.runner import (
    import_evaluation,
    resolve_evaluation,
    run_evaluation,
    run_evaluation_async,
    validate_request,
)
from aiq_evals.store import ResultStore

__all__ = [
    'ENGINE_SPECS',
    'EngineSpec',
    'EvaluationRequest',
    'EvaluationResult',
    'ExecutionContext',
    'MeasurementIdentity',
    'ModelBinding',
    'ResolvedEvaluation',
    'ResultStore',
    '__version__',
    'import_evaluation',
    'load_run',
    'resolve_evaluation',
    'run_evaluation',
    'run_evaluation_async',
    'validate_request',
]
