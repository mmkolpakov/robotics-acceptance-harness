from __future__ import annotations

from robotics_acceptance_harness import __version__ as current_version
from robotics_acceptance_harness.plugin import _load_scenario as current_loader
from robotics_simulation_harness import __version__ as legacy_version
from robotics_simulation_harness.plugin import _load_scenario as legacy_loader


def test_legacy_import_forwards_to_renamed_package() -> None:
    assert legacy_version == current_version == "0.5.1"
    assert legacy_loader is current_loader
