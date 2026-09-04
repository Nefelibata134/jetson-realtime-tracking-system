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

struct DetectorStageTiming {
    double preprocess_ms{0.0};
    double tensorrt_inference_ms{0.0};
    double postprocess_ms{0.0};
    double total_ms{0.0};
};

struct DetectorResult {
    std::vector<Detection> detections;
    DetectorStageTiming timing;
};

class IDetector {
public:
    virtual ~IDetector() = default;
    virtual std::vector<Detection> infer(const Frame& frame) = 0;
};

class IProfiledDetector : public IDetector {
public:
    [[nodiscard]] std::vector<Detection> infer(const Frame& frame) override {
        return infer_profiled(frame).detections;
    }

    [[nodiscard]] virtual DetectorResult infer_profiled(const Frame& frame) = 0;
};

}  // namespace edge_vision
