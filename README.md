# aiq-evals

`aiq-evals` is a backend-agnostic evaluation runtime and artifact interface.
Its intended high-level operation is:

```text
fully specified evaluation request
        |
        v
resolve measurement identity
        |
        +---- reusable compatible result exists? ----+
        |                                            |
       yes                                           no
        |                                            |
        v                                            v
load / import                                 execute native engine
        |                                            |
        +----------------------+---------------------+
                               |
                               v
                  normalized evaluation result
```

The initial engines are HELM, OLMo Eval, and Inspect. `aiq-evals` is not a
scheduler and is not a scientific claim system. MAGNET is expected to consume
its results and decide how a selected metric becomes claim evidence.

## Current status

This archive implements the **phase-1 repository foundation**. It intentionally
does not claim that native HELM/OLMo Eval/Inspect runtime checks were performed
in the build environment. Those runtimes were not installed here.

Implemented now:

- standalone package/repository boundary;
- machine-readable phase-1 checklist;
- engine research metadata;
- source-checkout and local-environment probe tooling;
- locked `uv` worker command helper;
- canonical phase-1 evidence ledger format;
- refined standalone roadmap;
- separate MAGNET integration roadmap;
- dependency-free core tests.

Open phase-1 work is explicit in `docs/planning/phase1-evidence.md`.

## Bootstrap

```bash
python -m pip install -e '.[tests]'
pytest -q
aiq-evals phase1-status
aiq-evals phase1-probe
```

To inspect exact upstream source checkouts without importing them:

```bash
aiq-evals phase1-probe \
    --checkout olmo_eval=/path/to/olmo-eval \
    --checkout inspect_ai=/path/to/inspect_ai \
    --checkout helm=/path/to/helm \
    --output phase1-artifacts/local-probe.json
```

The probe is deliberately non-executing. Native generation/tool/cancellation
fixtures are the next phase-1 acceptance work.

## Planning

- `docs/planning/aiq-evals-plan.md`: work owned by this repository.
- `docs/planning/aiq-magnet-integration-plan.md`: work that belongs in MAGNET.
- `docs/planning/phase1-evidence.md`: canonical phase-1 evidence ledger.
- `docs/planning/architecture.md`: package boundary and identity model.
