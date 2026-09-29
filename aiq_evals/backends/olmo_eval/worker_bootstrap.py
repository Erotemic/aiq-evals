"""Import registered OLMo task/tool modules in native spawned workers."""

import importlib
from typing import Any


def inference_worker_with_registration(modules: tuple[str, ...], *args: Any) -> None:
    for module in modules:
        importlib.import_module(module)
    from olmo_eval.runners.asynq.workers import inference_worker

    # The adapter restores the original target in the parent after run_async;
    # the spawned interpreter imports the unpatched upstream function here.
    inference_worker(*args)
