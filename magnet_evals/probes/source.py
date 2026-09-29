from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import Any

from magnet_evals.probes.model import ProbeRecord, ProbeStatus


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


def _installed_vcs_commit(distribution: str) -> str | None:
    """PEP 610 ``direct_url.json`` commit of a VCS (non-editable) install."""
    import importlib.metadata
    import json

    try:
        text = importlib.metadata.distribution(distribution).read_text('direct_url.json')
    except importlib.metadata.PackageNotFoundError:
        return None
    if not text:
        return None
    try:
        commit = json.loads(text).get('vcs_info', {}).get('commit_id')
    except (ValueError, AttributeError):
        return None
    return str(commit) if commit else None


def verify_engine_revision(
    requested: str | None,
    *,
    module_file: str | None,
    distribution: str,
) -> tuple[str | None, dict[str, Any], list[str]]:
    """Determine the executing engine's source revision instead of trusting a request.

    Returns ``(engine_revision, facts, identity_unknown_reasons)``. The revision is
    observed from the imported module's git checkout, else from PEP 610 install
    metadata. A requested revision that contradicts the observed one raises; one
    that cannot be verified is recorded but not used as identity.
    """
    from magnet_evals.errors import EngineCompatibilityError

    facts: dict[str, Any] = {'requested_engine_revision': requested}
    reasons: list[str] = []
    observed: str | None = None
    dirty = False
    if module_file:
        path = Path(module_file).resolve()
        try:
            root = Path(_git(path.parent, 'rev-parse', '--show-toplevel'))
            # A site-packages install inside an unrelated repository (e.g. a
            # project .venv) is not the engine checkout: require it be tracked.
            _git(root, 'ls-files', '--error-unmatch', str(path))
            observed = _git(root, 'rev-parse', 'HEAD')
            dirty = bool(_git(root, 'status', '--porcelain', '--untracked-files=no'))
            facts['engine_revision_source'] = 'git-checkout'
        except (OSError, subprocess.CalledProcessError):
            observed = None
    if observed is None:
        observed = _installed_vcs_commit(distribution)
        if observed is not None:
            facts['engine_revision_source'] = 'pep610-direct-url'
    facts['observed_engine_revision'] = observed
    facts['engine_checkout_dirty'] = dirty

    if requested is not None and observed is not None and requested != observed:
        raise EngineCompatibilityError(
            f'requested {distribution} upstream_revision {requested} but the executing '
            f'source is at {observed}'
        )
    if dirty:
        reasons.append(f'{distribution} source checkout has tracked modifications')
        return None, facts, reasons
    if requested is not None and observed is None:
        reasons.append(
            f'requested {distribution} upstream_revision could not be verified against '
            'the executing source'
        )
        return None, facts, reasons
    return observed, facts, reasons
