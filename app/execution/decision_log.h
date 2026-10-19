// This file was generated with the help of Claude Code.
//
// Decision log.
//
// Every order is recorded *before* it is sent, so the log shows what we
// intended to have on the exchange. Recording copies a fixed-size entry into
// a buffer reserved before the run starts: no formatting and no I/O on the
// order path. The text is written off the order path by Flush(), which the
// timer calls, and by the destructor at the end of the run, in the same
// format and order as the entries were recorded.
//
// Like any buffered file output (stdio buffers too), entries not yet written
// are lost if the process dies. Here that is at most one timer interval.
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <vector>

#include "sim/messages/types.h"

namespace app {

class DecisionLog {
public:
    explicit DecisionLog(const std::string& path) : file_(std::fopen(path.c_str(), "w")) {
        if (file_ == nullptr) {
            throw std::runtime_error("DecisionLog: cannot open " + path);
        }
        entries_.reserve(kInitialCapacity);
    }
    ~DecisionLog() {
        Flush();
        std::fclose(file_);
    }
    DecisionLog(const DecisionLog&) = delete;
    DecisionLog& operator=(const DecisionLog&) = delete;

    // `action` must be a string literal: only the pointer is kept.
    void Record(sim::Timestamp now, const char* action, sim::Side side, sim::Price price,
                std::uint32_t shares, sim::Token token) {
        entries_.push_back({now, action, side, price, shares, token, {}});
    }

    void Note(sim::Timestamp now, const char* text) {
        entries_.push_back({now, nullptr, sim::Side::Buy, 0, 0, 0, text});
    }

    // Writes every entry recorded since the last flush. Not for the order path.
    void Flush() {
        for (const Entry& e : entries_) {
            if (e.action == nullptr) {
                std::fprintf(file_, "%llu %s\n", static_cast<unsigned long long>(e.now),
                             e.note.c_str());
                continue;
            }
            std::fprintf(file_, "%llu %s %c %lld.%04lld x %u token=%llu\n",
                         static_cast<unsigned long long>(e.now), e.action,
                         static_cast<char>(e.side),
                         static_cast<long long>(e.price / sim::kPriceScale),
                         static_cast<long long>(e.price % sim::kPriceScale), e.shares,
                         static_cast<unsigned long long>(e.token));
        }
        entries_.clear();
    }

private:
    // Entries per timer interval before the buffer has to grow.
    static constexpr std::size_t kInitialCapacity = 4096;

    struct Entry {
        sim::Timestamp now;
        const char* action;  // "ENTER" or "REPLACE"; nullptr for a note
        sim::Side side;
        sim::Price price;
        std::uint32_t shares;
        sim::Token token;
        std::string note;  // copied: a halt reason may not outlive the call
    };

    std::FILE* file_;
    std::vector<Entry> entries_;
};

}  // namespace app
