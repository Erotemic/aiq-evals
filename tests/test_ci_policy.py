import textwrap

pytest_plugins = ['pytester']


def _conftest():
    from pathlib import Path

    return (Path(__file__).with_name('conftest.py')).read_text()


def test_release_gate_tests_cannot_be_quarantined(pytester):
    pytester.makeconftest(_conftest())
    pytester.makepyfile(test_schema_compat='def test_gate():\n    assert False\n')
    pytester.makefile('.txt', quarantine='test_schema_compat.py::test_gate\n')
    result = pytester.runpytest_subprocess()
    result.stderr.fnmatch_lines(['*release_gate test and cannot be quarantined*'])
    assert result.ret != 0


def test_quarantined_failure_reports_xfail_not_pass(pytester):
    pytester.makeconftest(_conftest())
    pytester.makepyfile(test_flaky='def test_flaky():\n    assert False\n')
    pytester.makefile('.txt', quarantine='test_flaky.py::test_flaky\n')
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(xfailed=1)


def test_external_network_failures_are_classified_once(pytester):
    pytester.makeconftest(_conftest())
    pytester.makepyfile(
        test_ext=textwrap.dedent(
            """
            import pytest

            @pytest.mark.external
            def test_endpoint():
                raise ConnectionError('service down')

            @pytest.mark.external
            def test_logic():
                assert False
            """
        )
    )
    result = pytester.runpytest_subprocess('-rs', '-p', 'no:cacheprovider')
    result.assert_outcomes(skipped=1, failed=1)
    result.stdout.fnmatch_lines(['*external-unavailable*'])
