"""Native Inspect tasks for phase-7 limit and tool/judge error mapping."""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import ToolError, tool

from tests.native.inspect_fixture import auxiliary_probe, double


@tool
def refusing_tool():
    async def execute(value: int) -> str:
        """Refuse the request with a model-visible tool error.

        Args:
            value: Ignored.
        """
        raise ToolError("tool refused input")

    return execute


@tool
def crashing_tool():
    async def execute(value: int) -> str:
        """Crash with an uncaught exception.

        Args:
            value: Ignored.
        """
        raise RuntimeError("tool crashed")

    return execute


def _task(solver, **kwargs):
    return Task(dataset=[Sample(input="Use the tool on two.", target="4")], solver=solver, scorer=match(), **kwargs)


@task
def message_limit_task():
    return _task([use_tools(double()), generate()], message_limit=2)


@task
def time_limit_task():
    return _task(generate(), time_limit=2)


@task
def tool_error_task():
    return _task([use_tools(refusing_tool()), generate()])


@task
def tool_crash_task():
    return _task([use_tools(crashing_tool()), generate()], fail_on_error=False)


@task
def judge_error_task():
    return _task([auxiliary_probe(), generate()], fail_on_error=False)
