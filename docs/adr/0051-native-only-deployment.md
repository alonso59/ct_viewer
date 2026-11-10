# ADR-0051 Native conda is the only deployment; the image is a test artifact; udocker is removed
Status: Accepted · Date: 2026-11-10 (owner decision, same date)
Supersedes: ADR-0007. Supersedes ADR-0043 only for its Docker/udocker option, its decision 4 ("the image stays" as a deployment) and Apptainer on HPC; its native release, Node-as-build-tool and HPC placement decisions stand. Does not change ADR-0002, ADR-0014, ADR-0016 or ADR-0034.

**Context.** ADR-0043 measured udocker at 2.6–8.7× slower conversions and 1.7–16.7× slower server responses than native on `john`, with no isolation gained. Production has run native releases only since 2026-11-04, and every rollback target in use is native. Keeping a second deployment path cost a vendored udocker release, a launcher (`./rw`), a compose definition with a parity test, an image-tar normalizer, and a rule (R3) that every feature work under both.

**Decision.**
1. **One deployment.** Production is the native conda release of ADR-0043 (`scripts/rw-native.py`, OPS-22), on a single server and on an HPC service or submission node (OPS-23).
2. **The image is a test artifact.** CI still builds one OCI image with Docker and runs the container smoke and DICOM lifecycle checks in it (TST-10), because that proves the product installs and runs from a clean, pinned tree. Nothing deploys it: no compose file, launcher, saved tar or Apptainer conversion.
3. **udocker is removed**: the vendored release, its wrapper and run scripts, the Makefile runtime and the launcher. On a server without sudo, Node for building and development comes from a conda environment (R4).
4. **R3 is reworded** to state 1 and 2. OPS-09 is retired.

**Consequences.**
+ One path to keep correct; about 11,000 lines (the vendored release, the launcher and the parity machinery) go. − No portable artifact for a host without conda, and Docker users lose `./rw up`; a container deployment would need a new ADR.
− Old container releases still on disk can no longer be started from this repository. `rw-native.py rollback` keeps restoring whatever unit a backup holds, but nothing here rebuilds a container.
− The host browser acceptance (`make test-host-browser`) now needs Playwright's browsers installed for the user instead of a prepared container.

**Rejected.**
- Keeping Docker compose as a second supported deployment: it is the cost this ADR removes, without a user.
- Dropping the image from CI too: the clean-tree install and arbitrary-UID checks cover what a developer checkout cannot.
