"""OLMo runner probe; run in its upstream locked Python 3.12 environment."""

import asyncio
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("olmo_eval")

from aiq_evals.contracts import EvaluationRequest, ExecutionContext, ModelBinding
from aiq_evals.runner import import_evaluation, run_evaluation, run_evaluation_async


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


class _DeterministicChatHandler(BaseHTTPRequestHandler):
    calls = 0
    fail = False

    def do_POST(self) -> None:
        size = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(size))
        type(self).calls += 1
        if type(self).fail:
            body = b'{"error":{"message":"intentional local failure","type":"server_error"}}'
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not any(message.get("role") == "tool" for message in request["messages"]):
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_p1",
                    "type": "function",
                    "function": {"name": "double", "arguments": '{"value":2}'},
                }],
            }
            finish_reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": "4"}
            finish_reason = "stop"
        body = json.dumps({
            "id": f"chatcmpl-p1-{self.calls}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request["model"],
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def _tool_request(port: int, *, failure_gate: bool = False) -> EvaluationRequest:
    harness = {
        "scaffold": "openai_agents",
        "tools": ["double"],
        "scaffold_kwargs": {"enable_compaction": False},
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
