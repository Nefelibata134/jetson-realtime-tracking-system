#pragma once

#include <cstdint>
#include <vector>

#include "edge_vision/detector.hpp"

namespace edge_vision {

enum class TrackState {
    Tentative,
    Tracked,
    Lost,
    Removed,
};

struct Track {
    std::int64_t track_id{-1};
    BoundingBox box{};
    int class_id{-1};
    float confidence{0.0F};
    TrackState state{TrackState::Tentative};

    // Number of frame updates since the track was created.
    std::uint32_t age{0};

    // Number of consecutive updates without a matching detection.
    std::uint32_t missed_frames{0};
};

class ITracker {
public:
    virtual ~ITracker() = default;

    virtual std::vector<Track> update(
        const std::vector<Detection>& detections) = 0;

    virtual void reset() = 0;
};

}  // namespace edge_vision
