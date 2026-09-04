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
#include "edge_vision/detector_factory.hpp"

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
    if (argc < 4) {
        std::cerr << "Usage: " << argv[0]
                  << " ENGINE_PATH INPUT_IMAGE OUTPUT_IMAGE [--detector yolox|yolo26]"
                  << " [--score-threshold VALUE] [--nms-threshold VALUE]\n";
        return 2;
    }

    try {
        edge_vision::DetectorConfig config;
        bool score_explicit = false;
        bool nms_explicit = false;
        for (int index = 4; index < argc; ++index) {
            const std::string option = argv[index];
            if (++index >= argc) {
                throw std::invalid_argument("missing value for " + option);
            }
            const std::string value = argv[index];
            if (option == "--detector") {
                config.kind = edge_vision::parse_detector_kind(value);
            } else if (option == "--score-threshold" || option == "--nms-threshold") {
                std::size_t parsed = 0;
                const float threshold = std::stof(value, &parsed);
                if (parsed != value.size() || !std::isfinite(threshold) ||
                    threshold < 0.0F || threshold > 1.0F) {
                    throw std::invalid_argument("invalid threshold for " + option);
                }
                if (option == "--score-threshold") {
                    config.score_threshold = threshold;
                    score_explicit = true;
                } else {
                    config.nms_threshold = threshold;
                    nms_explicit = true;
                }
            } else {
                throw std::invalid_argument("unknown option: " + option);
            }
        }
        if (config.kind == edge_vision::DetectorKind::Yolo26 && (!score_explicit || !nms_explicit)) {
            throw std::invalid_argument("YOLO26 requires explicit score and NMS thresholds");
        }
        cv::Mat image = cv::imread(argv[2], cv::IMREAD_COLOR);
        if (image.empty()) {
            throw std::runtime_error(
                std::string("Failed to read input image: ") + argv[2]);
        }

        auto detector = edge_vision::make_detector(argv[1], config);
        const auto detections = detector->infer(make_frame(image));

        std::cout << std::fixed << std::setprecision(3);
        std::cout << "detector=" << edge_vision::detector_kind_name(config.kind) << '\n';
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
