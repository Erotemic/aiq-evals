"""ADR-0009 pins the first public surface; changing it must be deliberate."""
import aiq_evals
from aiq_evals import cli, contracts, identity

FROZEN_EXPORTS = {
    'ENGINE_SPECS', 'EngineSpec', 'EnsureOutcome', 'EvaluationRequest', 'EvaluationResult',
    'ExecutionContext', 'MeasurementIdentity', 'ModelBinding', 'ResolvedEvaluation', 'ResultStore',
    '__version__', 'ensure_evaluation', 'ensure_evaluation_async', 'import_evaluation', 'load_run',
    'resolve_evaluation', 'resolve_evaluation_async', 'run_evaluation', 'run_evaluation_async',
    'validate_request',
}
FROZEN_COMMANDS = {
    'phase1-status', 'phase1-probe', 'engines', 'backends', 'validate', 'resolve', 'ensure',
    'run', 'import-native', 'show',
}


def test_exports_are_a_superset_of_the_frozen_surface():
    # Additions are allowed; removals/renames need a superseding ADR.
    assert FROZEN_EXPORTS <= set(aiq_evals.__all__)
    for name in FROZEN_EXPORTS:
        assert hasattr(aiq_evals, name)


def test_schema_versions_and_identity_algorithm_are_frozen():
    assert contracts.REQUEST_SCHEMA_VERSION == 1
    assert contracts.RESULT_SCHEMA_VERSION == 1
    assert contracts.MANIFEST_SCHEMA_VERSION == 1
    assert identity.IDENTITY_ALGORITHM == 'aiq-evals-measurement-v2+sha256'


def test_cli_commands_are_a_superset_of_the_frozen_surface():
    parser = cli._parser()
    subparsers = next(a for a in parser._actions if a.dest == 'command')
    assert FROZEN_COMMANDS <= set(subparsers.choices)
