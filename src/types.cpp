#include "lob/types.hpp"

namespace lob {

const char* to_string(RejectReason r) noexcept {
    switch (r) {
        case RejectReason::Accepted:           return "Accepted";
        case RejectReason::InvalidQuantity:    return "InvalidQuantity";
        case RejectReason::InvalidPrice:       return "InvalidPrice";
        case RejectReason::PriceOutOfRange:    return "PriceOutOfRange";
        case RejectReason::InvalidFlags:       return "InvalidFlags";
        case RejectReason::PostOnlyWouldCross: return "PostOnlyWouldCross";
        case RejectReason::FokNotFillable:     return "FokNotFillable";
        case RejectReason::UnknownOrder:       return "UnknownOrder";
        case RejectReason::InvalidModify:      return "InvalidModify";
    }
    return "?";
}

}  // namespace lob
