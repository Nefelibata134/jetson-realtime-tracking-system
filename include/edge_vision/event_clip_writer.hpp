#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "edge_vision/event_journal.hpp"
#include "edge_vision/frame_annotator.hpp"
#include "edge_vision/annotated_video_writer.hpp"

namespace edge_vision {

struct EventClipWriterConfig {
    std::string output_directory;
    double frames_per_second{30.0};
    double pre_event_seconds{2.0};
    double post_event_seconds{3.0};
    std::size_t max_active_clips{2};
    std::size_t encoding_queue_capacity{2};
    FrameAnnotationConfig annotation;
    AnnotatedVideoEncoder encoder{AnnotatedVideoEncoder::OpenCvMp4v};
    std::uint32_t bitrate_kbps{10000};
    bool share_overlapping{false};
    double max_shared_seconds{10.0};
    std::size_t max_events_per_clip{32};
};

struct EventClipWriterStats {
    std::uint64_t clips_started{0};
    std::uint64_t clips_completed{0};
    std::uint64_t clips_reused{0};
    std::uint64_t clips_skipped{0};
    // Event counts, not physical clips. Worker queue excludes its in-flight failed job.
    std::uint64_t events_skipped_capacity{0};
    std::uint64_t events_skipped_queue{0};
    std::uint64_t events_skipped_worker_queue{0};
    std::uint64_t events_completed{0};
    std::uint64_t events_shared{0};
    std::size_t prebuffer_frames{0};
    std::size_t prebuffer_bytes{0};
    std::size_t prebuffer_peak_bytes{0};
    std::size_t max_active_clips{0};
    std::size_t encoding_queue_high_watermark{0};
    std::size_t pending_jobs_high_watermark{0};
    // Monotonic time between queue submission and worker pickup, per physical job.
    std::uint64_t encoding_queue_wait_samples{0};
    double encoding_queue_wait_total_ms{0.0};
    double encoding_queue_wait_max_ms{0.0};
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
