"""Native Inspect sample error fixture, separate from multi-log success tasks."""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match
from inspect_ai.solver import generate, solver


@solver
def fail_one():
    async def solve(state, generate):
        del generate
        if state.input_text == "fail":
            raise RuntimeError("intentional sample failure")
        return state

    return solve


@task
def partial_task():
    return Task(
        dataset=[Sample(input="fail", target="4"), Sample(input="okay", target="4")],
        solver=[fail_one(), generate()],
        scorer=match(),
        fail_on_error=False,
    )
