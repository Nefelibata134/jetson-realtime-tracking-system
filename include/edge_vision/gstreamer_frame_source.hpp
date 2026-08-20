#pragma once

#include <cstdint>
#include <memory>
#include <string>

#include "edge_vision/frame_source.hpp"

namespace edge_vision {

struct CsiCameraConfig {
    int sensor_id{0};
    int sensor_mode{-1};
    int capture_width{0};
    int capture_height{0};
    int capture_frames_per_second{0};
    int width{1280};
    int height{720};
    int frames_per_second{30};
};

enum class RtspTransport {
    tcp,
    udp,
};

struct RtspStreamConfig {
    std::string uri;
    RtspTransport transport{RtspTransport::tcp};
    std::uint64_t latency_ms{200};
    std::uint64_t read_timeout_ms{5000};
    int width{1280};
    int height{720};
    int frames_per_second{30};
};

std::unique_ptr<IFrameSource> make_gstreamer_file_source(
    const std::string& path);
std::unique_ptr<IFrameSource> make_gstreamer_csi_source(
    const CsiCameraConfig& config);
std::string build_gstreamer_rtsp_pipeline(const RtspStreamConfig& config);
std::unique_ptr<IFrameSource> make_gstreamer_rtsp_source(
    const RtspStreamConfig& config);

}  // namespace edge_vision
