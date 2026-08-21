#pragma once

#include <string>
#include <vector>

#include "edge_vision/detector.hpp"
#include "edge_vision/tensorrt_engine.hpp"
#include "edge_vision/yolox_postprocessor.hpp"
#include "edge_vision/yolox_preprocessor.hpp"

namespace edge_vision {

struct YoloXDetectorConfig {
    int input_width{416};
    int input_height{416};
    int class_count{80};
    float score_threshold{0.3F};
    float nms_threshold{0.45F};
};

struct YoloXDetectorStageTiming {
    double preprocess_ms{0.0};
    double tensorrt_inference_ms{0.0};
    double postprocess_ms{0.0};
    double total_ms{0.0};
};

struct YoloXDetectorResult {
    std::vector<Detection> detections;
    YoloXDetectorStageTiming timing;
};

class YoloXDetector final : public IDetector {
public:
    explicit YoloXDetector(
        const std::string& engine_path,
        YoloXDetectorConfig config = {});

    [[nodiscard]] std::vector<Detection> infer(const Frame& frame) override;
    [[nodiscard]] YoloXDetectorResult infer_profiled(const Frame& frame);

    [[nodiscard]] const TensorContract& input_contract() const noexcept;
    [[nodiscard]] const TensorContract& output_contract() const noexcept;

private:
    void validate_contracts() const;

    TensorRTEngine engine_;
    YoloXDetectorConfig config_;
    YoloXPreprocessor preprocessor_;
    YoloXPostprocessor postprocessor_;
};

}  // namespace edge_vision
