# ADR-0003 Client-side rendering with NiiVue
Status: Accepted · Date: 2026-09-23

**Context.** v2 rendered PNG slices server-side, which costs one round trip per slice and hurts smooth scrolling. The target UX is 3D Slicer-like MPR with overlays and 3D.

**Decision.** The browser downloads the original NIfTI (and mask) once and renders with NiiVue (WebGL2): MPR, label overlays, volume rendering, meshes. NiiVue is wrapped behind `ViewerHandle` (VIEWER.md) so the engine can be swapped.

**Consequences.** + 60 fps scrolling and W/L; + a stateless backend for viewing; + works in Electron as-is. − Browser memory grows with volume size (VW-14 budget); − requires WebGL2; − `.npy` needs conversion server-side (IMP-10).

**Rejected.** Server PNG (latency). Cornerstone3D (DICOM-centric, heavier to integrate for NIfTI-only). vtk.js directly (more code for MPR tooling that NiiVue already provides).
