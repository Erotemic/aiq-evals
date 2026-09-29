"""Installed, deterministic example tasks for each engine.

These modules let the example requests (``examples/*.json``) and MAGNET's
``magnet/examples/aiq_evals`` recipes run from an installed package, without a
source checkout. Each engine module imports its engine at import time, so it is
only ever imported inside that engine's worker (through ``task_modules`` /
``registration_modules`` or a ``python:`` task reference):

* :mod:`magnet_evals.examples.inspect_tasks` - Inspect tasks and a local
  deterministic ``aiq_example`` model provider (generation, tool use, and a
  tool running in Inspect's ``local`` sandbox);
* :mod:`magnet_evals.examples.olmo_tasks` - registered OLMo Eval tasks and an
  ``aiq_example_double`` tool;
* :mod:`magnet_evals.examples.chat_server` - an engine-free, deterministic
  OpenAI-compatible endpoint for the agent/tool examples.

The model is deterministic and local, but everything else is the engine's own
behavior: task loading, tool dispatch, scoring, epoch reduction, and logs.
HELM needs no example module; its examples use HELM's built-in
``simple_mcqa`` scenario and ``simple/model1`` client.
"""
