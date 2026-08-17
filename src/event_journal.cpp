#include "edge_vision/event_journal.hpp"

#include <nlohmann/json.hpp>

#include <chrono>
#include <cmath>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <random>
#include <sstream>
#include <stdexcept>
#include <unordered_set>
#include <utility>

namespace edge_vision {
namespace {

using Json = nlohmann::json;

const char* event_type_name(const SafetyEventType type) {
    switch (type) {
        case SafetyEventType::RoiIntrusion:
            return "roi_intrusion";
        case SafetyEventType::LineCrossing:
            return "line_crossing";
        case SafetyEventType::Dwell:
            return "dwell";
    }
    throw std::invalid_argument("unknown safety event type");
}

const char* direction_name(const CrossingDirection direction) {
    switch (direction) {
        case CrossingDirection::None:
            return "none";
        case CrossingDirection::NegativeToPositive:
            return "negative_to_positive";
        case CrossingDirection::PositiveToNegative:
            return "positive_to_negative";
    }
    throw std::invalid_argument("unknown crossing direction");
}

std::string utc_timestamp(
    const std::chrono::system_clock::time_point time_point,
    const bool compact) {
    const auto milliseconds = std::chrono::duration_cast<
        std::chrono::milliseconds>(time_point.time_since_epoch());
    const std::time_t time = std::chrono::system_clock::to_time_t(time_point);
    std::tm utc{};
    if (gmtime_r(&time, &utc) == nullptr) {
        throw std::runtime_error("failed to convert event timestamp to UTC");
    }

    std::ostringstream output;
    output << std::put_time(
        &utc,
        compact ? "%Y%m%dT%H%M%S" : "%Y-%m-%dT%H:%M:%S");
    output << '.' << std::setw(3) << std::setfill('0')
           << milliseconds.count() % 1000 << 'Z';
    return output.str();
}

std::uint64_t fnv1a(const std::string& value) {
    std::uint64_t hash = 14'695'981'039'346'656'037ULL;
    for (const unsigned char byte : value) {
        hash ^= byte;
        hash *= 1'099'511'628'211ULL;
    }
    return hash;
}

std::string make_event_id(
    const SafetyEvent& event,
    const std::string& session_id,
    const std::string& source_id,
    const std::uint64_t stream_generation) {
    std::ostringstream identity;
    identity << session_id << '\x1f' << source_id << '\x1f'
             << stream_generation << '\x1f' << event_type_name(event.type)
             << '\x1f' << event.rule_id << '\x1f' << event.track_id
             << '\x1f' << event.class_id << '\x1f'
             << event.frame_sequence;

    std::ostringstream output;
    output << "evt-" << std::hex << std::setw(16) << std::setfill('0')
           << fnv1a(identity.str());
    return output.str();
}

Json optional_path(const std::optional<std::string>& path) {
    return path.has_value() ? Json(*path) : Json(nullptr);
}

Json to_json(const EventRecord& record) {
    return {
        {"schema_version", record.schema_version},
        {"event_id", record.event_id},
        {"session_id", record.session_id},
        {"source_id", record.source_id},
        {"stream_generation", record.stream_generation},
        {"recorded_at_utc", record.recorded_at_utc},
        {"event_type", event_type_name(record.event.type)},
        {"rule_id", record.event.rule_id},
        {"track_id", record.event.track_id},
        {"class_id", record.event.class_id},
        {"frame_sequence", record.event.frame_sequence},
        {"pts_ns", record.event.pts_ns},
        {"anchor", {
            {"x", record.event.anchor.x},
            {"y", record.event.anchor.y},
        }},
        {"direction", direction_name(record.event.direction)},
        {"evidence", {
            {"snapshot_path", optional_path(record.evidence.snapshot_path)},
            {"clip_path", optional_path(record.evidence.clip_path)},
        }},
    };
}

void validate_record(const EventRecord& record) {
    if (record.schema_version.empty() || record.event_id.empty() ||
        record.session_id.empty() || record.source_id.empty() ||
        record.recorded_at_utc.empty() || record.event.rule_id.empty()) {
        throw std::invalid_argument(
            "event record identity fields must not be empty");
    }
    if (!std::isfinite(record.event.anchor.x) ||
        !std::isfinite(record.event.anchor.y)) {
        throw std::invalid_argument("event anchor must be finite");
    }
}

}  // namespace

std::string make_event_session_id() {
    std::random_device random;
    const std::uint32_t suffix = random();
    std::ostringstream output;
    output << utc_timestamp(std::chrono::system_clock::now(), true) << '-'
           << std::hex << std::setw(8) << std::setfill('0') << suffix;
    return output.str();
}

EventRecord make_event_record(
    const SafetyEvent& event,
    const std::string& session_id,
    const std::string& source_id,
    const std::uint64_t stream_generation,
    EventEvidence evidence) {
    EventRecord record;
    record.event_id =
        make_event_id(event, session_id, source_id, stream_generation);
    record.session_id = session_id;
    record.source_id = source_id;
    record.stream_generation = stream_generation;
    record.recorded_at_utc =
        utc_timestamp(std::chrono::system_clock::now(), false);
    record.event = event;
    record.evidence = std::move(evidence);
    validate_record(record);
    return record;
}

class JsonlEventJournal::Impl {
public:
    explicit Impl(EventJournalConfig config)
        : config_(std::move(config)) {
        if (config_.output_path.empty()) {
            throw std::invalid_argument(
                "event journal output path must not be empty");
        }

        const std::filesystem::path path(config_.output_path);
        if (path.has_parent_path()) {
            std::filesystem::create_directories(path.parent_path());
        }
        load_existing(path);
        output_.open(path, std::ios::out | std::ios::app);
        if (!output_) {
            throw std::runtime_error(
                "failed to open event journal: " + config_.output_path);
        }
    }

