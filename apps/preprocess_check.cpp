#include <cmath>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <iostream>
#include <stdexcept>
#include <vector>

#include "edge_vision/yolox_preprocessor.hpp"

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

bool approximately_equal(float left, float right) {
    return std::fabs(left - right) < 1.0e-6F;
}

edge_vision::Frame make_uniform_frame(
    int width,
    int height,
    edge_vision::PixelFormat format,
    std::uint8_t first,
    std::uint8_t second,
    std::uint8_t third) {
    edge_vision::Frame frame;
    frame.width = width;
    frame.height = height;
    frame.channels = 3;
    frame.format = format;
    frame.data.resize(frame.expected_bytes());

    for (std::size_t offset = 0; offset < frame.data.size(); offset += 3) {
        frame.data[offset] = first;
        frame.data[offset + 1] = second;
        frame.data[offset + 2] = third;
    }
    return frame;
}

}  // namespace

int main() {
    try {
        const edge_vision::YoloXPreprocessor preprocessor;
        const auto frame = make_uniform_frame(
            1280, 720, edge_vision::PixelFormat::bgr8, 10, 20, 30);
        const auto result = preprocessor.run(frame);
        constexpr std::size_t plane_size = 416U * 416U;

        require(approximately_equal(result.scale, 0.325F), "scale mismatch");
        require(result.resized_width == 416, "resized width mismatch");
        require(result.resized_height == 234, "resized height mismatch");
        require(result.pad_right == 0, "right padding mismatch");
        require(result.pad_bottom == 182, "bottom padding mismatch");
        require(result.tensor.size() == 3U * plane_size, "tensor size mismatch");
        require(result.tensor[0] == 10.0F, "B channel mismatch");
        require(result.tensor[plane_size] == 20.0F, "G channel mismatch");
        require(result.tensor[2U * plane_size] == 30.0F, "R channel mismatch");

        const std::size_t bottom_right = plane_size - 1U;
        require(result.tensor[bottom_right] == 114.0F, "B padding mismatch");
        require(
            result.tensor[plane_size + bottom_right] == 114.0F,
            "G padding mismatch");
        require(
            result.tensor[2U * plane_size + bottom_right] == 114.0F,
            "R padding mismatch");

        const edge_vision::YoloXPreprocessor tiny_preprocessor(1, 1);
        const auto rgb_frame = make_uniform_frame(
            1, 1, edge_vision::PixelFormat::rgb8, 1, 2, 3);
        const auto rgb_result = tiny_preprocessor.run(rgb_frame);
        require(rgb_result.tensor == std::vector<float>({3.0F, 2.0F, 1.0F}),
                "RGB to BGR conversion mismatch");

        bool invalid_rejected = false;
        try {
            static_cast<void>(preprocessor.run(edge_vision::Frame{}));
        } catch (const std::invalid_argument&) {
            invalid_rejected = true;
        }
        require(invalid_rejected, "invalid frame was not rejected");

        std::cout << "scale=" << result.scale << '\n';
        std::cout << "resized=" << result.resized_width << 'x'
                  << result.resized_height << '\n';
        std::cout << "padding=right:" << result.pad_right
                  << ",bottom:" << result.pad_bottom << '\n';
        std::cout << "tensor=1x3x416x416 float32 BGR\n";
        std::cout << "status=PASS\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "YOLOX preprocessing check failed: " << error.what() << '\n';
        return 1;
    }
}
