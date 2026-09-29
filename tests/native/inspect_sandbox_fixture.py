"""Native Inspect task whose tool executes inside Inspect's ``local`` sandbox.

The tool records the sandbox working directory (Inspect-created temporary
directory) so tests can check whether the engine removed it.
"""

import os

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import tool
from inspect_ai.util import sandbox


@tool
def sandbox_double():
    async def execute(value: int) -> str:
        """Double an integer inside the sandbox.

        Args:
            value: Integer to double.
        """
        where = await sandbox().exec(["sh", "-c", "pwd"])
        with open(os.environ["AIQ_P1_SANDBOX_RECORD"], "a") as file:
            file.write(where.stdout.strip() + "\n")
        if os.environ.get("AIQ_P1_SANDBOX_SLOW"):
            # Owned by the sandbox exec; cancellation arrives while it runs.
            await sandbox().exec(["sh", "-c", "echo $$ > child.pid; exec sleep 120"])
        result = await sandbox().exec(["sh", "-c", f"echo $(({value} * 2))"])
        return result.stdout.strip()

    return execute


@task
def sandbox_task():
    return Task(
        dataset=[Sample(input="Use sandbox_double on two.", target="4")],
        solver=[use_tools(sandbox_double()), generate()],
        scorer=match(),
        sandbox="local",
    )
