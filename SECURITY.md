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

## Observer Independence

The observer must remain outside the command and lifecycle control paths of the
system under test. Its process identity receives only the ROS graph permissions
needed to discover declared interfaces, subscribe to evidence topics, and query
managed-node state. A harness defect or compromise must not grant command
publication, service-server, action-server, or lifecycle-transition authority.

Semgrep is a repository-level tripwire, not the runtime enforcement boundary.
Physical deployments enforce least privilege with
[SROS2 security enclaves](https://docs.ros.org/en/ros2_documentation/jazzy/Tutorials/Advanced/Security/The-Keystore.html),
DDS Security governance and permissions, network isolation, and independent
hardware interlocks. The harness consumes the resulting verified facts; it does
not create keys or relax security policy.
