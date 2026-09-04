#include "edge_vision/yolo26_contract.hpp"

#include <stdexcept>
#include <vector>

namespace edge_vision {

void validate_yolo26_contracts(
    const TensorContract& input,
    const TensorContract& output) {
    if (input.shape != std::vector<std::int64_t>{
            1, 3, kYolo26InputHeight, kYolo26InputWidth}) {
        throw std::invalid_argument(
            "YOLO26s input must be static 1x3x640x640 float32 RGB");
    }
    if (output.shape != std::vector<std::int64_t>{
            1, static_cast<std::int64_t>(kYolo26OutputChannels),
            static_cast<std::int64_t>(kYolo26Candidates)}) {
        throw std::invalid_argument(
            "YOLO26s output must be one-to-many 1x84x8400; "
            "end-to-end/NMS-free, transposed, and YOLOX outputs are unsupported");
    }
}

}  // namespace edge_vision
