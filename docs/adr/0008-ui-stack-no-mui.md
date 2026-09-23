# ADR-0008 Drop MUI; Radix + tokens + codicons + dockview
Status: Accepted · Date: 2026-09-23

**Context.** The target look is VS Code: dense, flat, 13 px, codicons, dockable tabs. MUI's Material design fights this and adds weight.

**Decision.** Headless Radix primitives styled by CSS variable tokens (UI_SHELL.md), `@vscode/codicons` for icons, dockview for editor tabs and splits, cmdk for the command palette.

**Consequences.** + A faithful VS Code look; + smaller bundle. − More in-house styling work; − v2 frontend components are not reused.

**Rejected.** MUI with a heavy theme override (still looks Material, larger). Embedding the VS Code workbench or Monaco shell (too heavy and coupled).
