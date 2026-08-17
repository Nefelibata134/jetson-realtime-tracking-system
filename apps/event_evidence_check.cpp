#include <nlohmann/json.hpp>
#include <opencv2/imgcodecs.hpp>

#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

#include "edge_vision/event_evidence.hpp"

int main() {
    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() /
        "edge-vision-event-evidence-check";
    std::filesystem::remove_all(directory);

    edge_vision::Frame frame;
    frame.width = 320;
    frame.height = 180;
    frame.channels = 3;
    frame.format = edge_vision::PixelFormat::bgr8;
    frame.sequence = 31;
    frame.pts_ns = 1'033'333'323LL;
    frame.data.resize(frame.expected_bytes(), 48U);

    edge_vision::Track track;
    track.track_id = 5;
    track.box = {96.0F, 40.0F, 80.0F, 120.0F};
    track.class_id = 0;
    track.confidence = 0.91F;
    track.state = edge_vision::TrackState::Tracked;

    edge_vision::SafetyEvent event;
    event.type = edge_vision::SafetyEventType::RoiIntrusion;
    event.rule_id = "restricted-area";
    event.track_id = track.track_id;
    event.class_id = track.class_id;
    event.frame_sequence = frame.sequence;
    event.pts_ns = frame.pts_ns;
    event.anchor = {0.425F, 0.89F};

    auto record = edge_vision::make_event_record(
        event, "session-test", "file:synthetic", 0);

    edge_vision::EventEvidenceWriterConfig evidence_config;
    evidence_config.snapshot_directory = (directory / "snapshots").string();
    evidence_config.annotation.event_regions.push_back({{
        {0.25F, 0.20F},
        {0.75F, 0.20F},
        {0.75F, 0.95F},
        {0.25F, 0.95F},
    }});
    edge_vision::EventEvidenceWriter evidence_writer(evidence_config);
    record.evidence.snapshot_path =
        evidence_writer.write_snapshot(record, frame, {track});
    const std::string reused_path =
        evidence_writer.write_snapshot(record, frame, {track});

    edge_vision::JsonlEventJournal journal({
        (directory / "events.jsonl").string(),
    });
    const bool journal_written = journal.append(record);

    const cv::Mat snapshot = cv::imread(*record.evidence.snapshot_path);
    const bool snapshot_valid =
        !snapshot.empty() && snapshot.cols == frame.width &&
        snapshot.rows == frame.height;
    const auto stats = evidence_writer.stats();
    const bool reuse_valid =
        reused_path == *record.evidence.snapshot_path &&
        stats.snapshots_written == 1 && stats.snapshots_reused == 1;

    std::ifstream input(directory / "events.jsonl");
    std::string line;
    std::getline(input, line);
    const nlohmann::json serialized = nlohmann::json::parse(line);
    const bool path_linked =
        serialized.at("evidence").at("snapshot_path") ==
            *record.evidence.snapshot_path &&
        std::filesystem::exists(
            serialized.at("evidence").at("snapshot_path").get<std::string>());
    const bool passed =
        journal_written && snapshot_valid && reuse_valid && path_linked;

    std::cout << std::boolalpha;
    std::cout << "snapshot_valid=" << snapshot_valid << '\n';
    std::cout << "atomic_reuse=" << reuse_valid << '\n';
    std::cout << "journal_path_linked=" << path_linked << '\n';
    std::cout << "status=" << (passed ? "PASS" : "FAIL") << '\n';

    std::filesystem::remove_all(directory);
    return passed ? 0 : 1;
}
