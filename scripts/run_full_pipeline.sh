#!/usr/bin/env bash
# One command, whole stack: build -> C++ tests -> benchmark -> Python tests -> simulation -> SQL -> R.
set -euo pipefail
cd "$(dirname "$0")/.."

echo ">>> 1/7 build C++ (Release)"
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DLOB_NATIVE=ON >/dev/null
cmake --build build -j"$(nproc 2>/dev/null || echo 2)"

echo ">>> 2/7 C++ tests (unit + differential fuzz vs reference book)"
./build/lob_tests | tail -3

echo ">>> 3/7 benchmark (quick: 500k ops)"
./build/lob_bench --ops 500000 --reps 3

echo ">>> 4/7 install Python package + tests"
pip install -q -e ".[dev]"
python -m pytest -q

echo ">>> 5/7 simulate (CSV + SQLite + plots)"
python -m lob simulate --steps 20000 --out results --sqlite --plots

echo ">>> 6/7 SQL analytics"
python -m lob sql results/lob.sqlite --query 05_markouts
python -m lob sql results/lob.sqlite --query 06_strategy_pnl_attribution

echo ">>> 7/7 R analysis"
if command -v Rscript >/dev/null 2>&1; then Rscript r/analyze.R results; else echo "Rscript not found - skipped"; fi
echo "=== done: artifacts in results/ ==="
