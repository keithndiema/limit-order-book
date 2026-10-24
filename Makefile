.PHONY: all build test bench python pytest sim r sql sanitize mutation clean
all: build test

build:
	cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DLOB_NATIVE=ON
	cmake --build build -j

test: build
	ctest --test-dir build --output-on-failure

bench: build
	./build/lob_bench --ops 2000000 --reps 5 --json docs/assets/benchmark.json

python:
	pip install -e ".[dev]"

pytest:
	python -m pytest -q

sim:
	python -m lob simulate --out results --sqlite --plots

r: sim
	Rscript r/analyze.R results

sql: sim
	python -m lob sql results/lob.sqlite

sanitize:
	cmake -S . -B build-san -DCMAKE_BUILD_TYPE=Debug -DLOB_SANITIZE=ON -DLOB_BUILD_BENCH=OFF
	cmake --build build-san -j
	./build-san/lob_tests

mutation:
	./scripts/mutation_check.sh

clean:
	rm -rf build build-san build-py results
