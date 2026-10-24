#!/usr/bin/env bash
# One-command runner.   ./run.sh [demo|test|bench|sim|all|clean]
#   demo   (default) install, then 30-second market simulation
#   test   C++ tests + Python tests
#   bench  C++ benchmark (fast book vs std::map baseline)
#   sim    simulate -> CSV + SQLite + plots -> SQL queries -> R analysis
#   all    test + bench + sim
#   clean  remove build/venv/results
set -euo pipefail
cd "$(dirname "$0")"
CMD="${1:-demo}"

say() { printf '\n\033[1;34m>>> %s\033[0m\n' "$*"; }

if [ "$CMD" = "clean" ]; then rm -rf .venv build build-san results python/lob/_core*.so *.egg-info python/*.egg-info; echo "cleaned"; exit 0; fi

command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }

setup_python() {
  if [ ! -d .venv ]; then say "creating virtualenv (.venv)"; python3 -m venv .venv; fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  if ! python -c "import lob" 2>/dev/null; then
    say "installing package (builds the C++ extension if a compiler is present)"
    pip install -q --upgrade pip
    pip install -q -e ".[dev,analysis]" || { echo "build failed; need a C++17 compiler (g++/clang++)"; exit 1; }
  fi
  python -c "import lob; print('Python backend:', 'C++' if lob.HAS_CPP else 'pure-Python')"
}

build_cpp() {
  if command -v cmake >/dev/null && command -v c++ >/dev/null; then
    say "building C++ (Release)"
    cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DLOB_NATIVE=ON >/dev/null
    cmake --build build -j"$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)" >/dev/null
    return 0
  fi
  echo "cmake/c++ not found: skipping native C++ targets"; return 1
}

do_test()  { setup_python; if build_cpp; then say "C++ tests"; ./build/lob_tests | tail -3; fi; say "Python tests"; python -m pytest -q; }
do_bench() { if build_cpp; then say "benchmark (takes ~2 min at full size)"; ./build/lob_bench --ops 1000000 --reps 3; fi; }
do_sim() {
  setup_python
  say "simulate (CSV + SQLite + plots)"; python -m lob simulate --steps 20000 --out results --sqlite --plots
  say "SQL: adverse selection + PnL attribution"
  python -m lob sql results/lob.sqlite --query 05_markouts
  python -m lob sql results/lob.sqlite --query 06_strategy_pnl_attribution
  if command -v Rscript >/dev/null; then say "R analysis"; Rscript r/analyze.R results; else echo "Rscript not found: skipping R step"; fi
  echo; echo "Outputs in ./results (simulation.png, depth.png, r_*.png, lob.sqlite, *.csv)"
}

case "$CMD" in
  demo)  setup_python; say "demo"; python -m lob demo ;;
  test)  do_test ;;
  bench) do_bench ;;
  sim)   do_sim ;;
  all)   do_test; do_bench; do_sim ;;
  *)     echo "usage: ./run.sh [demo|test|bench|sim|all|clean]"; exit 2 ;;
esac
