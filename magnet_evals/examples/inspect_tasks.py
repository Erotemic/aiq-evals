"""Deterministic Inspect example tasks and the local ``aiq_example`` provider.

Use as ``"task": "python:magnet_evals.examples.inspect_tasks:generation"`` with
``"engine_options": {"registration_modules": ["magnet_evals.examples.inspect_tasks"]}``
and a primary model ``{"model": "local", "provider": "aiq_example"}``.
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelAPI, ModelOutput, modelapi
from inspect_ai.scorer import includes, match
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import tool
from inspect_ai.util import ComposeConfig, ComposeService, sandbox

#: The Docker sandbox image, pinned by digest. It is defined in this module's
#: source, so the measurement identity (which hashes the task source) changes
#: whenever the sandbox image does.
DOCKER_SANDBOX_IMAGE = (
    "ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3"
)


@modelapi(name="aiq_example")
class ExampleModel(ModelAPI):
    """Calls the first offered tool once with ``value=2``, then answers "4"."""

    async def generate(self, input, tools, tool_choice, config):
        del tool_choice, config
        if tools and not any(message.role == "tool" for message in input):
            return ModelOutput.for_tool_call(
                model=self.model_name,
                tool_name=tools[0].name,
                tool_arguments={"value": 2},
            )
        return ModelOutput.from_content(model=self.model_name, content="4")


@tool
def aiq_example_double():
    async def execute(value: int) -> str:
        """Double an integer value.

        Args:
            value: Integer to double.
        """
        return str(value * 2)

    return execute


@tool
def aiq_example_sandbox_double():
    async def execute(value: int) -> str:
        """Double an integer inside the sandbox.

        Args:
            value: Integer to double.
        """
        result = await sandbox().exec(["sh", "-c", f"echo $(({int(value)} * 2))"])
        return result.stdout.strip()

    return execute


@task
def generation():
    """Scored generation with two native scorers."""
    return Task(
        dataset=[Sample(input="Two plus two?", target="4")],
        solver=generate(),
        scorer=[match(), includes()],
    )


@task
def tool_task():
    """A multi-turn solver that really calls a tool before answering."""
    return Task(
        dataset=[Sample(input="Use aiq_example_double on two.", target="4")],
        solver=[use_tools(aiq_example_double()), generate()],
        scorer=match(),
    )


@task
def sandbox_task():
    """A tool that executes inside Inspect's ``local`` sandbox."""
    return Task(
        dataset=[Sample(input="Use aiq_example_sandbox_double on two.", target="4")],
        solver=[use_tools(aiq_example_sandbox_double()), generate()],
        scorer=match(),
        sandbox="local",
    )


@task
def docker_sandbox_task():
    """The same tool, executing inside a Docker container (opt-in; needs Docker).

    The container has no network and no host mounts; Inspect creates it for
    the sample and removes it afterwards.
    """
    compose = ComposeConfig(services={"default": ComposeService(
        image=DOCKER_SANDBOX_IMAGE,
        command="tail -f /dev/null",
        init=True,
        network_mode="none",
        stop_grace_period="1s",
    )})
    return Task(
        dataset=[Sample(input="Use aiq_example_sandbox_double on two.", target="4")],
        solver=[use_tools(aiq_example_sandbox_double()), generate()],
        scorer=match(),
        sandbox=("docker", compose),
    )
