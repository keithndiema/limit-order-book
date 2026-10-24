#pragma once
/// Straightforward reference implementation (std::map + std::deque + hash map).
///
/// It exists for two reasons:
///   1. as the *oracle* in differential tests: the optimised OrderBook must agree with it
///      on every result of every operation, over millions of randomised operations;
///   2. as the baseline in the benchmarks, so the speed-up of the optimised design is measured,
///      not asserted.
/// Semantics are identical to lob::OrderBook; cancel is O(queue length) at the level.

#include "lob/types.hpp"

#include <algorithm>
#include <deque>
#include <functional>
#include <map>
#include <optional>
#include <unordered_map>
#include <vector>

namespace lob {

class ReferenceBook {
public:
    explicit ReferenceBook(Price min_price = 1, Price max_price = 65535)
        : min_price_(min_price), max_price_(max_price) {}

    SubmitResult submit(const OrderRequest& req) {
        SubmitResult res;
        res.remaining = req.quantity;
        if (req.quantity <= 0) { res.reject = RejectReason::InvalidQuantity; return res; }

        const bool is_market = req.type == OrderType::Market;
        const bool buy = req.side == Side::Buy;
        Price limit;
        if (is_market) {
            if (req.post_only) { res.reject = RejectReason::InvalidFlags; return res; }
            limit = buy ? max_price_ : min_price_;
        } else {
            if (req.price <= 0) { res.reject = RejectReason::InvalidPrice; return res; }
            if (req.price < min_price_ || req.price > max_price_) { res.reject = RejectReason::PriceOutOfRange; return res; }
            limit = req.price;
        }
        TimeInForce tif = req.tif;
        if (is_market && tif == TimeInForce::GTC) tif = TimeInForce::IOC;
        if (req.post_only && tif != TimeInForce::GTC) { res.reject = RejectReason::InvalidFlags; return res; }

        if (req.post_only) {
            if (buy ? (!asks_.empty() && asks_.begin()->first <= limit)
                    : (!bids_.empty() && bids_.begin()->first >= limit)) {
                res.reject = RejectReason::PostOnlyWouldCross; return res;
            }
        }
        if (tif == TimeInForce::FOK) {
            Quantity avail = 0;
            if (buy) { for (auto& [p, q] : asks_) { if (p > limit) break; for (auto& o : q) avail += o.remaining; } }
            else     { for (auto& [p, q] : bids_) { if (p < limit) break; for (auto& o : q) avail += o.remaining; } }
            if (avail < req.quantity) { res.reject = RejectReason::FokNotFillable; return res; }
        }

        const OrderId id = next_id_++;
        const Timestamp ts = req.timestamp ? req.timestamp : ++clock_;
        res.order_id = id;
        Quantity remaining = req.quantity;
        if (buy) match(asks_, true,  limit, id, ts, remaining, res);
        else     match(bids_, false, limit, id, ts, remaining, res);
        res.filled = req.quantity - remaining;
        res.remaining = remaining;

        if (remaining > 0 && tif == TimeInForce::GTC) {
            Rest r{id, remaining};
            if (buy) bids_[limit].push_back(r); else asks_[limit].push_back(r);
            index_[id] = {req.side, limit};
            res.resting = true;
        }
        return res;
    }

    SubmitResult limit(Side s, Price p, Quantity q, TimeInForce t = TimeInForce::GTC, bool post_only = false) {
        return submit(OrderRequest::limit(s, p, q, t, post_only));
    }
    SubmitResult market(Side s, Quantity q) { return submit(OrderRequest::market(s, q)); }

    bool cancel(OrderId id) {
        auto it = index_.find(id);
        if (it == index_.end()) return false;
        const auto [side, price] = it->second;
        auto erase_in = [&](auto& book) {
            auto lv = book.find(price);
            auto& q = lv->second;
            q.erase(std::find_if(q.begin(), q.end(), [&](const Rest& r) { return r.id == id; }));
            if (q.empty()) book.erase(lv);
        };
        if (side == Side::Buy) erase_in(bids_); else erase_in(asks_);
        index_.erase(it);
        return true;
    }

    RejectReason reduce(OrderId id, Quantity new_qty) {
        auto it = index_.find(id);
        if (it == index_.end()) return RejectReason::UnknownOrder;
        const auto [side, price] = it->second;
        Rest* r = find_rest(side, price, id);
        if (new_qty <= 0 || new_qty >= r->remaining) return RejectReason::InvalidModify;
        r->remaining = new_qty;
        return RejectReason::Accepted;
    }

