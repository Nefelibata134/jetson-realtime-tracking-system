#pragma once

#include <vector>

#include "edge_vision/frame.hpp"

namespace edge_vision {

struct BoundingBox {
    float x{0.0F};
    float y{0.0F};
    float width{0.0F};
    float height{0.0F};
};

struct Detection {
    BoundingBox box;
    int class_id{-1};
    float confidence{0.0F};
};

class IDetector {
public:
    virtual ~IDetector() = default;
    virtual std::vector<Detection> infer(const Frame& frame) = 0;
};

}  // namespace edge_vision

