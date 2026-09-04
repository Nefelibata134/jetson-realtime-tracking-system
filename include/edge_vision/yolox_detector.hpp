#pragma once

#include <string>
#include <vector>

#include "edge_vision/detector.hpp"
#include "edge_vision/tensorrt_engine.hpp"
#include "edge_vision/yolox_postprocessor.hpp"
#include "edge_vision/yolox_preprocessor.hpp"

namespace edge_vision {

struct YoloXDetectorConfig {
    // Zero dimensions are resolved from the static TensorRT engine contract.
    int input_width{0};
    int input_height{0};
    int class_count{80};
    float score_threshold{0.3F};
    float nms_threshold{0.45F};
};

using YoloXDetectorStageTiming = DetectorStageTiming;
using YoloXDetectorResult = DetectorResult;

class YoloXDetector final : public IProfiledDetector {
public:
    explicit YoloXDetector(
        const std::string& engine_path,
        YoloXDetectorConfig config = {});

    [[nodiscard]] std::vector<Detection> infer(const Frame& frame) override;
    [[nodiscard]] YoloXDetectorResult infer_profiled(const Frame& frame) override;

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
