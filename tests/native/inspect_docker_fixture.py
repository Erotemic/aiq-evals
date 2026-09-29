"""Inspect task whose tool probes its Docker sandbox from inside.

The tool code runs in the Inspect worker (on the host) and executes commands
inside the sandbox container. It records what the container sees so tests can
check isolation (no host files, no network) and that Inspect removes the
container on completion and on cancellation.
"""

import json
import os

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import tool
from inspect_ai.util import ComposeConfig, ComposeService, sandbox

from magnet_evals.examples.inspect_tasks import DOCKER_SANDBOX_IMAGE


@tool
def probe():
    async def execute(value: int) -> str:
        """Report what the sandbox can see, then double an integer.

        Args:
            value: Integer to double.
        """
        marker = os.environ.get("AIQ_DOCKER_HOST_MARKER", "/nonexistent")
        seen = await sandbox().exec(["sh", "-c", (
            f"cat /etc/hostname; test -e {marker} && echo present || echo absent; ls /sys/class/net"
        )])
        lines = seen.stdout.split()
        record = {"hostname": lines[0], "host_marker": lines[1], "interfaces": lines[2:]}
        with open(os.environ["AIQ_DOCKER_RECORD"], "w") as file:
            json.dump(record, file)
        if os.environ.get("AIQ_DOCKER_SLOW"):
            await sandbox().exec(["sh", "-c", "exec sleep 120"])
        result = await sandbox().exec(["sh", "-c", f"echo $(({int(value)} * 2))"])
        return result.stdout.strip()

    return execute


@task
def probe_task():
    compose = ComposeConfig(services={"default": ComposeService(
        image=DOCKER_SANDBOX_IMAGE, command="tail -f /dev/null", init=True,
        network_mode="none", stop_grace_period="1s",
    )})
    return Task(
        dataset=[Sample(input="Use probe on two.", target="4")],
        solver=[use_tools(probe()), generate()],
        scorer=match(),
        sandbox=("docker", compose),
    )
