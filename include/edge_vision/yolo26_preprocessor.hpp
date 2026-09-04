#pragma once

#include <vector>

#include "edge_vision/frame.hpp"

namespace edge_vision {

struct Yolo26Letterbox {
    int original_width{0};
    int original_height{0};
    float scale{0.0F};
    int resized_width{0};
    int resized_height{0};
    int pad_left{0};
    int pad_top{0};
    int pad_right{0};
    int pad_bottom{0};
};

[[nodiscard]] Yolo26Letterbox make_yolo26_letterbox(int width, int height);

struct Yolo26PreprocessResult {
    std::vector<float> tensor;
    Yolo26Letterbox letterbox;
};

class Yolo26Preprocessor {
public:
    [[nodiscard]] Yolo26PreprocessResult run(const Frame& frame) const;
};

}  // namespace edge_vision
