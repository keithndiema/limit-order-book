#pragma once
/// High-performance limit order book (price-time priority).
///
/// Layout (see docs/DESIGN.md):
///   * one dense array of price levels per side, indexed by (price - min_price)
///   * a bitmap over non-empty levels -> best bid/ask in O(words) with ctz/clz
///   * every order is a node in a slab, linked into its level's FIFO queue
///     (intrusive doubly-linked list) -> O(1) insert, O(1) cancel, O(1) top-of-book
///   * order ids are dense, so id -> slot is a plain vector lookup (no hashing)
///
/// Not thread-safe: one writer thread, as in a real matching engine.

#include "lob/types.hpp"

#include <limits>
#include <optional>
#include <vector>

namespace lob {

class OrderBook {
public:
    /// Valid prices are the integer ticks in [min_price, max_price].
    explicit OrderBook(Price min_price = 1, Price max_price = 65535);

    // ---- order entry ------------------------------------------------------
    SubmitResult submit(const OrderRequest& req);

    SubmitResult limit(Side s, Price p, Quantity q,
                       TimeInForce tif = TimeInForce::GTC, bool post_only = false) {
        return submit(OrderRequest::limit(s, p, q, tif, post_only));
    }
    SubmitResult market(Side s, Quantity q) { return submit(OrderRequest::market(s, q)); }

    /// Cancel a resting order. Returns false if the id is unknown / already gone.
    bool cancel(OrderId id);

    /// Reduce the size of a resting order, keeping its queue priority.
    /// new_qty must satisfy 0 < new_qty < remaining.
    RejectReason reduce(OrderId id, Quantity new_qty);

    /// Cancel/replace: loses queue priority, receives a fresh id. Validated before
    /// anything is cancelled, so a rejected replace leaves the original order intact.
    SubmitResult replace(OrderId id, Price new_price, Quantity new_qty);

    // ---- market data ------------------------------------------------------
    std::optional<Price> best_bid() const;
    std::optional<Price> best_ask() const;
    std::optional<double> mid_price() const;
    /// Size-weighted mid (a.k.a. microprice): leans toward the thinner side.
    std::optional<double> microprice() const;
    std::optional<Price> spread() const;

    std::vector<Level> bid_levels(std::size_t n = 10) const;
    std::vector<Level> ask_levels(std::size_t n = 10) const;
    Quantity depth_at(Side side, Price price) const;
    std::optional<OrderInfo> find_order(OrderId id) const;

    // ---- statistics -------------------------------------------------------
    std::size_t order_count() const noexcept { return resting_; }
    bool        empty() const noexcept { return resting_ == 0; }
    std::uint64_t total_trades() const noexcept { return total_trades_; }
    std::uint64_t total_volume() const noexcept { return total_volume_; }
    Price min_price() const noexcept { return min_price_; }
    Price max_price() const noexcept { return max_price_; }

    // ---- trade tape -------------------------------------------------------
    void set_record_tape(bool on) noexcept { record_tape_ = on; }
    const std::vector<Trade>& trades() const noexcept { return tape_; }
    std::vector<Trade> trades_since(std::size_t pos) const;

    void reset();

private:
    static constexpr std::uint32_t kNil = 0;
    static constexpr std::size_t kNpos = std::numeric_limits<std::size_t>::max();

    struct Bitmap {
        std::vector<std::uint64_t> words;
        std::size_t bits = 0;
        void init(std::size_t n) { bits = n; words.assign((n + 63) / 64, 0); }
        void set(std::size_t i) noexcept { words[i >> 6] |= (1ULL << (i & 63)); }
        void clear(std::size_t i) noexcept { words[i >> 6] &= ~(1ULL << (i & 63)); }
        std::size_t next_set(std::size_t i) const noexcept;  // first set bit >= i
        std::size_t prev_set(std::size_t i) const noexcept;  // last set bit  <= i
    };

    struct Node {
        Price         price = 0;
        Quantity      remaining = 0;
        OrderId       id = 0;
        std::uint32_t prev = kNil;
        std::uint32_t next = kNil;
        Side          side = Side::Buy;
    };

    struct LevelSlot {
        std::uint32_t head = kNil;
        std::uint32_t tail = kNil;
        std::uint32_t count = 0;
        Quantity      total = 0;
    };

    struct SideBook {
        std::vector<LevelSlot> levels;
        Bitmap                 occupied;
        std::size_t            best = kNpos;   // index of best level (kNpos when empty)
    };

    SideBook& side_book(Side s) noexcept { return s == Side::Buy ? bids_ : asks_; }
    const SideBook& side_book(Side s) const noexcept { return s == Side::Buy ? bids_ : asks_; }

    std::size_t idx_of(Price p) const noexcept { return static_cast<std::size_t>(p - min_price_); }
    Price price_of(std::size_t idx) const noexcept { return min_price_ + static_cast<Price>(idx); }

    std::uint32_t alloc_node();
    void free_node(std::uint32_t slot);
    void link_tail(SideBook& sb, std::size_t idx, std::uint32_t slot);
    void unlink(SideBook& sb, std::size_t idx, std::uint32_t slot);
    void refresh_best_after_empty(Side s, SideBook& sb, std::size_t idx);
    Quantity available_to(Side aggressor, Price limit, Quantity need) const;
    bool would_cross(Side s, Price p) const;
    void match(Side aggressor, Price limit, OrderId id, Timestamp ts, SubmitResult& res);
    std::vector<Level> levels_of(const SideBook& sb, bool descending, std::size_t n) const;

    Price min_price_, max_price_;
    SideBook bids_, asks_;
    std::vector<Node> nodes_;               // slab; index 0 is the nil sentinel
    std::vector<std::uint32_t> free_;       // recycled slab slots
    std::vector<std::uint32_t> slot_of_;    // order id -> slab slot (0 = not resting)
    std::vector<Trade> tape_;
    bool record_tape_ = true;

    OrderId       next_id_ = 1;
    Timestamp     clock_ = 0;
    std::size_t   resting_ = 0;
    std::uint64_t total_trades_ = 0;
    std::uint64_t total_volume_ = 0;
};

}  // namespace lob
