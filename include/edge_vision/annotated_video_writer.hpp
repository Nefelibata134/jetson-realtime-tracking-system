#pragma once

#include <cstdint>
#include <cstddef>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

#include "edge_vision/frame_annotator.hpp"
#include "edge_vision/frame.hpp"
#include "edge_vision/tracker.hpp"

namespace edge_vision {

enum class AnnotatedVideoEncoder {
    OpenCvMp4v,
    GStreamerX264,
};

[[nodiscard]] std::string_view annotated_video_encoder_name(
    AnnotatedVideoEncoder encoder) noexcept;

struct AnnotatedVideoWriterConfig {
    std::string output_path;
    double frames_per_second{30.0};
    std::size_t queue_capacity{4};
    AnnotatedVideoEncoder encoder{AnnotatedVideoEncoder::OpenCvMp4v};
    std::uint32_t bitrate_kbps{10000};
    std::vector<PolygonRegion> event_regions;
    std::vector<NormalizedLineSegment> event_lines;
    double event_label_duration_seconds{1.5};
};

struct AnnotatedVideoWriterStats {
    std::uint64_t frames_submitted{0};
    std::uint64_t frames_written{0};
    std::uint64_t frames_dropped{0};
    std::size_t queue_high_watermark{0};
    double encoding_total_ms{0.0};
    double encoding_max_ms{0.0};
};

class AnnotatedVideoWriter {
public:
    explicit AnnotatedVideoWriter(AnnotatedVideoWriterConfig config);
    ~AnnotatedVideoWriter();

    AnnotatedVideoWriter(const AnnotatedVideoWriter&) = delete;
    AnnotatedVideoWriter& operator=(const AnnotatedVideoWriter&) = delete;

    void write(
        const Frame& frame,
        const std::vector<Track>& tracks,
        const std::vector<SafetyEvent>& events = {});
    void finish();
    void close() noexcept;

    [[nodiscard]] AnnotatedVideoWriterStats stats() const noexcept;
    [[nodiscard]] std::uint64_t frames_written() const noexcept;
    [[nodiscard]] const std::string& output_path() const noexcept;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace edge_vision
