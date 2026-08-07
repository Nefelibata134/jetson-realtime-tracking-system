#include "edge_vision/yolox_postprocessor.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <utility>

namespace edge_vision {
namespace {

struct Candidate {
    Detection detection;
    float x2{0.0F};
    float y2{0.0F};
};

float intersection_over_union(const Candidate& left, const Candidate& right) {
    const float intersection_left = std::max(left.detection.box.x, right.detection.box.x);
    const float intersection_top = std::max(left.detection.box.y, right.detection.box.y);
    const float intersection_right = std::min(left.x2, right.x2);
    const float intersection_bottom = std::min(left.y2, right.y2);

    const float intersection_width =
        std::max(0.0F, intersection_right - intersection_left + 1.0F);
    const float intersection_height =
        std::max(0.0F, intersection_bottom - intersection_top + 1.0F);
    const float intersection = intersection_width * intersection_height;

    const float left_area =
        (left.detection.box.width + 1.0F) * (left.detection.box.height + 1.0F);
    const float right_area =
        (right.detection.box.width + 1.0F) * (right.detection.box.height + 1.0F);
    const float union_area = left_area + right_area - intersection;
    return union_area > 0.0F ? intersection / union_area : 0.0F;
}

}  // namespace

YoloXPostprocessor::YoloXPostprocessor(YoloXPostprocessConfig config)
    : config_(std::move(config)) {
    if (config_.input_width <= 0 || config_.input_height <= 0) {
        throw std::invalid_argument("YOLOX input dimensions must be positive");
    }
    if (config_.class_count <= 0) {
        throw std::invalid_argument("YOLOX class count must be positive");
    }
    if (config_.score_threshold < 0.0F || config_.score_threshold > 1.0F ||
        config_.nms_threshold < 0.0F || config_.nms_threshold > 1.0F) {
        throw std::invalid_argument("YOLOX thresholds must be within [0, 1]");
    }

    for (const int stride : config_.strides) {
        if (stride <= 0 || config_.input_width % stride != 0 ||
            config_.input_height % stride != 0) {
            throw std::invalid_argument(
                "YOLOX input dimensions must be divisible by every stride");
        }
        expected_rows_ +=
            static_cast<std::size_t>(config_.input_width / stride) *
            static_cast<std::size_t>(config_.input_height / stride);
    }
}

std::vector<Detection> YoloXPostprocessor::run(
    const std::vector<float>& output,
    int original_width,
    int original_height,
    float scale) const {
    if (original_width <= 0 || original_height <= 0 || !std::isfinite(scale) ||
        scale <= 0.0F) {
        throw std::invalid_argument("YOLOX postprocessing received invalid image geometry");
    }

    const std::size_t columns = expected_columns();
    if (output.size() != expected_rows_ * columns) {
        throw std::invalid_argument("YOLOX output tensor size does not match its contract");
    }

    std::vector<Candidate> candidates;
    candidates.reserve(expected_rows_);

    std::size_t row = 0;
    for (const int stride : config_.strides) {
        const int grid_width = config_.input_width / stride;
        const int grid_height = config_.input_height / stride;

        for (int grid_y = 0; grid_y < grid_height; ++grid_y) {
            for (int grid_x = 0; grid_x < grid_width; ++grid_x, ++row) {
                const float* values = output.data() + row * columns;
                const float objectness = values[4];

                const float* class_begin = values + 5;
                const float* class_end = class_begin + config_.class_count;
                const float* best_class = std::max_element(class_begin, class_end);
                const float confidence = objectness * *best_class;
                if (!std::isfinite(confidence) ||
                    confidence <= config_.score_threshold) {
                    continue;
                }

                const float center_x =
                    (values[0] + static_cast<float>(grid_x)) *
                    static_cast<float>(stride);
                const float center_y =
                    (values[1] + static_cast<float>(grid_y)) *
                    static_cast<float>(stride);
                const float width = std::exp(values[2]) * static_cast<float>(stride);
                const float height = std::exp(values[3]) * static_cast<float>(stride);
                if (!std::isfinite(center_x) || !std::isfinite(center_y) ||
                    !std::isfinite(width) || !std::isfinite(height)) {
                    continue;
                }

                const float max_x = static_cast<float>(original_width - 1);
                const float max_y = static_cast<float>(original_height - 1);
                const float x1 = std::clamp((center_x - width * 0.5F) / scale, 0.0F, max_x);
                const float y1 = std::clamp((center_y - height * 0.5F) / scale, 0.0F, max_y);
                const float x2 = std::clamp((center_x + width * 0.5F) / scale, 0.0F, max_x);
                const float y2 = std::clamp((center_y + height * 0.5F) / scale, 0.0F, max_y);
                if (x2 <= x1 || y2 <= y1) {
                    continue;
                }

                candidates.push_back({
                    {
                        {x1, y1, x2 - x1, y2 - y1},
                        static_cast<int>(best_class - class_begin),
                        confidence,
                    },
                    x2,
                    y2,
                });
            }
        }
    }

    std::sort(
        candidates.begin(),
        candidates.end(),
        [](const Candidate& left, const Candidate& right) {
            return left.detection.confidence > right.detection.confidence;
        });

    std::vector<bool> suppressed(candidates.size(), false);
    std::vector<Detection> detections;
    detections.reserve(candidates.size());

    for (std::size_t current = 0; current < candidates.size(); ++current) {
        if (suppressed[current]) {
            continue;
        }
        detections.push_back(candidates[current].detection);

        for (std::size_t other = current + 1; other < candidates.size(); ++other) {
            if (!suppressed[other] &&
                intersection_over_union(candidates[current], candidates[other]) >
                    config_.nms_threshold) {
                suppressed[other] = true;
            }
        }
    }

    return detections;
}

std::size_t YoloXPostprocessor::expected_rows() const noexcept {
    return expected_rows_;
}

std::size_t YoloXPostprocessor::expected_columns() const noexcept {
    return static_cast<std::size_t>(5 + config_.class_count);
}

}  // namespace edge_vision
