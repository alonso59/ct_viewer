# ADR-0006 Radiomics via engine adapter; PyRadiomics default; IBSI hidden from the GUI
Status: Accepted (P1 spike pending) · Date: 2026-09-23

**Context.** Users need every extraction option configurable, defaults visible, and IBSI as the reference, without IBSI jargon in the UI. PyRadiomics is the de facto engine, but its maintenance and Python 3.12 wheel availability must be verified.

**Decision.** A `RadiomicsEngine` protocol (RADIOMICS.md) with PyRadiomics as the default adapter. The engine publishes a settings schema that drives the UI form. IBSI codes and compliance status live in `ibsi_map.json` and exports, and are verified by TST-06.

**Spike (P1).** Install the pinned PyRadiomics on Python 3.12 inside the runtime image and run the IBSI phantom tests. If this fails, evaluate an IBSI-validated alternative (e.g. MIRP) behind the same adapter and record the result in a superseding ADR.

**Consequences.** + Engine swappable without UI changes; + reproducibility through the profile hash. − Two sources of truth to keep aligned (engine and IBSI map), mitigated by tests.

**Rejected.** A hard-coded settings form (drifts from the engine). Showing IBSI codes in the GUI (user preference).
