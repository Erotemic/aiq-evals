"""Deterministic OpenAI-compatible chat-completions server for native tests.

Engine-free, so OLMo (LiteLLM/OpenAI Agents) and Inspect (OpenAI provider) can
both exercise a real HTTP endpoint without external services or credentials.
The first request asks for ``tool_name``; after a tool result it answers "4".
"""
import contextlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class DeterministicChatHandler(BaseHTTPRequestHandler):
    calls = 0
    fail = False
    tool_name = "double"

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
                    "function": {"name": type(self).tool_name, "arguments": '{"value":2}'},
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


@contextlib.contextmanager
def chat_server(tool_name: str = "double"):
    DeterministicChatHandler.tool_name = tool_name
    DeterministicChatHandler.calls = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), DeterministicChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        DeterministicChatHandler.tool_name = "double"


class ChatServerCLI:
    """Standalone use: serve until killed, writing the port (kwconf CLI)."""

    @staticmethod
    def main(argv=True) -> int:
        import pathlib

        import kwconf

        class Config(kwconf.Config):
            port_file = kwconf.Value(None, required=True, parser=str, help="Write the bound port here.")

        args = Config.cli(argv=argv, strict=True, special_options=False)
        with chat_server() as port:
            pathlib.Path(args.port_file).write_text(str(port))
            threading.Event().wait()
        return 0


if __name__ == "__main__":
    raise SystemExit(ChatServerCLI.main())
