"""Private subprocess protocol for isolated native engine execution."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from aiq_evals.backends.registry import get_backend
from aiq_evals.contracts import EvaluationRequest, ExecutionContext, ResolvedEvaluation
from aiq_evals.errors import AiqEvalsError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m aiq_evals.worker')
    sub = parser.add_subparsers(dest='command', required=True)
    execute = sub.add_parser('execute')
    execute.add_argument('--resolved', type=Path, required=True)
    execute.add_argument('--output-dir', type=Path, required=True)
    execute.add_argument('--result', type=Path, required=True)
    resolve = sub.add_parser('resolve')
    resolve.add_argument('--request', type=Path, required=True)
    resolve.add_argument('--result', type=Path, required=True)
    return parser


def _resolve(args: argparse.Namespace) -> int:
    request = EvaluationRequest.from_dict(json.loads(args.request.read_text()))
    try:
        backend = get_backend(request.engine)
        backend.validate_request(request)
        payload = {'resolved': backend.resolve(request).to_dict()}
    except AiqEvalsError as ex:
        # Typed errors cross the process boundary; anything else is a crash.
        payload = {'error': {'type': type(ex).__name__, 'message': str(ex)}}
    args.result.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
    return 0


def _execute(args: argparse.Namespace) -> int:
    resolved = ResolvedEvaluation.from_dict(json.loads(args.resolved.read_text()))
    backend = get_backend(resolved.request.engine)
    context = ExecutionContext(output_dir=args.output_dir)
    blocking = getattr(backend, 'execute_blocking', None)
    if callable(blocking):
        # Synchronous native APIs run on the main thread, where the runner's
        # cancellation SIGINT reaches the engine's own interruption handling.
        result = blocking(resolved, context)
    else:
        # asyncio.run turns SIGINT into cancellation of this task, so native
        # async runners get their finally/cleanup paths.
        result = asyncio.run(backend.execute(resolved, context))
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True) + '\n')
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == 'execute':
        return _execute(args)
    if args.command == 'resolve':
        return _resolve(args)
    raise AssertionError(args.command)


if __name__ == '__main__':
    raise SystemExit(main())
