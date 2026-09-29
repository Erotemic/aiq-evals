"""Run only in an environment with the real pinned Inspect runtime installed."""

import asyncio
import contextlib
import inspect
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")

from aiq_evals.artifacts import RunBundle
from aiq_evals.contracts import EvaluationRequest, ExecutionContext, ModelBinding
from aiq_evals.runner import import_evaluation, run_evaluation, run_evaluation_async


def request(task: str, log_format: str = "eval") -> EvaluationRequest:
    return EvaluationRequest(
        engine="inspect_ai",
        task=f"python:tests.native.inspect_fixture:{task}",
        models=(
            ModelBinding(role="primary", model="local", provider="fixture", revision="local-v1"),
            ModelBinding(role="grader", model="grader", provider="fixture", revision="local-v1"),
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


def test_cancel_terminates_owned_child(tmp_path: Path) -> None:
    async def exercise() -> None:
        pid_file = tmp_path / "child.pid"
        req = EvaluationRequest(
            engine="inspect_ai",
            task="python:tests.native.inspect_fixture:generation",
            models=(ModelBinding(role="primary", model="slow", provider="fixture", revision="local-v1"),),
        )
        task = asyncio.create_task(
            run_evaluation_async(
                req,
                ExecutionContext(
                    output_dir=tmp_path / "cancelled",
                    worker_python=sys.executable,
                    env={"AIQ_P1_CHILD_PID_FILE": str(pid_file)},
                ),
            )
        )
        for _ in range(100):
            if pid_file.exists():
                break
            await asyncio.sleep(0.1)
        assert pid_file.exists(), "native provider never started its child"
        child_pid = int(pid_file.read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        for _ in range(50):
            try:
                state = Path(f"/proc/{child_pid}/stat").read_text().split()[2]
            except FileNotFoundError:
                break
            if state == "Z":
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail(f"child process {child_pid} remained running after cancellation")
        assert (tmp_path / "cancelled" / "ATTEMPT_TERMINAL").read_text().strip() == "cancelled"
        assert not (tmp_path / "cancelled" / "RUN_COMPLETE").exists()

    asyncio.run(exercise())


def test_multi_log_and_auxiliary_role(tmp_path: Path) -> None:
    source = Path(__file__).with_name("inspect_fixture.py").resolve()
    req = EvaluationRequest(
        engine="inspect_ai",
        task=str(source),
        models=(
            ModelBinding(role="primary", model="local", provider="fixture", revision="local-v1"),
            ModelBinding(role="grader", model="grader", provider="fixture", revision="local-v1"),
        ),
        engine_options={
            "registration_modules": ["tests.native.inspect_fixture"],
            "eval_options": {"epochs": 2},
        },
    )
    bundle = run_evaluation(
        req,
        ExecutionContext(output_dir=tmp_path / "multi", worker_python=sys.executable),
    )
    assert bundle.result.status == "succeeded", bundle.result.diagnostics
    assert {record.task for record in bundle.result.records} == {
        "generation", "tool_task", "role_task"
    }
    assert len(list((tmp_path / "multi" / "native" / "inspect_ai" / "logs").glob("*.eval"))) == 3
    role_samples = [sample for sample in bundle.result.samples if sample.task == "role_task" and sample.epoch]
    assert len(role_samples) == 2
    assert all(sample.native["metadata"]["grader_output"] == "4" for sample in role_samples)
    assert all(
        {event.get("model") for event in sample.trajectory["events"] if event.get("event") == "model"}
        == {"fixture/grader", "fixture/local"}
        for sample in role_samples
    )
    imported = import_evaluation(
        req,
        tmp_path / "multi" / "native" / "inspect_ai" / "logs",
        ExecutionContext(output_dir=tmp_path / "multi-import"),
    )
    assert imported.result.status == "succeeded"
    assert len(imported.result.records) == 3


def test_explicit_epoch_reducers(tmp_path: Path) -> None:
    req = request("role_task")
    req = EvaluationRequest(
        engine=req.engine,
        task=req.task,
        models=req.models,
    )
    bundle = run_evaluation(
        req,
        ExecutionContext(output_dir=tmp_path / "reducers", worker_python=sys.executable),
    )
    assert bundle.result.status == "succeeded", bundle.result.diagnostics
    assert {sample.epoch for sample in bundle.result.samples if sample.epoch} == {1, 2}
    reductions = [sample for sample in bundle.result.samples if sample.native.get("kind") == "epoch_reduction"]
    assert {sample.native["reducer"] for sample in reductions} == {"mean", "mode"}


def test_sample_error_is_partial(tmp_path: Path) -> None:
    req = EvaluationRequest(
        engine="inspect_ai",
        task="python:tests.native.inspect_failure_fixture:partial_task",
        models=(ModelBinding(role="primary", model="local", provider="fixture", revision="local-v1"),),
        engine_options={"registration_modules": ["tests.native.inspect_fixture"]},
    )
    bundle = run_evaluation(
        req,
        ExecutionContext(output_dir=tmp_path / "partial", worker_python=sys.executable),
    )
    assert len(bundle.result.records) == 1
    assert bundle.result.records[0].coverage.status == "partial"
    assert bundle.result.records[0].coverage.failed == 1


def test_run_level_error_is_failed_with_partial_coverage(tmp_path: Path) -> None:
    req = EvaluationRequest(
        engine="inspect_ai",
        task="python:tests.native.inspect_failure_fixture:run_error_task",
        models=(ModelBinding(role="primary", model="local", provider="fixture", revision="local-v1"),),
        engine_options={
            "registration_modules": ["tests.native.inspect_fixture"],
            # Serial samples make the pre-error completed sample deterministic.
            "eval_options": {"max_samples": 1},
        },
    )
    bundle = run_evaluation(
        req,
        ExecutionContext(output_dir=tmp_path / "error", worker_python=sys.executable),
    )
    assert bundle.result.status == "failed", bundle.result.diagnostics
    assert (tmp_path / "error" / "ATTEMPT_TERMINAL").read_text().strip() == "failed"
    assert not (tmp_path / "error" / "RUN_COMPLETE").exists()
    (record,) = bundle.result.records
    assert record.native_status == "error"
    assert "intentional sample failure" in (record.error or "")
    assert record.metrics == ()
    assert record.coverage.status == "partial"
    assert (record.coverage.expected, record.coverage.processed, record.coverage.failed) == (3, 3, 2)

    log = next((tmp_path / "error" / "native" / "inspect_ai" / "logs").glob("*.eval"))
    imported = import_evaluation(req, log, ExecutionContext(output_dir=tmp_path / "error-import"))
    assert imported.result.status == "failed"
    assert imported.result.records[0].coverage == record.coverage
    assert not (tmp_path / "error-import" / "RUN_COMPLETE").exists()


@pytest.mark.parametrize(
    "sig,native_status,status,processed,failed",
    [
        # Inspect handles SIGINT itself and writes a terminal ``cancelled`` log.
        (signal.SIGINT, "cancelled", "cancelled", 1, 1),
        # SIGKILL (as when an owner kills the process) leaves a nonterminal log.
        (signal.SIGKILL, "started", "incomplete", 0, 0),
    ],
)
def test_native_signal_log_imports_without_success(
    tmp_path: Path, sig: signal.Signals, native_status: str, status: str, processed: int, failed: int
) -> None:
    log_dir = tmp_path / "logs"
    pid_file = tmp_path / "child.pid"
    driver = (
        "import tests.native.inspect_fixture\n"
        "from inspect_ai import eval\n"
        "from tests.native.inspect_failure_fixture import slow_task\n"
        f"eval(slow_task(), model='fixture/slow', log_dir={str(log_dir)!r}, display='none')\n"
    )
    env = dict(os.environ, AIQ_P1_CHILD_PID_FILE=str(pid_file), PYTHONPATH=str(Path.cwd()))
    proc = subprocess.Popen([sys.executable, "-c", driver], env=env)
    try:
        for _ in range(100):
            if pid_file.exists() and pid_file.read_text():
                break
            time.sleep(0.1)
        assert pid_file.exists(), "native provider never started its child"
        proc.send_signal(sig)
        proc.wait(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
        if pid_file.exists() and pid_file.read_text():
            # The sleep child belongs to the fixture provider; this test makes no
            # claim that Inspect cleans it up.
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(pid_file.read_text()), signal.SIGKILL)

    req = EvaluationRequest(
        engine="inspect_ai",
        task="python:tests.native.inspect_failure_fixture:slow_task",
        models=(ModelBinding(role="primary", model="slow", provider="fixture", revision="local-v1"),),
    )
    imported = import_evaluation(req, log_dir, ExecutionContext(output_dir=tmp_path / "import"))
    assert imported.result.status == status
    assert (tmp_path / "import" / "ATTEMPT_TERMINAL").read_text().strip() == status
    assert not (tmp_path / "import" / "RUN_COMPLETE").exists()
    (record,) = imported.result.records
    assert record.native_status == native_status
    assert record.metrics == ()
    assert record.coverage.status == "partial"
    assert (record.coverage.expected, record.coverage.processed, record.coverage.failed) == (1, processed, failed)


def test_active_event_loop_boundary(tmp_path: Path) -> None:
    # P1-06: Inspect's public sync eval() cannot run on a thread with an active
    # loop; the adapter must never call it there, and the aiq-evals sync facade
    # must refuse rather than nest asyncio.run.
    import inspect_ai

    from aiq_evals.backends.inspect_ai.adapter import InspectAIBackend
    from aiq_evals.errors import ActiveEventLoopError
    from tests.native.inspect_fixture import generation

    req = request("generation")

    async def exercise() -> None:
        assert inspect.iscoroutinefunction(inspect_ai.eval_async)
        with pytest.raises(RuntimeError, match="Already running asyncio"):
            inspect_ai.eval(generation(), model="fixture/local", log_dir=str(tmp_path / "raw"), display="none")
        with pytest.raises(ActiveEventLoopError):
            run_evaluation(req, ExecutionContext(output_dir=tmp_path / "facade"))
        backend = InspectAIBackend()
        direct = await backend.execute(backend.resolve(req), ExecutionContext(output_dir=tmp_path / "direct"))
        assert direct.status == "succeeded", direct.diagnostics
        bundle = await run_evaluation_async(
            req, ExecutionContext(output_dir=tmp_path / "worker", worker_python=sys.executable)
        )
        assert bundle.result.status == "succeeded"

    asyncio.run(exercise())


def sandbox_request() -> EvaluationRequest:
    return EvaluationRequest(
        engine="inspect_ai",
        task="python:tests.native.inspect_sandbox_fixture:sandbox_task",
        models=(ModelBinding(role="primary", model="local", provider="fixture", revision="local-v1"),),
        engine_options={"registration_modules": ["tests.native.inspect_fixture"]},
    )


def test_local_sandbox_is_removed_after_completion(tmp_path: Path) -> None:
    record = tmp_path / "sandboxes.txt"
    bundle = run_evaluation(
        sandbox_request(),
        ExecutionContext(
            output_dir=tmp_path / "run",
            worker_python=sys.executable,
            env={"AIQ_P1_SANDBOX_RECORD": str(record)},
        ),
    )
    assert bundle.result.status == "succeeded", bundle.result.diagnostics
    assert any(
        message["role"] == "tool" and message["content"] == "4"
        for sample in bundle.result.samples
        if sample.native.get("kind") == "sample"
        for message in sample.trajectory["messages"]
    )
    sandboxes = record.read_text().split()
    assert sandboxes
    assert not any(Path(directory).exists() for directory in sandboxes)


def test_cancellation_lets_inspect_clean_up_its_sandbox(tmp_path: Path) -> None:
    # Before the SIGINT-first protocol, SIGTERM killed Inspect before
    # sample_cleanup and the local sandbox directory leaked.
    record = tmp_path / "sandboxes.txt"

    async def exercise() -> tuple[Path, int]:
        task = asyncio.create_task(
            run_evaluation_async(
                sandbox_request(),
                ExecutionContext(
                    output_dir=tmp_path / "cancelled",
                    worker_python=sys.executable,
                    env={"AIQ_P1_SANDBOX_RECORD": str(record), "AIQ_P1_SANDBOX_SLOW": "1"},
                ),
            )
        )
        for _ in range(150):
            if record.exists() and record.read_text().strip():
                sandbox_dir = Path(record.read_text().split()[0])
                if (sandbox_dir / "child.pid").exists() and (sandbox_dir / "child.pid").read_text():
                    break
            await asyncio.sleep(0.1)
        else:
            pytest.fail("sandbox tool never started its child")
        child_pid = int((sandbox_dir / "child.pid").read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return sandbox_dir, child_pid

    sandbox_dir, child_pid = asyncio.run(exercise())
    assert not sandbox_dir.exists(), "Inspect local sandbox directory leaked"
    stat = Path(f"/proc/{child_pid}/stat")
    assert not stat.exists() or stat.read_text().split()[2] == "Z"
    root = tmp_path / "cancelled"
    assert (root / "ATTEMPT_TERMINAL").read_text().strip() == "cancelled"
    assert not (root / "RUN_COMPLETE").exists()
    bundle = RunBundle.load(root)
    # Inspect's own cancelled log was written and its facts retained.
    assert [record.native_status for record in bundle.result.records] == ["cancelled"]
    assert list((root / "native" / "inspect_ai" / "logs").glob("*.eval"))
