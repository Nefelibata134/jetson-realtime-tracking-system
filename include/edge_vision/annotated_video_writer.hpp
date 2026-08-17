#pragma once

#include <cstdint>
#include <cstddef>
#include <memory>
#include <string>
#include <vector>

#include "edge_vision/frame_annotator.hpp"
#include "edge_vision/frame.hpp"
#include "edge_vision/tracker.hpp"

namespace edge_vision {

struct AnnotatedVideoWriterConfig {
    std::string output_path;
    double frames_per_second{30.0};
    std::size_t queue_capacity{4};
    std::vector<PolygonRegion> event_regions;
    std::vector<NormalizedLineSegment> event_lines;
    double event_label_duration_seconds{1.5};
};

struct AnnotatedVideoWriterStats {
    std::uint64_t frames_submitted{0};
    std::uint64_t frames_written{0};
    std::uint64_t frames_dropped{0};
    std::size_t queue_high_watermark{0};
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
