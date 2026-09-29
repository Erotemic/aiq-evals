"""Small registered OLMo task for native runner probes."""

import os
import subprocess
import time

from olmo_eval.common.metrics import AccuracyMetric
from olmo_eval.common.scorers.substring import SubstringRecallScorer
from olmo_eval.common.types import Instance, LMRequest, RequestType
from olmo_eval.evals.suites.registry import Suite
from olmo_eval.evals.suites.registry import register as register_suite
from olmo_eval.evals.tasks.common import Task, register
from olmo_eval.harness.tools import registered_tool


@register("aiq_p1_local")
class LocalTask(Task):
    metrics = (AccuracyMetric(name="contains_42", scorer=SubstringRecallScorer()),)
    primary_metric = metrics[0]

    @property
    def instances(self):
        yield Instance(question="Answer with 42.", gold_answer="42")

    def format_request(self, instance):
        return LMRequest(request_type=RequestType.COMPLETION, prompt=instance.question)


@register("aiq_p1_slow")
class SlowTask(LocalTask):
    def format_request(self, instance):
        child = subprocess.Popen(["sleep", "120"])
        with open(os.environ["AIQ_P1_CHILD_PID_FILE"], "w") as file:
            file.write(str(child.pid))
        time.sleep(120)
        return super().format_request(instance)


@registered_tool(name="crash", description="Always raises")
def crash(value: int) -> str:
    raise RuntimeError("tool crashed")


@registered_tool(name="double", description="Double an integer")
def double(value: int) -> str:
    return str(value * 2)


@register("aiq_p1_tool")
class ToolTask(LocalTask):
    @property
    def instances(self):
        yield Instance(question="Use double on two.", gold_answer="4")

    def format_request(self, instance):
        return LMRequest(
            request_type=RequestType.CHAT,
            messages=({"role": "user", "content": "Use double on two. Return only the result."},),
        )


@register("aiq_p1_local_alt")
class AlternateLocalTask(LocalTask):
    @property
    def instances(self):
        yield Instance(question="Return 42.", gold_answer="42")


register_suite(Suite(name="aiq_p1_multi", tasks=("aiq_p1_local", "aiq_p1_local_alt")))
