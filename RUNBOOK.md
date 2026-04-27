# Running peach-loop on compute

This is everything you need to go from a fresh machine to a running autonomous training loop.

---

## First-time setup

```bash
git clone https://github.com/sid-senthilkumar/peach-loop.git
cd peach-loop
./launch.sh
```

That's it. The launch script handles Python version check, uv installation, virtual environment creation, a smoke test, and Phase 1 start — in that order. If the smoke test fails it halts with a clear error; fix it and re-run.

---

## What runs unattended

Once launched, the agent runs Phases 1 and 2 without you. It:

- Downloads and preprocesses PBMC 3K
- Runs PEACH hyperparameter search, then full training with checkpoints every 20 epochs
- Generates a daily digest at **08:00 local time** in `reports/digests/`
- Produces a Phase 1 report with loss curves and a 3D archetypal-space plot
- Runs the Phase 2 preprocessing sweep (7 variants × 3 seeds) and a comparison report

You are contacted at **three named checkpoints only** — not during runs.

---

## Checkpoint 1 — after Phase 1

The run halts and writes `checkpoints/CP1_WAITING.md`.

1. Read `checkpoints/CP1_WAITING.md` for the acceptance criteria summary
2. Read `reports/phase1/phase1_report.md` for the full Phase 1 output
3. Check `reports/digests/` for any daily digests from the run

Then write your response:

```bash
# Default: run the preprocessing sweep as configured
echo "proceed-default-sweep" > checkpoints/CP1_RESPONSE.txt

# Override: run a different sweep dimension instead
echo "proceed-with-override n_archetypes" > checkpoints/CP1_RESPONSE.txt

# Stop entirely
echo "abort" > checkpoints/CP1_RESPONSE.txt
```

The agent resumes within 60 seconds of finding the file.

---

## Checkpoint 2 — after Phase 2

The run halts and writes `checkpoints/CP2_WAITING.md`.

1. Read `checkpoints/CP2_WAITING.md`
2. Read `reports/phase2/phase2_comparison.md` — focus on the stability scores and the archetype correspondence heatmap

Then write your response:

```bash
# Produce a ~2000-word technical note from the sweep results
echo "writeup" > checkpoints/CP2_RESPONSE.txt

# Address pain points in the loop, then re-verify with a baseline run
echo "refactor" > checkpoints/CP2_RESPONSE.txt

# Both: refactor first, then writeup
echo "both" > checkpoints/CP2_RESPONSE.txt

# Generate a final summary and stop
echo "done" > checkpoints/CP2_RESPONSE.txt
```

If you choose `refactor` or `both`, also write your pain points (one per line) before responding:

```bash
nano checkpoints/PAIN_POINTS.txt   # write what bothered you about Phase 1/2
echo "refactor" > checkpoints/CP2_RESPONSE.txt
```

---

## Checkpoint 3 — after Phase 3

No halt. The agent writes `CP3_COMPLETE.md` at the repo root and stops. Review `reports/phase3/` for the final output.

---

## If the run crashes

```bash
./launch.sh --resume
```

Resumes from the last saved checkpoint automatically. The run state is in `logs/run_state.json` if you want to inspect it.

---

## Useful commands at any time

```bash
make status      # current phase, R², checkpoint path, event counts
make digest      # generate today's digest manually (useful for testing)
make smoke-test  # re-run the smoke test (good after a dependency change)
make test        # run the full test suite
```

Live event stream:
```bash
tail -f logs/events/events.jsonl
```

---

## If something goes wrong — Tier-1 alert

If a file called `TIER1_ALERT.md` appears in the repo root, the agent has halted the current phase. This means something needs human attention — the file will say exactly what.

Read it, fix the underlying issue, then:

```bash
./launch.sh --resume
```

Common causes: disk full, loss diverged to NaN, smoke test failing after a dependency update.

---

## File map

| Path | What it is |
|------|------------|
| `logs/run_state.json` | Full run state — current phase, checkpoint path, event history |
| `logs/events/events.jsonl` | Structured event log (one JSON object per line) |
| `logs/training/training.jsonl` | Per-step training metrics (loss components) |
| `reports/digests/` | Daily digests — start here for a quick status check |
| `reports/phase1/phase1_report.md` | Phase 1 results and acceptance criteria |
| `reports/phase2/phase2_comparison.md` | Sweep comparison with plots |
| `checkpoints/` | Saved model checkpoints + CP waiting/response files |
| `TIER1_ALERT.md` | Only appears on a Tier-1 halt — read immediately |
| `docs/decisions.md` | Engineering decisions and questions flagged for review |
