#include <cstdint>
#include <iostream>
#include <vector>

#include "edge_vision/detector.hpp"

namespace {

class StaticDetector final : public edge_vision::IDetector {
public:
    std::vector<edge_vision::Detection> infer(
        const edge_vision::Frame& frame) override {
        if (!frame.valid()) {
            return {};
        }

        return {{{0.0F, 0.0F, static_cast<float>(frame.width),
                   static_cast<float>(frame.height)},
                 0,
                 1.0F}};
    }
};

}  // namespace

int main() {
    edge_vision::Frame frame;
    frame.width = 2;
    frame.height = 2;
    frame.channels = 3;
    frame.pts_ns = 33'333'333;
    frame.sequence = 1;
    frame.data = std::vector<std::uint8_t>(12, 0);

    StaticDetector detector;
    const auto detections = detector.infer(frame);

    std::cout << "frame_valid=" << std::boolalpha << frame.valid() << '\n';
    std::cout << "frame_bytes=" << frame.data.size() << '\n';
    std::cout << "detections=" << detections.size() << '\n';

    return frame.valid() && detections.size() == 1 ? 0 : 1;
}

