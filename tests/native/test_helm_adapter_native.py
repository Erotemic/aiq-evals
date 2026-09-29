"""Native HELM adapter acceptance; run in the isolated crfm-helm 0.5.14 worker env."""

import asyncio
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("helm")

from aiq_evals.contracts import EvaluationRequest, ExecutionContext, ModelBinding
from aiq_evals.errors import ArtifactError, RequestValidationError
from aiq_evals.runner import (
    import_evaluation,
    resolve_evaluation,
    run_evaluation,
    run_evaluation_async,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "helm-native"
PLUGIN = "tests.native.helm_plugin_fixture"


def request(task: str, model: str = "simple/model1", **kwargs) -> EvaluationRequest:
    return EvaluationRequest(
        engine="helm",
        task=task,
        task_revision="helm-builtin",
        data_revision="helm-builtin",
        models=(ModelBinding(role="primary", model=model, revision="local-v1"),),
        **kwargs,
    )


def test_fresh_scored_run_and_import(tmp_path: Path) -> None:
    req = request("simple_mcqa", task_options={"max_eval_instances": 1})
    resolved = resolve_evaluation(req)
    assert resolved.native_config["run_spec_names"] == ["simple_mcqa:model=simple_model1"]
    assert resolved.identity.reusable
    bundle = run_evaluation(resolved, ExecutionContext(output_dir=tmp_path / "run", worker_python=sys.executable))
    assert bundle.result.status == "succeeded", bundle.result.diagnostics
    (record,) = bundle.result.records
    assert record.coverage.status == "complete" and record.coverage.processed == 1
    exact = [m for m in record.metrics if m.metric == "exact_match" and m.group == "test" and m.score is None]
    assert len(exact) == 1
    assert bundle.result.samples[0].trajectory["prompt"].rstrip().endswith("Answer:")
    assert (tmp_path / "run" / "RUN_COMPLETE").is_file()
    imported = import_evaluation(
        resolved, tmp_path / "run" / "native" / "helm", ExecutionContext(output_dir=tmp_path / "import")
    )
    assert imported.result.status == "succeeded"
    assert imported.result.records[0].metrics == record.metrics


def test_train_trials_become_epochs(tmp_path: Path) -> None:
    req = request("simple_mcqa", task_options={"max_eval_instances": 2, "num_train_trials": 2})
    bundle = run_evaluation(req, ExecutionContext(output_dir=tmp_path / "run", worker_python=sys.executable))
    assert bundle.result.status == "succeeded", bundle.result.diagnostics
    assert {sample.epoch for sample in bundle.result.samples} == {1, 2}
    assert bundle.result.records[0].coverage.processed == 4


def test_identity_tracks_resolved_run_spec_not_shorthand() -> None:
    one = resolve_evaluation(request("simple_mcqa", task_options={"max_eval_instances": 1}))
    two = resolve_evaluation(request("simple_mcqa", task_options={"max_eval_instances": 2}))
    assert one.identity.digest != two.identity.digest
    assert one.native_config["run_specs"][0]["adapter_spec"]["max_eval_instances"] == 1


def test_resolution_rejects_unknown_model_and_model_in_task() -> None:
    with pytest.raises(RequestValidationError, match="cannot resolve run entry"):
        resolve_evaluation(request("simple_mcqa", model="nonexistent/model"))
    with pytest.raises(RequestValidationError, match="must not name model"):
        resolve_evaluation(request("simple_mcqa:model=simple/model1"))


def test_native_failure_is_failed_with_diagnostics(tmp_path: Path) -> None:
    req = request("aiq_p5_fail", engine_options={"plugins": [PLUGIN]}, task_options={"max_eval_instances": 1})
    resolved = resolve_evaluation(req)
    assert set(resolved.resolved_facts["plugin_digests"]) == {PLUGIN}
    bundle = run_evaluation(resolved, ExecutionContext(output_dir=tmp_path / "run", worker_python=sys.executable))
    assert bundle.result.status == "failed"
    assert "intentional HELM scenario failure" in bundle.result.diagnostics["execution_error"]
    assert not (tmp_path / "run" / "RUN_COMPLETE").exists()
    assert (tmp_path / "run" / "native" / "helm" / "helm-run.stderr.log").is_file()


def test_cancel_terminates_helm_child(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    req = request("aiq_p5_slow", engine_options={"plugins": [PLUGIN]}, task_options={"max_eval_instances": 1})

    async def exercise() -> int:
        task = asyncio.create_task(
            run_evaluation_async(
                req,
                ExecutionContext(
                    output_dir=tmp_path / "cancelled",
                    worker_python=sys.executable,
                    env={"AIQ_P5_CHILD_PID_FILE": str(pid_file)},
                ),
            )
        )
        for _ in range(300):
            if pid_file.exists() and pid_file.read_text():
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail("HELM scenario never started its child")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return int(pid_file.read_text())

    child = asyncio.run(exercise())
    stat = Path(f"/proc/{child}/stat")
    assert not stat.exists() or stat.read_text().split()[2] == "Z"
    assert (tmp_path / "cancelled" / "ATTEMPT_TERMINAL").read_text().strip() == "cancelled"
    assert not (tmp_path / "cancelled" / "RUN_COMPLETE").exists()


def test_import_historical_run_by_exact_resolved_name(tmp_path: Path) -> None:
    req = request("mmlu:subject=philosophy", model="openai/gpt2")
    resolved = resolve_evaluation(req)
    assert resolved.native_config["run_spec_names"] == [
        "mmlu:subject=philosophy,method=multiple_choice_joint,model=openai_gpt2"
    ]
    source = tmp_path / "runs" / resolved.native_config["run_spec_names"][0]
    shutil.copytree(FIXTURES / "mmlu-philosophy-gpt2", source)
    bundle = import_evaluation(resolved, tmp_path / "runs", ExecutionContext(output_dir=tmp_path / "import"))
    assert bundle.result.status == "succeeded"
    assert bundle.result.records[0].coverage.processed == 10

    # Without per-instance stats, coverage is unknown, not inferred from aggregates.
    (source / "per_instance_stats.json").unlink()
    partial = import_evaluation(resolved, tmp_path / "runs", ExecutionContext(output_dir=tmp_path / "partial"))
    assert partial.result.records[0].coverage.status == "unknown"
    assert partial.result.samples == ()
    # Without stats.json the native run did not finish.
    (source / "stats.json").unlink()
    unfinished = import_evaluation(resolved, tmp_path / "runs", ExecutionContext(output_dir=tmp_path / "unfinished"))
    assert unfinished.result.status == "incomplete"
    assert not (tmp_path / "unfinished" / "RUN_COMPLETE").exists()


def test_import_rejects_other_run_specs(tmp_path: Path) -> None:
    resolved = resolve_evaluation(request("simple_mcqa", task_options={"max_eval_instances": 1}))
    with pytest.raises(ArtifactError, match="outside the resolved request"):
        import_evaluation(resolved, FIXTURES / "simple1-fresh", ExecutionContext(output_dir=tmp_path / "x"))
