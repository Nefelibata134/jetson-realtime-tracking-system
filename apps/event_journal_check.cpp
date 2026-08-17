#include <nlohmann/json.hpp>

#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "edge_vision/event_journal.hpp"

namespace {

edge_vision::SafetyEvent make_event(const std::uint64_t frame_sequence) {
    edge_vision::SafetyEvent event;
    event.type = edge_vision::SafetyEventType::LineCrossing;
    event.rule_id = "gate-\"east\"";
    event.track_id = 23;
    event.class_id = 0;
    event.frame_sequence = frame_sequence;
    event.pts_ns = static_cast<std::int64_t>(frame_sequence) * 33'333'333LL;
    event.anchor = {0.5F, 0.9F};
    event.direction = edge_vision::CrossingDirection::PositiveToNegative;
    return event;
}

}  // namespace

int main() {
    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() /
        "edge-vision-event-journal-check";
    const std::filesystem::path journal_path = directory / "events.jsonl";
    std::filesystem::remove_all(directory);

    const std::string session_id = "session-test";
    const auto first = edge_vision::make_event_record(
        make_event(131),
        session_id,
        "csi:0",
        2,
        {{"events/first.jpg"}, std::nullopt});
    const auto duplicate = edge_vision::make_event_record(
        make_event(131),
        session_id,
        "csi:0",
        2,
        {{"events/first.jpg"}, std::nullopt});
    const auto second = edge_vision::make_event_record(
        make_event(132), session_id, "csi:0", 2);

    bool first_written = false;
    bool duplicate_skipped = false;
    bool second_written = false;
    {
        edge_vision::JsonlEventJournal journal({journal_path.string()});
        first_written = journal.append(first);
        duplicate_skipped = !journal.append(duplicate);
        second_written = journal.append(second);
    }

    bool restart_duplicate_skipped = false;
    edge_vision::EventJournalStats restart_stats;
    {
        edge_vision::JsonlEventJournal journal({journal_path.string()});
        restart_duplicate_skipped = !journal.append(first);
        restart_stats = journal.stats();
    }

    std::ifstream input(journal_path);
    std::vector<nlohmann::json> records;
    std::string line;
    while (std::getline(input, line)) {
        if (!line.empty()) {
            records.push_back(nlohmann::json::parse(line));
        }
    }

    const bool valid_jsonl =
        records.size() == 2 &&
        records[0].at("schema_version") == "1.0" &&
        records[0].at("rule_id") == "gate-\"east\"" &&
        records[0].at("evidence").at("snapshot_path") ==
            "events/first.jpg" &&
        records[0].at("evidence").at("clip_path").is_null() &&
        records[1].at("frame_sequence") == 132;
    const bool persistent_dedup =
        restart_stats.records_loaded == 2 &&
        restart_stats.duplicates_skipped == 1;
    const bool passed = first_written && duplicate_skipped && second_written &&
                        restart_duplicate_skipped && valid_jsonl &&
                        persistent_dedup;

    std::cout << std::boolalpha;
    std::cout << "valid_jsonl=" << valid_jsonl << '\n';
    std::cout << "in_process_dedup=" << duplicate_skipped << '\n';
    std::cout << "restart_dedup=" << persistent_dedup << '\n';
    std::cout << "records=" << records.size() << '\n';
    std::cout << "status=" << (passed ? "PASS" : "FAIL") << '\n';

    std::filesystem::remove_all(directory);
    return passed ? 0 : 1;
}
