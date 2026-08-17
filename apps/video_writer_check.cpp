#include <cstdint>
#include <filesystem>
#include <iostream>
#include <vector>

#include "edge_vision/annotated_video_writer.hpp"

int main() {
    const std::filesystem::path output_path =
        "annotated_video_writer_check.mp4";
    std::filesystem::remove(output_path);

    edge_vision::AnnotatedVideoWriterConfig config;
    config.output_path = output_path.string();
    config.frames_per_second = 30.0;
    config.queue_capacity = 2;
    config.event_regions.push_back({{
        {0.5F, 0.2F},
        {0.9F, 0.2F},
        {0.9F, 0.9F},
        {0.5F, 0.9F},
    }});
    config.event_lines.push_back({{0.5F, 0.2F}, {0.5F, 0.9F}});

    edge_vision::Frame frame;
    frame.width = 320;
    frame.height = 180;
    frame.channels = 3;
    frame.format = edge_vision::PixelFormat::bgr8;
    frame.data.resize(frame.expected_bytes(), 32U);

    edge_vision::Track track;
    track.track_id = 7;
    track.box = {64.0F, 36.0F, 128.0F, 72.0F};
    track.class_id = 0;
    track.confidence = 0.92F;
    track.state = edge_vision::TrackState::Tracked;

    edge_vision::AnnotatedVideoWriter writer(config);
    edge_vision::SafetyEvent event;
    event.type = edge_vision::SafetyEventType::RoiIntrusion;
    event.track_id = track.track_id;
    event.anchor = {0.6F, 0.6F};
    constexpr std::uint64_t submitted_frames = 12;
    for (std::uint64_t index = 0; index < submitted_frames; ++index) {
        frame.sequence = index;
        writer.write(frame, {track}, index == 2
                                         ? std::vector{event}
                                         : std::vector<edge_vision::SafetyEvent>{});
    }
    writer.finish();

    const auto stats = writer.stats();
    const bool accounting_valid =
        stats.frames_submitted ==
        stats.frames_written + stats.frames_dropped;
    const bool queue_valid =
        stats.queue_high_watermark > 0 &&
        stats.queue_high_watermark <= config.queue_capacity;
    const bool output_valid =
        stats.frames_written > 0 && std::filesystem::exists(output_path) &&
        std::filesystem::file_size(output_path) > 0;

    std::cout << "submitted=" << stats.frames_submitted << '\n';
    std::cout << "written=" << stats.frames_written << '\n';
    std::cout << "dropped=" << stats.frames_dropped << '\n';
    std::cout << "queue_high_watermark=" << stats.queue_high_watermark
              << '\n';
    std::cout << "accounting_valid=" << std::boolalpha << accounting_valid
              << '\n';
    std::cout << "queue_valid=" << queue_valid << '\n';
    std::cout << "output_valid=" << output_valid << '\n';

    std::filesystem::remove(output_path);
    const bool passed = accounting_valid && queue_valid && output_valid;
    std::cout << "status=" << (passed ? "PASS" : "FAIL") << '\n';
    return passed ? 0 : 1;
}
