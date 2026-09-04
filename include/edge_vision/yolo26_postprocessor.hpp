#pragma once

#include <cstddef>
#include <vector>

#include "edge_vision/detector.hpp"
#include "edge_vision/yolo26_preprocessor.hpp"

namespace edge_vision {

struct Yolo26PostprocessConfig {
    float score_threshold{0.25F};
    float nms_threshold{0.45F};
    std::size_t max_detections{300};
};

class Yolo26Postprocessor {
public:
    explicit Yolo26Postprocessor(Yolo26PostprocessConfig config = {});

    [[nodiscard]] std::vector<Detection> run(
        const std::vector<float>& output,
        const Yolo26Letterbox& geometry) const;

private:
    Yolo26PostprocessConfig config_;
};

}  // namespace edge_vision
