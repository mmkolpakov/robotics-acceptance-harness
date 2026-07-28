from importlib.metadata import version

from robotics_acceptance_harness import __version__


def test_runtime_version_matches_distribution_metadata() -> None:
    assert __version__ == version("robotics-acceptance-harness")
