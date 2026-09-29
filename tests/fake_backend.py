"""In-process fake backend for engine-free ensure/store contract tests.

Task names select behavior: ``ok`` succeeds, ``fail`` fails, ``unknown``
resolves to a non-reusable identity. Executions are counted per task.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path

from aiq_evals.contracts import (
    CoverageFacts,
    EvaluationResult,
    MetricRecord,
    ResolvedEvaluation,
    ResultRecord,
    SampleRecord,
)
from aiq_evals.identity import build_measurement_identity

EXECUTIONS: Counter = Counter()


class FakeBackend:
    key = 'fake'
    adapter_version = 'fake-1'

    def capabilities(self):
        return {'requires_worker_process': False}

    def validate_request(self, request):
        pass

    def resolve(self, request):
        facts = {'engine_version': '1.0'}
        if request.task == 'unknown':
            facts['identity_unknown_reasons'] = ['mutable alias']
        identity = build_measurement_identity(
            request, adapter_version=self.adapter_version, engine_version='1.0',
            native_config={'task': request.task}, resolved_facts=facts,
        )
        return ResolvedEvaluation(
            request=request, adapter_version=self.adapter_version, engine_version='1.0',
            native_config={'task': request.task}, identity=identity, resolved_facts=facts,
        )

    async def execute(self, resolved, context):
        task = resolved.request.task
        EXECUTIONS[task] += 1
        native = context.output_dir / 'native'
        native.mkdir(parents=True, exist_ok=True)
        (native / 'log.txt').write_text(f'attempt {EXECUTIONS[task]}\n')
        await asyncio.sleep(0)
        failed = task == 'fail' or (task == 'flaky' and EXECUTIONS[task] < 3)
        return EvaluationResult(
            engine='fake',
            identity=resolved.identity,
            status='failed' if failed else 'succeeded',
            records=(
                ResultRecord(
                    task=task, model_role='primary',
                    metrics=() if failed else (MetricRecord(task=task, model_role='primary', metric='acc', value=1.0),),
                    coverage=CoverageFacts(status='partial' if failed else 'complete', expected=1, processed=1),
                ),
            ),
            samples=(SampleRecord(task=task, model_role='primary', sample_id='s1'),),
        )

    def import_results(self, resolved, source, context):
        text = Path(source, 'value.txt').read_text().strip()
        task = resolved.request.task
        return EvaluationResult(
            engine='fake',
            identity=resolved.identity,
            status='succeeded',
            records=(
                ResultRecord(
                    task=task, model_role='primary',
                    metrics=(MetricRecord(task=task, model_role='primary', metric='acc', value=float(text)),),
                    coverage=CoverageFacts(status='complete', expected=1, processed=1),
                ),
            ),
        )
