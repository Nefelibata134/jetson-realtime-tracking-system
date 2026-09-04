#pragma once

#include <string>

#include "edge_vision/detector.hpp"
#include "edge_vision/tensorrt_engine.hpp"
#include "edge_vision/yolo26_postprocessor.hpp"
#include "edge_vision/yolo26_preprocessor.hpp"

namespace edge_vision {

class Yolo26Detector final : public IProfiledDetector {
public:
    explicit Yolo26Detector(
        const std::string& engine_path,
        Yolo26PostprocessConfig config);

    [[nodiscard]] DetectorResult infer_profiled(const Frame& frame) override;
    [[nodiscard]] const TensorContract& input_contract() const noexcept;
    [[nodiscard]] const TensorContract& output_contract() const noexcept;

private:
    TensorRTEngine engine_;
    Yolo26Preprocessor preprocessor_;
    Yolo26Postprocessor postprocessor_;
};

}  // namespace edge_vision
