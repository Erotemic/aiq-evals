"""HELM plugin registering deterministic failing and slow run specs.

Imported by HELM through ``--plugins`` (and by the adapter during resolution).
Both reuse HELM's SimpleMCQA setup; only instance loading differs.
"""

import os
import subprocess
import time

from helm.benchmark.adaptation.common_adapter_specs import (
    get_multiple_choice_joint_adapter_spec,
)
from helm.benchmark.metrics.common_metric_specs import get_exact_match_metric_specs
from helm.benchmark.run_spec import RunSpec, run_spec_function
from helm.benchmark.scenarios.scenario import ScenarioSpec
from helm.benchmark.scenarios.simple_scenarios import SimpleMCQAScenario


class FailingScenario(SimpleMCQAScenario):
    name = "aiq_p5_fail"

    def get_instances(self, output_path):
        raise RuntimeError("intentional HELM scenario failure")


class SlowScenario(SimpleMCQAScenario):
    name = "aiq_p5_slow"

    def get_instances(self, output_path):
        child = subprocess.Popen(["sleep", "120"])
        with open(os.environ["AIQ_P5_CHILD_PID_FILE"], "w") as file:
            file.write(str(child.pid))
        time.sleep(120)
        return super().get_instances(output_path)


def _run_spec(name, scenario):
    return RunSpec(
        name=name,
        scenario_spec=ScenarioSpec(class_name=f"{__name__}.{scenario.__name__}"),
        adapter_spec=get_multiple_choice_joint_adapter_spec(
            instructions="Answer with a single letter.", input_noun="Question", output_noun="Answer"
        ),
        metric_specs=get_exact_match_metric_specs(),
        groups=[name],
    )


@run_spec_function("aiq_p5_fail")
def get_fail_run_spec():
    return _run_spec("aiq_p5_fail", FailingScenario)


@run_spec_function("aiq_p5_slow")
def get_slow_run_spec():
    return _run_spec("aiq_p5_slow", SlowScenario)
