#pragma once

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

std::unique_ptr<IFrameSource> make_gstreamer_file_source(
    const std::string& path);
std::unique_ptr<IFrameSource> make_gstreamer_csi_source(
    const CsiCameraConfig& config);

}  // namespace edge_vision
