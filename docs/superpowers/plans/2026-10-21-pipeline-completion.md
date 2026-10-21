# Forgeworks Asset Pipeline Completion Implementation Plan

> **For agentic workers:** execute this plan task-by-task with tests before implementation. Do not commit; the user explicitly forbids commits without the word “提交”.

**Goal:** Complete a usable asset-generation DAG with secure Bridge-side providers, persistent node results, incremental execution, an editable node canvas, validation/style application, variants, and templates.

**Architecture:** Persist per-asset graph definitions and file-backed node outputs under `_Source/pipeline/<assetId>/`. The browser owns graph editing and previews; Bridge owns secrets, provider calls, execution state, remote polling, and output files. Local fallback and fake providers keep the pipeline testable without credentials; remote generation remains disabled until a key exists.

**Tech Stack:** Existing static JavaScript app and Three.js r147; Python stdlib Bridge; Tripo official REST API adapter.

**Spec:** `docs/pipeline-design.md` §§2–9 and sync handoff constraints.

## Global Constraints

- Keep provider credentials in ignored Bridge configuration only; never expose keys to browser responses or logs.
- Remote tasks require an explicit cost preview and user-triggered run; changing graph inputs only marks downstream nodes dirty.
- Persist files, hashes, seeds, provider/model, estimated and actual costs, task IDs, and errors for restart-safe resume.
- Keep local fallback available with no network credentials and never make an external paid request in tests.
- Use the existing machine/style prompt builders and sync export path.
- Never commit or push.

## Review Focus

- Provider responses may be malformed, oversized, delayed, or return remote URLs; enforce size/time/type limits.
- DAG cycles, missing ports, stale outputs, and graph edits during a run must be rejected or safely invalidated.
- Secrets must not appear in API responses, SSE, HTML, logs, or generated graph files.
- Remote polling/retries must stop on cancellation and avoid duplicate paid tasks.
- Generated GLB and images must pass format/size validation before being promoted to final pipeline outputs.

---

### Task 1: Provider/config foundation (Q0)

**Files:** Create `tools/fw_providers.py`; modify `tools/bridge.py`, `tools/bridge_config.example.json`, `.gitignore`; add tests.

- [ ] Add provider registry, configuration/key-status endpoint, fake/local providers, and a Tripo adapter based on current official docs.
- [ ] Add safe credential write/status endpoints; redact secrets from all diagnostics.
- [ ] Implement Tripo multiview image and image-to-3D task creation/status/download with bounded retries and file limits.
- [ ] Verify adapter requests against a local fake HTTP server; do not contact paid services.

### Task 2: Graph model, storage, and incremental executor (Q1)

**Files:** Create `js/pipeline.js`, `tools/fw_pipeline.py`; modify `tools/bridge.py`; add Python/JS checks.

- [ ] Define graph schema and typed ports; validate unique node IDs, valid edges, and acyclic topology.
- [ ] Persist graph and file-backed node outputs under `_Source/pipeline/<assetId>/`.
- [ ] Compute per-node input/parameter hashes; propagate dirty state downstream without auto-running.
- [ ] Execute local nodes and Bridge provider jobs, support run-node/run-through/run-all, resume, retry, cancellation, and SSE progress.

### Task 3: Pipeline templates and graph canvas (Q2, Q5)

**Files:** Create `js/views/pipeline.js`, `js/pipeline-templates.js`; modify navigation/HTML and smoke checks.

- [ ] Add SVG canvas node cards, typed ports/edges, drag/drop, connect/disconnect, selection, parameter forms, and stable auto-layout.
- [ ] Add machine/item/icon starter templates and batch cost estimation.
- [ ] Render per-node state/output preview and expose run-node/run-through/run-all controls.
- [ ] Verify graph editing persistence, cycle rejection, template import, and dirty propagation in browser tests.

### Task 4: Style, decimate, validate, manual edit, export, and variants (Q3–Q4)

**Files:** Extend `tools/fw_pipeline.py`, `tools/fw_blender.py`, `js/pipeline.js`, `js/views/pipeline.js`; add tests.

- [ ] Implement prompt, image, model, decimate, styleApply, validate, manualEdit, export, and variant nodes.
- [ ] Prefer provider face limits, then Blender decimate; report when no safe method is available.
- [ ] Recolor PBR material factors using current style roles, preserve alpha/textures, and emit alignment reports.
- [ ] Enforce mesh/material/bounds/grounding gates and export the selected final GLB through the sync manifest path.
- [ ] Keep seed/provider variants and outputs addressable for comparison and rollback.

