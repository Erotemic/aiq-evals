from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from aiq_evals.backends.registry import registrations
from aiq_evals.contracts import EvaluationRequest, ExecutionContext
from aiq_evals.engines import ENGINE_SPECS
from aiq_evals.ensure import ensure_evaluation
from aiq_evals.outputs import load_run
from aiq_evals.phase1 import PHASE1_TASKS
from aiq_evals.probes.api_surface import probe_all_api_surfaces
from aiq_evals.probes.environment import host_facts, probe_all_engine_imports
from aiq_evals.probes.model import ProbeReport
from aiq_evals.probes.source import inspect_checkout
from aiq_evals.runner import (
    import_evaluation,
    resolve_evaluation,
    resolve_evaluation_async,
    run_evaluation,
    validate_request,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='aiq-evals',
        description='Backend-agnostic evaluation runtime and artifact tooling.',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    status = sub.add_parser('phase1-status', help='Show the refined phase-1 checklist.')
    status.add_argument('--json', action='store_true', help='Emit JSON instead of text.')

    probe = sub.add_parser(
        'phase1-probe',
        help='Capture local package/source facts without executing native evaluations.',
    )
    probe.add_argument(
        '--checkout',
        action='append',
        default=[],
        metavar='ENGINE=PATH',
        help='Inspect an upstream checkout; may be repeated.',
    )
    probe.add_argument('--output', type=Path, help='Write a JSON probe report here.')

    engines = sub.add_parser('engines', help='Show phase-1 engine research metadata.')
    engines.add_argument('--json', action='store_true')

    backends = sub.add_parser('backends', help='Show implemented lazy backend adapters.')
    backends.add_argument('--json', action='store_true')

    validate = sub.add_parser(
        'validate',
        help='Statically validate a request without importing the native engine.',
    )
    validate.add_argument('request', type=Path)

    resolve = sub.add_parser(
        'resolve',
        help='Resolve a request in the native engine environment and print its identity.',
    )
    resolve.add_argument('request', type=Path)
    resolve.add_argument('--output', type=Path)
    resolve.add_argument('--worker-python', help='Resolve inside this engine interpreter.')

    ensure = sub.add_parser(
        'ensure',
        help='Reuse a validated stored result, or import/execute and publish one.',
    )
    ensure.add_argument('request', type=Path)
    ensure.add_argument('--store', type=Path, required=True)
    ensure.add_argument('--worker-python')
    ensure.add_argument('--timeout', type=float)
    ensure.add_argument('--import-source', type=Path, help='Import these native artifacts instead of executing.')
    ensure.add_argument(
        '--allow-external-symlinks', action='store_true',
        help='Follow symlinks leaving the import source (trusted sources only).',
    )

    run = sub.add_parser('run', help='Execute a request and atomically publish a run bundle.')
    run.add_argument('request', type=Path)
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--worker-python')
    run.add_argument('--timeout', type=float)

    imp = sub.add_parser(
        'import-native',
        help='Import native engine artifacts into an engine-free run bundle.',
    )
    imp.add_argument('request', type=Path)
    imp.add_argument('source', type=Path)
    imp.add_argument('--output', type=Path, required=True)
    imp.add_argument(
        '--allow-external-symlinks', action='store_true',
        help='Follow symlinks leaving the import source (trusted sources only).',
    )

    show = sub.add_parser('show', help='Inspect a published run without engine dependencies.')
    show.add_argument('run_dir', type=Path)
    show.add_argument('--no-verify', action='store_true')
    return parser


def _load_request(path: Path) -> EvaluationRequest:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise SystemExit(f'request must be a JSON object: {path}')
    return EvaluationRequest.from_dict(data)


def _parse_checkouts(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in values:
        if '=' not in item:
            raise SystemExit(f'--checkout expects ENGINE=PATH, got {item!r}')
        engine, path = item.split('=', 1)
        if engine not in ENGINE_SPECS:
            known = ', '.join(sorted(ENGINE_SPECS))
            raise SystemExit(f'unknown engine {engine!r}; expected one of: {known}')
        parsed[engine] = path
    return parsed


def _phase1_status(as_json: bool) -> int:
    rows = [task.__dict__ for task in PHASE1_TASKS]
    if as_json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for task in PHASE1_TASKS:
            print(f'{task.id:6} {task.status:7} {task.title}')
            print(f'       {task.note}')
    return 0


def _engines(as_json: bool) -> int:
    rows = {key: spec.__dict__ for key, spec in ENGINE_SPECS.items()}
    if as_json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for key in sorted(ENGINE_SPECS):
            spec = ENGINE_SPECS[key]
            print(f'{key}: {spec.repository}')
            print(f'  pin_state={spec.pin_state} candidate_revision={spec.candidate_revision!r}')
            print(f'  candidate_version={spec.candidate_version!r}')
            print(f'  python_hint={spec.python_requirement_hint!r}')
    return 0


def _backends(as_json: bool) -> int:
    rows = {key: registration.__dict__ for key, registration in registrations().items()}
    if as_json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for key, row in sorted(rows.items()):
            print(f'{key}: {row["module"]}:{row["factory"]} experimental={row["experimental"]}')
    return 0


def _phase1_probe(args: argparse.Namespace) -> int:
    records = probe_all_engine_imports()
    records.extend(probe_all_api_surfaces())
    for engine, path in _parse_checkouts(args.checkout).items():
        records.extend(inspect_checkout(engine, path))
    report = ProbeReport(
        schema_version=1,
        generated_at=datetime.now(timezone.utc).isoformat(),
        host=host_facts(),
        records=records,
    )
    if args.output:
        path = report.write_json(args.output)
        print(path)
    else:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0


def _validate(path: Path) -> int:
    request = _load_request(path)
    validate_request(request)
    print(json.dumps({'valid': True, 'engine': request.engine}, sort_keys=True))
    return 0


def _resolve(path: Path, output: Path | None, worker_python: str | None = None) -> int:
    request = _load_request(path)
    if worker_python:
        context = ExecutionContext(output_dir=Path.cwd(), worker_python=worker_python)
        resolved = asyncio.run(resolve_evaluation_async(request, context))
    else:
        resolved = resolve_evaluation(request)
    text = json.dumps(resolved.to_dict(), indent=2, sort_keys=True) + '\n'
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)
        print(output)
    else:
        print(text, end='')
    return 0


def _ensure(args: argparse.Namespace) -> int:
    outcome = ensure_evaluation(
        _load_request(args.request),
        args.store,
        worker_python=args.worker_python,
        timeout_seconds=args.timeout,
        import_source=args.import_source,
        allow_external_symlinks=args.allow_external_symlinks,
    )
    payload = {
        'action': outcome.action,
        'path': str(outcome.run.path),
        'status': outcome.run.result.status,
        'measurement_identity': outcome.resolved.identity.to_dict(),
        'reuse_reason': outcome.reuse_reason,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if outcome.run.result.status == 'succeeded' else 2


def _run(args: argparse.Namespace) -> int:
    request = _load_request(args.request)
    context = ExecutionContext(
        output_dir=args.output,
        worker_python=args.worker_python,
        timeout_seconds=args.timeout,
    )
    bundle = run_evaluation(request, context)
    print(bundle.path)
    return 0 if bundle.result.status == 'succeeded' else 2


def _import_native(args: argparse.Namespace) -> int:
    request = _load_request(args.request)
    context = ExecutionContext(output_dir=args.output)
    bundle = import_evaluation(
        request, args.source, context, allow_external_symlinks=args.allow_external_symlinks
    )
    print(bundle.path)
    return 0 if bundle.result.status == 'succeeded' else 2


def _show(args: argparse.Namespace) -> int:
    bundle = load_run(args.run_dir, verify_checksums=not args.no_verify)
    payload = {
        'path': str(bundle.path),
        'complete': bundle.complete,
        'engine': bundle.result.engine,
        'status': bundle.result.status,
        'measurement_identity': bundle.resolved.identity.to_dict(),
        'records': [record.to_dict() for record in bundle.result.records],
        'sample_count': len(bundle.result.samples),
        'manifest': dict(bundle.manifest),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == 'phase1-status':
        return _phase1_status(args.json)
    if args.command == 'phase1-probe':
        return _phase1_probe(args)
    if args.command == 'engines':
        return _engines(args.json)
    if args.command == 'backends':
        return _backends(args.json)
    if args.command == 'validate':
        return _validate(args.request)
    if args.command == 'resolve':
        return _resolve(args.request, args.output, args.worker_python)
    if args.command == 'ensure':
        return _ensure(args)
    if args.command == 'run':
        return _run(args)
    if args.command == 'import-native':
        return _import_native(args)
    if args.command == 'show':
        return _show(args)
    raise AssertionError(args.command)
