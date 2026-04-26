# BOOTSTRAP_PROMPT.md

This file is the prompt to feed to Claude Code as the first action on a fresh clone of this repo. Copy the contents below the line and paste into Claude Code.

---

You are working in the `peach-loop` repository. Three files are present at the root: `README.md`, `AGENTS.md`, `BOOTSTRAP_PROMPT.md` (this file).

Read all three before doing anything else. They establish what the project is, who the audiences are, and the rules under which the autonomous agent will operate. `AGENTS.md` is the contract for the agent that will run this on remote compute; you are scaffolding the codebase that agent will execute against.

## Your task

Scaffold this repository so that an autonomous agent on a remote machine (DGX Spark or similar) can execute Phases 1–3 as specified in AGENTS.md without further human direction except at the three named checkpoints.

You have full latitude on engineering decisions per AGENTS.md §11. The science, budgets, acceptance criteria, checkpoint protocols, and daily digest schedule are frozen.

## Specifically

1. **Set up the environment.** Decide on package manager (uv, mamba, pip — your call), pin a working set of dependencies. PEACH (github.com/xhonkala/PEACH) is the core dependency. You'll also need scanpy or equivalent for scRNA-seq handling, a gene set enrichment tool, plotting, and whatever logging/config libraries you prefer. Verify everything imports.

2. **Build the directory structure.** AGENTS.md mentions `src/`, `data/`, `configs/`, `logs/`, `reports/`, `checkpoints/` as expected — beyond that, organize as you see fit. Add a `Makefile` or task runner (`just`, `invoke`, whatever) so common operations have one-line invocations.

3. **Implement the Phase 1 pipeline:**
   - Dataset acquisition with hash verification
   - Preprocessing pipeline (scanpy PBMC tutorial reference)
   - PEACH Deep_AA training loop with checkpointing
   - Held-out evaluation
   - Per-archetype gene set enrichment
   - Report generation (markdown)

4. **Implement the Phase 2 sweep harness:**
   - Variant configuration (default: preprocessing pipelines per AGENTS.md §4.1)
   - Sequential execution with per-variant resource caps
   - Comparison report generation with the plots specified in AGENTS.md §4.2
   - At least 3 seeds per variant for the stability metric

5. **Implement the operational layer:**
   - Daily digest generator (AGENTS.md §6)
   - Checkpoint protocol implementation (AGENTS.md §7) — including the halt-and-wait mechanism for CP1 and CP2
   - Tier-1/Tier-2 escalation handlers (AGENTS.md §8, §9)
   - Resume-from-checkpoint logic with the verification test specified in §3.5

6. **Implement Phase 3 sub-actions** (refactor / writeup / both / done) as separate scripts the agent can dispatch to based on human direction at CP2.

7. **Write a single launch script** (`launch.sh` or equivalent) that the human can invoke once on the remote machine to start the autonomous run. The script should:
   - Verify the environment
   - Run a setup-time smoke test (PEACH imports, model instantiates, forward pass succeeds — Tier-1 if it fails)
   - Launch Phase 1
   - Hand off to the autonomous loop

8. **Add minimal tests.** Not a full coverage suite — but at minimum: the resume test from §3.5 should be runnable as a unit test, the digest generator should have a smoke test, the report generators should be testable on synthetic outputs.

9. **Document your choices.** As you make engineering decisions (package versions, file formats, library choices), record them in `docs/decisions.md` with brief rationale. This is the project's living ADR log.

10. **Commit progressively.** Don't dump everything in one commit. Reasonable atomic commits the human can read in chronological order to understand how the scaffold was built.

## Notes and constraints

- This is a learning project for the human. They have not run an autonomous training loop before. Optimize for legibility over cleverness — they will read this code.
- The model is small (PEACH's encoder is 1-10M params). Don't over-engineer for scale.
- DO NOT add capabilities outside what AGENTS.md specifies (no Slack notifications instead of the digest format, no email, no exotic schedulers). The constraint is part of the learning.
- DO surface ambiguities. If something in AGENTS.md is unclear in a way that would meaningfully change your implementation, write the question to `docs/decisions.md` under "Questions for human review" and proceed with your best interpretation.
- The PEACH citation in AGENTS.md §12 is incomplete (author first name missing). Verify and update from the actual PEACH repo.

## When done

Write a `BOOTSTRAP_COMPLETE.md` at the repo root with:
- A summary of what you built
- The list of engineering decisions you made (or pointer to `docs/decisions.md`)
- Any questions that need human review before launch
- The exact command to launch the autonomous run on the remote machine
- An estimate of how long the smoke test takes vs. how long Phase 1 takes

Then commit, push if a remote is configured, and stop.

## What you should not do

- Do not start running Phase 1. The bootstrap is scaffolding only. The human launches the actual run on the remote machine.
- Do not modify AGENTS.md or README.md. They're the contract; if something seems wrong, flag it in `docs/decisions.md` for human review.
- Do not invent new phases, checkpoints, or tier conditions. The protocol is the protocol.
- Do not add a web UI, dashboard, or any agent-facing interface beyond what AGENTS.md specifies. Disk and digest are the interfaces.
