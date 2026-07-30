from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from robotics_acceptance_harness import __version__
from robotics_acceptance_harness.aggregate import (
    aggregate_results,
    evaluate_trace_aggregate,
    evaluate_transport_qualification,
)
from robotics_acceptance_harness.application import explain_bundle, run_verification
from robotics_acceptance_harness.documents import DocumentBundle, load_bundle
from robotics_acceptance_harness.run_context import create_run_context


def _add_bundle_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scenario", required=True, metavar="PATH")
    parser.add_argument("--runtime", required=True, metavar="PATH")
    parser.add_argument("--model", metavar="PATH")
    parser.add_argument("--dataset", metavar="PATH")
    parser.add_argument("--permit", metavar="PATH")
    parser.add_argument("--verification", metavar="PATH")
    parser.add_argument(
        "--extension-schema",
        action="append",
        default=[],
        metavar="NAMESPACE=PATH",
        help="Digest-pinned local extension schema; may be repeated.",
    )


def _add_trace_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--causal-chain",
        action="append",
        required=True,
        metavar="PATH",
        help="Causal-chain contract; may be repeated for branching flows.",
    )
    parser.add_argument(
        "--trace",
        action="append",
        required=True,
        metavar="DOMAIN=PATH",
        help="Verified per-domain OTLP trace evidence; may be repeated.",
    )
    parser.add_argument(
        "--evidence-index",
        action="append",
        required=True,
        metavar="DOMAIN=PATH",
        help="Finalized per-domain evidence index; may be repeated.",
    )
    parser.add_argument(
        "--channel-contract",
        action="append",
        required=True,
        metavar="PATH",
        help="Zenoh channel contract in causal order; may be repeated.",
    )
    parser.add_argument("--observation-output", required=True, metavar="DIR")
    parser.add_argument("--output", required=True, metavar="PATH")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="robotics-acceptance",
        description="Attach-only acceptance observer for an existing ROS 2 execution.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_run = subparsers.add_parser(
        "create-run",
        help="Create a validated acceptance-run.v1 context.",
    )
    create_run.add_argument("--scenario", required=True, metavar="PATH")
    create_run.add_argument("--output", required=True, metavar="PATH")
    create_run.add_argument("--domain", action="append", required=True, metavar="ID=ROLE")
    create_run.add_argument("--time-authority", required=True, metavar="KIND")
    create_run.add_argument("--time-source", required=True, metavar="ID")
    create_run.add_argument("--run-id", metavar="RUN_ID")

    explain = subparsers.add_parser("explain", help="Validate and explain an execution bundle.")
    _add_bundle_arguments(explain)

    verify = subparsers.add_parser("verify", help="Observe and evaluate a running execution.")
    _add_bundle_arguments(verify)
    verify.add_argument("--run-id", required=True, metavar="RUN_ID")
    verify.add_argument(
        "--domain-id",
        required=True,
        metavar="DOMAIN_ID",
        help="Domain identifier declared by the acceptance run.",
    )
    verify.add_argument(
        "--run-context",
        required=True,
        metavar="PATH",
        help="Validated acceptance-run.v1 context.",
    )
    verify.add_argument("--evidence-index", required=True, metavar="PATH")
    verify.add_argument(
        "--otel-metrics",
        required=True,
        metavar="PATH",
        help="Newline-delimited OTLP JSON from the OpenTelemetry Collector file exporter.",
    )
    verify.add_argument(
        "--measurement-complete",
        required=True,
        metavar="PATH",
        help="Atomically create a marker after the measurement window closes.",
    )
    verify.add_argument("--output", required=True, metavar="DIR")

    aggregate = subparsers.add_parser(
        "aggregate",
        help="Aggregate complete per-domain results for one run.",
    )
    aggregate.add_argument("--run-context", required=True, metavar="PATH")
    aggregate.add_argument("--result", required=True, action="append", metavar="PATH")

    trace_evaluate = subparsers.add_parser(
        "trace-evaluate",
        help="Extend a domain aggregate with channel delivery and causal-trace evidence.",
    )
    trace_evaluate.add_argument("--run-context", required=True, metavar="PATH")
    trace_evaluate.add_argument("--base-aggregate", required=True, metavar="PATH")
    _add_trace_arguments(trace_evaluate)

    transport_evaluate = subparsers.add_parser(
        "transport-evaluate",
        help="Evaluate channel delivery and causal traces without a domain execution.",
    )
    transport_evaluate.add_argument("--run-id", required=True, metavar="RUN_ID")
    _add_trace_arguments(transport_evaluate)

    aggregate.add_argument("--output", required=True, metavar="PATH")
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


