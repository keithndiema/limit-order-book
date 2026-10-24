#include "lob/order_book.hpp"

#include <algorithm>
#include <stdexcept>

#if defined(_MSC_VER)
#include <intrin.h>
#endif

namespace lob {

namespace {

inline unsigned ctz64(std::uint64_t x) noexcept {
#if defined(_MSC_VER)
    unsigned long i; _BitScanForward64(&i, x); return static_cast<unsigned>(i);
#else
    return static_cast<unsigned>(__builtin_ctzll(x));
#endif
}

inline unsigned clz64(std::uint64_t x) noexcept {
#if defined(_MSC_VER)
    unsigned long i; _BitScanReverse64(&i, x); return 63u - static_cast<unsigned>(i);
#else
    return static_cast<unsigned>(__builtin_clzll(x));
#endif
}

constexpr std::size_t kMaxLevels = std::size_t{1} << 22;  // ~200 MB worst case; plenty

}  // namespace

// ---------------------------------------------------------------- Bitmap ----

std::size_t OrderBook::Bitmap::next_set(std::size_t i) const noexcept {
    if (i >= bits) return kNpos;
    std::size_t wi = i >> 6;
    std::uint64_t x = words[wi] & (~0ULL << (i & 63));
    for (;;) {
        if (x) return (wi << 6) + ctz64(x);
        if (++wi >= words.size()) return kNpos;
        x = words[wi];
    }
}

std::size_t OrderBook::Bitmap::prev_set(std::size_t i) const noexcept {
    if (bits == 0) return kNpos;
    if (i >= bits) i = bits - 1;
    std::size_t wi = i >> 6;
    const unsigned b = static_cast<unsigned>(i & 63);
    std::uint64_t x = words[wi] & (b == 63 ? ~0ULL : ((1ULL << (b + 1)) - 1));
    for (;;) {
        if (x) return (wi << 6) + (63u - clz64(x));
        if (wi == 0) return kNpos;
        x = words[--wi];
    }
}

// ----------------------------------------------------------- construction ----

OrderBook::OrderBook(Price min_price, Price max_price)
    : min_price_(min_price), max_price_(max_price) {
    if (min_price < 1 || max_price < min_price)
        throw std::invalid_argument("OrderBook: need 1 <= min_price <= max_price");
    if (static_cast<std::size_t>(max_price - min_price) + 1 > kMaxLevels)
        throw std::invalid_argument("OrderBook: price range too wide (max 4,194,304 ticks)");
    reset();
}

void OrderBook::reset() {
    const std::size_t n = static_cast<std::size_t>(max_price_ - min_price_) + 1;
    for (SideBook* sb : {&bids_, &asks_}) {
        sb->levels.assign(n, LevelSlot{});
        sb->occupied.init(n);
        sb->best = kNpos;
    }
    nodes_.assign(1, Node{});          // slot 0 = nil sentinel
    free_.clear();
    slot_of_.assign(1, 0);             // id 0 is never used
    tape_.clear();
    next_id_ = 1;
    clock_ = 0;
    resting_ = 0;
    total_trades_ = 0;
    total_volume_ = 0;
}

// ------------------------------------------------------------ slab helpers ----

std::uint32_t OrderBook::alloc_node() {
    if (!free_.empty()) {
        std::uint32_t s = free_.back();
        free_.pop_back();
        return s;
    }
    nodes_.emplace_back();
    return static_cast<std::uint32_t>(nodes_.size() - 1);
}

void OrderBook::free_node(std::uint32_t slot) { free_.push_back(slot); }

void OrderBook::link_tail(SideBook& sb, std::size_t idx, std::uint32_t slot) {
    LevelSlot& L = sb.levels[idx];
    Node& n = nodes_[slot];
    n.prev = L.tail;
    n.next = kNil;
    if (L.tail != kNil) nodes_[L.tail].next = slot; else L.head = slot;
    L.tail = slot;
    ++L.count;
    L.total += n.remaining;
    if (L.count == 1) {
        sb.occupied.set(idx);
        if (sb.best == kNpos) sb.best = idx;
        else if (n.side == Side::Buy) { if (idx > sb.best) sb.best = idx; }
        else                          { if (idx < sb.best) sb.best = idx; }
    }
}

void OrderBook::refresh_best_after_empty(Side s, SideBook& sb, std::size_t idx) {
    if (sb.best != idx) return;
    if (s == Side::Buy) sb.best = (idx == 0) ? kNpos : sb.occupied.prev_set(idx - 1);
    else                sb.best = sb.occupied.next_set(idx + 1);
}

void OrderBook::unlink(SideBook& sb, std::size_t idx, std::uint32_t slot) {
    LevelSlot& L = sb.levels[idx];
    Node& n = nodes_[slot];
    if (n.prev != kNil) nodes_[n.prev].next = n.next; else L.head = n.next;
    if (n.next != kNil) nodes_[n.next].prev = n.prev; else L.tail = n.prev;
    --L.count;
    L.total -= n.remaining;
    if (L.count == 0) {
        sb.occupied.clear(idx);
        refresh_best_after_empty(n.side, sb, idx);
    }
}

// ----------------------------------------------------------------- queries ----

std::optional<Price> OrderBook::best_bid() const {
    return bids_.best == kNpos ? std::nullopt : std::optional<Price>{price_of(bids_.best)};
}
std::optional<Price> OrderBook::best_ask() const {
    return asks_.best == kNpos ? std::nullopt : std::optional<Price>{price_of(asks_.best)};
}
std::optional<Price> OrderBook::spread() const {
    if (bids_.best == kNpos || asks_.best == kNpos) return std::nullopt;
    return price_of(asks_.best) - price_of(bids_.best);
}
std::optional<double> OrderBook::mid_price() const {
    if (bids_.best == kNpos || asks_.best == kNpos) return std::nullopt;
    return 0.5 * (static_cast<double>(price_of(bids_.best)) + static_cast<double>(price_of(asks_.best)));
}
std::optional<double> OrderBook::microprice() const {
    if (bids_.best == kNpos || asks_.best == kNpos) return std::nullopt;
    const double bp = static_cast<double>(price_of(bids_.best));
    const double ap = static_cast<double>(price_of(asks_.best));
    const double bq = static_cast<double>(bids_.levels[bids_.best].total);
    const double aq = static_cast<double>(asks_.levels[asks_.best].total);
    return (bp * aq + ap * bq) / (bq + aq);
}

std::vector<Level> OrderBook::levels_of(const SideBook& sb, bool descending, std::size_t n) const {
    std::vector<Level> out;
    std::size_t idx = sb.best;
    while (idx != kNpos && out.size() < n) {
        const LevelSlot& L = sb.levels[idx];
        out.push_back(Level{price_of(idx), L.total, L.count});
        if (descending) idx = (idx == 0) ? kNpos : sb.occupied.prev_set(idx - 1);
        else            idx = sb.occupied.next_set(idx + 1);
    }
    return out;
}
std::vector<Level> OrderBook::bid_levels(std::size_t n) const { return levels_of(bids_, true, n); }
std::vector<Level> OrderBook::ask_levels(std::size_t n) const { return levels_of(asks_, false, n); }

Quantity OrderBook::depth_at(Side side, Price price) const {
    if (price < min_price_ || price > max_price_) return 0;
    return side_book(side).levels[idx_of(price)].total;
}

std::optional<OrderInfo> OrderBook::find_order(OrderId id) const {
    if (id == 0 || id >= slot_of_.size() || slot_of_[id] == 0) return std::nullopt;
    const Node& n = nodes_[slot_of_[id]];
    return OrderInfo{n.id, n.side, n.price, n.remaining};
}

std::vector<Trade> OrderBook::trades_since(std::size_t pos) const {
    if (pos >= tape_.size()) return {};
    return std::vector<Trade>(tape_.begin() + static_cast<std::ptrdiff_t>(pos), tape_.end());
}

// ---------------------------------------------------------------- matching ----

bool OrderBook::would_cross(Side s, Price p) const {
    if (s == Side::Buy) return asks_.best != kNpos && price_of(asks_.best) <= p;
    return bids_.best != kNpos && price_of(bids_.best) >= p;
}

Quantity OrderBook::available_to(Side aggressor, Price limit, Quantity need) const {
    const bool buy = aggressor == Side::Buy;
    const SideBook& opp = buy ? asks_ : bids_;
    Quantity sum = 0;
    std::size_t idx = opp.best;
    while (idx != kNpos) {
        const Price px = price_of(idx);
        if (buy ? px > limit : px < limit) break;
        sum += opp.levels[idx].total;
        if (sum >= need) return sum;
        idx = buy ? opp.occupied.next_set(idx + 1) : (idx == 0 ? kNpos : opp.occupied.prev_set(idx - 1));
    }
    return sum;
}

void OrderBook::match(Side aggressor, Price limit, OrderId id, Timestamp ts, SubmitResult& res) {
    const bool buy = aggressor == Side::Buy;
    SideBook& opp = buy ? asks_ : bids_;
    const Quantity original = res.remaining;
    Quantity remaining = original;

    while (remaining > 0 && opp.best != kNpos) {
        const std::size_t idx = opp.best;
        const Price px = price_of(idx);
        if (buy ? px > limit : px < limit) break;

        LevelSlot& L = opp.levels[idx];
        while (remaining > 0 && L.head != kNil) {
            Node& n = nodes_[L.head];
            const Quantity fill = std::min(remaining, n.remaining);

            Trade t;
            t.buy_order_id  = buy ? id : n.id;
            t.sell_order_id = buy ? n.id : id;
            t.price = px;
            t.quantity = fill;
            t.timestamp = ts;
            t.aggressor = aggressor;
            res.trades.push_back(t);
            if (record_tape_) tape_.push_back(t);

            remaining -= fill;
            n.remaining -= fill;
            L.total -= fill;
            ++total_trades_;
            total_volume_ += static_cast<std::uint64_t>(fill);

            if (n.remaining == 0) {
                const std::uint32_t slot = L.head;
                const OrderId rid = n.id;
                L.head = n.next;
                if (L.head != kNil) nodes_[L.head].prev = kNil; else L.tail = kNil;
                --L.count;
                slot_of_[rid] = 0;
                free_node(slot);
                --resting_;
            }
        }
        if (L.head == kNil) {
            opp.occupied.clear(idx);
            opp.best = buy ? opp.occupied.next_set(idx + 1)
                           : (idx == 0 ? kNpos : opp.occupied.prev_set(idx - 1));
        }
    }
    res.filled = original - remaining;
}

// ------------------------------------------------------------- order entry ----

SubmitResult OrderBook::submit(const OrderRequest& req) {
    SubmitResult res;
    res.remaining = req.quantity;
    auto reject = [&](RejectReason r) { res.reject = r; return res; };

    if (req.quantity <= 0) return reject(RejectReason::InvalidQuantity);

    const bool is_market = req.type == OrderType::Market;
    const bool buy = req.side == Side::Buy;
    Price limit;
    if (is_market) {
        if (req.post_only) return reject(RejectReason::InvalidFlags);
        limit = buy ? max_price_ : min_price_;
    } else {
        if (req.price <= 0) return reject(RejectReason::InvalidPrice);
        if (req.price < min_price_ || req.price > max_price_) return reject(RejectReason::PriceOutOfRange);
        limit = req.price;
    }
    TimeInForce tif = req.tif;
    if (is_market && tif == TimeInForce::GTC) tif = TimeInForce::IOC;   // markets never rest
    if (req.post_only && tif != TimeInForce::GTC) return reject(RejectReason::InvalidFlags);

    if (req.post_only && would_cross(req.side, limit)) return reject(RejectReason::PostOnlyWouldCross);
    if (tif == TimeInForce::FOK && available_to(req.side, limit, req.quantity) < req.quantity)
        return reject(RejectReason::FokNotFillable);

    const OrderId id = next_id_++;
    slot_of_.push_back(0);
    const Timestamp ts = req.timestamp ? req.timestamp : ++clock_;
    res.order_id = id;

    match(req.side, limit, id, ts, res);
    res.remaining = req.quantity - res.filled;

    if (res.remaining > 0 && tif == TimeInForce::GTC) {
        const std::uint32_t slot = alloc_node();
        Node& n = nodes_[slot];
        n.price = limit;
        n.remaining = res.remaining;
        n.id = id;
        n.side = req.side;
        slot_of_[id] = slot;
        link_tail(side_book(req.side), idx_of(limit), slot);
        ++resting_;
        res.resting = true;
    }
    return res;
}

bool OrderBook::cancel(OrderId id) {
    if (id == 0 || id >= slot_of_.size()) return false;
    const std::uint32_t slot = slot_of_[id];
    if (slot == 0) return false;
    const Node& n = nodes_[slot];
    unlink(side_book(n.side), idx_of(n.price), slot);
    slot_of_[id] = 0;
    free_node(slot);
    --resting_;
    return true;
}

RejectReason OrderBook::reduce(OrderId id, Quantity new_qty) {
    if (id == 0 || id >= slot_of_.size() || slot_of_[id] == 0) return RejectReason::UnknownOrder;
    Node& n = nodes_[slot_of_[id]];
    if (new_qty <= 0 || new_qty >= n.remaining) return RejectReason::InvalidModify;
    side_book(n.side).levels[idx_of(n.price)].total -= (n.remaining - new_qty);
    n.remaining = new_qty;
    return RejectReason::Accepted;
}

SubmitResult OrderBook::replace(OrderId id, Price new_price, Quantity new_qty) {
    SubmitResult res;
    res.remaining = new_qty;
    if (id == 0 || id >= slot_of_.size() || slot_of_[id] == 0) { res.reject = RejectReason::UnknownOrder; return res; }
    if (new_qty <= 0) { res.reject = RejectReason::InvalidQuantity; return res; }
    if (new_price <= 0) { res.reject = RejectReason::InvalidPrice; return res; }
    if (new_price < min_price_ || new_price > max_price_) { res.reject = RejectReason::PriceOutOfRange; return res; }
    const Side side = nodes_[slot_of_[id]].side;
    cancel(id);
    return submit(OrderRequest::limit(side, new_price, new_qty));
}

}  // namespace lob
