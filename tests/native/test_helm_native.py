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
