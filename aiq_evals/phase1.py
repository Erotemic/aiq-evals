"""Machine-readable phase-1 checklist.

Mirrors ``docs/planning/aiq-evals-plan.md``. A task is ``done`` only when its
native evidence is recorded in ``docs/planning/phase1-evidence.md``; notes name
what remains untested.
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
        'done',
        'Inspect 0.3.272, OLMo 73ade80 (upstream uv.lock), HELM 0.5.14; '
        'constraints in dev/environments/phase1/ reproduce identical environments.',
    ),
    Phase1Task(
        'P1-03',
        'Run OLMo Eval generation and agent/tool smokes',
        'done',
        'Native generation, OpenAI Agents tool call, hard failure, multi-task suite, cancellation.',
    ),
    Phase1Task(
        'P1-04',
        'Run Inspect generation and agent/tool smokes',
        'done',
        'Native generation, tool, roles, multi-log, epochs/reducers, sample/run errors, '
        'cancelled/started logs, local-sandbox cleanup.',
    ),
    Phase1Task(
        'P1-05',
        'Exercise HELM compute and cached materialization/import',
        'done',
        'Fresh local simple-model runs (incl. scored MCQA), MAGNET reuse, incomplete-coverage copy.',
    ),
    Phase1Task(
        'P1-06',
        'Verify worker imports, async boundaries, and cleanup behavior',
        'done',
        'Active-loop boundary and owned-process cleanup shown natively; Inspect local sandbox '
        'removed on completion and cancellation. Docker/OLMo sandboxes untested.',
    ),
    Phase1Task(
        'P1-07',
        'Record initial capability/dependency matrix',
        'done',
        'docs/planning/phase1-capabilities.md; untested cells stay T.',
    ),
    Phase1Task(
        'P1-08',
        'Decide EEE normalization strategy from fixture conversions',
        'done',
        'ADR-0008: independent normalized schema; EEE rejects Inspect local models, lacks OLMo.',
    ),
    Phase1Task(
        'P1-09',
        'Make OLMo Eval packaging go/no-go decision',
        'done',
        'Isolated pinned worker checkout with upstream lock; no co-installed extra.',
    ),
    Phase1Task(
        'P1-10',
        'Phase-1 acceptance gate',
        'done',
        'Native conditions met. The MAGNET cardinality spike moved to integration gate M6, '
        'which consumes the captured multi-result fixtures.',
    ),
)
