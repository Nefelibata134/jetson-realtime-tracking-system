#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace edge_vision {

enum class PixelFormat {
    bgr8,
    rgb8,
};

struct Frame {
    std::vector<std::uint8_t> data;
    int width{0};
    int height{0};
    int channels{0};
    PixelFormat format{PixelFormat::bgr8};
    std::int64_t pts_ns{0};
    std::int64_t captured_at_ns{0};
    std::uint64_t sequence{0};
    std::uint64_t stream_generation{0};

    [[nodiscard]] std::size_t expected_bytes() const noexcept {
        if (width <= 0 || height <= 0 || channels <= 0) {
            return 0;
        }

        return static_cast<std::size_t>(width) *
               static_cast<std::size_t>(height) *
               static_cast<std::size_t>(channels);
    }

    [[nodiscard]] bool valid() const noexcept {
        return expected_bytes() != 0 && data.size() == expected_bytes();
    }
};

}  // namespace edge_vision
