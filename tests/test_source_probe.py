import shutil
import subprocess

import pytest

from aiq_evals.probes.model import ProbeStatus
from aiq_evals.probes.source import inspect_checkout


@pytest.mark.skipif(shutil.which('git') is None, reason='git is required')
def test_inspect_checkout(tmp_path):
    repo = tmp_path / 'upstream'
    repo.mkdir()
    subprocess.run(['git', 'init', str(repo)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.email', 'test@example.com'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.name', 'Test'], check=True)
    subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin', 'https://example.com/upstream.git'], check=True)
    (repo / 'pyproject.toml').write_text(
        '[project]\nname = "fake-engine"\nversion = "1.2.3"\nrequires-python = ">=3.12"\n'
    )
    (repo / 'uv.lock').write_text('version = 1\n')
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-m', 'fixture'], check=True, capture_output=True)

    records = inspect_checkout('fake', repo)
    by_probe = {row.probe: row for row in records}
    assert by_probe['source-checkout:fake'].status == ProbeStatus.PASS
    assert by_probe['pyproject:fake'].details['requires_python'] == '>=3.12'
    assert by_probe['uv-lock:fake'].status == ProbeStatus.PASS

    (repo / 'pyproject.toml').write_text('[project]\nname = "changed"\n')
    records = inspect_checkout('fake', repo)
    by_probe = {row.probe: row for row in records}
    assert by_probe['source-checkout:fake'].status == ProbeStatus.FAIL
