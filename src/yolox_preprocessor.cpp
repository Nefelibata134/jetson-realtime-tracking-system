#include "edge_vision/yolox_preprocessor.hpp"

#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <cstddef>
#include <stdexcept>
#include <utility>

namespace edge_vision {

YoloXPreprocessor::YoloXPreprocessor(
    int target_width,
    int target_height,
    std::uint8_t padding_value)
    : target_width_(target_width),
      target_height_(target_height),
      padding_value_(padding_value) {
    if (target_width_ <= 0 || target_height_ <= 0) {
        throw std::invalid_argument("YOLOX target dimensions must be positive");
    }
}

YoloXPreprocessResult YoloXPreprocessor::run(const Frame& frame) const {
    if (!frame.valid()) {
        throw std::invalid_argument("YOLOX preprocessing received an invalid frame");
    }
    if (frame.channels != 3) {
        throw std::invalid_argument("YOLOX preprocessing requires three channels");
    }

    const double scale = std::min(
        static_cast<double>(target_height_) / static_cast<double>(frame.height),
        static_cast<double>(target_width_) / static_cast<double>(frame.width));
    const int resized_width = static_cast<int>(
        static_cast<double>(frame.width) * scale);
    const int resized_height = static_cast<int>(
        static_cast<double>(frame.height) * scale);

    const cv::Mat source(
        frame.height,
        frame.width,
        CV_8UC3,
        const_cast<std::uint8_t*>(frame.data.data()));

    cv::Mat bgr_source;
    if (frame.format == PixelFormat::rgb8) {
        cv::cvtColor(source, bgr_source, cv::COLOR_RGB2BGR);
    } else {
        bgr_source = source;
    }

    cv::Mat resized;
    cv::resize(
        bgr_source,
        resized,
        cv::Size(resized_width, resized_height),
        0.0,
        0.0,
        cv::INTER_LINEAR);

    cv::Mat padded(
        target_height_,
        target_width_,
        CV_8UC3,
        cv::Scalar(padding_value_, padding_value_, padding_value_));
    resized.copyTo(padded(cv::Rect(0, 0, resized_width, resized_height)));

    const std::size_t plane_size =
        static_cast<std::size_t>(target_width_) *
        static_cast<std::size_t>(target_height_);
    std::vector<float> tensor(3 * plane_size);

    for (int row = 0; row < target_height_; ++row) {
        const auto* pixels = padded.ptr<cv::Vec3b>(row);
        for (int column = 0; column < target_width_; ++column) {
            const std::size_t offset =
                static_cast<std::size_t>(row) *
                    static_cast<std::size_t>(target_width_) +
                static_cast<std::size_t>(column);
            tensor[offset] = static_cast<float>(pixels[column][0]);
            tensor[plane_size + offset] = static_cast<float>(pixels[column][1]);
            tensor[2 * plane_size + offset] =
                static_cast<float>(pixels[column][2]);
        }
    }

    return {
        std::move(tensor),
        static_cast<float>(scale),
        resized_width,
        resized_height,
        target_width_ - resized_width,
        target_height_ - resized_height,
    };
}

int YoloXPreprocessor::target_width() const noexcept {
    return target_width_;
}

int YoloXPreprocessor::target_height() const noexcept {
    return target_height_;
}

}  // namespace edge_vision
