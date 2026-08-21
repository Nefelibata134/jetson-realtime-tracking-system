#include "edge_vision/yolox_detector.hpp"

#include <chrono>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace edge_vision {
namespace {

YoloXPostprocessConfig make_postprocess_config(
    const YoloXDetectorConfig& config) {
    return {
        config.input_width,
        config.input_height,
        config.class_count,
        config.score_threshold,
        config.nms_threshold,
        {8, 16, 32},
    };
}

std::string shape_string(const TensorContract& contract) {
    std::ostringstream output;
    for (std::size_t index = 0; index < contract.shape.size(); ++index) {
        if (index != 0) {
            output << 'x';
        }
        output << contract.shape[index];
    }
    return output.str();
}

}  // namespace

YoloXDetector::YoloXDetector(
    const std::string& engine_path,
    YoloXDetectorConfig config)
    : engine_(engine_path),
      config_(std::move(config)),
      preprocessor_(config_.input_width, config_.input_height),
      postprocessor_(make_postprocess_config(config_)) {
    validate_contracts();
}

std::vector<Detection> YoloXDetector::infer(const Frame& frame) {
    return infer_profiled(frame).detections;
}

YoloXDetectorResult YoloXDetector::infer_profiled(const Frame& frame) {
    const auto total_started_at = std::chrono::steady_clock::now();
    const auto preprocessed = preprocessor_.run(frame);
    const auto preprocess_finished_at = std::chrono::steady_clock::now();
    const auto output = engine_.infer(preprocessed.tensor);
    const auto inference_finished_at = std::chrono::steady_clock::now();
    auto detections = postprocessor_.run(
        output,
        frame.width,
        frame.height,
        preprocessed.scale);
    const auto postprocess_finished_at = std::chrono::steady_clock::now();

    const auto elapsed_ms = [](
                                const auto started_at,
                                const auto finished_at) {
        return std::chrono::duration<double, std::milli>(
                   finished_at - started_at)
            .count();
    };
    return {
        std::move(detections),
        {
            elapsed_ms(total_started_at, preprocess_finished_at),
            elapsed_ms(preprocess_finished_at, inference_finished_at),
            elapsed_ms(inference_finished_at, postprocess_finished_at),
            elapsed_ms(total_started_at, postprocess_finished_at),
        },
    };
}

const TensorContract& YoloXDetector::input_contract() const noexcept {
    return engine_.input();
}

const TensorContract& YoloXDetector::output_contract() const noexcept {
    return engine_.output();
}

void YoloXDetector::validate_contracts() const {
    const auto& input = engine_.input();
    const std::vector<std::int64_t> expected_input{
        1,
        3,
        config_.input_height,
        config_.input_width,
    };
    if (input.shape != expected_input) {
        throw std::runtime_error(
            "YOLOX engine input contract mismatch: expected 1x3x" +
            std::to_string(config_.input_height) + "x" +
            std::to_string(config_.input_width) + ", received " +
            shape_string(input));
    }

    const auto& output = engine_.output();
    const std::vector<std::int64_t> expected_output{
        1,
        static_cast<std::int64_t>(postprocessor_.expected_rows()),
        static_cast<std::int64_t>(postprocessor_.expected_columns()),
    };
    if (output.shape != expected_output) {
        throw std::runtime_error(
            "YOLOX engine output contract mismatch: expected 1x" +
            std::to_string(postprocessor_.expected_rows()) + "x" +
            std::to_string(postprocessor_.expected_columns()) +
            ", received " + shape_string(output));
    }
}

}  // namespace edge_vision
