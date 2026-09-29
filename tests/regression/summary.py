"""Stable, engine-free summaries of normalized results for fixture regression.

Shared by ``dev/regenerate_native_regressions.py`` (which runs in the native
engine environments) and the dependency-free regression tests.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from magnet_evals.contracts import EvaluationResult


def summarize(result: EvaluationResult) -> dict[str, Any]:
    records = []
    for record in result.records:
        records.append(
            {
                'task': record.task,
                'native_status': record.native_status,
                'coverage': record.coverage.to_dict(),
                'has_error': record.error is not None,
                'metrics': sorted(
                    (
                        [m.scorer, m.score, m.metric, m.group, m.reducer, m.denominator, round(m.value, 9)]
                        for m in record.metrics
                    ),
                    key=json.dumps,
                ),
            }
        )
    kinds = Counter(str(sample.native.get('kind', 'sample')) for sample in result.samples)
    return {
        'status': result.status,
        'records': sorted(records, key=lambda item: item['task']),
        'sample_kinds': dict(sorted(kinds.items())),
        'epochs': sorted({sample.epoch for sample in result.samples if sample.epoch is not None}),
        'samples_with_trajectory': sum(1 for sample in result.samples if sample.trajectory),
        'tool_messages': sum(
            1
            for sample in result.samples
            if isinstance(sample.trajectory, dict)
            # Inspect trajectories hold ``messages``; OLMo trajectories ``turns``.
            for message in (sample.trajectory.get('messages') or sample.trajectory.get('turns') or [])
            if isinstance(message, dict) and message.get('role') == 'tool'
        ),
    }