    [[nodiscard]] bool append(const EventRecord& record) {
        validate_record(record);
        if (event_ids_.find(record.event_id) != event_ids_.end()) {
            ++stats_.duplicates_skipped;
            return false;
        }

        output_ << to_json(record).dump() << '\n';
        output_.flush();
        if (!output_) {
            throw std::runtime_error(
                "failed to append event journal: " + config_.output_path);
        }
        event_ids_.insert(record.event_id);
        ++stats_.records_written;
        return true;
    }

    [[nodiscard]] EventJournalStats stats() const noexcept {
        return stats_;
    }

    [[nodiscard]] const std::string& output_path() const noexcept {
        return config_.output_path;
    }

private:
    void load_existing(const std::filesystem::path& path) {
        if (!std::filesystem::exists(path)) {
            return;
        }

        std::ifstream input(path);
        if (!input) {
            throw std::runtime_error(
                "failed to read existing event journal: " + path.string());
        }

        std::string line;
        std::uint64_t line_number = 0;
        while (std::getline(input, line)) {
            ++line_number;
            if (line.empty()) {
                continue;
            }
            try {
                const Json record = Json::parse(line);
                const std::string event_id = record.at("event_id").get<std::string>();
                if (event_id.empty() || !event_ids_.insert(event_id).second) {
                    throw std::runtime_error("duplicate or empty event_id");
                }
                ++stats_.records_loaded;
            } catch (const std::exception& error) {
                throw std::runtime_error(
                    "invalid event journal line " +
                    std::to_string(line_number) + ": " + error.what());
            }
        }
    }

    EventJournalConfig config_;
    std::ofstream output_;
    std::unordered_set<std::string> event_ids_;
    EventJournalStats stats_;
};

JsonlEventJournal::JsonlEventJournal(EventJournalConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}

JsonlEventJournal::~JsonlEventJournal() = default;

bool JsonlEventJournal::append(const EventRecord& record) {
    return impl_->append(record);
}

EventJournalStats JsonlEventJournal::stats() const noexcept {
    return impl_->stats();
}

const std::string& JsonlEventJournal::output_path() const noexcept {
    return impl_->output_path();
}

}  // namespace edge_vision
