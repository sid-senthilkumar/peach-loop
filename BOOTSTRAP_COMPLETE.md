# BOOTSTRAP_COMPLETE.md

Scaffold built by Claude Code. Date: 2025-04-27.

---

## What Was Built

A complete autonomous training scaffold for the peach-loop project, implementing
all three phases and the operational layer specified in AGENTS.md.

### Repository layout

```
peach-loop/
├── src/peach_loop/
│   ├── config.py               # YAML loader with dot-access wrapper
│   ├── ops/
│   │   ├── logger.py           # structured JSON logging (events + training metrics)
│   │   ├── state.py            # RunState dataclass, atomic JSON persistence
│   │   ├── checkpoint.py       # save/load/verify checkpoints (adata.h5ad + model.pt)
│   │   ├── digest.py           # daily digest generator (AGENTS.md §6)
│   │   ├── tier1.py            # Tier-1 condition checks and escalation
│   │   └── tier2.py            # Tier-2 auto-recovery protocols
│   ├── phase1/
│   │   ├── dataset.py          # PBMC 3K download, SHA-256 verification, preprocessing
│   │   ├── train.py            # PEACH training loop with epoch-chunked checkpointing
│   │   ├── evaluate.py         # held-out evaluation, immune marker sanity check
│   │   ├── enrichment.py       # gene/pathway enrichment via PEACH API
│   │   ├── report.py           # Phase 1 markdown report + loss curves + 3D plot
│   │   └── run.py              # Phase 1 orchestration
│   ├── phase2/
│   │   ├── variants.py         # preprocessing variant applicator
│   │   ├── sweep.py            # per-(variant, seed) runner, stability + correspondence
│   │   ├── compare.py          # comparison report + 3 required plots
│   │   └── run.py              # Phase 2 orchestration
│   └── phase3/
│       ├── actions.py          # refactor / writeup / done sub-actions
│       └── run.py              # Phase 3 dispatch based on CP2 response
├── scripts/
│   ├── run_all.py              # main autonomous loop with CP1/CP2 halt-and-wait
│   ├── smoke_test.py           # setup-time smoke test (Tier-1 if fails)
│   └── resume_test.py          # §3.5 resume-from-checkpoint test
├── configs/
│   ├── base.yaml               # shared config (paths, logging, tier thresholds)
│   ├── phase1.yaml             # Phase 1 config (dataset, preprocessing, PEACH params)
│   └── phase2/sweep.yaml       # Phase 2 config (7 preprocessing variants, seeds, caps)
├── tests/
│   ├── test_resume.py          # pytest wrapper for resume test
│   ├── test_digest.py          # digest generator smoke tests
│   └── test_reports.py         # Phase 1 + Phase 2 report generator tests
├── docs/decisions.md           # ADR log with 14 decisions + 5 questions for review
├── launch.sh                   # single launch script for the remote machine
├── Makefile                    # common one-line operations
└── pyproject.toml              # uv-compatible package spec with all dependencies
```

---

## Engineering Decisions

Full log in `docs/decisions.md`. Summary:

| # | Decision | Choice |
|---|----------|--------|
| D1 | Package manager | uv |
| D2 | Config format | YAML + dot-access Python wrapper |
| D3 | Logging | Python logging + append-only JSONL |
| D4 | Checkpoint format | adata.h5ad + model.pt + meta.json |
| D5 | Resume mechanism | Epoch-chunked training with warm-start assumption |
| D6 | CP halt-and-wait | File-based polling (CPn_WAITING.md / CPn_RESPONSE.txt) |
| D7 | Test framework | pytest |
| D8 | Plot libraries | matplotlib (static) + plotly via kaleido |
| D9 | Stability metric | Mean Jaccard on archetype cell-assignment sets |
| D10 | Correspondence metric | Cell-overlap Jaccard across variant pairs |
| D11 | Device selection | auto: CUDA → MPS → CPU, with MPS fallback on instability |
| D12 | CellRank | Optional extra, not installed by default |
| D13 | Batch-correction variant | Substituted with Seurat v3 HVG flavor (PBMC 3K has no batch) |
| D14 | PEACH citation | Verified: Honkala, Alexander & Malhotra, Sanjay — already correct |

---

## Questions That Need Human Review Before Launch

See `docs/decisions.md` for full context. In priority order:

**Q1 (important):** Does `pc.tl.train_archetypal` warm-start from `adata.uns` when
called again on the same AnnData? The resume mechanism depends on this. If not, the
resume test tolerance (currently 10%) may need adjustment.

**Q4 (important):** Verify the exact key name for `final_archetype_r2` in PEACH's
TrainingResults dict. The scaffold uses `results.get("final_archetype_r2")` — if
PEACH uses a different key, this will silently return `None` and the R² criterion
will always show as N/A.

**Q5 (important):** Verify the key PEACH uses to store gene association results in
`adata.uns`. The scaffold tries `"peach_gene_assoc"`, `"gene_associations"`, and
`"peach"."gene_associations"`. Wrong key = silent enrichment failure.

**Q2/Q3 (minor):** See decisions.md for details on wall-clock cap behaviour and
PEACH's API for continuing training.

---

## Exact Launch Command

On the remote machine, after cloning the repo:

```bash
cd peach-loop
chmod +x launch.sh
./launch.sh
```

To resume after a crash or interrupt:

```bash
./launch.sh --resume
```

Other useful commands:

```bash
make smoke-test      # verify environment before launching
make test-resume     # run the §3.5 resume test
make test            # run full test suite
make status          # print current run state
make digest          # generate a digest manually
```

---

## Timing Estimates

| Operation | Estimated time (DGX Spark, CPU) |
|-----------|--------------------------------|
| `make install` (fresh) | 3–8 min (PEACH from git + torch) |
| Smoke test | ~30–60 s (2 synthetic training steps) |
| PBMC 3K download | ~30 s (via scanpy cache) |
| Preprocessing | ~10–30 s |
| Hyperparameter search (6 values × 3 folds × 15 epochs) | ~10–25 min |
| Phase 1 training (150 epochs, ~3k cells × 50 PCs) | ~20–60 min |
| Phase 1 enrichment | ~5–15 min |
| Phase 1 total | **~1–2 hours** (well within 4h cap) |
| Phase 2 (7 variants × 3 seeds × 150 epochs) | **~10–30 hours** (well within 48h cap) |

The 4h Phase 1 cap and 48h Phase 2 cap are unlikely to be hit on DGX Spark.
If running on a CPU-only laptop, Phase 1 may approach the cap — consider reducing
`n_epochs` in `configs/phase1.yaml` for a test run.

---

## Checkpoint Protocol Summary

```
launch.sh
  └── scripts/run_all.py
        ├── Phase 1 (run_phase1)
        │     └── saves checkpoints every 20 epochs
        │         writes daily digest at 08:00 local
        ├── CP1: writes checkpoints/CP1_WAITING.md
        │         polls for checkpoints/CP1_RESPONSE.txt every 60s
        │         valid responses: proceed-default-sweep | proceed-with-override | abort
        ├── Phase 2 (run_phase2)
        │     └── 7 variants × 3 seeds, comparison report
        ├── CP2: writes checkpoints/CP2_WAITING.md
        │         polls for checkpoints/CP2_RESPONSE.txt every 60s
        │         valid responses: refactor | writeup | both | done
        │         (for refactor/both: also write checkpoints/PAIN_POINTS.txt)
        └── Phase 3 (run_phase3)
              └── dispatches sub-action, writes CP3_COMPLETE.md
```

---

*Built by Claude Code. Engineering decisions are the scaffold's; science and protocol are frozen per AGENTS.md.*
