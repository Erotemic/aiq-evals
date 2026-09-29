"""Registered OLMo Eval example tasks and the ``aiq_example_double`` tool.

Use with ``"engine_options": {"task_modules": ["magnet_evals.examples.olmo_tasks"]}``.
``aiq_example_local`` scores a completion from OLMo's ``mock`` provider;
``aiq_example_tool`` is a chat task for a tool-using scaffold (for example
``openai_agents`` against :mod:`magnet_evals.examples.chat_server`).
"""

from olmo_eval.common.metrics import AccuracyMetric
from olmo_eval.common.scorers.substring import SubstringRecallScorer
from olmo_eval.common.types import Instance, LMRequest, RequestType
from olmo_eval.evals.tasks.common import Task, register
from olmo_eval.harness.tools import registered_tool


@register("aiq_example_local")
class ExampleLocalTask(Task):
    metrics = (AccuracyMetric(name="contains_42", scorer=SubstringRecallScorer()),)
    primary_metric = metrics[0]

    @property
    def instances(self):
        yield Instance(question="Answer with 42.", gold_answer="42")

    def format_request(self, instance):
        return LMRequest(request_type=RequestType.COMPLETION, prompt=instance.question)


@registered_tool(name="aiq_example_double", description="Double an integer")
def aiq_example_double(value: int) -> str:
    return str(value * 2)


@register("aiq_example_tool")
class ExampleToolTask(ExampleLocalTask):
    @property
    def instances(self):
        yield Instance(question="Use aiq_example_double on two.", gold_answer="4")

    def format_request(self, instance):
        return LMRequest(
            request_type=RequestType.CHAT,
            messages=({"role": "user", "content": "Use aiq_example_double on two. Return only the result."},),
        )
