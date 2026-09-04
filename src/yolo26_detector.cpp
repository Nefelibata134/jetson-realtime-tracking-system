#include "edge_vision/yolo26_detector.hpp"

#include <chrono>
#include <utility>

#include "edge_vision/yolo26_contract.hpp"

namespace edge_vision {

Yolo26Detector::Yolo26Detector(
    const std::string& engine_path,
    Yolo26PostprocessConfig config)
    : engine_(engine_path), postprocessor_(config) {
    validate_yolo26_contracts(engine_.input(), engine_.output());
}

DetectorResult Yolo26Detector::infer_profiled(const Frame& frame) {
    const auto started = std::chrono::steady_clock::now();
    const auto preprocessed = preprocessor_.run(frame);
    const auto prepared = std::chrono::steady_clock::now();
    const auto output = engine_.infer(preprocessed.tensor);
    const auto inferred = std::chrono::steady_clock::now();
    auto detections = postprocessor_.run(output, preprocessed.letterbox);
    const auto finished = std::chrono::steady_clock::now();
    const auto elapsed = [](const auto begin, const auto end) {
        return std::chrono::duration<double, std::milli>(end - begin).count();
    };
    return {std::move(detections), {
        elapsed(started, prepared), elapsed(prepared, inferred),
        elapsed(inferred, finished), elapsed(started, finished),
    }};
}

const TensorContract& Yolo26Detector::input_contract() const noexcept {
    return engine_.input();
}

const TensorContract& Yolo26Detector::output_contract() const noexcept {
    return engine_.output();
}

}  // namespace edge_vision
