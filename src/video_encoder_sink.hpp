#pragma once

#include <memory>
#include <string>

#include <opencv2/core/mat.hpp>
#include <opencv2/core/types.hpp>

namespace edge_vision::detail {

class VideoEncoderSink {
public:
    virtual ~VideoEncoderSink() = default;

    virtual void write(const cv::Mat& image) = 0;
    virtual void finish() = 0;
};

std::unique_ptr<VideoEncoderSink> make_opencv_mp4v_sink(
    const std::string& output_path,
    double frames_per_second,
    const cv::Size& frame_size);

#if defined(EDGE_VISION_HAS_GSTREAMER_X264)
std::unique_ptr<VideoEncoderSink> make_gstreamer_x264_sink(
    const std::string& output_path,
    double frames_per_second,
    const cv::Size& frame_size,
    unsigned int bitrate_kbps);
#endif

}  // namespace edge_vision::detail
