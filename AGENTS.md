# AGENTS.md

Specification for an autonomous agent running this project on a remote compute machine. Written to be agent-agnostic — works for Claude Code in agent mode, Hermes Agent, or anything else with comparable capabilities at execution time.

This document specifies *what* must happen and the rules under which it must happen. It does not specify how to organize code, which packages to use, or what file formats to choose — those are agent-side decisions.

For project context — what is being trained, why, and what the human is trying to learn — see README.md. This document is the execution contract.

---

## 1. Operating principles

1. **Budgets terminate, not convergence.** Every loop has a hard wall-clock or step cap. When the cap is hit, the loop stops and the next phase begins regardless of metric values. Do not "let it run a bit longer."
2. **Resume over restart.** Crashes default to resume-from-last-checkpoint. Three consecutive resume failures escalate.
3. **Disk is the source of truth.** Logs, metrics, plots, checkpoints all written to local disk in formats re-readable without external services. External logging services (W&B etc.) are allowed but never the only copy.
4. **Idempotent setup.** Every script can be re-run from any state without corruption.
5. **Three checkpoints, no others.** If unsure whether to ping the human, don't. Log the question to a "decisions pending" log and continue with the documented default. Accumulated questions are reviewed at the next scheduled checkpoint.

---

## 2. The substrate (frozen)

### 2.1 What is being trained

PEACH's archetypal autoencoder (`Deep_AA`) — github.com/xhonkala/PEACH. PEACH (Python Encoders for Archetypal Convex Hulls, Honkala & Malhotra 2025) is a PyTorch implementation of Deep Archetypal Analysis: an autoencoder whose latent space is constrained to be a simplex with archetype vertices. Cells are represented as convex combinations of these vertices.

Use the published model architecture as-is. Do not modify the model code.

The training task is archetype discovery on single-cell RNA-seq data. Input: cell × gene expression matrix (after PCA, per PEACH convention). Output: archetype coordinates per cell, archetype assignments, reconstructed expression, and per-archetype gene/pathway enrichment.

The agent should call PEACH's published API (`pc.tl.train_archetypal`, `pc.tl.archetypal_coordinates`, `pc.tl.assign_archetypes`, `pc.tl.gene_associations`, etc.) rather than reimplementing.

### 2.2 What is *not* in scope

- Modifying PEACH's architecture or core code
- Training a different model
- Wet-lab anything
- Multi-node distributed training

If during execution something suggests one of these is the right next step, write to the decisions-pending log and continue with the current spec.

---

## 3. Phase 1 — Baseline run

### 3.1 Required outputs

