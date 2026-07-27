# Supply-Chain Assurance

This declaration evaluates release wheel and source distributions against the
[SLSA 1.2 Build track](https://slsa.dev/spec/v1.2/). The current claim is
**Build L2**. It does not apply to local development builds.

## Component Assessment

| SLSA 1.2 requirement | Repository evidence | Status |
| --- | --- | --- |
| Consistent build process | Tagged releases run `.github/workflows/release.yml` and `uv build --no-sources` | Met |
| Hosted build platform | Releases use a GitHub-hosted Ubuntu runner | Met |
| Provenance exists | `actions/attest` records each wheel and source archive by digest | Met |
| Authentic provenance | GitHub signs the artifact attestation outside user build steps | Met |
| Provenance distribution | Attestations are discoverable with the GitHub release artifact | Met |
| Consumer verification | `gh attestation verify --repo mmkolpakov/robotics-acceptance-harness FILE` | Required |
| Unforgeable provenance | No Build L3 claim; the release workflow is not a qualified reusable builder | Not claimed |
| Isolated build platform | No independent Build L3 assessment is published by this project | Not claimed |

Build L2 permits best-effort resolved dependency completeness. The lockfile pins
the development graph; the wheel carries standard version constraints. The
contracts source override is disabled by `uv build --no-sources`.

The release workflow builds and tests the distributions once in a job without
OIDC authority. It uploads those files as a short-lived workflow artifact.
Two independent jobs then download the same files:

- `publish-pypi` publishes them through PyPI Trusted Publishing;
- `github-release` attests them and attaches them to the GitHub Release.

Only `publish-pypi` has the PyPI OIDC permission. That job does not check out
the repository or execute project code. No PyPI API token is used or stored.

## Release Verification

Download the wheel or source archive and verify its attestation before
installation:

```bash
gh attestation verify \
  --repo mmkolpakov/robotics-acceptance-harness \
  robotics_acceptance_harness-*.whl
```

The repository does not claim SLSA Source-track conformance or Build L3.
Reaching Build L3 requires a separately reviewed reusable build workflow and a
published assessment of the builder controls.

## Trusted Publisher Setup

Status: **pending external configuration**.

Before the first publication, create and protect the GitHub environment named
`pypi`. Register a pending publisher if the project does not yet exist on PyPI;
otherwise add a Trusted Publisher to the existing project. Use these exact
values:

| PyPI field | Value |
| --- | --- |
| Owner | `mmkolpakov` |
| Repository | `robotics-acceptance-harness` |
| Workflow | `release.yml` |
| Environment | `pypi` |

Do not create a `PYPI_API_TOKEN` secret. Until the external publisher is
registered, the PyPI job is expected to fail closed.

Release `robotics-runtime-contracts` v0.8.0 first and verify its GitHub Release
wheel and build-provenance attestation. Foundation consumers pin that wheel by
URL and SHA-256. PyPI promotion remains a separate fail-closed channel until
the trusted publisher is registered. Only then create and push the protected
`robotics-acceptance-harness` v0.9.1 tag. The tag must equal `v` followed by the
installed harness package version.
