import subprocess

import pytest

from aiq_evals.errors import EngineCompatibilityError
from aiq_evals.probes.source import verify_engine_revision


def _git(root, *args):
    return subprocess.run(
        ['git', '-C', str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / 'engine'
    (root / 'src' / 'engine_pkg').mkdir(parents=True)
    module = root / 'src' / 'engine_pkg' / '__init__.py'
    module.write_text('X = 1\n')
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'init')
    return root, module, _git(root, 'rev-parse', 'HEAD')


def test_observed_revision_is_used_even_without_request(checkout):
    _root, module, head = checkout
    revision, facts, reasons = verify_engine_revision(None, module_file=str(module), distribution='x')
    assert revision == head and not reasons
    assert facts['engine_revision_source'] == 'git-checkout'


def test_mismatched_request_is_rejected(checkout):
    _root, module, _head = checkout
    with pytest.raises(EngineCompatibilityError, match='executing source is at'):
        verify_engine_revision('a' * 40, module_file=str(module), distribution='x')


def test_dirty_checkout_is_not_reusable(checkout):
    _root, module, head = checkout
    module.write_text('X = 2\n')
    revision, facts, reasons = verify_engine_revision(head, module_file=str(module), distribution='x')
    assert revision is None and facts['engine_checkout_dirty']
    assert any('tracked modifications' in reason for reason in reasons)


def test_unverifiable_request_is_recorded_but_not_trusted(tmp_path):
    module = tmp_path / 'loose.py'
    module.write_text('')
    revision, facts, reasons = verify_engine_revision(
        'a' * 40, module_file=str(module), distribution='definitely-not-installed'
    )
    assert revision is None
    assert facts['requested_engine_revision'] == 'a' * 40
    assert any('could not be verified' in reason for reason in reasons)


def test_untracked_install_inside_other_repo_is_not_a_checkout(checkout):
    root, _module, _head = checkout
    installed = root / '.venv' / 'site-packages' / 'engine_pkg' / '__init__.py'
    installed.parent.mkdir(parents=True)
    installed.write_text('')
    revision, facts, _reasons = verify_engine_revision(
        None, module_file=str(installed), distribution='definitely-not-installed'
    )
    assert revision is None and facts['observed_engine_revision'] is None
