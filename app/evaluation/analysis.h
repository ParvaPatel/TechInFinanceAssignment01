// This file was generated with the help of Claude Code.
//
// Latency report.
//
// The headline figure is tick-to-trade: for every order sent while handling a
// market data message, the time from that message reaching the application
// (the capture tap's callback-entry stamp) to the order leaving it (the tap's
// Send stamp). Both timestamps are taken outside the application.
//
// Everything else is reported on its own rows, never blended into that
// figure: orders sent while handling an execution report or a timer tick, and
// handler times (callback entry to the handler's completion record in the
// latency log), split by whether the delivery sent an order. Every row is a
// distribution (count, mean, nearest-rank percentiles), not just an average.
//
// The first two lines are the original report, kept for comparison: the mean
// handler time over every delivery.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <map>
#include <ostream>
#include <utility>
#include <vector>

#include "app/evaluation/latency_log.h"
#include "sim/messages/execution_report.h"
#include "sim/messages/market_data.h"
#include "sim/runtime/capture.h"

namespace app {

// Prints one row of the report: count, mean, min, p50, p90, p99 and max of
// `ns`, in nanoseconds. Sorts `ns`.
inline void PrintDistribution(const char* label, std::vector<double>& ns, std::ostream& out) {
    char row[160];
    if (ns.empty()) {
        std::snprintf(row, sizeof(row), "%-28s %6d\n", label, 0);
        out << row;
        return;
    }
    std::sort(ns.begin(), ns.end());
    double total = 0;
    for (const double v : ns) {
        total += v;
    }
    // Nearest rank: the smallest sample with at least a fraction p of all
    // samples at or below it. With fewer than 100 samples, p99 is the max.
    const auto percentile = [&](double p) {
        const auto rank = static_cast<std::size_t>(std::ceil(p * static_cast<double>(ns.size())));
        return ns[std::max<std::size_t>(rank, 1) - 1];
    };
    std::snprintf(row, sizeof(row), "%-28s %6zu %8.0f %8.0f %8.0f %8.0f %8.0f %8.0f\n", label,
                  ns.size(), total / static_cast<double>(ns.size()), ns.front(), percentile(0.50),
                  percentile(0.90), percentile(0.99), ns.back());
    out << row;
}

inline void PrintLatencyReport(const sim::Capture& capture, const LatencyLog& log,
                               std::ostream& out) {
    std::map<std::pair<sim::DeliveryKind, std::uint64_t>, sim::WallTime> completed;
    for (const LatencyRecord& r : log.records()) {
        completed[{r.kind, r.key}] = r.completed;
    }

    // Order latency, from the tap alone: Send stamp minus the entry stamp of
    // the delivery being handled, grouped by what kind of delivery that was.
    std::vector<bool> sent_order(capture.deliveries.size(), false);
    std::vector<double> tick_to_trade;
    std::vector<double> after_report;
    std::vector<double> after_timer;
    for (const sim::SendRecord& s : capture.sends) {
        if (s.delivery_index >= capture.deliveries.size()) {
            continue;  // only if a callback threw before its delivery was recorded
        }
        const sim::DeliveryRecord& d = capture.deliveries[s.delivery_index];
        sent_order[s.delivery_index] = true;
        const auto ns = static_cast<double>(s.time - d.entry);
        switch (d.kind) {
            case sim::DeliveryKind::MarketData:
                tick_to_trade.push_back(ns);
                break;
            case sim::DeliveryKind::ExecutionReport:
                after_report.push_back(ns);
                break;
            case sim::DeliveryKind::Timer:
                after_timer.push_back(ns);
                break;
        }
    }

    // Handler time: the latency log's completion stamp minus the tap's entry stamp.
    double total_ns = 0;
    std::uint64_t count = 0;
    std::vector<double> handler_sent;
    std::vector<double> handler_md;
    std::vector<double> handler_report;
    std::vector<double> handler_timer;
    for (const sim::DeliveryRecord& d : capture.deliveries) {
        std::uint64_t key = d.sim_time;
        const auto bytes = d.packet.view();
        if (d.kind == sim::DeliveryKind::MarketData) {
            key = sim::Decode<sim::md::Header>(bytes.first(sizeof(sim::md::Header))).sequence;
        } else if (d.kind == sim::DeliveryKind::ExecutionReport) {
            key = sim::Decode<sim::oe::ReportHeader>(bytes.first(sizeof(sim::oe::ReportHeader)))
                      .sequence;
        }
        const auto it = completed.find({d.kind, key});
        if (it == completed.end()) {
            continue;
        }
        const auto ns = static_cast<double>(it->second - d.entry);
        total_ns += ns;
        ++count;
        if (sent_order[d.index]) {
            handler_sent.push_back(ns);
        } else if (d.kind == sim::DeliveryKind::MarketData) {
            handler_md.push_back(ns);
        } else if (d.kind == sim::DeliveryKind::ExecutionReport) {
            handler_report.push_back(ns);
        } else {
            handler_timer.push_back(ns);
        }
    }

    out << "messages: " << count << '\n';
    out << "average latency: " << (count > 0 ? total_ns / static_cast<double>(count) : 0.0)
        << " ns  (original metric: mean handler time over every delivery)\n\n";

    char header[160];
    std::snprintf(header, sizeof(header), "%-28s %6s %8s %8s %8s %8s %8s %8s\n", "(ns)", "count",
                  "mean", "min", "p50", "p90", "p99", "max");
    out << header;
    PrintDistribution("tick-to-trade (market data)", tick_to_trade, out);
    PrintDistribution("order after exec report", after_report, out);
    PrintDistribution("order after timer tick", after_timer, out);
    PrintDistribution("handler, sent an order", handler_sent, out);
    PrintDistribution("handler, no order: md", handler_md, out);
    PrintDistribution("handler, no order: report", handler_report, out);
    PrintDistribution("handler, no order: timer", handler_timer, out);
}

}  // namespace app
