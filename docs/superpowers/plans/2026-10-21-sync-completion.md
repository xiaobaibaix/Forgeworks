# Forgeworks Sync Completion Implementation Plan

> **For agentic workers:** execute this plan task-by-task with tests before implementation. Do not commit; the user explicitly forbids commits without the word “提交”.

**Goal:** Complete UE import, reverse asset discovery, per-part 3D/material editing, and filesystem conflict handling for the Forgeworks sync system.

**Architecture:** UE Editor Python scripts import GLB assets through Interchange, persist them, and write a machine-readable registry snapshot. The Bridge exposes those snapshots and serializes filesystem changes/conflict decisions. The browser editor layers persistent per-part transforms and material overrides over the existing procedural machine geometry and exports them through the existing GLB path.

**Tech Stack:** Existing static JavaScript app, Three.js r147, Python stdlib Bridge, Unreal Engine 5.8 Editor Python API.

**Spec:** `docs/sync-design.md` §§3–7 and `docs/ue-import.md`.

## Global Constraints

- Keep the static app dependency-free and preserve existing machine preview output when no overrides exist.
- UE scripts run inside the UE Editor Python environment and target UE 5.8.3 Interchange APIs.
- GLB dimensions are meters with Y-up; UE import scale is 100 and UE bounds use centimeters with Z-up.
- Store overrides in `S.machines[i].ui3d`; preserve the procedural machine definition as the default source.
- Keep Bridge metadata and user text escaped before insertion into HTML.
- Do not add code comments unless a one-line WHY comment is needed.
- Never commit or push.

## Review Focus

- UE API drift or missing Editor Python/Interchange plugins must fail with actionable diagnostics.
- Empty, malformed, stale, or path-traversal UE registry/conflict inputs must not corrupt project state.
- Transform edits must preserve the unchanged procedural render and export dimensions.
- Material input must clamp finite PBR values and reject unsafe upload paths/types.
- Filesystem events must debounce bursts, distinguish Bridge writes from external edits, and retain both conflict versions.

---

### Task 1: UE import and report loop (P2)

**Files:** Create `ue/fw_sync.py`; modify `tools/bridge.py`, `js/sync.js`, `js/views/sync.js`, `docs/ue-import.md`; add Python/JS behavior checks.

- [ ] Implement an Editor-executable script that imports selected manifest GLBs into `/Game/Forgeworks/Machines/<ID>`, sets Interchange scale 100, waits for completion, saves the destination, measures bounds/materials, and POSTs UE asset paths/status to Bridge.
- [ ] Add Bridge `/api/ue/report` validation and manifest updates; reject unknown IDs and malformed paths.
- [ ] Add UI actions and per-machine UE import status.
- [ ] Validate parser/Bridge behavior locally; document the exact in-editor UE 5.8.3 acceptance steps and mark platform-only checks explicitly.

### Task 2: UE registry reverse discovery (P3)

**Files:** Create `ue/fw_registry.py`; modify `tools/bridge.py`, `js/sync.js`, `js/views/sync.js`; add behavior checks.

- [ ] Scan AssetRegistry for Forgeworks StaticMesh assets; record object path, class, bounds in cm, triangle count, material slots, and dependencies to `_Sync/ue_assets.json`.
- [ ] Add safe Bridge read/accept endpoints and show UE-present/external assets and design-size differences in the machine/sync views.
- [ ] Verify malformed/stale snapshots and assets not in the manifest do not break rendering.

### Task 3: Per-part scene model and transforms (P4)

**Files:** Modify `js/engines/viewer3d.js`, `js/core/state.js`, `js/sync.js`, `js/views/machines.js`; create `js/views/editor3d.js`; modify `index.html`, `tests/smoke.html`; add browser checks.

- [ ] Create stable per-part IDs and semantic role groups without changing default geometry positions.
- [ ] Persist transform/hidden overrides on each machine and apply them to preview/GLB generation.
- [ ] Add editor selection, hierarchy, translate/rotate/scale gizmo, local/world mode, snapping, numeric editing, focus, visibility, undo/redo (50 steps), and reset.
- [ ] Verify unchanged geometry bounds and all 32 machine previews; verify selecting/editing/exporting a part round-trips its override.

### Task 4: Material overrides (P5)

**Files:** Extend `js/views/editor3d.js`, `js/engines/viewer3d.js`, `js/sync.js`; add browser checks.

- [ ] Persist per-machine/per-part material overrides for base color, metallic, roughness, emissive, and alpha.
- [ ] Apply overrides live and during GLB export; show whether a value follows the style or overrides it.
- [ ] Provide texture upload slots with type/size validation and a restore-style action.
- [ ] Verify GLB material factors and alpha mode after export.

### Task 5: Filesystem watch, conflicts, and Blender round-trip (P6)

**Files:** Modify `tools/bridge.py`, `js/sync.js`, `js/views/sync.js`; create Bridge tests and a Blender round-trip script if needed.

- [ ] Add a debounced stdlib watcher that detects external create/delete/modify operations and emits SSE changes.
- [ ] Compare disk hashes to manifest, archive both sides under `_Sync/conflicts/`, and expose explicit keep-tool/keep-disk/save-copy decisions.
- [ ] Protect `.blend`/`.edited.glb` refinements from silent overwrite; support opening a Blender work file and reimporting an edited GLB.
- [ ] Verify external deletion/modify, conflict archival, each decision, watcher recovery, and event latency below three seconds.

