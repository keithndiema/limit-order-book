#include "check.hpp"
#include "lob/order_book.hpp"
#include "lob/reference_book.hpp"

#include <stdexcept>

using namespace lob;

TEST_BOTH(resting_orders_and_bbo) {
    Book b;
    auto r1 = b.limit(Side::Buy, 100, 10);
    auto r2 = b.limit(Side::Sell, 105, 5);
    CHECK(r1.accepted() && r1.resting && r1.order_id == 1);
    CHECK(r2.accepted() && r2.resting && r2.order_id == 2);
    CHECK_EQ(b.best_bid().value(), 100);
    CHECK_EQ(b.best_ask().value(), 105);
    CHECK_EQ(b.spread().value(), 5);
    CHECK(b.mid_price().value() == 102.5);
    CHECK_EQ(b.order_count(), 2u);
}

TEST_BOTH(full_match_leaves_empty_book) {
    Book b;
    auto maker = b.limit(Side::Sell, 100, 10);
    auto r = b.limit(Side::Buy, 100, 10);
    CHECK_EQ(r.filled, 10);
    CHECK_EQ(r.remaining, 0);
    CHECK(!r.resting);
    CHECK_EQ(r.trades.size(), 1u);
    CHECK_EQ(r.trades[0].sell_order_id, maker.order_id);
    CHECK_EQ(r.trades[0].buy_order_id, r.order_id);
    CHECK(!b.best_bid() && !b.best_ask());
    CHECK_EQ(b.total_trades(), 1u);
    CHECK_EQ(b.order_count(), 0u);
}

TEST_BOTH(partial_fill_rests_remainder_with_same_id) {
    Book b;
    b.limit(Side::Sell, 100, 6);
    auto r = b.limit(Side::Buy, 100, 10);
    CHECK_EQ(r.filled, 6);
    CHECK_EQ(r.remaining, 4);
    CHECK(r.resting);
    CHECK_EQ(b.best_bid().value(), 100);
    CHECK(!b.best_ask());
    // The id used in the trade is the id the order rests under.
    CHECK_EQ(r.trades[0].buy_order_id, r.order_id);
    auto info = b.find_order(r.order_id);
    CHECK(info.has_value());
    CHECK_EQ(info->remaining, 4);
}

TEST_BOTH(trade_executes_at_resting_price_and_sweeps_levels) {
    Book b;
    b.limit(Side::Sell, 100, 5);
    b.limit(Side::Sell, 101, 5);
    b.limit(Side::Sell, 103, 5);
    auto r = b.limit(Side::Buy, 102, 20);   // sweeps 100 and 101, stops before 103
    CHECK_EQ(r.trades.size(), 2u);
    CHECK_EQ(r.trades[0].price, 100);
    CHECK_EQ(r.trades[1].price, 101);
    CHECK_EQ(r.filled, 10);
    CHECK_EQ(r.remaining, 10);
    CHECK_EQ(b.best_bid().value(), 102);
    CHECK_EQ(b.best_ask().value(), 103);
}

TEST_BOTH(price_time_priority) {
    Book b;
    auto first  = b.limit(Side::Sell, 100, 5);
    auto second = b.limit(Side::Sell, 100, 5);
    auto r = b.limit(Side::Buy, 100, 5);
    CHECK_EQ(r.trades.size(), 1u);
    CHECK_EQ(r.trades[0].sell_order_id, first.order_id);       // earlier order fills first
    CHECK(!b.find_order(first.order_id).has_value());
    CHECK(b.find_order(second.order_id).has_value());
    // Better price beats earlier time.
    Book c;
    auto worse  = c.limit(Side::Sell, 101, 5);
    auto better = c.limit(Side::Sell, 100, 5);
    auto r2 = c.limit(Side::Buy, 101, 5);
    CHECK_EQ(r2.trades[0].sell_order_id, better.order_id);
    CHECK(c.find_order(worse.order_id).has_value());
}

TEST_BOTH(market_orders_never_rest) {
    Book b;
    b.limit(Side::Sell, 100, 5);
    b.limit(Side::Sell, 101, 5);
    auto r = b.market(Side::Buy, 8);
    CHECK_EQ(r.filled, 8);
    CHECK_EQ(r.remaining, 0);
    CHECK(!r.resting);
    auto r2 = b.market(Side::Buy, 100);     // only 2 left
    CHECK_EQ(r2.filled, 2);
    CHECK_EQ(r2.remaining, 98);
    CHECK(!r2.resting);
    CHECK(!b.best_bid() && !b.best_ask());
    auto r3 = b.market(Side::Sell, 5);      // empty book
    CHECK(r3.accepted());
    CHECK_EQ(r3.filled, 0);
}

TEST_BOTH(ioc_discards_remainder) {
    Book b;
    b.limit(Side::Sell, 100, 3);
    auto r = b.limit(Side::Buy, 100, 10, TimeInForce::IOC);
    CHECK_EQ(r.filled, 3);
    CHECK_EQ(r.remaining, 7);
    CHECK(!r.resting);
    CHECK(!b.best_bid());
}

