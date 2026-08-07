#pragma once

#include <array>
#include <cstddef>
#include <vector>

#include "edge_vision/detector.hpp"

namespace edge_vision {

struct YoloXPostprocessConfig {
    int input_width{416};
    int input_height{416};
    int class_count{80};
    float score_threshold{0.3F};
    float nms_threshold{0.45F};
    std::array<int, 3> strides{8, 16, 32};
};

class YoloXPostprocessor {
public:
    explicit YoloXPostprocessor(YoloXPostprocessConfig config = {});

    [[nodiscard]] std::vector<Detection> run(
        const std::vector<float>& output,
        int original_width,
        int original_height,
        float scale) const;

    [[nodiscard]] std::size_t expected_rows() const noexcept;
    [[nodiscard]] std::size_t expected_columns() const noexcept;

private:
    YoloXPostprocessConfig config_;
    std::size_t expected_rows_{0};
};

}  // namespace edge_vision
