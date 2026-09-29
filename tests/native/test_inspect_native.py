"""Run only in an environment with the real pinned Inspect runtime installed."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")

from aiq_evals.contracts import EvaluationRequest, ExecutionContext, ModelBinding
from aiq_evals.runner import import_evaluation, run_evaluation


def request(task: str, log_format: str = "eval") -> EvaluationRequest:
    return EvaluationRequest(
        engine="inspect_ai",
        task=f"python:tests.native.inspect_fixture:{task}",
        models=(
            ModelBinding(role="primary", model="local", provider="fixture", revision="local-v1"),
            ModelBinding(role="grader", model="local", provider="fixture", revision="local-v1"),
        ),
        engine_options={"log_format": log_format, "eval_options": {"epochs": 2}},
    )


@pytest.mark.parametrize("task,log_format", [("generation", "eval"), ("tool_task", "eval"), ("generation", "json")])
def test_inspect_native_run_and_import(tmp_path: Path, task: str, log_format: str) -> None:
    req = request(task, log_format)
    bundle = run_evaluation(
        req,
        ExecutionContext(output_dir=tmp_path / "run", worker_python=sys.executable),
    )
    assert bundle.result.status == "succeeded", bundle.result.diagnostics
    assert len(bundle.result.records) == 1
    assert bundle.result.records[0].coverage.status == "complete"
    assert {sample.epoch for sample in bundle.result.samples if sample.epoch} == {1, 2}
    assert all(
        (tmp_path / "run" / sample.native["log_location"]).is_file()
        for sample in bundle.result.samples
        if sample.native.get("kind") == "sample"
    )
    if task == "generation":
        assert {metric.scorer for metric in bundle.result.records[0].metrics} == {"match", "includes"}
    else:
        assert all(
            any(message["role"] == "tool" and message["content"] == "4" for message in sample.trajectory["messages"])
            for sample in bundle.result.samples
            if sample.native.get("kind") == "sample"
        )

    log = next((tmp_path / "run" / "native" / "inspect_ai" / "logs").glob(f"*.{log_format}"))
    imported = import_evaluation(
        req,
        log,
        ExecutionContext(output_dir=tmp_path / "import"),
    )
    assert imported.result.status == "succeeded"
    assert len(imported.result.samples) == len(bundle.result.samples)
    assert (tmp_path / "import" / imported.result.diagnostics["native_logs"][0]["location"]).is_file()
