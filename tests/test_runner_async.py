import asyncio

import pytest

from magnet_evals.contracts import EvaluationRequest, ExecutionContext, ModelBinding
from magnet_evals.errors import ActiveEventLoopError
from magnet_evals.runner import run_evaluation


def test_sync_facade_rejects_active_event_loop(tmp_path):
    request = EvaluationRequest(
        engine='olmo_eval',
        task='tiny',
        models=(ModelBinding(role='primary', model='m'),),
    )

    async def inner():
        with pytest.raises(ActiveEventLoopError):
            run_evaluation(request, ExecutionContext(output_dir=tmp_path / 'x'))

    asyncio.run(inner())
