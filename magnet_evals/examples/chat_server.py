"""Deterministic OpenAI-compatible chat-completions endpoint for the examples.

Engine-free and local, so the OLMo Eval and Inspect agent/tool examples
exercise a real HTTP endpoint without external services or credentials. The
first request in a conversation asks for ``tool_name`` with ``{"value": 2}``;
once a tool result is present it answers "4".

Run it standalone::

    python -m magnet_evals.examples.chat_server --port_file port.txt \\
        [--port 0] [--tool_name aiq_example_double]

and point a model binding's ``provider_options.base_url`` at
``http://127.0.0.1:<port>/v1``.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

DEFAULT_TOOL = 'aiq_example_double'


def _handler(tool_name: str) -> type[BaseHTTPRequestHandler]:
    class DeterministicChatHandler(BaseHTTPRequestHandler):
        calls = 0

        def do_POST(self) -> None:
            size = int(self.headers['Content-Length'])
            request = json.loads(self.rfile.read(size))
            type(self).calls += 1
            if not any(message.get('role') == 'tool' for message in request['messages']):
                message = {
                    'role': 'assistant',
                    'content': None,
                    'tool_calls': [{
                        'id': f'call_{type(self).calls}',
                        'type': 'function',
                        'function': {'name': tool_name, 'arguments': '{"value":2}'},
                    }],
                }
                finish_reason = 'tool_calls'
            else:
                message = {'role': 'assistant', 'content': '4'}
                finish_reason = 'stop'
            body = json.dumps({
                'id': f'chatcmpl-example-{type(self).calls}',
                'object': 'chat.completion',
                'created': int(time.time()),
                'model': request['model'],
                'choices': [{'index': 0, 'message': message, 'finish_reason': finish_reason}],
                'usage': {'prompt_tokens': 5, 'completion_tokens': 2, 'total_tokens': 7},
            }).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    return DeterministicChatHandler


@contextlib.contextmanager
def chat_server(tool_name: str = DEFAULT_TOOL, port: int = 0) -> Iterator[int]:
    """Serve on 127.0.0.1 in a background thread; yields the bound port."""
    server = ThreadingHTTPServer(('127.0.0.1', port), _handler(tool_name))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _cli_class():
    # kwconf is imported only for the CLI: engine environments import this
    # module for chat_server() without it.
    import kwconf

    class ChatServerCLI(kwconf.Config):
        """Serve the deterministic OpenAI-compatible example endpoint."""

        __prog__ = 'python -m magnet_evals.examples.chat_server'

        port_file = kwconf.Value(None, parser=str, help='Write the bound port here once serving.')
        port = kwconf.Value(0, type=int, help='Port to bind (0 picks a free one).')
        tool_name = kwconf.Value(DEFAULT_TOOL, parser=str, help='Tool the first reply asks to call.')

    return ChatServerCLI


def main(argv: list[str] | None = None) -> int:
    cls = _cli_class()
    args = cls.cli(argv=True if argv is None else argv, strict=True, special_options=False)
    with chat_server(args.tool_name, args.port) as port:
        if args.port_file is not None:
            Path(args.port_file).write_text(str(port))
        print(f'serving on http://127.0.0.1:{port}/v1', flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
