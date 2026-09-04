#include <cmath>
#include <cstdint>
#include <exception>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <type_traits>
#include <vector>

#include "edge_vision/detector_factory.hpp"
#include "edge_vision/yolo26_contract.hpp"
#include "edge_vision/yolo26_postprocessor.hpp"
#include "edge_vision/yolo26_preprocessor.hpp"
#include "edge_vision/yolox_detector.hpp"

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

bool close(float a, float b) {
    return std::fabs(a - b) < 1.0e-4F;
}

template <typename Function>
void require_rejected(Function function, const char* message) {
    try {
        function();
    } catch (const std::invalid_argument&) {
        return;
    }
    throw std::runtime_error(message);
}

edge_vision::Frame uniform_frame(
    int width, int height, edge_vision::PixelFormat format) {
    edge_vision::Frame frame;
    frame.width = width;
    frame.height = height;
    frame.channels = 3;
    frame.format = format;
    frame.data.resize(frame.expected_bytes());
    for (std::size_t i = 0; i < frame.data.size(); i += 3) {
        frame.data[i] = 10;
        frame.data[i + 1] = 20;
        frame.data[i + 2] = 30;
    }
    return frame;
}

std::vector<float> empty_output() {
    return std::vector<float>(
        edge_vision::kYolo26Candidates * edge_vision::kYolo26OutputChannels, 0.0F);
}

void candidate(std::vector<float>& output, std::size_t index,
               float cx, float cy, float width, float height, int category, float score) {
    constexpr auto count = edge_vision::kYolo26Candidates;
    output[index] = cx;
    output[count + index] = cy;
    output[2 * count + index] = width;
    output[3 * count + index] = height;
    output[(4 + category) * count + index] = score;
}

class ProfiledFixture final : public edge_vision::IProfiledDetector {
public:
    edge_vision::DetectorResult infer_profiled(const edge_vision::Frame&) override {
        return {{{{1.0F, 2.0F, 3.0F, 4.0F}, 0, 0.8F}}, {1.0, 2.0, 3.0, 6.0}};
    }
};

void check_interface_and_contract() {
    using namespace edge_vision;
    static_assert(std::is_same_v<YoloXDetectorResult, DetectorResult>);
    static_assert(std::is_same_v<YoloXDetectorStageTiming, DetectorStageTiming>);
    ProfiledFixture fixture;
    IDetector& detector = fixture;
    require(detector.infer({}).size() == 1, "profiled detector lost the inference interface");
    require(fixture.infer_profiled({}).timing.tensorrt_inference_ms == 2.0,
            "profiled timing contract changed");
    require(DetectorConfig{}.kind == DetectorKind::YoloX, "default detector changed");
    require(!DetectorConfig{}.score_threshold.has_value() &&
            !DetectorConfig{}.nms_threshold.has_value(), "candidate thresholds became implicit");
    require(parse_detector_kind("yolo26") == DetectorKind::Yolo26, "candidate selector failed");
    require(parse_detector_kind("yolox") == DetectorKind::YoloX, "baseline selector failed");
    require_rejected([] { static_cast<void>(parse_detector_kind("automatic")); },
                     "unknown detector selector was accepted");
    const TensorContract input{"images", {1, 3, 640, 640}};
    const TensorContract output{"output0", {1, 84, 8400}};
    validate_yolo26_contracts(input, output);
    require_rejected([&] { validate_yolo26_contracts({"images", {1, 3, 416, 416}}, output); },
                     "incorrect input shape was accepted");
    for (const std::vector<std::int64_t>& shape : {
             std::vector<std::int64_t>{1, 300, 6}, {1, 8400, 84},
             {1, 3549, 85}, {-1, 84, 8400}, {2, 84, 8400}}) {
        require_rejected([&] { validate_yolo26_contracts(input, {"output", shape}); },
                         "incorrect output shape was accepted");
    }
}

