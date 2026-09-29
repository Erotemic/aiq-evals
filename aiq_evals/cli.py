from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from aiq_evals.engines import ENGINE_SPECS
from aiq_evals.phase1 import PHASE1_TASKS
from aiq_evals.probes.api_surface import probe_all_api_surfaces
from aiq_evals.probes.environment import host_facts, probe_all_engine_imports
from aiq_evals.probes.model import ProbeReport
from aiq_evals.probes.source import inspect_checkout


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='aiq-evals',
        description='Research and runtime tooling for backend-agnostic evaluations.',
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
    return parser


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


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == 'phase1-status':
        return _phase1_status(args.json)
    if args.command == 'phase1-probe':
        return _phase1_probe(args)
    if args.command == 'engines':
        return _engines(args.json)
    raise AssertionError(args.command)
