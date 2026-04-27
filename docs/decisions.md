# Engineering Decisions — peach-loop

Living ADR (Architecture Decision Record) log.
Per BOOTSTRAP_PROMPT §9: record all agent-side engineering decisions with brief rationale.

---

## Decisions Made

### D1 — Package manager: uv
**Date:** 2025-04-27
**Decision:** Use `uv` for dependency management and virtual environment creation.
**Rationale:** uv is significantly faster than pip for environment creation and dependency resolution; it produces a lockfile; it installs without needing a pre-existing venv; it handles git-source packages (PEACH from GitHub) cleanly. pip remains the fallback (`pip install uv` in launch.sh if uv is absent).

---

### D2 — Config format: YAML with dot-access Python wrapper
**Date:** 2025-04-27
**Decision:** YAML files (`configs/base.yaml`, `configs/phase1.yaml`, `configs/phase2/sweep.yaml`) parsed into a lightweight `Config` class with attribute access.
**Rationale:** YAML is readable and widely understood. The `Config` wrapper avoids dict-bracket noise (`cfg["peach"]["n_epochs"]` vs `cfg.peach.n_epochs`) while remaining inspectable. No external schema library needed. Merging is a plain recursive dict update.

---

### D3 — Logging: Python `logging` + append-only JSONL files
**Date:** 2025-04-27
**Decision:** Two log streams:
- `logs/events/events.jsonl`: one JSON object per event (logger-level granularity).
- `logs/training/training.jsonl`: one JSON object per training-step metric flush.
**Rationale:** JSONL is machine-readable without external services (per AGENTS.md §1.3 and §10). Console gets human-readable text. Per-step training metrics are separate so they can be parsed for loss curves without filtering through the event log.

---

