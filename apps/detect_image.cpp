#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <cmath>
#include <exception>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "edge_vision/frame.hpp"
#include "edge_vision/yolox_detector.hpp"

namespace {

edge_vision::Frame make_frame(const cv::Mat& image) {
    cv::Mat contiguous = image.isContinuous() ? image : image.clone();
    edge_vision::Frame frame;
    frame.width = contiguous.cols;
    frame.height = contiguous.rows;
    frame.channels = contiguous.channels();
    frame.format = edge_vision::PixelFormat::bgr8;
    frame.data.assign(
        contiguous.data,
        contiguous.data + contiguous.total() * contiguous.elemSize());
    return frame;
}

cv::Rect to_rectangle(
    const edge_vision::BoundingBox& box,
    const cv::Size& image_size) {
    const int x = std::clamp(
        static_cast<int>(std::lround(box.x)), 0, image_size.width - 1);
    const int y = std::clamp(
        static_cast<int>(std::lround(box.y)), 0, image_size.height - 1);
    const int right = std::clamp(
        static_cast<int>(std::lround(box.x + box.width)),
        x + 1,
        image_size.width);
    const int bottom = std::clamp(
        static_cast<int>(std::lround(box.y + box.height)),
        y + 1,
        image_size.height);
    return {x, y, right - x, bottom - y};
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "Usage: " << argv[0]
                  << " ENGINE_PATH INPUT_IMAGE OUTPUT_IMAGE\n";
        return 2;
    }

    try {
        cv::Mat image = cv::imread(argv[2], cv::IMREAD_COLOR);
        if (image.empty()) {
            throw std::runtime_error(
                std::string("Failed to read input image: ") + argv[2]);
        }

        edge_vision::YoloXDetector detector(argv[1]);
        const auto detections = detector.infer(make_frame(image));

        std::cout << std::fixed << std::setprecision(3);
        std::cout << "image=" << image.cols << 'x' << image.rows << '\n';
        std::cout << "detections=" << detections.size() << '\n';

        for (const auto& detection : detections) {
            const cv::Rect rectangle = to_rectangle(detection.box, image.size());
            const std::string label =
                "class=" + std::to_string(detection.class_id) +
                " score=" + std::to_string(detection.confidence).substr(0, 5);

            cv::rectangle(image, rectangle, cv::Scalar(0, 255, 0), 2);
            cv::putText(
                image,
                label,
                cv::Point(rectangle.x, std::max(18, rectangle.y - 5)),
                cv::FONT_HERSHEY_SIMPLEX,
                0.5,
                cv::Scalar(0, 255, 0),
                1,
                cv::LINE_AA);

            std::cout << "class=" << detection.class_id
                      << " score=" << detection.confidence
                      << " box=" << detection.box.x << ','
                      << detection.box.y << ','
                      << detection.box.width << ','
                      << detection.box.height << '\n';
        }

        if (!cv::imwrite(argv[3], image)) {
            throw std::runtime_error(
                std::string("Failed to write output image: ") + argv[3]);
        }
        std::cout << "saved=" << argv[3] << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Image detection failed: " << error.what() << '\n';
        return 1;
    }
}
