"""Machine-readable phase-1 checklist.

The checklist mirrors the refined planning documents. Status here describes the
repository snapshot, not external runtime validation performed elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TaskStatus = Literal['done', 'partial', 'open', 'blocked']


@dataclass(frozen=True)
class Phase1Task:
    id: str
    title: str
    status: TaskStatus
    note: str


PHASE1_TASKS = (
    Phase1Task(
        'P1-01',
        'Create canonical evidence ledger and record template',
        'done',
        'docs/planning/phase1-evidence.md defines the durable record format.',
    ),
    Phase1Task(
        'P1-02',
        'Select exact upstream pins and reproducible worker instructions',
        'partial',
        'Candidate history and source-probe tooling are recorded; exact tested pins remain open.',
    ),
    Phase1Task(
        'P1-03',
        'Run OLMo Eval generation and agent/tool smokes',
        'open',
        'Requires an upstream checkout/runtime; do not infer success from the older eval_audit prototype.',
    ),
    Phase1Task(
        'P1-04',
        'Run Inspect generation and agent/tool smokes',
        'open',
        'Requires selected Inspect pin and native fixtures.',
    ),
    Phase1Task(
        'P1-05',
        'Exercise HELM compute and cached materialization/import',
        'open',
        'Requires MAGNET/HELM integration fixture execution.',
    ),
    Phase1Task(
        'P1-06',
        'Verify worker imports, async boundaries, and cleanup behavior',
        'open',
        'Must be demonstrated against native runtimes.',
    ),
    Phase1Task(
        'P1-07',
        'Record initial capability/dependency matrix',
        'partial',
        'Architecture and candidate dependency strategy are documented; runtime capabilities remain unverified.',
    ),
    Phase1Task(
        'P1-08',
        'Prove MAGNET one-artifact/one-row cardinality',
        'open',
        'Owned by the aiq-magnet integration plan, not by aiq-evals core.',
    ),
    Phase1Task(
        'P1-09',
        'Make OLMo Eval packaging go/no-go decision',
        'open',
        'Requires clean worker installation and native smoke evidence.',
    ),
    Phase1Task(
        'P1-10',
        'Phase-1 acceptance gate',
        'blocked',
        'Blocked until P1-02 through P1-09 have runtime evidence.',
    ),
)
