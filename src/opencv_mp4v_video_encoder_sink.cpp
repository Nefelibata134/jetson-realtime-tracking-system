#include "video_encoder_sink.hpp"

#include <opencv2/videoio.hpp>

#include <memory>
#include <stdexcept>
#include <utility>

namespace edge_vision::detail {
namespace {

class OpenCvMp4vSink final : public VideoEncoderSink {
public:
    OpenCvMp4vSink(
        std::string output_path,
        const double frames_per_second,
        const cv::Size& frame_size)
        : output_path_(std::move(output_path)), frame_size_(frame_size) {
        const int codec = cv::VideoWriter::fourcc('m', 'p', '4', 'v');
        if (!writer_.open(
                output_path_,
                codec,
                frames_per_second,
                frame_size_,
                true)) {
            throw std::runtime_error(
                "failed to open MP4V video output: " + output_path_);
        }
    }

    ~OpenCvMp4vSink() override {
        finish();
    }

    void write(const cv::Mat& image) override {
        if (image.size() != frame_size_) {
            throw std::invalid_argument(
                "video output frame dimensions changed during the stream");
        }
        writer_.write(image);
    }

    void finish() override {
        if (writer_.isOpened()) {
            writer_.release();
        }
    }

private:
    std::string output_path_;
    cv::Size frame_size_;
    cv::VideoWriter writer_;
};

}  // namespace

std::unique_ptr<VideoEncoderSink> make_opencv_mp4v_sink(
    const std::string& output_path,
    const double frames_per_second,
    const cv::Size& frame_size) {
    return std::make_unique<OpenCvMp4vSink>(
        output_path,
        frames_per_second,
        frame_size);
}

}  // namespace edge_vision::detail
