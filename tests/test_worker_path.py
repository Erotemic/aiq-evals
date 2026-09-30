"""Workers see exactly magnet_evals and kwconf from the caller (runner.worker_package_path)."""
import os
import subprocess
import sys
from pathlib import Path

from magnet_evals.runner import WORKER_PACKAGES, worker_package_path


def test_worker_path_exposes_only_the_worker_packages():
    root = Path(worker_package_path())
    assert sorted(p.name for p in root.iterdir() if not p.name.startswith('.')) == sorted(WORKER_PACKAGES)


def test_a_worker_runs_with_nothing_installed_but_the_private_path(tmp_path):
    # `python -S` skips site-packages, as in an engine environment that has
    # neither magnet_evals nor kwconf installed: both come from the path.
    env = dict(os.environ, PYTHONPATH=worker_package_path())
    proc = subprocess.run(
        [sys.executable, '-S', '-m', 'magnet_evals.worker', '--help'],
        capture_output=True, text=True, env=env, cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert 'execute' in proc.stdout and 'resolve' in proc.stdout
