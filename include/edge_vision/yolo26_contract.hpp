#pragma once

#include <cstddef>

#include "edge_vision/tensorrt_engine.hpp"

namespace edge_vision {

inline constexpr int kYolo26InputWidth = 640;
inline constexpr int kYolo26InputHeight = 640;
inline constexpr int kYolo26ClassCount = 80;
inline constexpr std::size_t kYolo26Candidates = 8400;
inline constexpr std::size_t kYolo26OutputChannels = 4 + kYolo26ClassCount;

void validate_yolo26_contracts(
    const TensorContract& input,
    const TensorContract& output);

}  // namespace edge_vision
