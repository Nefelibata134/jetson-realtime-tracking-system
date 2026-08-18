#include <opencv2/videoio.hpp>

#include <cstdint>
#include <filesystem>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>

#include "edge_vision/event_clip_writer.hpp"

namespace {

edge_vision::Frame make_frame(const std::uint64_t sequence) {
    edge_vision::Frame frame;
    frame.width = 320;
    frame.height = 180;
    frame.channels = 3;
    frame.format = edge_vision::PixelFormat::bgr8;
    frame.sequence = sequence;
    frame.pts_ns = static_cast<std::int64_t>(sequence) * 100'000'000LL;
    frame.data.resize(
        frame.expected_bytes(), static_cast<std::uint8_t>(32 + sequence));
    return frame;
}

}  // namespace

int main() {
    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() /
        "edge-vision-event-clip-check";
    std::filesystem::remove_all(directory);

    edge_vision::SafetyEvent event;
    event.type = edge_vision::SafetyEventType::LineCrossing;
    event.rule_id = "exit-line";
    event.track_id = 5;
    event.class_id = 0;
    event.frame_sequence = 2;
    event.pts_ns = 200'000'000LL;
    event.anchor = {0.5F, 0.9F};
    auto record = edge_vision::make_event_record(
        event, "session-test", "file:synthetic", 0);

    edge_vision::EventClipWriterConfig config;
    config.output_directory = directory.string();
    config.frames_per_second = 10.0;
    config.pre_event_seconds = 0.2;
    config.post_event_seconds = 0.2;
    edge_vision::EventClipWriter writer(config);

    std::vector<edge_vision::EventRecord> completed;
    for (std::uint64_t sequence = 0; sequence < 5; ++sequence) {
        auto ready = writer.process(
            make_frame(sequence),
            {},
            sequence == 2 ? std::vector{record}
                          : std::vector<edge_vision::EventRecord>{});
        completed.insert(
            completed.end(),
            std::make_move_iterator(ready.begin()),
            std::make_move_iterator(ready.end()));
    }
    auto remaining = writer.finish();
    completed.insert(
        completed.end(),
        std::make_move_iterator(remaining.begin()),
        std::make_move_iterator(remaining.end()));

    bool clip_valid = completed.size() == 1 &&
                      completed.front().evidence.clip_path.has_value();
    int frame_count = 0;
    if (clip_valid) {
        cv::VideoCapture capture(*completed.front().evidence.clip_path);
        cv::Mat frame;
        while (capture.read(frame)) {
            ++frame_count;
        }
        clip_valid = frame_count == 5;
    }

    const auto stats = writer.stats();
    const bool bounded_buffer =
        stats.prebuffer_frames == 0 && stats.prebuffer_bytes == 0;
    const bool accounting_valid =
        stats.clips_started == 1 && stats.clips_completed == 1 &&
        stats.clips_skipped == 0 &&
        stats.encoding_queue_high_watermark == 1;
    const bool passed = clip_valid && bounded_buffer && accounting_valid;

    std::cout << std::boolalpha;
    std::cout << "clip_frames=" << frame_count << '\n';
    std::cout << "bounded_buffer=" << bounded_buffer << '\n';
    std::cout << "accounting_valid=" << accounting_valid << '\n';
    std::cout << "encoding_queue_high_watermark="
              << stats.encoding_queue_high_watermark << '\n';
    std::cout << "status=" << (passed ? "PASS" : "FAIL") << '\n';

    std::filesystem::remove_all(directory);
    return passed ? 0 : 1;
}
