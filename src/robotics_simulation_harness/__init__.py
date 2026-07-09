"""pytest plugin: simulation-only execution guard for robotics test suites.

Scenario resolution now belongs to Hydra, process/container lifecycle to
`pytest-docker`, ROS graph readiness checks to `launch_testing_ros`, and
evidence/metrics to `pytest --junitxml` + SLSA Provenance. This package's
only remaining job is the execution guard in `guard.py`, exposed as a
`pytest11` plugin (see `pyproject.toml`).
"""

__version__ = "0.3.0"
