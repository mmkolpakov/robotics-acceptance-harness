"""Attach-only acceptance harness for validated robotics executions."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("robotics-acceptance-harness")
except PackageNotFoundError:
    __version__ = "0+unknown"
