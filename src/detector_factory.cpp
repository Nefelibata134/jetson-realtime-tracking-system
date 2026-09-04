#include "edge_vision/detector_factory.hpp"

#include "edge_vision/yolo26_detector.hpp"
#include "edge_vision/yolox_detector.hpp"

namespace edge_vision {

std::unique_ptr<IProfiledDetector> make_detector(
    const std::string& engine_path,
    DetectorConfig config) {
    switch (config.kind) {
        case DetectorKind::YoloX: {
            YoloXDetectorConfig yolox;
            yolox.score_threshold = config.score_threshold.value_or(yolox.score_threshold);
            yolox.nms_threshold = config.nms_threshold.value_or(yolox.nms_threshold);
            return std::make_unique<YoloXDetector>(engine_path, yolox);
        }
        case DetectorKind::Yolo26:
            if (!config.score_threshold.has_value() || !config.nms_threshold.has_value()) {
                throw std::invalid_argument("YOLO26 requires explicit score and NMS thresholds");
            }
            return std::make_unique<Yolo26Detector>(engine_path,
                Yolo26PostprocessConfig{*config.score_threshold, *config.nms_threshold, 300});
    }
    throw std::invalid_argument("Unsupported detector kind");
}

}  // namespace edge_vision
