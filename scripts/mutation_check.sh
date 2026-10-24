#!/usr/bin/env bash
# Sanity-check the test-suite itself: inject known bugs into the engine and require the C++ tests to FAIL.
# A suite that cannot fail proves nothing.
set -u
cd "$(dirname "$0")/.."
SRC=src/order_book.cpp
BAK=$(mktemp)
cp "$SRC" "$BAK"
trap 'cp "$BAK" "$SRC"; rm -f "$BAK"' EXIT

mutants=(
  "buy limit off-by-one|0,/if (buy ? px > limit : px < limit) break;/s//if (buy ? px >= limit : px < limit) break;/"
  "best level not refreshed on cancel|s/    if (sb.best != idx) return;/    return;/"
  "reduce forgets level total|s/    side_book(n.side).levels\\[idx_of(n.price)\\].total -= (n.remaining - new_qty);//"
  "FIFO becomes LIFO|s/Node& n = nodes_\\[L.head\\];/Node\\& n = nodes_[L.tail];/"
  "trade at aggressor price|s/t.price = px;/t.price = limit;/"
  "post-only check removed|s/if (req.post_only \\&\\& would_cross(req.side, limit)) return reject(RejectReason::PostOnlyWouldCross);//"
)
survived=0
for m in "${mutants[@]}"; do
  name="${m%%|*}"; expr="${m#*|}"
  cp "$BAK" "$SRC"; sed -i "$expr" "$SRC"
  if cmp -s "$SRC" "$BAK"; then echo "  [skip] $name (pattern did not apply)"; continue; fi
  if g++ -std=c++17 -O1 -Iinclude -Itests tests/main.cpp tests/test_order_book.cpp tests/test_differential.cpp \
        "$SRC" src/types.cpp -o /tmp/lob_mut 2>/dev/null && /tmp/lob_mut >/dev/null 2>&1; then
    echo "  [SURVIVED] $name   <-- the tests did not notice this bug"; survived=$((survived+1))
  else
    echo "  [killed]   $name"
  fi
done
cp "$BAK" "$SRC"
[ "$survived" -eq 0 ] && echo "all mutants killed" || { echo "$survived mutant(s) survived"; exit 1; }
