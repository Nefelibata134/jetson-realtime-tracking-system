#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "edge_vision/event_journal.hpp"
#include "edge_vision/frame_annotator.hpp"

namespace edge_vision {

struct EventEvidenceWriterConfig {
    std::string snapshot_directory;
    int jpeg_quality{90};
    FrameAnnotationConfig annotation;
};

struct EventEvidenceWriterStats {
    std::uint64_t snapshots_written{0};
    std::uint64_t snapshots_reused{0};
};

class EventEvidenceWriter final {
public:
    explicit EventEvidenceWriter(EventEvidenceWriterConfig config);
    ~EventEvidenceWriter();

    EventEvidenceWriter(const EventEvidenceWriter&) = delete;
    EventEvidenceWriter& operator=(const EventEvidenceWriter&) = delete;

    [[nodiscard]] std::string write_snapshot(
        const EventRecord& record,
        const Frame& frame,
        const std::vector<Track>& tracks);

    [[nodiscard]] EventEvidenceWriterStats stats() const noexcept;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace edge_vision
