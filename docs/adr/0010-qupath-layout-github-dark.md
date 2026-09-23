# ADR-0010 QuPath-style layout in a VS Code shell with the GitHub Dark theme
Status: Accepted · Date: 2026-09-23 · Refines: ADR-0008

**Context.** Users want a brand-new UI/UX: the project-first workflow of QuPath, the shell ergonomics of VS Code, the GitHub Dark look, and a CT 2×2 viewer that QuPath lacks.

**Decision.**
- Layout: QuPath-style left pane (Project with thumbnails, Image, Curation, Labels, History), a tool bar above the viewer, and a Measurements panel. These are hosted in VS Code regions: activity bar, editor tabs and splits, bottom panel, status bar, command palette.
- The center is the 3D Slicer-style 2×2 viewer (VIEWER.md).
- The theme is GitHub Dark (Primer colors); icons are codicons plus a custom CT icon set drawn to codicon rules.
- A UX design phase (P0.5) produces tokens, icons and a clickable prototype before shell code (P2).

**Consequences.** + Familiar to QuPath and VS Code users; + a coherent single visual system. − Axial thumbnails need a backend job (IMP-12) that decodes volumes in workers. − Custom icons are a design deliverable (UI-15).

**Rejected.** A pure VS Code layout (loses QuPath's image-list-with-thumbnails workflow). A pure QuPath clone with floating dialogs, such as its Brightness/Contrast window (feels dated and conflicts with docking). VS Code Dark Modern colors (the user prefers GitHub Dark).
