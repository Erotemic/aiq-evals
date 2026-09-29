from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from magnet_evals.engines import ENGINE_SPECS
from magnet_evals.probes.model import ProbeRecord, ProbeStatus


def host_facts() -> dict[str, Any]:
    """Capture non-secret host facts useful for reproducing a probe."""
    return {
        'python': sys.version.split()[0],
        'python_executable': str(Path(sys.executable).resolve()),
        'platform': platform.platform(),
        'machine': platform.machine(),
        'implementation': platform.python_implementation(),
        'uv': shutil.which('uv'),
        'git': shutil.which('git'),
        'cwd': os.getcwd(),
    }


def _distribution_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def probe_engine_import(engine: str) -> ProbeRecord:
    spec = ENGINE_SPECS[engine]
    module_found = importlib.util.find_spec(spec.module) is not None
    version = _distribution_version(spec.distribution)
    if module_found:
        return ProbeRecord(
            probe=f'engine-import:{engine}',
            status=ProbeStatus.PASS,
            summary=f'{spec.module} is importable in the current interpreter',
            details={
                'engine': engine,
                'module': spec.module,
                'distribution': spec.distribution,
                'distribution_version': version,
            },
        )
    return ProbeRecord(
        probe=f'engine-import:{engine}',
        status=ProbeStatus.BLOCKED,
        summary=f'{spec.module} is not installed in the current interpreter',
        details={
            'engine': engine,
            'module': spec.module,
            'distribution': spec.distribution,
            'distribution_version': version,
        },
    )


def probe_all_engine_imports() -> list[ProbeRecord]:
    return [probe_engine_import(key) for key in sorted(ENGINE_SPECS)]
