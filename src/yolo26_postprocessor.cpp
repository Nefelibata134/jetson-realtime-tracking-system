#include "edge_vision/yolo26_postprocessor.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

#include "edge_vision/yolo26_contract.hpp"

namespace edge_vision {
namespace {

struct Candidate {
    float x1;
    float y1;
    float x2;
    float y2;
    float confidence;
    int class_id;
};

double intersection_over_union(const Candidate& a, const Candidate& b) {
    const double width = std::max(
        0.0, static_cast<double>(std::min(a.x2, b.x2)) - std::max(a.x1, b.x1));
    const double height = std::max(
        0.0, static_cast<double>(std::min(a.y2, b.y2)) - std::max(a.y1, b.y1));
    const double intersection = width * height;
    const double area_a = (static_cast<double>(a.x2) - a.x1) *
                          (static_cast<double>(a.y2) - a.y1);
    const double area_b = (static_cast<double>(b.x2) - b.x1) *
                          (static_cast<double>(b.y2) - b.y1);
    const double total = area_a + area_b - intersection;
    return total > 0.0 ? intersection / total : 0.0;
}

}  // namespace

Yolo26Postprocessor::Yolo26Postprocessor(Yolo26PostprocessConfig config)
    : config_(config) {
    if (!std::isfinite(config_.score_threshold) ||
        !std::isfinite(config_.nms_threshold) ||
        config_.score_threshold < 0.0F || config_.score_threshold > 1.0F ||
        config_.nms_threshold < 0.0F || config_.nms_threshold > 1.0F ||
        config_.max_detections == 0 || config_.max_detections > kYolo26Candidates) {
        throw std::invalid_argument("YOLO26 thresholds or detection limit are invalid");
    }
}

std::vector<Detection> Yolo26Postprocessor::run(
    const std::vector<float>& output,
    const Yolo26Letterbox& geometry) const {
    if (output.size() != kYolo26OutputChannels * kYolo26Candidates) {
        throw std::invalid_argument("YOLO26 output size must match 1x84x8400");
    }
    const auto expected = make_yolo26_letterbox(
        geometry.original_width, geometry.original_height);
    if (geometry.scale != expected.scale ||
        geometry.resized_width != expected.resized_width ||
        geometry.resized_height != expected.resized_height ||
        geometry.pad_left != expected.pad_left || geometry.pad_top != expected.pad_top ||
        geometry.pad_right != expected.pad_right || geometry.pad_bottom != expected.pad_bottom) {
        throw std::invalid_argument("YOLO26 letterbox geometry does not match the frame");
    }

    std::vector<Candidate> candidates;
    candidates.reserve(kYolo26Candidates);
    for (std::size_t index = 0; index < kYolo26Candidates; ++index) {
        float confidence = 0.0F;
        int class_id = -1;
        for (int category = 0; category < kYolo26ClassCount; ++category) {
            const float score = output[(4 + category) * kYolo26Candidates + index];
            if (std::isfinite(score) && score <= 1.0F && score > confidence) {
                confidence = score;
                class_id = category;
            }
        }
        if (class_id < 0 || confidence <= config_.score_threshold) {
            continue;
        }
        const float cx = output[index];
        const float cy = output[kYolo26Candidates + index];
        const float width = output[2 * kYolo26Candidates + index];
        const float height = output[3 * kYolo26Candidates + index];
        if (!std::isfinite(cx) || !std::isfinite(cy) || !std::isfinite(width) ||
            !std::isfinite(height) || width <= 0.0F || height <= 0.0F) {
            continue;
        }
        // Map to original coordinates without clipping, so padding cannot alter NMS IoU.
        const float x1 = (cx - width * 0.5F - geometry.pad_left) / geometry.scale;
        const float y1 = (cy - height * 0.5F - geometry.pad_top) / geometry.scale;
        const float x2 = (cx + width * 0.5F - geometry.pad_left) / geometry.scale;
        const float y2 = (cy + height * 0.5F - geometry.pad_top) / geometry.scale;
        if (!std::isfinite(x1) || !std::isfinite(y1) || !std::isfinite(x2) ||
            !std::isfinite(y2) || x2 <= x1 || y2 <= y1) {
            continue;
        }
        candidates.push_back({x1, y1, x2, y2, confidence, class_id});
    }
    std::stable_sort(candidates.begin(), candidates.end(),
        [](const Candidate& a, const Candidate& b) { return a.confidence > b.confidence; });

    std::vector<bool> suppressed(candidates.size(), false);
    std::vector<Detection> detections;
    detections.reserve(std::min(candidates.size(), config_.max_detections));
    std::size_t selected = 0;
    for (std::size_t current = 0;
         current < candidates.size() && selected < config_.max_detections; ++current) {
        if (suppressed[current]) {
            continue;
        }
        ++selected;
        const auto& candidate = candidates[current];
        const float x1 = std::clamp(candidate.x1, 0.0F, static_cast<float>(geometry.original_width));
        const float y1 = std::clamp(candidate.y1, 0.0F, static_cast<float>(geometry.original_height));
        const float x2 = std::clamp(candidate.x2, 0.0F, static_cast<float>(geometry.original_width));
        const float y2 = std::clamp(candidate.y2, 0.0F, static_cast<float>(geometry.original_height));
        if (x2 > x1 && y2 > y1) {
            detections.push_back({{x1, y1, x2 - x1, y2 - y1},
                                  candidate.class_id, candidate.confidence});
        }
        for (std::size_t other = current + 1; other < candidates.size(); ++other) {
            if (!suppressed[other] && candidate.class_id == candidates[other].class_id &&
                intersection_over_union(candidate, candidates[other]) > config_.nms_threshold) {
                suppressed[other] = true;
            }
        }
    }
    return detections;
}

}  // namespace edge_vision
