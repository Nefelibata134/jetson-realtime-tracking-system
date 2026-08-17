#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string>

#include "edge_vision/event_analytics.hpp"

namespace edge_vision {

struct EventEvidence {
    std::optional<std::string> snapshot_path;
    std::optional<std::string> clip_path;
};

struct EventRecord {
    std::string schema_version{"1.0"};
    std::string event_id;
    std::string session_id;
    std::string source_id;
    std::uint64_t stream_generation{0};
    std::string recorded_at_utc;
    SafetyEvent event;
    EventEvidence evidence;
};

struct EventJournalConfig {
    std::string output_path;
};

struct EventJournalStats {
    std::uint64_t records_loaded{0};
    std::uint64_t records_written{0};
    std::uint64_t duplicates_skipped{0};
};

[[nodiscard]] std::string make_event_session_id();

[[nodiscard]] EventRecord make_event_record(
    const SafetyEvent& event,
    const std::string& session_id,
    const std::string& source_id,
    std::uint64_t stream_generation,
    EventEvidence evidence = {});

class JsonlEventJournal final {
public:
    explicit JsonlEventJournal(EventJournalConfig config);
    ~JsonlEventJournal();

    JsonlEventJournal(const JsonlEventJournal&) = delete;
    JsonlEventJournal& operator=(const JsonlEventJournal&) = delete;

    [[nodiscard]] bool append(const EventRecord& record);
    [[nodiscard]] EventJournalStats stats() const noexcept;
    [[nodiscard]] const std::string& output_path() const noexcept;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace edge_vision
