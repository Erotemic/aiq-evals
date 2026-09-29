from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Sequence

_FULL_GIT_SHA = re.compile(r'^[0-9a-fA-F]{40}$')


def validate_git_revision(revision: str) -> str:
    """Require an immutable full commit SHA for source-pinned workers."""
    if not _FULL_GIT_SHA.fullmatch(revision):
        raise ValueError(
            'revision must be a full 40-character git commit SHA; '
            f'got {revision!r}'
        )
    return revision.lower()


def build_locked_uv_command(
    project: str | Path,
    inner: Sequence[str],
    *,
    extras: Iterable[str] = (),
    python: str | None = None,
) -> list[str]:
    """Build a locked ``uv run`` command for an isolated upstream project."""
    project = Path(project).expanduser().resolve()
    command = [
        'uv',
        'run',
        '--project',
        str(project),
        '--locked',
        '--no-default-groups',
    ]
    for extra in extras:
        extra = str(extra).strip()
        if not extra:
            raise ValueError('extra names must be non-empty')
        command.extend(['--extra', extra])
    if python:
        command.extend(['--python', python])
    command.extend(str(part) for part in inner)
    return command
