#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "lob/order_book.hpp"

namespace py = pybind11;
using namespace lob;

PYBIND11_MODULE(_core, m) {
    m.doc() = "C++ limit order book / matching engine (price-time priority)";

    // Enums accept plain ints too, so the pure-Python IntEnums in lob.types interoperate.
    py::enum_<Side>(m, "Side", py::arithmetic())
        .value("Buy", Side::Buy).value("Sell", Side::Sell);
    py::enum_<TimeInForce>(m, "TimeInForce", py::arithmetic())
        .value("GTC", TimeInForce::GTC).value("IOC", TimeInForce::IOC).value("FOK", TimeInForce::FOK);
    py::enum_<RejectReason>(m, "RejectReason", py::arithmetic())
        .value("Accepted", RejectReason::Accepted)
        .value("InvalidQuantity", RejectReason::InvalidQuantity)
        .value("InvalidPrice", RejectReason::InvalidPrice)
        .value("PriceOutOfRange", RejectReason::PriceOutOfRange)
        .value("InvalidFlags", RejectReason::InvalidFlags)
        .value("PostOnlyWouldCross", RejectReason::PostOnlyWouldCross)
        .value("FokNotFillable", RejectReason::FokNotFillable)
        .value("UnknownOrder", RejectReason::UnknownOrder)
        .value("InvalidModify", RejectReason::InvalidModify);
    py::implicitly_convertible<int, Side>();
    py::implicitly_convertible<int, TimeInForce>();
    py::implicitly_convertible<int, RejectReason>();

    py::class_<Trade>(m, "Trade")
        .def_readonly("buy_order_id", &Trade::buy_order_id)
        .def_readonly("sell_order_id", &Trade::sell_order_id)
        .def_readonly("price", &Trade::price)
        .def_readonly("quantity", &Trade::quantity)
        .def_readonly("timestamp", &Trade::timestamp)
        .def_property_readonly("aggressor", [](const Trade& t) { return static_cast<int>(t.aggressor); })
        .def("__repr__", [](const Trade& t) {
            return "Trade(buy=" + std::to_string(t.buy_order_id) + ", sell=" + std::to_string(t.sell_order_id) +
                   ", price=" + std::to_string(t.price) + ", qty=" + std::to_string(t.quantity) + ")";
        });

    py::class_<Level>(m, "Level")
        .def_readonly("price", &Level::price)
        .def_readonly("quantity", &Level::quantity)
        .def_readonly("order_count", &Level::order_count)
        .def("__repr__", [](const Level& l) {
            return "Level(price=" + std::to_string(l.price) + ", qty=" + std::to_string(l.quantity) +
                   ", orders=" + std::to_string(l.order_count) + ")";
        });

    py::class_<OrderInfo>(m, "OrderInfo")
        .def_readonly("id", &OrderInfo::id)
        .def_property_readonly("side", [](const OrderInfo& o) { return static_cast<int>(o.side); })
        .def_readonly("price", &OrderInfo::price)
        .def_readonly("remaining", &OrderInfo::remaining);

    py::class_<SubmitResult>(m, "SubmitResult")
        .def_readonly("order_id", &SubmitResult::order_id)
        .def_readonly("trades", &SubmitResult::trades)
        .def_readonly("filled", &SubmitResult::filled)
        .def_readonly("remaining", &SubmitResult::remaining)
        .def_readonly("resting", &SubmitResult::resting)
        .def_readonly("reject", &SubmitResult::reject)
        .def_property_readonly("accepted", &SubmitResult::accepted)
        .def("__repr__", [](const SubmitResult& r) {
            return std::string("SubmitResult(id=") + std::to_string(r.order_id) + ", filled=" +
                   std::to_string(r.filled) + ", remaining=" + std::to_string(r.remaining) +
                   ", resting=" + (r.resting ? "True" : "False") + ", reject=" + to_string(r.reject) + ")";
        });

    py::class_<OrderBook>(m, "OrderBook")
        .def(py::init<Price, Price>(), py::arg("min_price") = 1, py::arg("max_price") = 65535)
        .def("limit", &OrderBook::limit, py::arg("side"), py::arg("price"), py::arg("qty"),
             py::arg("tif") = TimeInForce::GTC, py::arg("post_only") = false)
        .def("market", &OrderBook::market, py::arg("side"), py::arg("qty"))
        .def("cancel", &OrderBook::cancel, py::arg("order_id"))
        .def("reduce", &OrderBook::reduce, py::arg("order_id"), py::arg("new_qty"))
        .def("replace", &OrderBook::replace, py::arg("order_id"), py::arg("price"), py::arg("qty"))
        .def("best_bid", &OrderBook::best_bid)
        .def("best_ask", &OrderBook::best_ask)
        .def("spread", &OrderBook::spread)
        .def("mid_price", &OrderBook::mid_price)
        .def("microprice", &OrderBook::microprice)
        .def("bid_levels", &OrderBook::bid_levels, py::arg("n") = 10)
        .def("ask_levels", &OrderBook::ask_levels, py::arg("n") = 10)
        .def("depth_at", &OrderBook::depth_at, py::arg("side"), py::arg("price"))
        .def("find_order", &OrderBook::find_order, py::arg("order_id"))
        .def("order_count", &OrderBook::order_count)
        .def("total_trades", &OrderBook::total_trades)
        .def("total_volume", &OrderBook::total_volume)
        .def("trade_count", [](const OrderBook& b) { return b.trades().size(); })
        .def("trades_since", &OrderBook::trades_since, py::arg("pos") = 0)
        .def("set_record_tape", &OrderBook::set_record_tape, py::arg("on"))
        .def("reset", &OrderBook::reset);
}
