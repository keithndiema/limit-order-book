// Benchmark: optimised OrderBook vs. the std::map+deque ReferenceBook baseline.
//
// Method (details and caveats in docs/BENCHMARKS.md):
//   * the operation stream is generated ONCE from a fixed seed, outside any timed region, and
//     replayed identically against both implementations;
//   * throughput = median of several full replays, no per-operation timing inside the loop;
//   * latency   = separate replay with a steady_clock read around every operation; the median
//     cost of an empty clock-read pair is measured and subtracted (reported separately);
//   * trade-tape recording is disabled so we measure matching, not vector growth;
//   * a checksum of the final book state is printed so the optimiser cannot delete the work
//     and so you can see both implementations ended in the same state.

#include "lob/order_book.hpp"
#include "lob/reference_book.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <functional>
#include <random>
#include <string>
#include <vector>

using namespace lob;
using clk = std::chrono::steady_clock;

namespace {

enum class Kind : std::uint8_t { Limit, Market, Cancel };

struct Op {
    Kind kind;
    Side side;
    std::int32_t offset;     // ticks from the reference mid (negative = crosses the spread)
    std::int32_t qty;
    std::uint32_t pick;      // random number used to choose a cancel target
};

struct Workload {
    std::string name;
    std::vector<Op> ops;
    Price mid;
};

// mean_offset: average passive distance in ticks (bigger -> deeper, more spread-out book)
Workload make_workload(const std::string& name, std::size_t n, double mean_offset,
                       double p_cancel, double p_market, double p_aggressive, std::uint64_t seed) {
    Workload w{name, {}, 20000};
    w.ops.reserve(n);
    std::mt19937_64 rng(seed);
    std::uniform_real_distribution<double> u(0.0, 1.0);
    std::exponential_distribution<double> expo(1.0 / mean_offset);
    std::uniform_int_distribution<int> qty(1, 100);
    for (std::size_t i = 0; i < n; ++i) {
        Op op{};
        op.side = (u(rng) < 0.5) ? Side::Buy : Side::Sell;
        op.qty = qty(rng);
        op.pick = static_cast<std::uint32_t>(rng());
        const double r = u(rng);
        if (r < p_cancel) {
            op.kind = Kind::Cancel;
        } else if (r < p_cancel + p_market) {
            op.kind = Kind::Market;
        } else {
            op.kind = Kind::Limit;
            op.offset = (u(rng) < p_aggressive) ? -static_cast<std::int32_t>(expo(rng) * 0.5)
                                                : 1 + static_cast<std::int32_t>(expo(rng));
        }
        w.ops.push_back(op);
    }
    return w;
}

struct Outcome {
    std::uint64_t checksum = 0;
    std::uint64_t trades = 0;
    std::size_t resting = 0;
};

// Applies one op; `live` tracks resting ids so cancels hit real orders (like a real client would).
template <class Book>
inline void apply(Book& book, const Workload& w, const Op& op, std::vector<OrderId>& live) {
    switch (op.kind) {
        case Kind::Limit: {
            const Price px = op.side == Side::Buy ? w.mid - op.offset : w.mid + op.offset;
            auto r = book.limit(op.side, px, op.qty);
            if (r.resting) live.push_back(r.order_id);
            break;
        }
        case Kind::Market:
            book.market(op.side, op.qty);
            break;
        case Kind::Cancel:
            if (!live.empty()) {
                const std::size_t i = op.pick % live.size();
                const OrderId id = live[i];
                live[i] = live.back();
                live.pop_back();
                book.cancel(id);
            }
            break;
    }
}

template <class Book>
Outcome replay(const Workload& w, double* seconds) {
    Book book;
    book.set_record_tape(false);
    std::vector<OrderId> live;
    live.reserve(1 << 20);
    const auto t0 = clk::now();
    for (const Op& op : w.ops) apply(book, w, op, live);
    const auto t1 = clk::now();
    if (seconds) *seconds = std::chrono::duration<double>(t1 - t0).count();
    Outcome o;
    o.trades = book.total_trades();
    o.resting = book.order_count();
    o.checksum = book.total_volume() * 1000003ULL + book.order_count();
    if (auto b = book.best_bid()) o.checksum ^= static_cast<std::uint64_t>(*b) << 20;
    if (auto a = book.best_ask()) o.checksum ^= static_cast<std::uint64_t>(*a) << 40;
    return o;
}

struct Pct { double p50, p90, p99, p999, mean; };

Pct percentiles(std::vector<double>& v) {
    if (v.empty()) return {0, 0, 0, 0, 0};
    std::sort(v.begin(), v.end());
    auto at = [&](double q) { return v[std::min(v.size() - 1, static_cast<std::size_t>(q * static_cast<double>(v.size())))]; };
    double s = 0;
    for (double x : v) s += x;
    return {at(0.50), at(0.90), at(0.99), at(0.999), s / static_cast<double>(v.size())};
}

double clock_overhead_ns() {
    std::vector<double> d;
    d.reserve(200000);
    for (int i = 0; i < 200000; ++i) {
        const auto a = clk::now();
        const auto b = clk::now();
        d.push_back(static_cast<double>(std::chrono::duration_cast<std::chrono::nanoseconds>(b - a).count()));
    }
    std::sort(d.begin(), d.end());
    return d[d.size() / 2];
}

struct LatencyReport { Pct limit, cancel, market; };

template <class Book>
LatencyReport latency(const Workload& w, double overhead) {
    Book book;
    book.set_record_tape(false);
    std::vector<OrderId> live;
    live.reserve(1 << 20);
    std::vector<double> lim, can, mkt;
    lim.reserve(w.ops.size()); can.reserve(w.ops.size()); mkt.reserve(w.ops.size() / 8);
    for (const Op& op : w.ops) {
        if (op.kind == Kind::Cancel && live.empty()) continue;
        const auto a = clk::now();
        apply(book, w, op, live);
        const auto b = clk::now();
        const double ns = std::max(0.0, static_cast<double>(std::chrono::duration_cast<std::chrono::nanoseconds>(b - a).count()) - overhead);
        (op.kind == Kind::Limit ? lim : op.kind == Kind::Cancel ? can : mkt).push_back(ns);
    }
    return {percentiles(lim), percentiles(can), percentiles(mkt)};
}

double median(std::vector<double> v) { std::sort(v.begin(), v.end()); return v[v.size() / 2]; }

struct Row {
    std::string workload, impl;
    double mops, speedup;
    LatencyReport lat;
    std::uint64_t checksum;
};

}  // namespace

