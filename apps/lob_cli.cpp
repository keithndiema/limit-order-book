// lob_cli: replay an order file through the matching engine and print what happened.
//
//   lob_cli data/sample_orders.csv
//
// CSV columns: side,type,price,quantity,tif   (type: limit|market, tif: GTC|IOC|FOK; the last
// two are optional, and a 3-column "side,price,quantity" file is also accepted).

#include "lob/order_book.hpp"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

using namespace lob;

namespace {

std::vector<std::string> split(const std::string& line) {
    std::vector<std::string> out;
    std::string cell;
    std::stringstream ss(line);
    while (std::getline(ss, cell, ',')) {
        cell.erase(std::remove_if(cell.begin(), cell.end(),
                                  [](unsigned char c) { return c == '\r' || c == ' '; }),
                   cell.end());
        out.push_back(cell);
    }
    if (!line.empty() && line.back() == ',') out.emplace_back();
    return out;
}

std::string lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return s;
}

void print_ladder(const OrderBook& b, std::size_t depth) {
    auto asks = b.ask_levels(depth);
    auto bids = b.bid_levels(depth);
    std::cout << "\n  ASKS\n";
    for (auto it = asks.rbegin(); it != asks.rend(); ++it)
        std::cout << "    " << std::setw(8) << it->price << "  x " << std::setw(6) << it->quantity
                  << "  (" << it->order_count << " orders)\n";
    if (auto s = b.spread(); s && b.mid_price())
        std::cout << "  ---- spread " << *s << "  mid " << std::fixed << std::setprecision(1)
                  << *b.mid_price() << " ----\n";
    else
        std::cout << "  ---- one-sided / empty ----\n";
    for (const auto& l : bids)
        std::cout << "    " << std::setw(8) << l.price << "  x " << std::setw(6) << l.quantity
                  << "  (" << l.order_count << " orders)\n";
    std::cout << "  BIDS\n";
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) { std::cerr << "usage: lob_cli <orders.csv> [depth]\n"; return 2; }
    std::ifstream in(argv[1]);
    if (!in) { std::cerr << "cannot open " << argv[1] << "\n"; return 2; }
    const std::size_t depth = argc > 2 ? static_cast<std::size_t>(std::stoul(argv[2])) : 5;

    OrderBook book;
    std::string line;
    std::size_t row = 0, n = 0;
    while (std::getline(in, line)) {
        ++row;
        if (line.empty() || line[0] == '#') continue;
        auto c = split(line);
        const std::string first = lower(c[0]);
        if (first == "side") continue;  // header

        const Side side = (first == "buy" || first == "b") ? Side::Buy : Side::Sell;
        std::string type = "limit", tif = "gtc";
        Price price = 0;
        Quantity qty = 0;
        try {
            if (c.size() == 3) {
                price = std::stoll(c[1]);
                qty = std::stoll(c[2]);
            } else if (c.size() >= 4) {
                type = lower(c[1]);
                price = c[2].empty() ? 0 : std::stoll(c[2]);
                qty = std::stoll(c[3]);
                if (c.size() >= 5 && !c[4].empty()) tif = lower(c[4]);
            } else {
                std::cerr << "row " << row << ": expected 3-5 columns\n";
                continue;
            }
        } catch (const std::exception&) {
            std::cerr << "row " << row << ": unparsable number\n";
            continue;
        }

        const TimeInForce t = tif == "ioc" ? TimeInForce::IOC : tif == "fok" ? TimeInForce::FOK : TimeInForce::GTC;
        OrderRequest req = (type == "market") ? OrderRequest::market(side, qty)
                                              : OrderRequest::limit(side, price, qty, t);
        if (type == "market" && t == TimeInForce::FOK) req.tif = TimeInForce::FOK;

        const auto r = book.submit(req);
        std::cout << "#" << std::setw(2) << ++n << " " << (side == Side::Buy ? "BUY " : "SELL") << " "
                  << std::setw(6) << (type == "market" ? std::string("MKT") : std::to_string(price))
                  << " x" << std::setw(4) << qty << " " << tif << " -> ";
        if (!r.accepted()) {
            std::cout << "REJECTED (" << to_string(r.reject) << ")\n";
            continue;
        }
        std::cout << "id " << r.order_id << ", filled " << r.filled << ", "
                  << (r.resting ? "rests " : "unfilled ") << r.remaining << "\n";
        for (const auto& tr : r.trades)
            std::cout << "      TRADE " << tr.quantity << " @ " << tr.price << "  (buy#" << tr.buy_order_id
                      << " sell#" << tr.sell_order_id << ")\n";
    }
    print_ladder(book, depth);
    std::cout << "\n  " << book.total_trades() << " trades, volume " << book.total_volume() << ", "
              << book.order_count() << " resting orders\n";
    return 0;
}
