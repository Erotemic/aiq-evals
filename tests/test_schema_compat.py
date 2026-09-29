import json
import shutil
from pathlib import Path

import pytest

from aiq_evals.artifacts import RunBundle
from aiq_evals.errors import ArtifactError, RequestValidationError


FIXTURE = Path(__file__).parent / 'fixtures' / 'run-v1'


def test_frozen_schema_v1_bundle_remains_engine_free_readable():
    bundle = RunBundle.load(FIXTURE)
    assert bundle.complete
    assert bundle.result.engine == 'olmo_eval'
    assert bundle.result.records[0].metrics[0].value == 0.75
    assert bundle.manifest['schema_version'] == 1
    assert bundle.manifest['normalized_artifact_identity']


def test_unknown_future_manifest_schema_fails_conservatively(tmp_path):
    dst = tmp_path / 'future'
    shutil.copytree(FIXTURE, dst)
    manifest_path = dst / 'run_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['schema_version'] = 999
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    with pytest.raises(ArtifactError, match='unsupported run manifest schema'):
        RunBundle.load(dst)


def test_unknown_future_result_schema_fails_conservatively(tmp_path):
    dst = tmp_path / 'future-result'
    shutil.copytree(FIXTURE, dst)
    result_path = dst / 'results.json'
    result = json.loads(result_path.read_text())
    result['schema_version'] = 999
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    with pytest.raises(RequestValidationError, match='unsupported result schema'):
        RunBundle.load(dst)


def test_normalized_payload_tamper_is_detected(tmp_path):
    dst = tmp_path / 'tampered'
    shutil.copytree(FIXTURE, dst)
    result_path = dst / 'results.json'
    result = json.loads(result_path.read_text())
    result['records'][0]['metrics'][0]['value'] = 0.99
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    with pytest.raises(ArtifactError, match='normalized artifact identity'):
        RunBundle.load(dst)


def test_engine_free_output_accessors():
    from aiq_evals.outputs import native_artifacts, normalized_artifact_identity, sample_records

    bundle = RunBundle.load(FIXTURE)
    assert sample_records(bundle) == ()
    refs = native_artifacts(bundle)
    assert len(refs) == 1
    assert refs[0].path == 'metrics.json'
    assert len(normalized_artifact_identity(bundle)) == 64