def _keyed_values(values: Sequence[str], option: str) -> Mapping[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        key, separator, item = value.partition("=")
        if not separator or not key or not item:
            raise ValueError(f"invalid {option} value: {value!r}")
        if key in parsed:
            raise ValueError(f"duplicate {option} key: {key}")
        parsed[key] = item
    return parsed


def _bundle(arguments: argparse.Namespace) -> DocumentBundle:
    return load_bundle(
        arguments.scenario,
        runtime_path=arguments.runtime,
        model_path=arguments.model,
        dataset_path=arguments.dataset,
        permit_path=arguments.permit,
        verification_path=arguments.verification,
        extension_schemas=_extension_schemas(arguments.extension_schema),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "create-run":
            run_id = create_run_context(
                arguments.scenario,
                arguments.output,
                domains=_keyed_values(arguments.domain, "--domain"),
                time_authority=arguments.time_authority,
                time_source=arguments.time_source,
                run_id=arguments.run_id,
            )
            print(run_id)
            return 0

        if arguments.command == "aggregate":
            output = aggregate_results(
                run_context_path=arguments.run_context,
                result_paths=arguments.result,
                output_path=arguments.output,
            )
            aggregate = json.loads(output.read_text(encoding="utf-8"))
            status = aggregate["per_domain_aggregate"]
            print(json.dumps({"aggregate": str(output), "status": status}, sort_keys=True))
            return 0 if status == "passed" else 1

        if arguments.command == "trace-evaluate":
            output = evaluate_trace_aggregate(
                run_context_path=arguments.run_context,
                base_aggregate_path=arguments.base_aggregate,
                causal_chain_paths=arguments.causal_chain,
                channel_contract_paths=arguments.channel_contract,
                trace_paths=_keyed_values(arguments.trace, "--trace"),
                evidence_index_paths=_keyed_values(
                    arguments.evidence_index,
                    "--evidence-index",
                ),
                observation_output_dir=arguments.observation_output,
                output_path=arguments.output,
            )
            aggregate = json.loads(output.read_text(encoding="utf-8"))
            status = aggregate["cross_domain_e2e"]["status"]
            print(json.dumps({"aggregate": str(output), "status": status}, sort_keys=True))
            return 0 if status == "passed" else 1

        if arguments.command == "transport-evaluate":
            output = evaluate_transport_qualification(
                run_id=arguments.run_id,
                causal_chain_paths=arguments.causal_chain,
                channel_contract_paths=arguments.channel_contract,
                trace_paths=_keyed_values(arguments.trace, "--trace"),
                evidence_index_paths=_keyed_values(
                    arguments.evidence_index,
                    "--evidence-index",
                ),
                observation_output_dir=arguments.observation_output,
                output_path=arguments.output,
            )
            result = json.loads(output.read_text(encoding="utf-8"))
            status = result["verdict"]["status"]
            print(
                json.dumps(
                    {"qualification": str(output), "status": status},
                    sort_keys=True,
                )
            )
            return 0 if status == "passed" else 1

        bundle = _bundle(arguments)
        if arguments.command == "explain":
            print(json.dumps(explain_bundle(bundle), indent=2, sort_keys=True))
            return 0

        outputs = run_verification(
            run_id=arguments.run_id,
            domain_id=arguments.domain_id,
            run_context_path=arguments.run_context,
            bundle=bundle,
            evidence_index_path=arguments.evidence_index,
            otel_metrics_path=arguments.otel_metrics,
            measurement_complete_path=arguments.measurement_complete,
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
