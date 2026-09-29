from pathlib import Path

import pytest

from aiq_evals.probes.isolated import build_locked_uv_command, validate_git_revision


def test_validate_git_revision():
    revision = 'A' * 40
    assert validate_git_revision(revision) == 'a' * 40
    with pytest.raises(ValueError):
        validate_git_revision('main')


def test_build_locked_uv_command(tmp_path):
    command = build_locked_uv_command(
        tmp_path,
        ['python', 'worker.py'],
        extras=['agents', 'beaker'],
        python='3.12',
    )
    assert command[:5] == [
        'uv',
        'run',
        '--project',
        str(Path(tmp_path).resolve()),
        '--locked',
    ]
    assert '--no-default-groups' in command
    assert command.count('--extra') == 2
    assert command[-2:] == ['python', 'worker.py']