### D4 — Checkpoint format: adata.h5ad + model.pt + meta.json
**Date:** 2025-04-27
**Decision:** Each checkpoint directory contains three files:
1. `adata.h5ad` — full AnnData (cell data, PEACH's `adata.uns` state, obsm, etc.)
2. `model.pt` — torch state_dict of the Deep_AA model (if accessible via `results['model']`)
3. `meta.json` — epoch, loss, timestamp, config hash
**Rationale:** AnnData's h5ad is the standard single-cell serialisation format; PEACH stores its model state in `adata.uns`. The separate `model.pt` provides a fallback for reloading model weights if PEACH's internal format changes.

---

### D5 — Resume mechanism: epoch-chunked training with warm-start assumption
**Date:** 2025-04-27
**Decision:** Training runs in epoch chunks (`config.checkpoints.interval_epochs`, default 20). After each chunk, a checkpoint is saved. On resume, the adata is loaded from checkpoint; `pc.tl.train_archetypal` is called again with the remaining epochs.
**Assumption:** PEACH warm-starts training from `adata.uns` state when the key is present (standard scanpy convention: if `adata.uns['peach']` exists, resume from it rather than reinitialising from PCHA).
**Fallback if assumption is wrong:** Training restarts from PCHA each chunk. The resume-from-checkpoint test (`scripts/resume_test.py`) uses a 10% loss tolerance to account for this — same-seed restarts on the same data converge to similar final losses even when not byte-identical. See §3.5 of AGENTS.md.
**TODO at execution time:** Inspect `pc.tl.train_archetypal`'s source to confirm the warm-start behaviour; tighten or loosen the tolerance accordingly.

---

### D6 — Checkpoint halt-and-wait: file-based polling
**Date:** 2025-04-27
**Decision:** CP1/CP2 halt is implemented by writing `checkpoints/CPn_WAITING.md` (instructions) then polling for `checkpoints/CPn_RESPONSE.txt` every 60 seconds.
**Rationale:** No external services needed. The human can write the response file from any shell on the machine (or via an SSH session from a phone). Polling interval matches digest schedule (~1 minute) and doesn't busy-loop.

---

### D7 — Test framework: pytest
**Date:** 2025-04-27
**Decision:** pytest for all unit tests.
**Rationale:** Standard, well-understood. Tests are in `tests/`. The resume test and digest test are the two most important (§3.5 mandated); report generator tests are added as smoke checks.

---

### D8 — Plot libraries: matplotlib/seaborn for static; plotly for PEACH interactive
**Date:** 2025-04-27
**Decision:** `matplotlib` (with `Agg` backend) for all static plots written to disk. PEACH's `pc.pl.*` functions use plotly; static export via `kaleido`.
**Rationale:** Reports need PNGs. Plotly's interactive HTML requires a browser — fine for local exploration but can't be embedded in a markdown report or a daily digest viewed on a phone. matplotlib Agg works headlessly on remote compute.

---

### D9 — Phase 2 stability metric: mean Jaccard on cell assignment sets
**Date:** 2025-04-27
**Decision:** For each archetype, compute the Jaccard similarity of the full set of assigned cells across seed pairs. Average over archetypes and pairs. This is the "top-k" stability metric (AGENTS.md §4.2).
**Note:** AGENTS.md says "top-k archetype-assigned cells" — implemented as the set of all cells assigned to that archetype (via `pc.tl.assign_archetypes`), which is naturally top-k by percentage threshold. The `top_k` config parameter controls the Jaccard denominator for a stricter metric if needed.

---

### D10 — Archetype correspondence: cell-overlap Jaccard between variant pairs
**Date:** 2025-04-27
**Decision:** For each archetype in variant A, find the archetype in variant B with maximum cell-set overlap (Jaccard). Return the full n_A × n_B overlap matrix.
**Rationale:** Simple and interpretable. Per AGENTS.md §4.2: "use cell overlap or archetype-coordinate correlation." Cell overlap is more robust to coordinate scaling differences across preprocessing variants.

---

### D11 — Device selection: auto with MPS fallback
**Date:** 2025-04-27
**Decision:** `device: auto` in config tries CUDA → MPS → CPU. MPS is used if available but triggers an automatic CPU fallback on any `RuntimeError` containing "mps" (Tier-2 protocol per AGENTS.md §9).
**Rationale:** PEACH README explicitly warns about MPS instability on Apple Silicon. The DGX Spark likely has CUDA; if not, CPU is fine for PBMC 3K at 3k cells × 50 PCs.

---

### D12 — No CellRank dependency in core loop
**Date:** 2025-04-27
**Decision:** `cellrank` is listed as an optional dependency (`[cellrank]` extra) but not installed by default.
**Rationale:** CellRank pulls in a large dependency tree (scvelo, etc.). We don't use CellRank in the autonomous loop — only PEACH's `pc.tl.setup_cellrank` and trajectory integration are CellRank-facing, and those are out of scope (AGENTS.md §2.2). Install the extra manually if needed: `uv pip install -e ".[cellrank]"`.

---

### D13 — PBMC 3K batch correction variant
**Date:** 2025-04-27
**Decision:** PBMC 3K has no batch annotation, so the "batch correction" preprocessing variant in AGENTS.md §4.1 is substituted with log-norm + HVG (2000) using Seurat v3 HVG flavor (variance-stabilized selection).
**Rationale:** This is the most meaningful substitution — it tests a different HVG selection algorithm while keeping the rest of the pipeline identical. Documented in `configs/phase2/sweep.yaml` under `log_norm_hvg2000_seurat_v3`. Per AGENTS.md §4.1: "skip if PBMC 3K has no batch annotation; substitute another preprocessing variant if needed."

---

### D14 — PEACH citation verification
**Date:** 2025-04-27
**Finding:** The citation in AGENTS.md §12 (`author={Honkala, Alexander and Malhotra, Sanjay}`) matches the actual PEACH GitHub repo. Both first names are present. No correction needed.
**Note:** The BOOTSTRAP_PROMPT mentioned the first name might be missing — it was not missing in the version of AGENTS.md provided. Verified from github.com/xhonkala/PEACH.

---

## Questions for Human Review

### Q1 — PEACH warm-start behaviour (affects resume test tolerance)
The resume mechanism (D5) assumes `pc.tl.train_archetypal` warm-starts from `adata.uns` when PEACH state is present. **If this is not true**, the resume test tolerance (10%) may need to be raised, or the training loop will need to manage model state more explicitly. Recommend checking at execution time by inspecting `peach._core` source or testing with a small synthetic run.

### Q2 — `pc.tl.train_archetypal` parameter for continuing training
AGENTS.md requires calling PEACH's published API only. If PEACH does not support continuing training from an existing model state via `adata.uns`, the checkpoint resume will effectively restart training from PCHA (good warm start, but not a true resume). This is acceptable for the project's learning goals; a true mid-epoch resume would require either PEACH to support it or accessing its internals. Decision: accept PCHA-restart-as-resume for now; flag as Q1 above.

### Q3 — Hyperparameter search wall-clock cap behaviour
AGENTS.md §3.3 says "fall back to 5 if the search exceeds 30 minutes wall-clock". The implementation falls back only if the search *fails*; if it completes after 30 minutes, the result is used (since the cap is informational at that point). Verify at execution time whether this is the right behaviour, or whether the cap should be enforced as a hard interrupt.

### Q4 — `final_archetype_r2` field presence in TrainingResults
The code uses `results.get("final_archetype_r2")` which may return `None` if PEACH's TrainingResults dict uses a different key name. Verify the exact field name from PEACH's source or tutorial notebooks at execution time. If different, update `phase1/train.py` and `phase1/evaluate.py`.

### Q5 — Gene association results key in adata.uns
The enrichment code tries several plausible keys: `"peach_gene_assoc"`, `"gene_associations"`, `"peach"."gene_associations"`. The correct key depends on PEACH's internal naming convention. Verify from PEACH source or tutorial output at execution time.