- A trained PEACH model checkpoint (use PEACH's TrainingResults serialization)
- An evaluation report on the held-out portion of the dataset
- Archetype-to-cell assignments persisted as AnnData (`adata.obs` columns + `adata.obsm['X_archetypal']`)
- Per-archetype gene set enrichment (use PEACH's `pc.tl.gene_associations` and `pc.tl.pathway_associations`)
- 3D archetypal-space visualization (PEACH's `pc.pl.archetypal_space`)
- A daily digest written each day the run is active
- One generated report (markdown) summarizing what happened

### 3.2 Dataset

PBMC 3K (peripheral blood mononuclear cells, ~3000 cells, ~13K genes). Available via `scanpy.datasets.pbmc3k()` or 10x Genomics' public download. Hash-verify after download. Document the source URL and download timestamp in the report.

### 3.3 Configuration

Use PEACH's default hyperparameters:
- `n_archetypes`: use PEACH's `hyperparameter_search` with `cv_folds=3` to determine, or fall back to 5 if the search exceeds 30 minutes wall-clock
- Training epochs, learning rate, loss weights: PEACH defaults
- Device: CPU is fine on Spark for this scale; if MPS/CUDA is reliable in the environment, use it, but don't fight unstable backends — PEACH's README explicitly notes Apple Silicon MPS instability

For preprocessing, use the standard scanpy PBMC tutorial pipeline: filter cells/genes, normalize total to 1e4, log-transform, identify highly variable genes (top 2000), scale, PCA to 50 components. This is the reference everyone uses; deviations should be flagged in the report.

### 3.4 Hard caps

- Wall-clock cap: 4 hours from training start to report generated
- If the cap is hit before completion, this is a Tier-1 condition (the run is too slow and something is wrong)

### 3.5 Acceptance criteria

- Reconstruction loss decreased monotonically (with usual small-step noise) from start to end
- Final archetype R² (`final_archetype_r2` from TrainingResults) > 0.7
- Each top archetype has at least 3 statistically significant gene-set associations (FDR < 0.05) — if not, flag in report; this is a soft criterion
- Resume-from-checkpoint test passes: force-kill at midpoint, resume, verify final loss matches non-interrupted reference within tolerance
- Daily digest was generated and contains the required fields (§6)
- Archetypes pass a sanity check: for PBMC, at least one archetype's top genes should match a known immune cell type (T cell markers like CD3D/CD3E, B cell markers like CD79A, monocyte markers like CD14/LYZ, NK markers like NKG7/GNLY). Soft criterion — flag if violated, don't fail.

If hard criteria fail, this is Checkpoint 1's go/no-go decision.

---

## 4. Phase 2 — Sweep

### 4.1 Sweep dimension

Default: vary preprocessing pipeline, holding all other hyperparameters at Phase 1 values. The variants:

- Raw counts (no normalization, no log)
- Log-normalized only (no HVG selection, no scaling)
- Log-normalized + HVG selection at 1000 genes
- Log-normalized + HVG selection at 2000 genes (Phase 1 reference, included for direct comparison)
- Log-normalized + HVG selection at 4000 genes
- Log-normalized + HVG (2000) + scaling — the Phase 1 reference with explicit scaling
- Log-normalized + HVG (2000) + scaling + batch correction (skip if PBMC 3K has no batch annotation; substitute another preprocessing variant if needed)

Total: 6-7 runs.

The human may override the sweep dimension at Checkpoint 1; default to preprocessing if no override given.

### 4.2 Required outputs

- All sweep runs completed (or failed gracefully with documentation)
- A comparison report containing, at minimum:
  - Per-variant final reconstruction loss and archetype R²
  - Per-variant loss trajectories overlaid on a single plot
  - Per-variant archetype stability metric: Jaccard similarity of top-k archetype-assigned cells across 3 random seeds per variant
  - Per-variant top gene-set enrichment for the top 3 archetypes (table)
  - Pairwise archetype-correspondence matrix across variants: which archetypes in variant A map to which in variant B (use cell overlap or archetype-coordinate correlation)
  - Plots: loss curves overlaid, stability heatmap, correspondence heatmap

### 4.3 Hard caps

- Wall-clock cap: 48 hours from Phase 2 start to comparison report
- Per-variant cap: 2 hours
- Per-seed-within-variant cap: 45 minutes

### 4.4 Acceptance criteria

- All variants attempted (failures documented, not silently skipped)
- Comparison report exists and is readable
- Daily digest continued through Phase 2

---

## 5. Phase 3 — Refactor or writeup

This phase requires human direction at Checkpoint 2. The agent does not auto-launch Phase 3.

When given direction (one of: `refactor`, `writeup`, `both`, `done`), execute accordingly:

- `refactor`: human will provide a list of pain points to address. Agent updates the relevant code, re-runs a single Phase-1-style baseline to verify nothing broke, produces a delta report.
- `writeup`: agent produces a markdown technical note based on Phase 2 results, in the style of a short methodological paper. ~2000 words, with figures pulled from the Phase 2 comparison report. Title default: "Sensitivity of PEACH archetypes to preprocessing choices" (or whatever fits the actual sweep dimension).
- `both`: refactor first, then writeup using the refactored loop's output.
- `done`: agent generates a final summary digest and stops.

### 5.1 Hard caps

- Wall-clock cap: 24 hours per sub-action

---

## 6. Daily digest

Every day at 08:00 in the human's local timezone, write a digest containing:

- Phase status
- % of phase budget consumed
- Wall-clock since launch
- ETA to next checkpoint
- Last 24h: runs completed, throughput stats, current loss values, eval results if any
- Tier-2 events handled (auto-recovered failures)
- Tier-1 events (should be empty)
- Decisions pending human review (non-blocking, accumulated)
- One-sentence forecast for the next 24h
- Path to one plot (recent loss curve or sweep progress)

Format and filename are agent's choice. Place in a directory the human can navigate from a phone.

---

## 7. Checkpoints (the only times the human is contacted)

### CP1 — Phase 1 complete

Trigger: Phase 1 finishes (success or cap hit).

Auto-prepare a CP1 report containing: §3.5 acceptance criteria with actual values, the generated Phase 1 report, the Phase 1 daily digests, list of Tier-2 events, and 3D archetypal-space plot rendered as static image (since interactive plotly may not survive the digest channel).

**Halt before Phase 2 launches.** Wait for one of: `proceed-default-sweep | proceed-with-override | abort`.

If `proceed-with-override`, the human will specify which sweep dimension (n_archetypes, latent_dim, dataset). Apply override and proceed.

### CP2 — Phase 2 complete

Trigger: Phase 2 finishes (success or cap hit).

Auto-prepare a CP2 report containing: §4.4 acceptance criteria with actual values, the comparison report, the Phase 2 digests, observations about what the sweep revealed (especially the archetype-correspondence matrix — does archetype identity survive preprocessing changes?).

**Halt before Phase 3 launches.** Wait for one of: `refactor | writeup | both | done`.

### CP3 — Phase 3 complete

Trigger: Phase 3 finishes.

Notify human; no halt needed (project is done).

---

## 8. Tier-1 conditions (page human immediately, halt offending phase)

Exact list — do not extend without human direction.

- 3 consecutive checkpoint resumes fail
- Loss diverges (NaN/inf, or grows >2× over rolling baseline) for two consecutive checkpoint intervals
- Disk usage > 90% on any mount
- Hardware fault detected (XID errors on GPU, ECC errors)
- Data corruption detected by hash check
- Phase wall-clock cap hit while phase status is `incomplete`
- Any error in checkpoint-saving code path
- Setup-time smoke test fails: PEACH imports cleanly, `Deep_AA` instantiates, single training step on synthetic data succeeds, PEACH's tutorial PBMC example runs end-to-end
- PCHA initialization fails or returns archetypes with all-equal coordinates (indicates the warm start collapsed)

Before paging: stage a Tier-1 log with full context (timestamp, condition, traceback, last 100 log lines), halt the offending phase, keep daemons running. Do not improvise recovery beyond the Tier-2 protocols.

---

## 9. Tier-2 protocols (handle silently, log to digest)

- **Single process crash:** auto-resume from last checkpoint. Increment a consecutive-resume-failures counter. If post-resume metrics match pre-crash within tolerance, reset counter and continue.
- **Transient OOM:** halve batch size, double gradient accumulation if applicable, resume. Log the new config. Restore original after a stable period.
- **Dataloader stall (under 10 min):** kill workers, reinitialize. Sustained over 10 min: Tier-1.
- **Single-checkpoint loss spike that recovers within 200 steps:** log only.
- **Network timeout on data download:** exponential backoff. Three failures: Tier-1.
- **Disk warning 80–90%:** delete oldest non-protected checkpoints (keep last 5 + the best). Logs are protected. Still over 85% after cleanup: Tier-1.
- **External logging service failure:** disable, continue with local logs. Note in digest.
- **MPS instability (Apple Silicon only):** fall back to CPU per PEACH's README guidance. Log only.

---

## 10. Logging requirements

Agent chooses formats. Requirements:

- Per-step training metrics (loss components — reconstruction, archetypal, diversity, regularity, sparsity, manifold — captured separately, not just total) at minimum every 10 steps. Re-readable without external services.
- Eval metrics with timestamps and step counts.
- Event log for phase transitions, checkpoint saves, resumes, Tier-2 recoveries.
- Decisions-pending log for non-blocking questions.
- Tier-2 events log included in daily digest.
- Tier-1 staging log written before any Tier-1 page.

Logs are protected. Never deleted as part of disk cleanup.

---

## 11. Latitude — agent's call

Document choices once made; no permission needed:

- Repository structure beyond the README/AGENTS/BOOTSTRAP root files
- All Python package choices and versions (pin once working)
- Config file format (YAML, TOML, Python dataclass — agent's choice)
- Logging library
- Data shard format
- Checkpoint format and directory layout (must integrate with PEACH's TrainingResults)
- Plot library beyond what PEACH ships (PEACH uses plotly; agent may add matplotlib/seaborn for static plots in reports)
- Test framework
- Specific URLs/paths for PEACH installation, dataset downloads, gene-set databases — find current ones at execution time
- Resume implementation details
- Throughput optimization techniques as long as they don't change PEACH's behavior or eval protocol
- Container vs. virtual environment vs. system Python

Not the agent's call: model architecture (PEACH default), Phase 1 dataset (PBMC 3K), default sweep dimension (preprocessing), budgets, acceptance criteria, Tier-1 list, checkpoint protocols, daily digest schedule.

---

## 12. Citations

```bibtex
@article{honkala2025peach,
  title={Python Encoders for Archetypal Convex Hulls (PEACH): PyTorch-Based Archetypal Analysis},
  author={Honkala, Alexander and Malhotra, Sanjay},
  journal={bioRxiv},
  year={2025},
  note={Software: github.com/xhonkala/PEACH}
}

@article{morup2012archetypal,
  title={Archetypal analysis for machine learning and data mining},
  author={M{\o}rup, Morten and Hansen, Lars Kai},
  journal={Neurocomputing},
  volume={80},
  pages={54--63},
  year={2012}
}

@article{cutler1994archetypal,
  title={Archetypal analysis},
  author={Cutler, Adele and Breiman, Leo},
  journal={Technometrics},
  volume={36},
  number={4},
  pages={338--347},
  year={1994}
}

@article{shoval2012evolutionary,
  title={Evolutionary trade-offs, {P}areto optimality, and the geometry of phenotype space},
  author={Shoval, Oren and Sheftel, Hila and Shinar, Guy and Hart, Yuval and Ramote, Omer and Mayo, Avi and Dekel, Erez and Kavanagh, Kathryn and Alon, Uri},
  journal={Science},
  volume={336},
  number={6085},
  pages={1157--1160},
  year={2012},
  doi={10.1126/science.1217405}
}

@article{hart2015parti,
  title={Inferring biological tasks using {P}areto analysis of high-dimensional data},
  author={Hart, Yuval and Sheftel, Hila and Hausser, Jean and Szekely, Pablo and Ben-Moshe, Noa Bossel and Korem, Yael and Tendler, Avichai and Mayo, Avraham E and Alon, Uri},
  journal={Nature Methods},
  volume={12},
  number={3},
  pages={233--235},
  year={2015}
}

@article{wolf2018scanpy,
  title={SCANPY: large-scale single-cell gene expression data analysis},
  author={Wolf, F Alexander and Angerer, Philipp and Theis, Fabian J},
  journal={Genome Biology},
  volume={19},
  pages={1--5},
  year={2018}
}
```

The agent should verify these at execution time and update with any newer versions or DOIs that appear.

---

## 13. Final note

If anything in this document seems wrong or ambiguous, write to the decisions-pending log and continue with documented behavior. Do not improvise on the science or the protocol. Improvise on the engineering — that's the whole point of this division.

The project's value is in the loop being built, debugged, and understood. Getting a particular result on PEACH is secondary.
