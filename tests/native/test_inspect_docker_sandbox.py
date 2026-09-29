"""Inspect's Docker sandbox at the verified pin (plan P7-06 / V-030 / V-046).

Opt-in: marked ``docker_sandbox`` and skipped unless Inspect is installed and
the Docker daemon is usable by the current user. Evidence covers only the
container configuration used here (pinned ``ubuntu:24.04`` digest,
``network_mode: none``, no volumes); it says nothing about other images or
compose files.

    <inspect-venv>/bin/python -m pytest -q tests/native/test_inspect_docker_sandbox.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import subprocess
import time

import pytest

from magnet_evals.contracts import EvaluationRequest, ModelBinding
from magnet_evals.ensure import ensure_evaluation, ensure_evaluation_async
from magnet_evals.store import ResultStore


def _docker_usable() -> bool:
    if shutil.which('docker') is None:
        return False
    return subprocess.run(['docker', 'info'], capture_output=True).returncode == 0


pytestmark = [
    pytest.mark.docker_sandbox,
    pytest.mark.skipif(importlib.util.find_spec('inspect_ai') is None, reason='needs inspect_ai'),
    pytest.mark.skipif(not _docker_usable(), reason='needs a Docker daemon usable by this user'),
]


def _request() -> EvaluationRequest:
    return EvaluationRequest(
        engine='inspect_ai',
        task='python:tests.native.inspect_docker_fixture:probe_task',
        data_revision='fixture-v1',
        models=(ModelBinding(role='primary', model='local', provider='aiq_example', revision='local-v1'),),
        engine_options={'registration_modules': ['magnet_evals.examples.inspect_tasks']},
    )


def _containers() -> set[str]:
    out = subprocess.run(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}'],
                         capture_output=True, text=True, check=True).stdout
    return set(out.split())


def _gone(hostname: str, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(cid.startswith(hostname) for cid in _containers()):
            return True
        time.sleep(0.5)
    return False


def test_docker_sandbox_isolates_the_tool_and_removes_the_container(tmp_path, monkeypatch):
    marker = tmp_path / 'host-only-marker'
    marker.write_text('visible on the host\n')
    record = tmp_path / 'record.json'
    monkeypatch.setenv('AIQ_DOCKER_HOST_MARKER', str(marker))
    monkeypatch.setenv('AIQ_DOCKER_RECORD', str(record))
    outcome = ensure_evaluation(_request(), ResultStore(tmp_path / 'store'))
    assert outcome.run.result.status == 'succeeded', outcome.run.result.diagnostics
    (metric,) = [m for rec in outcome.run.result.records for m in rec.metrics
                 if m.scorer == 'match' and m.metric == 'accuracy']
    assert metric.value == 1.0
    seen = json.loads(record.read_text())
    # The tool ran in a container: no host file system, no network but loopback.
    assert seen['host_marker'] == 'absent'
    assert seen['interfaces'] == ['lo']
    assert _gone(seen['hostname'])
    # The tool call is in the normalized trajectory.
    events = json.dumps([s.to_dict() for s in outcome.run.result.samples])
    assert 'probe' in events


def test_cancellation_removes_the_docker_sandbox(tmp_path, monkeypatch):
    record = tmp_path / 'record.json'
    monkeypatch.setenv('AIQ_DOCKER_RECORD', str(record))
    monkeypatch.setenv('AIQ_DOCKER_SLOW', '1')
    store = ResultStore(tmp_path / 'store')

    async def scenario():
        task = asyncio.create_task(ensure_evaluation_async(_request(), store))
        for _ in range(1200):
            if record.exists() and record.read_text():
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail('sandboxed tool never started')
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    seen = json.loads(record.read_text())
    assert _gone(seen['hostname']), 'the sandbox container outlived cancellation'
    statuses = [p.read_text().strip() for p in (tmp_path / 'store' / 'attempts').rglob('ATTEMPT_TERMINAL')]
    assert statuses == ['cancelled']
