"""Engine-free OLMo native import used by regression tests and golden generation."""
from __future__ import annotations

from pathlib import Path

from magnet_evals.backends.olmo_eval.adapter import OlmoEvalBackend
from magnet_evals.contracts import (
    EvaluationRequest,
    EvaluationResult,
    ExecutionContext,
    MeasurementIdentity,
    ModelBinding,
    ResolvedEvaluation,
)

OLMO_ROOT = Path(__file__).resolve().parents[1] / 'fixtures' / 'olmo-native'


def import_fixture(key: str, tasks: list[str], output_dir: Path | None = None) -> EvaluationResult:
    # OLMo import reads metrics/prediction files only; resolution is what needs
    # the engine, so construct the resolved evaluation directly.
    request = EvaluationRequest(
        engine='olmo_eval',
        task=tasks[0],
        models=(ModelBinding(role='primary', model='mock', provider='mock', revision='local-v1'),),
    )
    resolved = ResolvedEvaluation(
        request=request,
        adapter_version='regression',
        engine_version=None,
        native_config={'resolved_task_specs': tasks},
        identity=MeasurementIdentity(algorithm='regression', digest='0' * 64, reusable=False),
    )
    return OlmoEvalBackend().import_results(
        resolved,
        str(OLMO_ROOT / key),
        ExecutionContext(output_dir=output_dir or OLMO_ROOT),
    )
