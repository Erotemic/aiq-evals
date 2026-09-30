"""Private subprocess protocol for isolated native engine execution."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import kwconf

from magnet_evals.backends.registry import get_backend
from magnet_evals.contracts import (
    EvaluationRequest,
    ExecutionContext,
    ResolvedEvaluation,
)
from magnet_evals.errors import AiqEvalsError


def _resolve(args) -> int:
    request = EvaluationRequest.from_dict(json.loads(Path(args.request).read_text()))
    try:
        backend = get_backend(request.engine)
        backend.validate_request(request)
        payload = {'resolved': backend.resolve(request).to_dict()}
    except AiqEvalsError as ex:
        # Typed errors cross the process boundary; anything else is a crash.
        payload = {'error': {'type': type(ex).__name__, 'message': str(ex)}}
    Path(args.result).write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
    return 0


def _import(args) -> int:
    resolved = ResolvedEvaluation.from_dict(json.loads(Path(args.resolved).read_text()))
    try:
        backend = get_backend(resolved.request.engine)
        result = backend.import_results(resolved, str(args.source), ExecutionContext(output_dir=Path(args.output_dir)))
        payload = {'result': result.to_dict()}
    except AiqEvalsError as ex:
        payload = {'error': {'type': type(ex).__name__, 'message': str(ex)}}
    Path(args.result).write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
    return 0


def _execute(args) -> int:
    resolved = ResolvedEvaluation.from_dict(json.loads(Path(args.resolved).read_text()))
    backend = get_backend(resolved.request.engine)
    context = ExecutionContext(
        output_dir=Path(args.output_dir), model_endpoints=json.loads(args.model_endpoints)
    )
    blocking = getattr(backend, 'execute_blocking', None)
    if callable(blocking):
        # Synchronous native APIs run on the main thread, where the runner's
        # cancellation SIGINT reaches the engine's own interruption handling.
        result = blocking(resolved, context)
    else:
        # asyncio.run turns SIGINT into cancellation of this task, so native
        # async runners get their finally/cleanup paths.
        result = asyncio.run(backend.execute(resolved, context))
    result_path = Path(args.result)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True) + '\n')
    return 0


def _args(cls, argv, kwargs):
    return cls.cli(argv=argv, data=kwargs, strict=True, special_options=False)


class ExecuteCLI(kwconf.Config):
    """Execute a resolved evaluation and write its result protocol file."""

    resolved = kwconf.Value(None, required=True, parser=str)
    output_dir = kwconf.Value(None, required=True, parser=str)
    result = kwconf.Value(None, required=True, parser=str)
    model_endpoints = kwconf.Value('{}', parser=str, help='JSON {role: base_url}')

    @classmethod
    def main(cls, argv=True, **kwargs) -> int:
        return _execute(_args(cls, argv, kwargs))


class ImportCLI(kwconf.Config):
    """Read native artifacts for a resolved evaluation."""

    resolved = kwconf.Value(None, required=True, parser=str)
    source = kwconf.Value(None, required=True, parser=str)
    output_dir = kwconf.Value(None, required=True, parser=str)
    result = kwconf.Value(None, required=True, parser=str)

    @classmethod
    def main(cls, argv=True, **kwargs) -> int:
        return _import(_args(cls, argv, kwargs))


class ResolveCLI(kwconf.Config):
    """Resolve a request in this engine environment."""

    request = kwconf.Value(None, required=True, parser=str)
    result = kwconf.Value(None, required=True, parser=str)

    @classmethod
    def main(cls, argv=True, **kwargs) -> int:
        return _resolve(_args(cls, argv, kwargs))


class WorkerCLI(kwconf.ModalCLI):
    """Private subprocess protocol for isolated native engine execution."""

    __prog__ = 'python -m magnet_evals.worker'


WorkerCLI.register(ExecuteCLI, command='execute')
WorkerCLI.register(ImportCLI, command='import')
WorkerCLI.register(ResolveCLI, command='resolve')


def main(argv: list[str] | None = None) -> int:
    return WorkerCLI.main(argv=argv)


if __name__ == '__main__':
    raise SystemExit(main())
