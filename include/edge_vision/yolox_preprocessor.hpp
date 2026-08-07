#pragma once

#include <cstdint>
#include <vector>

#include "edge_vision/frame.hpp"

namespace edge_vision {

struct YoloXPreprocessResult {
    std::vector<float> tensor;
    float scale{0.0F};
    int resized_width{0};
    int resized_height{0};
    int pad_right{0};
    int pad_bottom{0};
};

class YoloXPreprocessor {
public:
    explicit YoloXPreprocessor(
        int target_width = 416,
        int target_height = 416,
        std::uint8_t padding_value = 114);

    [[nodiscard]] YoloXPreprocessResult run(const Frame& frame) const;
    [[nodiscard]] int target_width() const noexcept;
    [[nodiscard]] int target_height() const noexcept;

private:
    int target_width_{0};
    int target_height_{0};
    std::uint8_t padding_value_{0};
};

}  // namespace edge_vision