void check_preprocessing() {
    using namespace edge_vision;
    const Yolo26Preprocessor preprocessor;
    const auto result = preprocessor.run(uniform_frame(1280, 720, PixelFormat::bgr8));
    const auto& geometry = result.letterbox;
    constexpr std::size_t plane = 640 * 640;
    require(result.tensor.size() == 3 * plane, "input tensor size mismatch");
    require(close(geometry.scale, 0.5F), "letterbox scale mismatch");
    require(geometry.resized_width == 640 && geometry.resized_height == 360,
            "resize dimensions mismatch");
    require(geometry.pad_left == 0 && geometry.pad_right == 0 &&
            geometry.pad_top == 140 && geometry.pad_bottom == 140,
            "letterbox was not centered");
    constexpr std::size_t pixel = 140 * 640;
    require(close(result.tensor[pixel], 30.0F / 255.0F), "RGB red normalization failed");
    require(close(result.tensor[plane + pixel], 20.0F / 255.0F), "green normalization failed");
    require(close(result.tensor[2 * plane + pixel], 10.0F / 255.0F), "RGB blue normalization failed");
    require(close(result.tensor[0], 114.0F / 255.0F), "top padding normalization failed");
    require(close(result.tensor[plane - 1], 114.0F / 255.0F), "bottom padding failed");
    const auto rgb = preprocessor.run(uniform_frame(1, 1, PixelFormat::rgb8));
    require(close(rgb.tensor[0], 10.0F / 255.0F) &&
            close(rgb.tensor[2 * plane], 30.0F / 255.0F), "RGB input was reordered");
    const auto odd = make_yolo26_letterbox(640, 479);
    require(odd.pad_top == 80 && odd.pad_bottom == 81, "odd padding mismatch");
    const auto portrait = make_yolo26_letterbox(480, 640);
    require(portrait.pad_left == 80 && portrait.pad_right == 80, "portrait padding mismatch");
    require(make_yolo26_letterbox(1280, 721).resized_height == 360,
            "half-even rounding down mismatch");
    require(make_yolo26_letterbox(1280, 723).resized_height == 362,
            "half-even rounding up mismatch");
    require_rejected([&] { static_cast<void>(preprocessor.run({})); }, "invalid frame accepted");
    auto invalid = uniform_frame(1, 1, PixelFormat::rgb8);
    invalid.format = static_cast<PixelFormat>(99);
    require_rejected([&] { static_cast<void>(preprocessor.run(invalid)); }, "invalid format accepted");
}

void check_postprocessing() {
    using namespace edge_vision;
    const Yolo26Postprocessor processor({0.3F, 0.45F, 300});
    const auto geometry = make_yolo26_letterbox(1280, 720);
    auto output = empty_output();
    require(processor.run(output, geometry).empty(), "empty output produced detections");
    candidate(output, 0, 320, 320, 100, 100, 0, 0.9F);
    candidate(output, 1, 320, 320, 100, 100, 0, 0.8F);
    candidate(output, 2, 320, 320, 100, 100, 2, 0.85F);
    candidate(output, 3, 200, 200, -20, 20, 0, 0.99F);
    candidate(output, 4, std::numeric_limits<float>::quiet_NaN(), 200, 20, 20, 0, 0.98F);
    candidate(output, 5, 200, 200, 20, 20, 0, 0.3F);
    candidate(output, 6, 200, 200, 20, 0, 0, 0.97F);
    candidate(output, 7, 200, 200, 20, 20, 0, std::numeric_limits<float>::infinity());
    const auto detections = processor.run(output, geometry);
    require(detections.size() == 2, "class-aware NMS or invalid-value filtering failed");
    const auto& first = detections[0];
    require(first.class_id == 0 && close(first.confidence, 0.9F), "score used objectness or sigmoid twice");
    require(close(first.box.x, 540) && close(first.box.y, 260) &&
            close(first.box.width, 200) && close(first.box.height, 200),
            "xywh decoding or letterbox reversal failed");
    require(detections[1].class_id == 2, "different classes suppressed one another");
    require_rejected([&] { static_cast<void>(processor.run({}, geometry)); }, "invalid tensor length accepted");
    auto invalid = geometry;
    ++invalid.pad_top;
    require_rejected([&] { static_cast<void>(processor.run(output, invalid)); }, "invalid geometry accepted");
    require_rejected([] {
        const Yolo26Postprocessor bad({std::numeric_limits<float>::quiet_NaN(), 0.45F, 300});
    }, "NaN threshold accepted");
    require_rejected([] { const Yolo26Postprocessor bad({0.3F, 0.45F, 0}); }, "zero limit accepted");

    const auto square = make_yolo26_letterbox(640, 640);
    output = empty_output();
    candidate(output, 0, 0, 20, 40, 40, 0, 0.9F);
    candidate(output, 1, 10, 20, 20, 40, 0, 0.8F);
    const auto unclipped_nms = Yolo26Postprocessor({0.3F, 0.6F, 300}).run(output, square);
    require(unclipped_nms.size() == 2, "NMS clipped boxes too early");
    require(close(unclipped_nms[0].box.x, 0) && close(unclipped_nms[0].box.width, 20),
            "final clipping failed");

    output = empty_output();
    candidate(output, 0, 100.5F, 100.5F, 1, 1, 0, 0.9F);
    candidate(output, 1, 101.5F, 100.5F, 1, 1, 0, 0.9F);
    const auto touching = Yolo26Postprocessor({0.3F, 0.0F, 300}).run(output, square);
    require(touching.size() == 2, "NMS used inclusive pixel-area semantics");
    const auto limited = Yolo26Postprocessor({0.3F, 0.0F, 1}).run(output, square);
    require(limited.size() == 1 && close(limited[0].box.x, 100), "limit or stable tie ordering failed");
}

}  // namespace

int main() {
    try {
        check_interface_and_contract();
        check_preprocessing();
        check_postprocessing();
        std::cout << "contract=1x3x640x640_to_1x84x8400\n"
                  << "preprocess=RGB_normalized_centered_letterbox\n"
                  << "postprocess=xywh_class_scores_class_aware_nms\n"
                  << "status=PASS\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "YOLO26 contract check failed: " << error.what() << '\n';
        return 1;
    }
}
