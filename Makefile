# Makefile — common one-line operations for peach-loop
# Usage: make <target>

PYTHON   ?= .venv/bin/python
UV       ?= uv
VENV     := .venv

.PHONY: help install smoke-test test-resume test test-all run resume \
        clean-checkpoints clean-logs clean digest status fmt lint

# ── Default ──────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "peach-loop — available targets:"
	@echo ""
	@echo "  make install          Install all dependencies via uv"
	@echo "  make smoke-test       Run setup-time smoke test (AGENTS.md §8)"
	@echo "  make test-resume      Run the §3.5 resume-from-checkpoint test"
	@echo "  make test             Run the full pytest test suite"
	@echo "  make test-all         smoke-test + test-resume + pytest"
	@echo ""
	@echo "  make run              Start a fresh autonomous run (via launch.sh)"
	@echo "  make resume           Resume an interrupted run"
	@echo ""
	@echo "  make digest           Generate today's digest manually (for testing)"
	@echo "  make status           Print current run state"
	@echo ""
	@echo "  make clean-checkpoints  Delete non-essential checkpoint files"
	@echo "  make clean-logs         Delete all log files (caution: logs are precious)"
	@echo "  make clean              Remove .venv and caches (preserve data/logs)"
	@echo ""

# ── Environment ───────────────────────────────────────────────────────────────
install:
	$(UV) venv $(VENV)
	$(UV) pip install -e ".[dev]" --python $(VENV)/bin/python
	@echo ""
	@echo "Environment ready.  Activate with: source .venv/bin/activate"

# ── Tests ─────────────────────────────────────────────────────────────────────
smoke-test:
	$(PYTHON) scripts/smoke_test.py

test-resume:
	$(PYTHON) scripts/resume_test.py

test:
	$(PYTHON) -m pytest tests/ -v

test-all: smoke-test test-resume test

# ── Run ───────────────────────────────────────────────────────────────────────
run:
	./launch.sh

resume:
	./launch.sh --resume

# ── Operational helpers ───────────────────────────────────────────────────────
digest:
	$(PYTHON) -c "\
from pathlib import Path; \
import sys; sys.path.insert(0, 'src'); \
from peach_loop.config import load_config, resolve_path; \
from peach_loop.ops.state import load_state; \
from peach_loop.ops.digest import generate_digest; \
cfg = load_config('configs/base.yaml', 'configs/phase1.yaml'); \
state = load_state('logs/run_state.json'); \
p = generate_digest(state, cfg, resolve_path(cfg, 'digests')); \
print(f'Digest written: {p}')"

status:
	@if [ -f logs/run_state.json ]; then \
		$(PYTHON) -c "\
import json, sys; \
d = json.load(open('logs/run_state.json')); \
print(f'Phase:      {d.get(\"current_phase\", \"?\")}'); \
print(f'Status:     {d.get(\"phase_status\", \"?\")}'); \
print(f'R² (P1):    {d.get(\"phase1_archetype_r2\", \"N/A\")}'); \
print(f'n_arch:     {d.get(\"phase1_n_archetypes\", \"N/A\")}'); \
print(f'Checkpoint: {d.get(\"checkpoint_path\", \"none\")}'); \
print(f'Tier-1:     {len(d.get(\"tier1_events\", []))} events'); \
print(f'Tier-2:     {len(d.get(\"tier2_events\", []))} events')"; \
	else \
		echo "No state file found (run not started yet)."; \
	fi

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean-checkpoints:
	@echo "Keeping last 5 checkpoints per phase, removing older ones …"
	$(PYTHON) -c "\
import sys; sys.path.insert(0, 'src'); \
from pathlib import Path; \
from peach_loop.ops.checkpoint import _cleanup_old_checkpoints; \
for d in Path('checkpoints').rglob('*'): \
    if d.is_dir() and not any(d.iterdir() if d.exists() else []): continue; \
print('Done (run manually per phase dir for finer control)')"

clean-logs:
	@echo "WARNING: logs are protected per AGENTS.md §10. Proceed? [y/N]" && read ans && [ "$$ans" = y ]
	rm -f logs/events/*.jsonl logs/training/*.jsonl logs/tier1/*.json logs/tier2/*.json

clean:
	rm -rf $(VENV) __pycache__ src/peach_loop/__pycache__ \
	       src/peach_loop/**/__pycache__ .pytest_cache *.egg-info
	@echo "Cleaned. Data, logs, checkpoints, and reports preserved."
