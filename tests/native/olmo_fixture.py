"""Small registered OLMo task for native runner probes."""

import os
import subprocess
import time

from olmo_eval.common.metrics import AccuracyMetric
from olmo_eval.common.scorers.substring import SubstringRecallScorer
from olmo_eval.common.types import Instance, LMRequest, RequestType
from olmo_eval.evals.tasks.common import Task, register


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