TEST_BOTH(fok_is_all_or_nothing) {
    Book b;
    b.limit(Side::Sell, 100, 5);
    b.limit(Side::Sell, 101, 5);
    auto no = b.limit(Side::Buy, 101, 11, TimeInForce::FOK);
    CHECK(!no.accepted());
    CHECK(no.reject == RejectReason::FokNotFillable);
    CHECK_EQ(b.total_trades(), 0u);                    // nothing was touched
    CHECK_EQ(b.ask_levels(5).size(), 2u);
    auto no2 = b.limit(Side::Buy, 100, 6, TimeInForce::FOK);   // price limit blocks level 101
    CHECK(!no2.accepted());
    auto yes = b.limit(Side::Buy, 101, 10, TimeInForce::FOK);
    CHECK(yes.accepted());
    CHECK_EQ(yes.filled, 10);
    CHECK(!b.best_ask());
}

TEST_BOTH(post_only_rejects_instead_of_crossing) {
    Book b;
    b.limit(Side::Sell, 100, 5);
    auto r = b.limit(Side::Buy, 100, 5, TimeInForce::GTC, true);
    CHECK(r.reject == RejectReason::PostOnlyWouldCross);
    auto ok = b.limit(Side::Buy, 99, 5, TimeInForce::GTC, true);
    CHECK(ok.accepted() && ok.resting);
    auto bad = b.limit(Side::Buy, 98, 5, TimeInForce::IOC, true);
    CHECK(bad.reject == RejectReason::InvalidFlags);
}

TEST_BOTH(cancel_semantics) {
    Book b;
    auto a = b.limit(Side::Buy, 50, 20);
    auto c = b.limit(Side::Buy, 50, 10);
    CHECK(b.cancel(a.order_id));
    CHECK(!b.cancel(a.order_id));       // double cancel
    CHECK(!b.cancel(9999));             // unknown
    CHECK(!b.cancel(0));
    CHECK_EQ(b.bid_levels(1)[0].quantity, 10);
    CHECK(b.cancel(c.order_id));
    CHECK(!b.best_bid());
    CHECK_EQ(b.order_count(), 0u);
    auto f = b.limit(Side::Sell, 60, 5);
    b.limit(Side::Buy, 60, 5);          // fully filled
    CHECK(!b.cancel(f.order_id));       // cannot cancel a filled order
}

TEST_BOTH(cancel_best_level_exposes_next_best) {
    Book b;
    auto hi = b.limit(Side::Buy, 105, 1);
    b.limit(Side::Buy, 103, 1);
    b.limit(Side::Buy, 90, 1);
    CHECK_EQ(b.best_bid().value(), 105);
    b.cancel(hi.order_id);
    CHECK_EQ(b.best_bid().value(), 103);
    auto lo = b.limit(Side::Sell, 200, 1);
    auto lo2 = b.limit(Side::Sell, 150, 1);
    CHECK_EQ(b.best_ask().value(), 150);
    b.cancel(lo2.order_id);
    CHECK_EQ(b.best_ask().value(), 200);
    b.cancel(lo.order_id);
    CHECK(!b.best_ask());
}

TEST_BOTH(reduce_keeps_queue_priority) {
    Book b;
    auto first  = b.limit(Side::Sell, 100, 10);
    auto second = b.limit(Side::Sell, 100, 10);
    CHECK(b.reduce(first.order_id, 4) == RejectReason::Accepted);
    CHECK(b.reduce(first.order_id, 4) == RejectReason::InvalidModify);    // not a reduction
    CHECK(b.reduce(first.order_id, 0) == RejectReason::InvalidModify);
    CHECK(b.reduce(777, 1) == RejectReason::UnknownOrder);
    auto r = b.limit(Side::Buy, 100, 4);
    CHECK_EQ(r.trades.size(), 1u);
    CHECK_EQ(r.trades[0].sell_order_id, first.order_id);                  // still first in line
    CHECK_EQ(b.ask_levels(1)[0].quantity, 10);
    (void)second;
}

TEST_BOTH(replace_loses_priority_and_gets_new_id) {
    Book b;
    auto first  = b.limit(Side::Sell, 100, 5);
    auto second = b.limit(Side::Sell, 100, 5);
    auto rep = b.replace(first.order_id, 100, 5);
    CHECK(rep.accepted() && rep.resting);
    CHECK(rep.order_id != first.order_id);
    CHECK(!b.find_order(first.order_id).has_value());
    auto r = b.limit(Side::Buy, 100, 5);
    CHECK_EQ(r.trades[0].sell_order_id, second.order_id);                 // 'second' is now ahead
    // A rejected replace must leave the original untouched.
    auto keep = b.limit(Side::Buy, 90, 5);
    auto bad = b.replace(keep.order_id, 0, 5);
    CHECK(bad.reject == RejectReason::InvalidPrice);
    CHECK(b.find_order(keep.order_id).has_value());
    CHECK(b.replace(424242, 90, 1).reject == RejectReason::UnknownOrder);
}

