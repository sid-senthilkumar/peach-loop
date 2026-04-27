#!/usr/bin/env bash
# launch.sh — single-command entry point for the autonomous peach-loop run.
#
# Usage (on the remote machine):
#   chmod +x launch.sh
#   ./launch.sh
#
# What this does:
#   1. Verify Python version (≥ 3.10)
#   2. Install uv if not present
#   3. Create / sync the virtual environment from pyproject.toml
#   4. Run the smoke test (Tier-1 halt if it fails)
#   5. Launch Phase 1 → autonomous loop
#
# To resume after a crash or interrupt:
#   ./launch.sh --resume

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

PYTHON_MIN_MAJOR=3
PYTHON_MIN_MINOR=10
VENV_DIR="$REPO_ROOT/.venv"
LOG_DIR="$REPO_ROOT/logs"
LAUNCH_LOG="$LOG_DIR/launch.log"

mkdir -p "$LOG_DIR/events"

# Redirect all output to both console and launch log
exec > >(tee -a "$LAUNCH_LOG") 2>&1

echo ""
echo "======================================================="
echo "  peach-loop autonomous run"
echo "  $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "  Repo: $REPO_ROOT"
echo "======================================================="
echo ""

# ── 1. Python version check ──────────────────────────────────────────────────
echo "[1/5] Checking Python version …"
if command -v python3 &>/dev/null; then
    PYTHON_CMD=python3
elif command -v python &>/dev/null; then
    PYTHON_CMD=python
else
    echo "ERROR: Python not found. Install Python $PYTHON_MIN_MAJOR.$PYTHON_MIN_MINOR or later."
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.minor)")

if [ "$PYTHON_MAJOR" -lt "$PYTHON_MIN_MAJOR" ] || \
   { [ "$PYTHON_MAJOR" -eq "$PYTHON_MIN_MAJOR" ] && [ "$PYTHON_MINOR" -lt "$PYTHON_MIN_MINOR" ]; }; then
    echo "ERROR: Python $PYTHON_VERSION found, but $PYTHON_MIN_MAJOR.$PYTHON_MIN_MINOR+ required."
    exit 1
fi
echo "  Python $PYTHON_VERSION OK"

# ── 2. Install uv ────────────────────────────────────────────────────────────
echo ""
echo "[2/5] Checking uv package manager …"
if ! command -v uv &>/dev/null; then
    echo "  uv not found — installing via pip …"
    $PYTHON_CMD -m pip install --quiet uv
fi
echo "  uv: $(uv --version)"

# ── 3. Sync virtual environment ──────────────────────────────────────────────
echo ""
echo "[3/5] Syncing virtual environment …"
if [ ! -d "$VENV_DIR" ]; then
    echo "  Creating .venv …"
    uv venv "$VENV_DIR" --python "$PYTHON_CMD"
fi

echo "  Installing dependencies from pyproject.toml …"
# Install the package itself plus all dependencies (PEACH from git)
uv pip install --quiet -e ".[dev]" --python "$VENV_DIR/bin/python"

# Activate the venv for subsequent commands in this script
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"
echo "  Virtual environment ready."

# ── 4. Smoke test ────────────────────────────────────────────────────────────
echo ""
echo "[4/5] Running smoke test (Tier-1 if this fails) …"
if ! python scripts/smoke_test.py; then
    echo ""
    echo "SMOKE TEST FAILED — Tier-1 condition (AGENTS.md §8)."
    echo "Details written to: logs/tier1/"
    echo ""
    echo "Fix the issue and re-run: ./launch.sh"
    exit 2
fi
echo "  Smoke test passed."

# ── 5. Launch autonomous run ─────────────────────────────────────────────────
echo ""
echo "[5/5] Launching autonomous run …"
echo ""

RESUME_FLAG=""
if [[ "${1:-}" == "--resume" ]]; then
    RESUME_FLAG="--resume"
    echo "  Mode: RESUME from existing state"
else
    echo "  Mode: FRESH start"
fi

echo "  Run log: $LAUNCH_LOG"
echo "  State file: logs/run_state.json"
echo "  Digest directory: reports/digests/"
echo ""
echo "  The run will halt at CP1 and CP2 waiting for your response."
echo "  Watch for files: checkpoints/CP1_WAITING.md and checkpoints/CP2_WAITING.md"
echo ""
echo "======================================================="
echo "  Starting Phase 1 …"
echo "======================================================="
echo ""

exec python scripts/run_all.py $RESUME_FLAG
