"""Static metadata for evaluation engines under phase-1 investigation.

These are research targets, not compatibility guarantees. Exact supported pins
remain gated on native smoke tests recorded in the phase-1 evidence ledger.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PinState = Literal['unresolved', 'candidate', 'verified']


@dataclass(frozen=True)
class EngineSpec:
    """Phase-1 metadata for one evaluation engine."""

    key: str
    distribution: str
    module: str
    repository: str
    candidate_revision: str | None
    candidate_version: str | None
    pin_state: PinState
    python_requirement_hint: str | None
    research_notes: tuple[str, ...] = ()


ENGINE_SPECS: dict[str, EngineSpec] = {
    'helm': EngineSpec(
        key='helm',
        distribution='crfm-helm',
        module='helm',
        repository='https://github.com/stanford-crfm/helm.git',
        candidate_revision=None,
        candidate_version='>=0.5.8',
        pin_state='unresolved',
        python_requirement_hint=None,
        research_notes=(
            'aiq-magnet currently declares crfm-helm>=0.5.8.',
            'Phase 1 must select an exact tested version/revision.',
            'Existing MAGNET materialization behavior is an integration target.',
        ),
    ),
    'olmo_eval': EngineSpec(
        key='olmo_eval',
        distribution='olmo-eval',
        module='olmo_eval',
        repository='https://github.com/allenai/olmo-eval.git',
        candidate_revision=None,
        candidate_version=None,
        pin_state='unresolved',
        python_requirement_hint='>=3.12 at the plan-inspected revision',
        research_notes=(
            'The source plan inspected 73ade80e24f796af55caeb8fd7b75a7f3fd607fd.',
            'The supplied eval_audit prototype used c84828e4af096004c561b668b68e0b126c7f60e9.',
            'Do not inherit either pin without rerunning native generation/tool smokes.',
            'Prefer the upstream committed uv.lock in an isolated worker checkout.',
        ),
    ),
    'inspect_ai': EngineSpec(
        key='inspect_ai',
        distribution='inspect-ai',
        module='inspect_ai',
        repository='https://github.com/UKGovernmentBEIS/inspect_ai.git',
        candidate_revision=None,
        candidate_version='0.3.272',
        pin_state='candidate',
        python_requirement_hint='>=3.10 for inspect-ai 0.3.272',
        research_notes=(
            'Phase 4 targets the 0.3.272 public eval/log API surface.',
            'The candidate release was published 2026-09-28; native acceptance is still open.',
            'Use public eval/log APIs only; do not freeze against private internals.',
            'Task factories, agents, scorers, and tools may execute arbitrary Python.',
        ),
    ),
}


def get_engine_spec(key: str) -> EngineSpec:
    """Return an engine spec or raise with the supported names."""
    try:
        return ENGINE_SPECS[key]
    except KeyError as ex:
        known = ', '.join(sorted(ENGINE_SPECS))
        raise KeyError(f'unknown engine {key!r}; expected one of: {known}') from ex
