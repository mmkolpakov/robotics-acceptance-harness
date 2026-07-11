# Security Policy

## Supported Version

Security fixes are provided for the latest tagged minor release.

## Reporting

Report vulnerabilities through GitHub private vulnerability reporting. Do not
open a public issue for credentials, unsafe physical-target behavior, or a way
to bypass the attach-only boundary.

Include the affected release, execution mode, minimal reproduction, and impact.
Do not include production keys, private scenarios, or real device identities.

The harness is an acceptance observer, not a functional-safety mechanism. HIL
and physical operation require independent interlocks, authorization, network
policy, and emergency-stop controls in the consuming system.
