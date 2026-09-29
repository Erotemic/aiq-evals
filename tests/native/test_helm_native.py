"""Exercise MAGNET's existing HELM import/reuse path against native files."""

from pathlib import Path

import pytest

pytest.importorskip("helm")

from magnet.backends.helm.cli.materialize_helm_run import MaterializeHelmRunConfig
from magnet.backends.helm.helm_outputs import HelmRun

FIXTURE = Path(__file__).parents[1] / "fixtures" / "helm-native" / "mmlu-philosophy-gpt2"
RUN_NAME = "mmlu:subject=philosophy,method=multiple_choice_joint,model=openai_gpt2"


def test_helm_reuse_and_incomplete_coverage(tmp_path: Path) -> None:
    precomputed = tmp_path / "precomputed" / "benchmark_output" / "runs" / "source"
    precomputed.mkdir(parents=True)
    (precomputed / RUN_NAME).symlink_to(FIXTURE.resolve(), target_is_directory=True)
    output = tmp_path / "reused"
    manifest = MaterializeHelmRunConfig.main(
        [
            "--run-entry", "mmlu:subject=philosophy,model=openai/gpt2",
            "--suite", "native-fixture",
            "--out-dpath", str(output),
            "--precomputed-root", str(tmp_path / "precomputed"),
            "--mode", "reuse_only",
            "--materialize", "copy",
        ]
    )
    assert manifest["status"] == "reused"
    assert (output / "DONE").exists()
    run = HelmRun(output / "benchmark_output" / "runs" / "native-fixture" / RUN_NAME)
    assert run.exists()
    assert len(run.json.stats()) == 162
    assert len(run.json.per_instance_stats()) == 10

    partial_source = tmp_path / "partial" / "benchmark_output" / "runs" / "source" / RUN_NAME
    partial_source.mkdir(parents=True)
    for name in ("run_spec.json", "scenario_state.json", "stats.json"):
        (partial_source / name).symlink_to(FIXTURE / name)
    partial = MaterializeHelmRunConfig.main(
        [
            "--run-entry", "mmlu:subject=philosophy,model=openai/gpt2",
            "--suite", "native-fixture",
            "--out-dpath", str(tmp_path / "partial-reused"),
            "--precomputed-root", str(tmp_path / "partial"),
            "--mode", "reuse_only",
            "--require-per-instance-stats", "false",
        ]
    )
    assert partial["status"] == "reused"
    assert not (Path(partial["reuse"]["materialized_run_dir"]) / "per_instance_stats.json").exists()


def test_helm_fresh_simple_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Compute a real HELM run through MAGNET with HELM's local simple client."""
    import os
    import sys

    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"])
    output = tmp_path / "fresh"
    manifest = MaterializeHelmRunConfig.main(
        [
            "--run-entry", "simple1:model=simple/model1",
            "--suite", "aiq-p1-fresh",
            "--max-eval-instances", "1",
            "--num-threads", "1",
            "--out-dpath", str(output),
            "--mode", "compute_if_missing",
        ]
    )
    assert manifest["status"] == "computed"
    assert (output / "DONE").exists()
    run = HelmRun(output / "benchmark_output" / "runs" / "aiq-p1-fresh" / "simple1:model=simple_model1")
    assert len(run.json.stats()) == 57
    assert len(run.json.per_instance_stats()) == 30  # Ten test IDs over three train trials.
    assert "30 computes" in (output / "helm-run.log").read_text()
