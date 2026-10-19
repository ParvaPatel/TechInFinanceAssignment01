// This file was generated with the help of Claude Code.
//
// Pre-trade risk checks.
//
// Safety first: a quote must never go out if anything is wrong. Every check
// returns a RiskError, which is [[nodiscard]], so a caller that ignores the
// result gets a compiler warning; the quoting code returns as soon as a check
// fails. The failures are routine (an empty side of the book, a side blocked
// by the position limit, every message after a halt), so they are returned
// as values: a thrown exception costs microseconds each time.
#pragma once

#include <cstdint>

#include "app/config.h"
#include "app/strategy/pricing.h"

namespace app {

enum class [[nodiscard]] RiskError : std::uint8_t {
    None,               // the check passed
    BookInvalid,        // per tick: a side is empty or the book is crossed
    SequenceGap,        // standing, latched: a feed message was missed
    PositionLimit,      // per order: this side would exceed the position limit
    LossLimitBreached,  // standing, latched: detected on the timer
};

inline bool IsStanding(RiskError error) {
    return error == RiskError::SequenceGap || error == RiskError::LossLimitBreached;
}

// The reason written to the decision log when a standing condition halts quoting.
inline const char* Describe(RiskError error) {
    switch (error) {
        case RiskError::None:
            return "ok";
        case RiskError::BookInvalid:
            return "book side empty or crossed";
        case RiskError::SequenceGap:
            return "market data sequence gap";
        case RiskError::PositionLimit:
            return "position limit";
        case RiskError::LossLimitBreached:
            return "loss limit breached";
    }
    return "unknown";
}

class RiskGate {
public:
    void LatchSequenceGap() { sequence_gap_ = true; }
    void LatchLossLimit() { loss_limit_breached_ = true; }
    bool Halted() const { return sequence_gap_ || loss_limit_breached_; }

    // Standing conditions: once latched, nothing is quoted for the rest of the run.
    RiskError CheckStanding() const {
        if (sequence_gap_) {
            return RiskError::SequenceGap;
        }
        if (loss_limit_breached_) {
            return RiskError::LossLimitBreached;
        }
        return RiskError::None;
    }

    // Also guards the division in CalcMicroprice.
    static RiskError CheckBook(const BookTop& top) {
        return top.Valid() ? RiskError::None : RiskError::BookInvalid;
    }

    // A new or replacement quote of kQuoteShares on `side` must not be able to
    // take the position past the limit. With one order per side, the order
    // being replaced is superseded, so it isn't counted.
    static RiskError CheckPosition(sim::Side side, std::int64_t position) {
        const bool breach = side == sim::Side::Buy ? position + kQuoteShares > kPositionLimit
                                                   : position - kQuoteShares < -kPositionLimit;
        return breach ? RiskError::PositionLimit : RiskError::None;
    }

private:
    bool sequence_gap_ = false;
    bool loss_limit_breached_ = false;
};

}  // namespace app