TEST_BOTH(input_validation) {
    Book b(10, 20);
    CHECK(b.limit(Side::Buy, 100, 0).reject == RejectReason::InvalidQuantity);
    CHECK(b.limit(Side::Buy, 100, -5).reject == RejectReason::InvalidQuantity);
    CHECK(b.limit(Side::Buy, 0, 5).reject == RejectReason::InvalidPrice);
    CHECK(b.limit(Side::Buy, -3, 5).reject == RejectReason::InvalidPrice);
    CHECK(b.limit(Side::Buy, 9, 5).reject == RejectReason::PriceOutOfRange);
    CHECK(b.limit(Side::Buy, 21, 5).reject == RejectReason::PriceOutOfRange);
    CHECK(b.market(Side::Buy, 0).reject == RejectReason::InvalidQuantity);
    CHECK(b.limit(Side::Buy, 10, 1).accepted());   // inclusive bounds
    CHECK(b.limit(Side::Sell, 20, 1).accepted());
    CHECK_EQ(b.best_bid().value(), 10);
    CHECK_EQ(b.best_ask().value(), 20);
    auto r = b.market(Side::Buy, 1);               // sweeps to the top of the range
    CHECK_EQ(r.filled, 1);
    CHECK_EQ(r.trades[0].price, 20);
}

TEST_BOTH(rejected_orders_consume_no_id) {
    Book b;
    b.limit(Side::Buy, 100, 0);
    auto ok = b.limit(Side::Buy, 100, 1);
    CHECK_EQ(ok.order_id, 1u);
}

TEST_BOTH(levels_aggregate_quantity_and_count) {
    Book b;
    b.limit(Side::Buy, 100, 5);
    b.limit(Side::Buy, 100, 7);
    b.limit(Side::Buy, 98, 1);
    auto lv = b.bid_levels(10);
    CHECK_EQ(lv.size(), 2u);
    CHECK(lv[0] == (Level{100, 12, 2}));
    CHECK(lv[1] == (Level{98, 1, 1}));
    CHECK_EQ(b.bid_levels(1).size(), 1u);
}

// Bitmap word boundaries: levels at 63/64/65 ticks above min price, and scans across empty words.
TEST_BOTH(sparse_levels_across_bitmap_words) {
    Book b(1, 5000);
    const Price ps[] = {1, 63, 64, 65, 127, 128, 1000, 4999, 5000};
    for (Price p : ps) b.limit(Side::Buy, p, 1);
    auto lv = b.bid_levels(100);
    CHECK_EQ(lv.size(), 9u);
    CHECK_EQ(lv.front().price, 5000);
    CHECK_EQ(lv.back().price, 1);
    for (std::size_t i = 1; i < lv.size(); ++i) CHECK(lv[i - 1].price > lv[i].price);
    // Walk the book down by selling into it.
    for (Price p : {5000, 4999, 1000, 128, 127, 65, 64, 63, 1}) {
        CHECK_EQ(b.best_bid().value(), p);
        b.market(Side::Sell, 1);
    }
    CHECK(!b.best_bid());
}

TEST_CASE(order_book_slab_recycles_slots) {
    OrderBook b;
    for (int round = 0; round < 50; ++round) {
        std::vector<OrderId> ids;
        for (int i = 0; i < 200; ++i) ids.push_back(b.limit(Side::Buy, 1000 + (i % 7), 1).order_id);
        for (OrderId id : ids) CHECK(b.cancel(id));
        CHECK_EQ(b.order_count(), 0u);
    }
    CHECK(!b.best_bid());
}

TEST_CASE(microprice_leans_toward_thin_side) {
    OrderBook b;
    b.limit(Side::Buy, 100, 90);
    b.limit(Side::Sell, 102, 10);
    // Big bid, thin ask -> fair value closer to the ask.
    CHECK(b.microprice().value() > b.mid_price().value());
    CHECK(b.microprice().value() < 102.0);
}

TEST_CASE(reset_restores_pristine_state) {
    OrderBook b;
    b.limit(Side::Sell, 100, 5);
    b.limit(Side::Buy, 100, 5);
    b.reset();
    CHECK_EQ(b.total_trades(), 0u);
    CHECK(b.trades().empty());
    CHECK_EQ(b.limit(Side::Buy, 10, 1).order_id, 1u);
}

TEST_CASE(constructor_rejects_bad_ranges) {
    bool threw = false;
    try { OrderBook b(0, 10); } catch (const std::invalid_argument&) { threw = true; }
    CHECK(threw);
    threw = false;
    try { OrderBook b(10, 5); } catch (const std::invalid_argument&) { threw = true; }
    CHECK(threw);
}