int main(int argc, char** argv) {
    std::size_t n = 2'000'000;
    int reps = 5;
    std::string json_path;
    for (int i = 1; i < argc; ++i) {
        if (!std::strcmp(argv[i], "--ops") && i + 1 < argc) n = static_cast<std::size_t>(std::atoll(argv[++i]));
        else if (!std::strcmp(argv[i], "--reps") && i + 1 < argc) reps = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "--json") && i + 1 < argc) json_path = argv[++i];
        else { std::fprintf(stderr, "usage: bench [--ops N] [--reps R] [--json out.json]\n"); return 2; }
    }

    const double overhead = clock_overhead_ns();
    std::printf("lob benchmark | ops/workload=%zu reps=%d | clock-read overhead subtracted: %.0f ns\n\n", n, reps, overhead);

    std::vector<Workload> loads;
    loads.push_back(make_workload("tight   (mean offset 4 ticks, 30% cancel)", n, 4.0, 0.30, 0.06, 0.10, 42));
    loads.push_back(make_workload("deep    (mean offset 60 ticks, 30% cancel)", n, 60.0, 0.30, 0.06, 0.10, 43));
    loads.push_back(make_workload("churn   (mean offset 15 ticks, 40% cancel)", n, 15.0, 0.40, 0.04, 0.08, 44));

    std::vector<Row> rows;
    for (const auto& w : loads) {
        double t_fast_med, t_ref_med;
        Outcome of{}, orf{};
        std::vector<double> tf, tr;
        for (int r = 0; r < reps; ++r) { double s; of = replay<OrderBook>(w, &s); tf.push_back(s); }
        for (int r = 0; r < reps; ++r) { double s; orf = replay<ReferenceBook>(w, &s); tr.push_back(s); }
        t_fast_med = median(tf); t_ref_med = median(tr);
        const double mops_fast = static_cast<double>(n) / t_fast_med / 1e6;
        const double mops_ref = static_cast<double>(n) / t_ref_med / 1e6;
        const bool agree = of.checksum == orf.checksum && of.trades == orf.trades;

        auto lf = latency<OrderBook>(w, overhead);
        auto lr = latency<ReferenceBook>(w, overhead);

        std::printf("== %s\n", w.name.c_str());
        std::printf("   final state: %zu resting, %llu trades | implementations agree: %s\n",
                    of.resting, static_cast<unsigned long long>(of.trades), agree ? "yes" : "NO (BUG)");
        std::printf("   %-14s %8s %9s   %-22s %-22s %-22s\n", "", "Mops/s", "speedup", "limit p50/p99 (ns)", "cancel p50/p99 (ns)", "market p50/p99 (ns)");
        auto line = [&](const char* name, double mops, double sp, const LatencyReport& l) {
            std::printf("   %-14s %8.2f %8.1fx   %8.0f / %-11.0f %8.0f / %-11.0f %8.0f / %-11.0f\n", name, mops, sp,
                        l.limit.p50, l.limit.p99, l.cancel.p50, l.cancel.p99, l.market.p50, l.market.p99);
        };
        line("OrderBook", mops_fast, mops_fast / mops_ref, lf);
        line("ReferenceBook", mops_ref, 1.0, lr);
        std::printf("\n");
        rows.push_back({w.name, "OrderBook", mops_fast, mops_fast / mops_ref, lf, of.checksum});
        rows.push_back({w.name, "ReferenceBook", mops_ref, 1.0, lr, orf.checksum});
        if (!agree) return 1;
    }

    if (!json_path.empty()) {
        std::ofstream f(json_path);
        f << "{\n  \"ops_per_workload\": " << n << ",\n  \"clock_overhead_ns\": " << overhead << ",\n  \"results\": [\n";
        for (std::size_t i = 0; i < rows.size(); ++i) {
            const auto& r = rows[i];
            auto pct = [&](const char* k, const Pct& p) {
                f << "\"" << k << "\": {\"p50\": " << p.p50 << ", \"p90\": " << p.p90 << ", \"p99\": " << p.p99
                  << ", \"p999\": " << p.p999 << ", \"mean\": " << p.mean << "}";
            };
            std::string wl = r.workload.substr(0, r.workload.find(' '));
            f << "    {\"workload\": \"" << wl << "\", \"impl\": \"" << r.impl << "\", \"mops\": " << r.mops
              << ", \"speedup\": " << r.speedup << ", ";
            pct("limit", r.lat.limit); f << ", "; pct("cancel", r.lat.cancel); f << ", "; pct("market", r.lat.market);
            f << "}" << (i + 1 < rows.size() ? "," : "") << "\n";
        }
        f << "  ]\n}\n";
        std::printf("wrote %s\n", json_path.c_str());
    }
    return 0;
}
