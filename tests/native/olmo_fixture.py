"""Small registered OLMo task for native runner probes."""

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
