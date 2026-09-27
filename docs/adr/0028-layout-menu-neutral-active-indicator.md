# ADR-0028 One "Layout" menu in the title bar; a neutral active indicator
Status: Proposed · Date: 2026-09-26
Supersedes: ADR-0023's scope clause "the title bar's menus/search/layout toggles … GitHub Dark's remaining tokens … unchanged", for the title-bar layout toggles and `--tab-active-indicator` only
Refines: ADR-0010

**Context.** After ADR-0023, two literal VS Code / GitHub signals remain (AUD-A3-23): the title bar ends in VS Code's own trio of `layout-sidebar-left` / `layout-panel` / `layout-sidebar-right` toggles, and the active activity-bar item, editor tab and panel tab carry GitHub's orange 2 px underline (`#F78166` dark, `#FD8C73` light). Neither is structural and neither carries meaning that the app needs: the orange is the only warm accent outside the status colours, so it reads as a warning next to `--warn` chips; the trio is three unlabelled icons whose pressed state was 1:1 against the title bar (AUD-A3-02). ADR-0023 kept both explicitly out of its scope; the owner asked for a new decision (2026-09-25). The theme names in Settings ("GitHub Dark" / "GitHub Light") become "Dark · Light · System" in the same batch; that is a string change, not part of this ADR (UI-11).

**Decision (proposal of AUD-A3-23, owner review pending).**
1. **One "Layout ▾" menu** replaces the three title-bar toggles: a `layout` codicon, the word "Layout" and a chevron (`.titlebar-menu`, the menus' own look). Its items are check items **Side bar · Panel · Inspector**, each with its unchanged shortcut (`Ctrl/Cmd+B`, `Ctrl/Cmd+J`, `Ctrl/Cmd+Alt+B`). The View menu and the palette keep their toggle commands. The viewer tool bar drops its duplicate inspector toggle (the menu and `Ctrl/Cmd+Alt+B` remain).
2. **Neutral active indicator:** `--tab-active-indicator` is `var(--fg)` in both themes (activity bar, editor tabs, panel tabs); an inactive group's active tab keeps `--border`. No new token, no new colour; the brand mark stays identity only (UI-21).
3. Nothing else changes: menus, search box, share menu, tab and activity-bar geometry, codicons and the Primer palette stay as ADR-0010 / ADR-0023 decided.

**Consequences.**
- \+ The title bar reads as the app's own (menus, search, share, one labelled Layout menu); the three toggles' state is spelled out as check marks.
- \+ The only warm accent left is the status colours; the indicator is ≥ 14.8:1 against every tab background, where the orange was 7.5:1 in Dark but only 2.2:1 in Light (under the 3:1 of WCAG 1.4.11).
- − One more click to toggle a region with the mouse (shortcuts unchanged); E2E steps that clicked "Toggle inspector" in the title bar now open the menu.
- − A user who knows VS Code loses the familiar trio (the View menu and the shortcuts are the same).

**Rejected.** Keeping the trio with a `--bg-pressed` state only (fixes the contrast, keeps the VS Code tell). The brand colour for the indicator (the logo is multi-colour; UI-21 keeps it identity only). Removing the indicator (the active tab would rely on the background alone, 1.0–1.1:1 in Light).

**Doc updates:** `frontend/UI_SHELL.md` (theme tokens, §Implementation notes FB6), `adr/README.md`, ADR-0023 status.
