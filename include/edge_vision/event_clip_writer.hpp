#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "edge_vision/event_journal.hpp"
#include "edge_vision/frame_annotator.hpp"

namespace edge_vision {

struct EventClipWriterConfig {
    std::string output_directory;
    double frames_per_second{30.0};
    double pre_event_seconds{2.0};
    double post_event_seconds{3.0};
    std::size_t max_active_clips{2};
    std::size_t encoding_queue_capacity{2};
    FrameAnnotationConfig annotation;
};

struct EventClipWriterStats {
    std::uint64_t clips_started{0};
    std::uint64_t clips_completed{0};
    std::uint64_t clips_reused{0};
    std::uint64_t clips_skipped{0};
    std::size_t prebuffer_frames{0};
    std::size_t prebuffer_bytes{0};
    std::size_t prebuffer_peak_bytes{0};
    std::size_t max_active_clips{0};
    std::size_t encoding_queue_high_watermark{0};
    std::uint64_t encoded_frames{0};
    double encoding_total_ms{0.0};
    double encoding_max_ms{0.0};
};

class EventClipWriter final {
public:
    explicit EventClipWriter(EventClipWriterConfig config);
    ~EventClipWriter();

    EventClipWriter(const EventClipWriter&) = delete;
    EventClipWriter& operator=(const EventClipWriter&) = delete;

    [[nodiscard]] std::vector<EventRecord> process(
        const Frame& frame,
        const std::vector<Track>& tracks,
        std::vector<EventRecord> records = {});

    [[nodiscard]] std::vector<EventRecord> reset();
    [[nodiscard]] std::vector<EventRecord> finish();
    [[nodiscard]] EventClipWriterStats stats() const noexcept;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace edge_vision
