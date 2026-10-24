// Differential fuzzing: drive the optimised OrderBook and the straightforward ReferenceBook with
// the same random stream of operations (limit/market/IOC/FOK/post-only/cancel/reduce/replace,
// including invalid inputs) and require *identical* observable behaviour after every single step.

#include "check.hpp"
#include "lob/order_book.hpp"
#include "lob/reference_book.hpp"

#include <random>
#include <unordered_set>

using namespace lob;

namespace {

bool same(const SubmitResult& a, const SubmitResult& b) {
    return a.order_id == b.order_id && a.filled == b.filled && a.remaining == b.remaining &&
           a.resting == b.resting && a.reject == b.reject && a.trades == b.trades;
}

struct Harness {
    OrderBook fast;
    ReferenceBook ref;
    std::vector<OrderId> ids;           // every id ever accepted (some are dead; tests unknown-id paths)
    std::size_t ops = 0;

    Harness(Price lo, Price hi) : fast(lo, hi), ref(lo, hi) {}

    void compare_state(bool deep) {
        CHECK(fast.best_bid() == ref.best_bid());
        CHECK(fast.best_ask() == ref.best_ask());
        CHECK(fast.spread() == ref.spread());
        CHECK(fast.mid_price() == ref.mid_price());
        CHECK_EQ(fast.order_count(), ref.order_count());
        CHECK_EQ(fast.total_trades(), ref.total_trades());
        CHECK_EQ(fast.total_volume(), ref.total_volume());
        const std::size_t depth = deep ? 100000 : 5;
        CHECK(fast.bid_levels(depth) == ref.bid_levels(depth));
        CHECK(fast.ask_levels(depth) == ref.ask_levels(depth));
        // Book must never be crossed.
        if (fast.best_bid() && fast.best_ask()) CHECK(*fast.best_bid() < *fast.best_ask());
        if (deep) CHECK(fast.trades() == ref.trades());
    }
};

void run(std::uint64_t seed, std::size_t n_ops, Price lo, Price hi, Price band_lo, Price band_hi) {
    Harness h(lo, hi);
    std::mt19937_64 rng(seed);
    auto uni = [&](std::int64_t a, std::int64_t b) { return std::uniform_int_distribution<std::int64_t>(a, b)(rng); };

    for (std::size_t i = 0; i < n_ops; ++i) {
        const int dice = static_cast<int>(uni(0, 99));
        const Side side = uni(0, 1) ? Side::Buy : Side::Sell;
        // Mostly prices inside a tight band (lots of crossing); sometimes extremes and invalid values.
        Price px = uni(band_lo, band_hi);
        const int pdice = static_cast<int>(uni(0, 49));
        if (pdice == 0) px = lo; else if (pdice == 1) px = hi; else if (pdice == 2) px = uni(-3, 0);
        else if (pdice == 3) px = hi + uni(1, 5);
        Quantity q = uni(1, 30);
        if (uni(0, 60) == 0) q = uni(-2, 0);

        if (dice < 45) {                                   // plain GTC limit
            auto a = h.fast.limit(side, px, q), b = h.ref.limit(side, px, q);
            CHECK(same(a, b));
            if (a.accepted()) h.ids.push_back(a.order_id);
        } else if (dice < 52) {                            // IOC
            auto a = h.fast.limit(side, px, q, TimeInForce::IOC), b = h.ref.limit(side, px, q, TimeInForce::IOC);
            CHECK(same(a, b));
            if (a.accepted()) h.ids.push_back(a.order_id);
        } else if (dice < 56) {                            // FOK
            auto a = h.fast.limit(side, px, q, TimeInForce::FOK), b = h.ref.limit(side, px, q, TimeInForce::FOK);
            CHECK(same(a, b));
            if (a.accepted()) h.ids.push_back(a.order_id);
        } else if (dice < 62) {                            // post-only
            auto a = h.fast.limit(side, px, q, TimeInForce::GTC, true), b = h.ref.limit(side, px, q, TimeInForce::GTC, true);
            CHECK(same(a, b));
            if (a.accepted()) h.ids.push_back(a.order_id);
        } else if (dice < 70) {                            // market
            Quantity mq = uni(1, 60);
            auto a = h.fast.market(side, mq), b = h.ref.market(side, mq);
            CHECK(same(a, b));
            if (a.accepted()) h.ids.push_back(a.order_id);
        } else if (dice < 88) {                            // cancel (live, dead or bogus id)
            OrderId id = h.ids.empty() ? 1 : h.ids[static_cast<std::size_t>(uni(0, static_cast<std::int64_t>(h.ids.size()) - 1))];
            if (uni(0, 20) == 0) id = static_cast<OrderId>(uni(0, 1000000));
            CHECK_EQ(h.fast.cancel(id), h.ref.cancel(id));
        } else if (dice < 94) {                            // reduce
            if (h.ids.empty()) continue;
            OrderId id = h.ids[static_cast<std::size_t>(uni(0, static_cast<std::int64_t>(h.ids.size()) - 1))];
            Quantity nq = uni(-1, 25);
            CHECK(h.fast.reduce(id, nq) == h.ref.reduce(id, nq));
        } else {                                           // replace
            if (h.ids.empty()) continue;
            OrderId id = h.ids[static_cast<std::size_t>(uni(0, static_cast<std::int64_t>(h.ids.size()) - 1))];
            auto a = h.fast.replace(id, px, q), b = h.ref.replace(id, px, q);
            CHECK(same(a, b));
            if (a.accepted()) h.ids.push_back(a.order_id);
        }
        ++h.ops;
        h.compare_state(i % 2000 == 0);
        if (check::Registry::get().failures > 20) { std::fprintf(stderr, "    seed %llu, op %zu\n", (unsigned long long)seed, i); return; }
    }
    h.compare_state(true);

    // Per-order cross-check of find_order for every id ever seen.
    for (OrderId id : h.ids) {
        auto a = h.fast.find_order(id), b = h.ref.find_order(id);
        CHECK(a.has_value() == b.has_value());
        if (a && b) CHECK(a->side == b->side && a->price == b->price && a->remaining == b->remaining);
    }
}

}  // namespace

TEST_CASE(differential_tight_band_heavy_crossing) {
    for (std::uint64_t seed = 1; seed <= 12; ++seed) run(seed, 40000, 1, 2000, 995, 1005);
}

TEST_CASE(differential_wide_band_deep_book) {
    for (std::uint64_t seed = 100; seed < 106; ++seed) run(seed, 40000, 1, 5000, 800, 1200);
}

TEST_CASE(differential_tiny_range_boundary_stress) {
    for (std::uint64_t seed = 200; seed < 210; ++seed) run(seed, 30000, 1, 70, 1, 70);   // spans a bitmap word boundary
}

TEST_CASE(differential_offset_min_price) {
    for (std::uint64_t seed = 300; seed < 304; ++seed) run(seed, 30000, 9000, 11000, 9990, 10010);
}
