#pragma once

#include <memory>

#include "edge_vision/tracker.hpp"

namespace edge_vision {

struct ByteTrackerConfig {
    int frame_rate{30};
    int track_buffer{30};
    float track_threshold{0.5F};
    float new_track_threshold{0.6F};
    float match_threshold{0.8F};
    float second_match_threshold{0.5F};
    float unconfirmed_match_threshold{0.7F};
};

class ByteTracker final : public ITracker {
public:
    explicit ByteTracker(ByteTrackerConfig config = {});
    ~ByteTracker() override;

    ByteTracker(const ByteTracker&) = delete;
    ByteTracker& operator=(const ByteTracker&) = delete;
    ByteTracker(ByteTracker&&) noexcept;
    ByteTracker& operator=(ByteTracker&&) noexcept;

    [[nodiscard]] std::vector<Track> update(
        const std::vector<Detection>& detections) override;
    void reset() override;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace edge_vision
