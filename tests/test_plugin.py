from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def run_isolated(pytester: pytest.Pytester, *args: str) -> pytest.RunResult:
    config = pytester.makeini("[pytest]\n")
    return pytester.runpytest(
        "-c",
        str(config),
        "--rootdir",
        str(pytester.path),
        *args,
    )


def make_test(pytester: pytest.Pytester) -> Path:
    return pytester.makepyfile(
        """
        def test_scenario_is_available(robotics_scenario):
            assert robotics_scenario["scenario_id"]
        """
    )


def run_with_fixture(
    pytester: pytest.Pytester,
    fixture_name: str,
) -> pytest.RunResult:
    test_file = make_test(pytester)
    return run_isolated(
        pytester,
        test_file.name,
        "--robotics-scenario",
        str(FIXTURES / fixture_name),
    )


def test_simulation_scenario_runs_tests(pytester: pytest.Pytester) -> None:
    result = run_with_fixture(pytester, "simulation.yaml")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize("fixture_name", ["hil.yaml", "real-robot.yaml"])
def test_non_simulation_target_stops_before_test_body(
    pytester: pytest.Pytester,
    fixture_name: str,
) -> None:
    result = run_with_fixture(pytester, fixture_name)

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*accepts only target_environment=simulation*"])


def test_missing_scenario_option_is_a_usage_error(pytester: pytest.Pytester) -> None:
    test_file = make_test(pytester)
    result = run_isolated(pytester, test_file.name)

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*--robotics-scenario PATH is required*"])


def test_malformed_yaml_is_a_usage_error(pytester: pytest.Pytester) -> None:
    test_file = make_test(pytester)
    scenario = pytester.makefile(".yaml", scenario="expected_ros_graph: [")
    result = run_isolated(
        pytester,
        test_file.name,
        "--robotics-scenario",
        str(scenario),
    )

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*cannot parse robotics scenario*"])


def test_invalid_contract_reports_json_path(pytester: pytest.Pytester) -> None:
    test_file = make_test(pytester)
    scenario = pytester.makefile(
        ".yaml",
        scenario="""
        schema_version: acceptance-scenario.v1
        scenario_id: invalid-target
        target_environment: staging
        seed: 0
        timeouts:
          startup_sec: 1
          graph_ready_sec: 1
          execution_sec: 1
          shutdown_sec: 1
        expected_ros_graph:
          stable_for_sec: 0
          topics: []
          services: []
          actions: []
        """,
    )
    result = run_isolated(
        pytester,
        test_file.name,
        "--robotics-scenario",
        str(scenario),
    )

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*$.target_environment:*"])


def test_scenario_fixture_is_deeply_immutable(pytester: pytest.Pytester) -> None:
    test_file = pytester.makepyfile(
        """
        import pytest

        def test_scenario_is_immutable(robotics_scenario):
            with pytest.raises(TypeError):
                robotics_scenario["seed"] = 2
            with pytest.raises(TypeError):
                robotics_scenario["timeouts"]["startup_sec"] = 2
        """
    )
    result = run_isolated(
        pytester,
        test_file.name,
        "--robotics-scenario",
        str(FIXTURES / "simulation.yaml"),
    )
    result.assert_outcomes(passed=1)


def test_help_has_no_physical_execution_bypass(pytester: pytest.Pytester) -> None:
    result = run_isolated(pytester, "--help")

    assert result.ret == pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*--robotics-scenario=PATH*"])
    assert "allow-physical" not in result.stdout.str()
