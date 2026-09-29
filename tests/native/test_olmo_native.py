"""OLMo runner probe; run in its upstream locked Python 3.12 environment."""

import asyncio
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.native.chat_server import (
    DeterministicChatHandler as _DeterministicChatHandler,
)
from tests.native.chat_server import chat_server as _chat_server

pytest.importorskip("olmo_eval")

from magnet_evals.contracts import EvaluationRequest, ExecutionContext, ModelBinding
from magnet_evals.runner import import_evaluation, run_evaluation, run_evaluation_async


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


def test_cancel_terminates_native_worker_tree(tmp_path: Path) -> None:
    async def exercise() -> None:
        pid_file = tmp_path / "child.pid"
        request = EvaluationRequest(
            engine="olmo_eval",
            task="aiq_p1_slow",
            models=(ModelBinding(role="primary", model="mock", provider="mock", revision="local-v1"),),
            engine_options={
                "upstream_revision": "73ade80e24f796af55caeb8fd7b75a7f3fd607fd",
                "task_modules": ["tests.native.olmo_fixture"],
            },
        )
        task = asyncio.create_task(
            run_evaluation_async(
                request,
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
        assert pid_file.exists(), "native task never started its child"
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


def _tool_request(
    port: int, *, failure_gate: bool = False, tool: str = "double", **harness_extra
) -> EvaluationRequest:
    harness = {
        "scaffold": "openai_agents",
        "tools": [tool],
        "scaffold_kwargs": {"enable_compaction": False},
        **harness_extra,
    }
    if failure_gate:
        harness["max_hard_failure_rate"] = 0.0
    return EvaluationRequest(
        engine="olmo_eval",
        task="aiq_p1_tool",
        models=(ModelBinding(
            role="primary",
            model="gpt-4o-mini",
            provider="litellm",
            revision="local-script-v1",
            provider_options={"base_url": f"http://127.0.0.1:{port}/v1"},
        ),),
        engine_options={
            "upstream_revision": "73ade80e24f796af55caeb8fd7b75a7f3fd607fd",
            "task_modules": ["tests.native.olmo_fixture"],
            "harness_config": harness,
        },
    )


def test_native_agent_invokes_registered_tool(tmp_path: Path) -> None:
    pytest.importorskip("agents")
    _DeterministicChatHandler.calls = 0
    _DeterministicChatHandler.fail = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DeterministicChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = _tool_request(server.server_port)
        bundle = run_evaluation(
            request,
            ExecutionContext(
                output_dir=tmp_path / "tool",
                worker_python=sys.executable,
                env={"OPENAI_API_KEY": "local-fixture"},
            ),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert bundle.result.status == "succeeded", bundle.result.diagnostics
    assert _DeterministicChatHandler.calls == 2
    assert bundle.result.records[0].metrics[0].value == 1.0
    turns = bundle.result.samples[0].trajectory["turns"]
    assert [turn["role"] for turn in turns] == ["assistant", "tool", "assistant"]
    assert turns[1]["tool_results"][0]["content"] == "4"
    assert list((tmp_path / "tool" / "native" / "predictions").rglob("*.jsonl"))
    imported = import_evaluation(
        request,
        tmp_path / "tool" / "native",
        ExecutionContext(output_dir=tmp_path / "tool-import"),
    )
    assert imported.result.status == "succeeded"
    assert imported.result.samples[0].trajectory["turns"][1]["tool_results"][0]["content"] == "4"


def test_hard_failure_retains_diagnostics(tmp_path: Path) -> None:
    pytest.importorskip("agents")
    _DeterministicChatHandler.calls = 0
    _DeterministicChatHandler.fail = True
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DeterministicChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        bundle = run_evaluation(
            _tool_request(server.server_port, failure_gate=True),
            ExecutionContext(
                output_dir=tmp_path / "failed",
                worker_python=sys.executable,
                env={"OPENAI_API_KEY": "local-fixture"},
            ),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        _DeterministicChatHandler.fail = False
    assert _DeterministicChatHandler.calls > 0
    assert bundle.result.status == "failed", bundle.result.diagnostics
    assert (tmp_path / "failed" / "native" / "metrics.json").is_file()
    assert bundle.result.records[0].coverage.processed == 1
    assert bundle.result.records[0].coverage.saved == 0
    assert bundle.result.records[0].coverage.failed == 1
    assert not (tmp_path / "failed" / "RUN_COMPLETE").exists()


def test_native_multi_task_suite(tmp_path: Path) -> None:
    request = EvaluationRequest(
        engine="olmo_eval",
        task="aiq_p1_multi",
        models=(ModelBinding(role="primary", model="mock", provider="mock", revision="local-v1"),),
        engine_options={
            "upstream_revision": "73ade80e24f796af55caeb8fd7b75a7f3fd607fd",
            "task_modules": ["tests.native.olmo_fixture"],
        },
    )
    bundle = run_evaluation(
        request,
        ExecutionContext(output_dir=tmp_path / "multi", worker_python=sys.executable),
    )
    assert bundle.result.status == "succeeded", bundle.result.diagnostics
    assert {record.task for record in bundle.result.records} == {"aiq_p1_local", "aiq_p1_local_alt"}
    assert all(record.coverage.status == "complete" for record in bundle.result.records)
    imported = import_evaluation(
        request,
        tmp_path / "multi" / "native",
        ExecutionContext(output_dir=tmp_path / "multi-import"),
    )
    assert len(imported.result.records) == 2
    # Task names prefix each other; samples must not fall back to file stems.
    for result in (bundle.result, imported.result):
        assert {sample.task for sample in result.samples} == {"aiq_p1_local", "aiq_p1_local_alt"}


# The deliberately failing sync runner.run() leaves its run_async() coroutine unawaited.
@pytest.mark.filterwarnings("ignore:coroutine 'AsyncEvalRunner.run_async' was never awaited")
def test_active_event_loop_boundary(tmp_path: Path) -> None:
    # P1-06: AsyncEvalRunner.run() is asyncio.run(run_async()) at the pin and
    # fails inside an active loop; the adapter awaits run_async() instead, and
    # the aiq-evals sync facade refuses rather than nesting asyncio.run.
    import inspect

    from magnet_evals.backends.olmo_eval import adapter as olmo_adapter
    from magnet_evals.errors import ActiveEventLoopError

    request = EvaluationRequest(
        engine="olmo_eval",
        task="aiq_p1_local",
        models=(ModelBinding(role="primary", model="mock", provider="mock", revision="local-v1"),),
        engine_options={
            "upstream_revision": "73ade80e24f796af55caeb8fd7b75a7f3fd607fd",
            "task_modules": ["tests.native.olmo_fixture"],
        },
    )
    backend = olmo_adapter.OlmoEvalBackend()
    resolved = backend.resolve(request)
    harness_cls, runner_cls, *_ = olmo_adapter._native_symbols()
    assert inspect.iscoroutinefunction(runner_cls.run_async)
    assert not inspect.iscoroutinefunction(runner_cls.run)

    async def exercise() -> None:
        runner = runner_cls(
            harness_config=harness_cls.from_dict(dict(resolved.native_config["harness_config"])),
            task_specs=list(resolved.native_config["task_specs"]),
            output_dir=str(tmp_path / "raw"),
        )
        with pytest.raises(RuntimeError, match="cannot be called from a running event loop"):
            runner.run()
        with pytest.raises(ActiveEventLoopError):
            run_evaluation(request, ExecutionContext(output_dir=tmp_path / "facade"))
        direct = await backend.execute(resolved, ExecutionContext(output_dir=tmp_path / "direct"))
        assert direct.status == "succeeded", direct.diagnostics
        bundle = await run_evaluation_async(
            request, ExecutionContext(output_dir=tmp_path / "worker", worker_python=sys.executable)
        )
        assert bundle.result.status == "succeeded"

    asyncio.run(exercise())





def test_max_turns_limit_changes_native_trajectory(tmp_path: Path) -> None:
    # P7: max_turns is a native measurement input (it enters identity) and the
    # scaffold stops after one model turn: assistant/tool, no final assistant turn.
    pytest.importorskip("agents")
    from magnet_evals.runner import resolve_evaluation

    with _chat_server() as port:
        unlimited = _tool_request(port)
        limited = _tool_request(port, max_turns=1)
        assert resolve_evaluation(unlimited).identity.digest != resolve_evaluation(limited).identity.digest
        bundle = run_evaluation(
            limited,
            ExecutionContext(output_dir=tmp_path / "turns", worker_python=sys.executable,
                             env={"OPENAI_API_KEY": "local-fixture"}),
        )
    assert bundle.result.status == "succeeded", bundle.result.diagnostics
    roles = [turn["role"] for turn in bundle.result.samples[0].trajectory["turns"]]
    assert roles == ["assistant", "tool"]


def test_crashing_tool_is_reported_to_the_model(tmp_path: Path) -> None:
    # P7 error mapping at this pin: the OpenAI Agents scaffold turns a tool
    # exception into an ordinary tool result string the model sees, with
    # is_error False. The failure survives only as text; aiq-evals keeps the
    # native record and does not invent an error flag. The sample completes.
    pytest.importorskip("agents")
    with _chat_server("crash") as port:
        bundle = run_evaluation(
            _tool_request(port, tool="crash"),
            ExecutionContext(output_dir=tmp_path / "crash", worker_python=sys.executable,
                             env={"OPENAI_API_KEY": "local-fixture"}),
        )
    turns = bundle.result.samples[0].trajectory["turns"]
    results = [result for turn in turns for result in turn.get("tool_results") or []]
    assert results and results[0]["is_error"] is False
    assert "An error occurred while running the tool" in results[0]["content"]
    assert "tool crashed" in results[0]["content"]
    assert bundle.result.records[0].coverage.status == "complete"


def test_leased_endpoint_override_reaches_the_provider(tmp_path: Path) -> None:
    # M8 support: the request's base_url is dead; the operational override wins.
    pytest.importorskip("agents")
    from dataclasses import replace

    with _chat_server() as port:
        request = _tool_request(9)  # base_url http://127.0.0.1:9/v1 is unreachable
        bundle = run_evaluation(
            request,
            ExecutionContext(
                output_dir=tmp_path / "run", worker_python=sys.executable,
                env={"OPENAI_API_KEY": "local-fixture"},
                model_endpoints={"primary": f"http://127.0.0.1:{port}/v1"},
            ),
        )
        calls = _DeterministicChatHandler.calls
    assert bundle.result.status == "succeeded", bundle.result.diagnostics
    assert calls >= 2
    del replace