    SubmitResult replace(OrderId id, Price new_price, Quantity new_qty) {
        SubmitResult res;
        res.remaining = new_qty;
        auto it = index_.find(id);
        if (it == index_.end()) { res.reject = RejectReason::UnknownOrder; return res; }
        if (new_qty <= 0) { res.reject = RejectReason::InvalidQuantity; return res; }
        if (new_price <= 0) { res.reject = RejectReason::InvalidPrice; return res; }
        if (new_price < min_price_ || new_price > max_price_) { res.reject = RejectReason::PriceOutOfRange; return res; }
        const Side side = it->second.first;
        cancel(id);
        return submit(OrderRequest::limit(side, new_price, new_qty));
    }

    std::optional<Price> best_bid() const { return bids_.empty() ? std::nullopt : std::optional<Price>{bids_.begin()->first}; }
    std::optional<Price> best_ask() const { return asks_.empty() ? std::nullopt : std::optional<Price>{asks_.begin()->first}; }
    std::optional<Price> spread() const {
        if (bids_.empty() || asks_.empty()) return std::nullopt;
        return asks_.begin()->first - bids_.begin()->first;
    }
    std::optional<double> mid_price() const {
        if (bids_.empty() || asks_.empty()) return std::nullopt;
        return 0.5 * (double(bids_.begin()->first) + double(asks_.begin()->first));
    }
    std::vector<Level> bid_levels(std::size_t n = 10) const { return levels(bids_, n); }
    std::vector<Level> ask_levels(std::size_t n = 10) const { return levels(asks_, n); }

    std::optional<OrderInfo> find_order(OrderId id) const {
        auto it = index_.find(id);
        if (it == index_.end()) return std::nullopt;
        const auto [side, price] = it->second;
        const Rest* r = find_rest(side, price, id);
        return OrderInfo{id, side, price, r->remaining};
    }

    std::size_t order_count() const { return index_.size(); }
    std::uint64_t total_trades() const { return total_trades_; }
    std::uint64_t total_volume() const { return total_volume_; }
    void set_record_tape(bool on) { record_tape_ = on; }
    const std::vector<Trade>& trades() const { return tape_; }

private:
    struct Rest { OrderId id; Quantity remaining; };
    using Queue = std::deque<Rest>;

    Rest* find_rest(Side side, Price price, OrderId id) const {
        auto& q = (side == Side::Buy) ? bids_.at(price) : asks_.at(price);
        for (auto& r : const_cast<Queue&>(q)) if (r.id == id) return &r;
        return nullptr;
    }

    template <class Book>
    void match(Book& opp, bool buy, Price limit, OrderId id, Timestamp ts, Quantity& remaining, SubmitResult& res) {
        while (remaining > 0 && !opp.empty()) {
            auto lv = opp.begin();
            const Price px = lv->first;
            if (buy ? px > limit : px < limit) break;
            Queue& q = lv->second;
            while (remaining > 0 && !q.empty()) {
                Rest& r = q.front();
                const Quantity fill = std::min(remaining, r.remaining);
                Trade t{buy ? id : r.id, buy ? r.id : id, px, fill, ts, buy ? Side::Buy : Side::Sell};
                res.trades.push_back(t);
                if (record_tape_) tape_.push_back(t);
                remaining -= fill;
                r.remaining -= fill;
                ++total_trades_;
                total_volume_ += static_cast<std::uint64_t>(fill);
                if (r.remaining == 0) { index_.erase(r.id); q.pop_front(); }
            }
            if (q.empty()) opp.erase(lv);
        }
    }

    template <class Book>
    static std::vector<Level> levels(const Book& b, std::size_t n) {
        std::vector<Level> out;
        for (const auto& [px, q] : b) {
            if (out.size() >= n) break;
            Quantity tot = 0;
            for (const auto& r : q) tot += r.remaining;
            out.push_back(Level{px, tot, q.size()});
        }
        return out;
    }

    Price min_price_, max_price_;
    std::map<Price, Queue, std::greater<Price>> bids_;
    std::map<Price, Queue, std::less<Price>> asks_;
    std::unordered_map<OrderId, std::pair<Side, Price>> index_;
    std::vector<Trade> tape_;
    bool record_tape_ = true;
    OrderId next_id_ = 1;
    Timestamp clock_ = 0;
    std::uint64_t total_trades_ = 0, total_volume_ = 0;
};

}  // namespace lob
