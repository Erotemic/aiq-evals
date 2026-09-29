import json
from pathlib import Path

import pytest

from aiq_evals.contracts import EvaluationRequest
from aiq_evals.runner import validate_request

EXAMPLES = sorted((Path(__file__).parents[1] / 'examples').glob('*.json'))


@pytest.mark.parametrize('path', EXAMPLES, ids=lambda p: p.name)
def test_examples_validate_without_engines(path):
    validate_request(EvaluationRequest.from_dict(json.loads(path.read_text())))
