#pragma once
/// Core value types shared by every order-book implementation in this repo.

#include <cstddef>
#include <cstdint>
#include <vector>

namespace lob {

using Price     = std::int64_t;   ///< price in integer ticks (no floating point, ever)
using Quantity  = std::int64_t;   ///< size in lots
using OrderId   = std::uint64_t;  ///< 1-based, assigned to every *accepted* order
using Timestamp = std::uint64_t;  ///< logical clock by default (deterministic replays)

enum class Side : std::uint8_t { Buy = 0, Sell = 1 };
enum class OrderType : std::uint8_t { Limit = 0, Market = 1 };

/// Time-in-force. GTC rests its remainder; IOC cancels it; FOK fills entirely or not at all.
enum class TimeInForce : std::uint8_t { GTC = 0, IOC = 1, FOK = 2 };

enum class RejectReason : std::uint8_t {
    Accepted = 0,
    InvalidQuantity,
    InvalidPrice,
    PriceOutOfRange,
    InvalidFlags,
    PostOnlyWouldCross,
    FokNotFillable,
    UnknownOrder,
    InvalidModify,
};

const char* to_string(RejectReason r) noexcept;

struct OrderRequest {
    Side        side     = Side::Buy;
    OrderType   type     = OrderType::Limit;
    Price       price    = 0;          ///< ignored for market orders
    Quantity    quantity = 0;
    TimeInForce tif      = TimeInForce::GTC;
    bool        post_only = false;     ///< reject instead of crossing the spread
    Timestamp   timestamp = 0;         ///< 0 = assign from the book's logical clock

    static OrderRequest limit(Side s, Price p, Quantity q,
                              TimeInForce t = TimeInForce::GTC, bool post_only = false) {
        OrderRequest r;
        r.side = s; r.type = OrderType::Limit; r.price = p; r.quantity = q;
        r.tif = t; r.post_only = post_only;
        return r;
    }
    static OrderRequest market(Side s, Quantity q) {
        OrderRequest r;
        r.side = s; r.type = OrderType::Market; r.quantity = q; r.tif = TimeInForce::IOC;
        return r;
    }
};

struct Trade {
    OrderId   buy_order_id  = 0;
    OrderId   sell_order_id = 0;
    Price     price         = 0;   ///< always the *resting* order's price
    Quantity  quantity      = 0;
    Timestamp timestamp     = 0;
    Side      aggressor     = Side::Buy;

    bool operator==(const Trade& o) const noexcept {
        return buy_order_id == o.buy_order_id && sell_order_id == o.sell_order_id &&
               price == o.price && quantity == o.quantity && timestamp == o.timestamp &&
               aggressor == o.aggressor;
    }
};

struct Level {
    Price    price       = 0;
    Quantity quantity    = 0;
    std::size_t order_count = 0;

    bool operator==(const Level& o) const noexcept {
        return price == o.price && quantity == o.quantity && order_count == o.order_count;
    }
};

struct OrderInfo {
    OrderId  id        = 0;
    Side     side      = Side::Buy;
    Price    price     = 0;
    Quantity remaining = 0;
};

struct SubmitResult {
    OrderId            order_id  = 0;   ///< id of the accepted order (0 if rejected); stable across fills
    std::vector<Trade> trades;
    Quantity           filled    = 0;
    Quantity           remaining = 0;   ///< unfilled quantity (resting, or discarded for IOC/market)
    bool               resting   = false;
    RejectReason       reject    = RejectReason::Accepted;

    bool accepted() const noexcept { return reject == RejectReason::Accepted; }
};

}  // namespace lob
