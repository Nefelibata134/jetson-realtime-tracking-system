#include <iostream>
#include <stdexcept>
#include <string>

#include "edge_vision/gstreamer_frame_source.hpp"

namespace {

bool contains(const std::string& text, const std::string& expected) {
    return text.find(expected) != std::string::npos;
}

bool check_tcp_pipeline() {
    edge_vision::RtspStreamConfig config;
    config.uri = "rtsp://user:secret@127.0.0.1:8554/test";
    config.transport = edge_vision::RtspTransport::tcp;
    config.latency_ms = 150;
    config.read_timeout_ms = 2500;
    config.width = 1280;
    config.height = 720;
    config.frames_per_second = 30;

    const std::string pipeline =
        edge_vision::build_gstreamer_rtsp_pipeline(config);
    return contains(pipeline, "rtspsrc location=") &&
           contains(pipeline, "protocols=tcp") &&
           contains(pipeline, "latency=150") &&
           contains(pipeline, "tcp-timeout=2500000") &&
           contains(pipeline, "rtph264depay ! h264parse ! nvv4l2decoder") &&
           contains(pipeline, "width=1280,height=720") &&
           contains(pipeline, "framerate=30/1") &&
           contains(pipeline, "appsink name=framesink");
}

bool check_udp_pipeline() {
    edge_vision::RtspStreamConfig config;
    config.uri = "rtsp://127.0.0.1:8554/test";
    config.transport = edge_vision::RtspTransport::udp;
    config.read_timeout_ms = 1000;

    const std::string pipeline =
        edge_vision::build_gstreamer_rtsp_pipeline(config);
    return contains(pipeline, "protocols=udp") &&
           contains(pipeline, "timeout=1000000") &&
           !contains(pipeline, "tcp-timeout=");
}

bool check_invalid_config() {
    edge_vision::RtspStreamConfig config;
    config.uri = "http://127.0.0.1/video";
    try {
        static_cast<void>(
            edge_vision::build_gstreamer_rtsp_pipeline(config));
    } catch (const std::invalid_argument&) {
        return true;
    }
    return false;
}

}  // namespace

int main() {
    const bool tcp_pipeline = check_tcp_pipeline();
    const bool udp_pipeline = check_udp_pipeline();
    const bool invalid_config = check_invalid_config();

    std::cout << "tcp_pipeline=" << std::boolalpha << tcp_pipeline << '\n';
    std::cout << "udp_pipeline=" << udp_pipeline << '\n';
    std::cout << "invalid_config=" << invalid_config << '\n';

    const bool passed = tcp_pipeline && udp_pipeline && invalid_config;
    std::cout << "status=" << (passed ? "PASS" : "FAIL") << '\n';
    return passed ? 0 : 1;
}
