"""OLMo runner probe; run in its upstream locked Python 3.12 environment."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("olmo_eval")

from aiq_evals.contracts import EvaluationRequest, ExecutionContext, ModelBinding
from aiq_evals.runner import import_evaluation, run_evaluation


def test_registered_task_in_owned_worker(tmp_path: Path) -> None:
    request = EvaluationRequest(
        engine="olmo_eval",
        task="aiq_p1_local",
        models=(ModelBinding(role="primary", model="mock", provider="mock", revision="local-v1"),),
        engine_options={
            "upstream_revision": "73ade80e24f796af55caeb8fd7b75a7f3fd607fd",
            "task_modules": ["tests.native.olmo_fixture"],
        },
    )
    bundle = run_evaluation(
        request,
        ExecutionContext(output_dir=tmp_path / "run", worker_python=sys.executable),
    )
    assert bundle.result.status == "succeeded", bundle.result.diagnostics
    assert len(bundle.result.records) == 1
    assert bundle.result.records[0].coverage.status == "complete"
    assert [(metric.metric, metric.scorer, metric.value) for metric in bundle.result.records[0].metrics] == [
        ("contains_42", "substring_recall", 1.0)
    ]
    assert bundle.result.samples
    native = tmp_path / "run" / "native"
    assert list(native.rglob("metrics.json"))
    assert list(native.rglob("*-requests.jsonl"))
    assert list(native.rglob("*-predictions.jsonl"))
    imported = import_evaluation(
        request,
        native,
        ExecutionContext(output_dir=tmp_path / "import"),
    )
    assert imported.result.status == "succeeded", imported.result.diagnostics
