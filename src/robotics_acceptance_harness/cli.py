from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from robotics_acceptance_harness import __version__
from robotics_acceptance_harness.application import explain_bundle, run_verification
from robotics_acceptance_harness.documents import DocumentBundle, load_bundle


def _add_bundle_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scenario", required=True, metavar="PATH")
    parser.add_argument("--runtime", metavar="PATH")
    parser.add_argument("--model", metavar="PATH")
    parser.add_argument("--dataset", metavar="PATH")
    parser.add_argument("--permit", metavar="PATH")
    parser.add_argument(
        "--extension-schema",
        action="append",
        default=[],
        metavar="NAMESPACE=PATH",
        help="Digest-pinned local extension schema; may be repeated.",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="robotics-acceptance",
        description="Attach-only acceptance observer for an existing ROS 2 execution.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    explain = subparsers.add_parser("explain", help="Validate and explain an execution bundle.")
    _add_bundle_arguments(explain)

    verify = subparsers.add_parser("verify", help="Observe and evaluate a running simulation.")
    _add_bundle_arguments(verify)
    verify.add_argument("--evidence-index", required=True, metavar="PATH")
    verify.add_argument(
        "--otel-metrics",
        metavar="PATH",
        help="Newline-delimited OTLP JSON from the OpenTelemetry Collector file exporter.",
    )
    verify.add_argument("--output", required=True, metavar="DIR")
    return parser


def _extension_schemas(values: Sequence[str]) -> Mapping[str, bytes]:
    schemas: dict[str, bytes] = {}
    for value in values:
        namespace, separator, path_value = value.partition("=")
        if not separator or not namespace or not path_value:
            raise ValueError(f"invalid --extension-schema value: {value!r}")
        if namespace in schemas:
            raise ValueError(f"duplicate extension schema namespace: {namespace}")
        path = Path(path_value).expanduser().resolve()
        try:
            schemas[namespace] = path.read_bytes()
        except OSError as error:
            raise ValueError(f"cannot read extension schema {path}: {error}") from error
    return schemas


def _bundle(arguments: argparse.Namespace) -> DocumentBundle:
    return load_bundle(
        arguments.scenario,
        runtime_path=arguments.runtime,
        model_path=arguments.model,
        dataset_path=arguments.dataset,
        permit_path=arguments.permit,
        extension_schemas=_extension_schemas(arguments.extension_schema),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        bundle = _bundle(arguments)
        if arguments.command == "explain":
            print(json.dumps(explain_bundle(bundle), indent=2, sort_keys=True))
            return 0

        outputs = run_verification(
            bundle=bundle,
            evidence_index_path=arguments.evidence_index,
            otel_metrics_path=arguments.otel_metrics,
            output_dir=arguments.output,
        )
        print(
            json.dumps(
                {
                    "status": outputs.result["status"],
                    "result": str(outputs.result_path),
                    "junit": str(outputs.junit_path),
                },
                sort_keys=True,
            )
        )
        return 0 if outputs.result["status"] == "passed" else 1
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
