from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


def load_extension_schemas(
    values: Sequence[str],
    *,
    option: str = "--extension-schema",
) -> dict[str, bytes]:
    """Load digest-pinned extension schemas keyed by their canonical URI."""

    schemas: dict[str, bytes] = {}
    for value in values:
        uri, separator, path_value = value.partition("=")
        if not separator or not uri or not path_value:
            raise ValueError(f"invalid {option} value: {value!r}; expected URI=PATH")
        if uri in schemas:
            raise ValueError(f"duplicate {option} URI: {uri}")
        path = Path(path_value).expanduser().resolve()
        try:
            schemas[uri] = path.read_bytes()
        except OSError as error:
            raise ValueError(f"cannot read extension schema {path}: {error}") from error
    return schemas


__all__ = ["load_extension_schemas"]
