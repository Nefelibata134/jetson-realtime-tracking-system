#pragma once

#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>

#include "edge_vision/detector.hpp"

namespace edge_vision {

enum class DetectorKind { YoloX, Yolo26 };

[[nodiscard]] inline DetectorKind parse_detector_kind(std::string_view name) {
    if (name == "yolox") {
        return DetectorKind::YoloX;
    }
    if (name == "yolo26") {
        return DetectorKind::Yolo26;
    }
    throw std::invalid_argument("Unsupported detector: " + std::string(name));
}

[[nodiscard]] inline const char* detector_kind_name(DetectorKind kind) {
    switch (kind) {
        case DetectorKind::YoloX: return "yolox";
        case DetectorKind::Yolo26: return "yolo26";
    }
    throw std::invalid_argument("Unsupported detector kind");
}

struct DetectorConfig {
    DetectorKind kind{DetectorKind::YoloX};
    std::optional<float> score_threshold;
    std::optional<float> nms_threshold;
};

[[nodiscard]] std::unique_ptr<IProfiledDetector> make_detector(
    const std::string& engine_path,
    DetectorConfig config = {});

}  // namespace edge_vision
