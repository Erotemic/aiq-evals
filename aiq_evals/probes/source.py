from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import Any

from aiq_evals.probes.model import ProbeRecord, ProbeStatus


def _git(checkout: Path, *args: str) -> str:
    proc = subprocess.run(
        ['git', '-C', str(checkout), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def inspect_checkout(engine: str, checkout: str | Path) -> list[ProbeRecord]:
    """Inspect an upstream source checkout without importing its package."""
    checkout = Path(checkout).expanduser().resolve()
    records: list[ProbeRecord] = []
    if not checkout.is_dir():
        return [
            ProbeRecord(
                probe=f'source-checkout:{engine}',
                status=ProbeStatus.FAIL,
                summary='checkout directory does not exist',
                details={'engine': engine, 'checkout': str(checkout)},
            )
        ]

    try:
        head = _git(checkout, 'rev-parse', 'HEAD')
        status = _git(checkout, 'status', '--porcelain', '--untracked-files=no')
        remote = _git(checkout, 'remote', 'get-url', 'origin')
    except (OSError, subprocess.CalledProcessError) as ex:
        return [
            ProbeRecord(
                probe=f'source-checkout:{engine}',
                status=ProbeStatus.FAIL,
                summary='cannot verify checkout as a git repository',
                details={'engine': engine, 'checkout': str(checkout), 'error': str(ex)},
            )
        ]

    records.append(
        ProbeRecord(
            probe=f'source-checkout:{engine}',
            status=ProbeStatus.PASS if not status else ProbeStatus.FAIL,
            summary='upstream checkout is clean' if not status else 'upstream checkout has tracked modifications',
            details={
                'engine': engine,
                'checkout': str(checkout),
                'head': head,
                'origin': remote,
                'tracked_status': status,
            },
        )
    )

    pyproject = checkout / 'pyproject.toml'
    metadata: dict[str, Any] = {'pyproject': str(pyproject)}
    if pyproject.is_file():
        data = tomllib.loads(pyproject.read_text())
        project = data.get('project') or {}
        metadata.update(
            {
                'project_name': project.get('name'),
                'requires_python': project.get('requires-python'),
                'version': project.get('version'),
                'dynamic': project.get('dynamic'),
            }
        )
        records.append(
            ProbeRecord(
                probe=f'pyproject:{engine}',
                status=ProbeStatus.PASS,
                summary='read upstream pyproject metadata',
                details=metadata,
            )
        )
    else:
        records.append(
            ProbeRecord(
                probe=f'pyproject:{engine}',
                status=ProbeStatus.FAIL,
                summary='upstream checkout has no pyproject.toml',
                details=metadata,
            )
        )

    lock = checkout / 'uv.lock'
    records.append(
        ProbeRecord(
            probe=f'uv-lock:{engine}',
            status=ProbeStatus.PASS if lock.is_file() else ProbeStatus.INFO,
            summary='upstream checkout has uv.lock' if lock.is_file() else 'upstream checkout has no uv.lock',
            details={'engine': engine, 'uv_lock': str(lock), 'exists': lock.is_file()},
        )
    )
    return records
