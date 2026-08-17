#pragma once

#include <vector>

#include "edge_vision/event_analytics.hpp"
#include "edge_vision/frame.hpp"
#include "edge_vision/tracker.hpp"

namespace edge_vision {

struct NormalizedLineSegment {
    NormalizedPoint start;
    NormalizedPoint end;
};

struct FrameAnnotationConfig {
    std::vector<PolygonRegion> event_regions;
    std::vector<NormalizedLineSegment> event_lines;
};

[[nodiscard]] Frame annotate_frame(
    const Frame& frame,
    const std::vector<Track>& tracks,
    const std::vector<SafetyEvent>& events,
    const FrameAnnotationConfig& config = {});

}  // namespace edge_vision
