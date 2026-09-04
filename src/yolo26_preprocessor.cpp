#include "edge_vision/yolo26_preprocessor.hpp"

#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>

#include "edge_vision/yolo26_contract.hpp"

namespace edge_vision {
namespace {

int round_half_even(double value) {
    const auto lower = static_cast<int>(std::floor(value));
    const double fraction = value - lower;
    return lower + (fraction > 0.5 || (fraction == 0.5 && lower % 2 != 0));
}

}  // namespace

Yolo26Letterbox make_yolo26_letterbox(int width, int height) {
    if (width <= 0 || height <= 0) {
        throw std::invalid_argument("YOLO26 image dimensions must be positive");
    }
    const double scale = std::min(
        static_cast<double>(kYolo26InputWidth) / width,
        static_cast<double>(kYolo26InputHeight) / height);
    const int resized_width = round_half_even(width * scale);
    const int resized_height = round_half_even(height * scale);
    if (resized_width <= 0 || resized_height <= 0) {
        throw std::invalid_argument("YOLO26 image aspect ratio is unsupported");
    }
    const int horizontal = kYolo26InputWidth - resized_width;
    const int vertical = kYolo26InputHeight - resized_height;
    return {
        width, height, static_cast<float>(scale), resized_width, resized_height,
        horizontal / 2, vertical / 2,
        horizontal - horizontal / 2, vertical - vertical / 2,
    };
}

Yolo26PreprocessResult Yolo26Preprocessor::run(const Frame& frame) const {
    if (!frame.valid() || frame.channels != 3 ||
        (frame.format != PixelFormat::bgr8 && frame.format != PixelFormat::rgb8)) {
        throw std::invalid_argument("YOLO26 preprocessing requires a valid RGB/BGR frame");
    }
    const auto geometry = make_yolo26_letterbox(frame.width, frame.height);
    const cv::Mat source(
        frame.height, frame.width, CV_8UC3,
        const_cast<std::uint8_t*>(frame.data.data()));
    cv::Mat resized;
    cv::resize(source, resized,
               cv::Size(geometry.resized_width, geometry.resized_height),
               0.0, 0.0, cv::INTER_LINEAR);
    cv::Mat padded;
    cv::copyMakeBorder(
        resized, padded, geometry.pad_top, geometry.pad_bottom,
        geometry.pad_left, geometry.pad_right, cv::BORDER_CONSTANT,
        cv::Scalar(114, 114, 114));

    constexpr std::size_t plane = kYolo26InputWidth * kYolo26InputHeight;
    std::vector<float> tensor(3 * plane);
    const int red = frame.format == PixelFormat::bgr8 ? 2 : 0;
    const int blue = frame.format == PixelFormat::bgr8 ? 0 : 2;
    for (int row = 0; row < kYolo26InputHeight; ++row) {
        const auto* pixels = padded.ptr<cv::Vec3b>(row);
        for (int column = 0; column < kYolo26InputWidth; ++column) {
            const auto offset = static_cast<std::size_t>(row) * kYolo26InputWidth + column;
            tensor[offset] = static_cast<float>(pixels[column][red]) / 255.0F;
            tensor[plane + offset] = static_cast<float>(pixels[column][1]) / 255.0F;
            tensor[2 * plane + offset] = static_cast<float>(pixels[column][blue]) / 255.0F;
        }
    }
    return {std::move(tensor), geometry};
}

}  // namespace edge_vision
