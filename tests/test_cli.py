import json

from magnet_evals.cli import main


def test_status_json(capsys):
    assert main(['phase1-status', '--json']) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]['id'] == 'P1-01'


def test_engines_json(capsys):
    assert main(['engines', '--json']) == 0
    data = json.loads(capsys.readouterr().out)
    assert 'olmo_eval' in data


def test_probe_json(capsys):
    assert main(['phase1-probe']) == 0
    data = json.loads(capsys.readouterr().out)
    assert data['schema_version'] == 1
    assert len(data['records']) >= 6
