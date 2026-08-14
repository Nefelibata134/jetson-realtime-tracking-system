#include "edge_vision/annotated_video_writer.hpp"

#include <opencv2/imgproc.hpp>
#include <opencv2/videoio.hpp>

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace edge_vision {
namespace {

cv::Mat frame_to_bgr(const Frame& frame) {
    if (!frame.valid() || frame.channels != 3) {
        throw std::invalid_argument(
            "video output requires a valid three-channel frame");
    }

    const cv::Mat view(
        frame.height,
        frame.width,
        CV_8UC3,
        const_cast<std::uint8_t*>(frame.data.data()));
    if (frame.format == PixelFormat::bgr8) {
        return view.clone();
    }

    cv::Mat bgr;
    cv::cvtColor(view, bgr, cv::COLOR_RGB2BGR);
    return bgr;
}

cv::Rect to_rectangle(const BoundingBox& box, const cv::Size& image_size) {
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

cv::Scalar track_color(const std::int64_t track_id) {
    const auto seed = static_cast<std::uint64_t>(track_id) * 2'654'435'761ULL;
    return {
        static_cast<double>(64U + (seed & 0x7FU)),
        static_cast<double>(64U + ((seed >> 8U) & 0x7FU)),
        static_cast<double>(64U + ((seed >> 16U) & 0x7FU)),
    };
}

std::string track_label(const Track& track) {
    std::ostringstream label;
    label << "ID " << track.track_id << " class " << track.class_id << ' '
          << std::fixed << std::setprecision(2) << track.confidence;
    return label.str();
}

void draw_label(
    cv::Mat& image,
    const cv::Rect& rectangle,
    const std::string& label,
    const cv::Scalar& color) {
    constexpr double font_scale = 0.5;
    constexpr int thickness = 1;
    int baseline = 0;
    const cv::Size text_size = cv::getTextSize(
        label,
        cv::FONT_HERSHEY_SIMPLEX,
        font_scale,
        thickness,
        &baseline);

    const int label_x = rectangle.x;
    const int label_top = std::max(0, rectangle.y - text_size.height - 8);
    const int label_right = std::min(
        image.cols - 1, label_x + text_size.width + 8);
    const int label_bottom = std::min(
        image.rows - 1, label_top + text_size.height + baseline + 8);

    cv::rectangle(
        image,
        cv::Point(label_x, label_top),
        cv::Point(label_right, label_bottom),
        color,
        cv::FILLED);
    cv::putText(
        image,
        label,
        cv::Point(label_x + 4, label_bottom - baseline - 4),
        cv::FONT_HERSHEY_SIMPLEX,
        font_scale,
        cv::Scalar(255, 255, 255),
        thickness,
        cv::LINE_AA);
}

}  // namespace

class AnnotatedVideoWriter::Impl {
public:
    explicit Impl(AnnotatedVideoWriterConfig config)
        : config_(std::move(config)) {
        if (config_.output_path.empty()) {
            throw std::invalid_argument("video output path must not be empty");
        }
        if (!std::isfinite(config_.frames_per_second) ||
            config_.frames_per_second <= 0.0) {
            throw std::invalid_argument("video output FPS must be positive");
        }
    }

    void write(const Frame& frame, const std::vector<Track>& tracks) {
        cv::Mat image = frame_to_bgr(frame);
        open_if_needed(image.size());
        if (image.size() != frame_size_) {
            throw std::invalid_argument(
                "video output frame dimensions changed during the stream");
        }

        for (const Track& track : tracks) {
            if (track.box.width <= 0.0F || track.box.height <= 0.0F) {
                continue;
            }
            const cv::Rect rectangle = to_rectangle(track.box, image.size());
            const cv::Scalar color = track_color(track.track_id);
            cv::rectangle(image, rectangle, color, 2, cv::LINE_AA);
            draw_label(image, rectangle, track_label(track), color);
        }

        writer_.write(image);
        ++frames_written_;
    }

    void close() noexcept {
        if (writer_.isOpened()) {
            writer_.release();
        }
    }

    [[nodiscard]] std::uint64_t frames_written() const noexcept {
        return frames_written_;
    }

    [[nodiscard]] const std::string& output_path() const noexcept {
        return config_.output_path;
    }

private:
    void open_if_needed(const cv::Size& frame_size) {
        if (writer_.isOpened()) {
            return;
        }

        const std::filesystem::path path(config_.output_path);
        if (path.has_parent_path()) {
            std::filesystem::create_directories(path.parent_path());
        }

        const int codec = cv::VideoWriter::fourcc('m', 'p', '4', 'v');
        if (!writer_.open(
                config_.output_path,
                codec,
                config_.frames_per_second,
                frame_size,
                true)) {
            throw std::runtime_error(
                "failed to open annotated video output: " +
                config_.output_path);
        }
        frame_size_ = frame_size;
    }

    AnnotatedVideoWriterConfig config_;
    cv::VideoWriter writer_;
    cv::Size frame_size_;
    std::uint64_t frames_written_{0};
};

AnnotatedVideoWriter::AnnotatedVideoWriter(AnnotatedVideoWriterConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}

AnnotatedVideoWriter::~AnnotatedVideoWriter() {
    close();
}

void AnnotatedVideoWriter::write(
    const Frame& frame,
    const std::vector<Track>& tracks) {
    impl_->write(frame, tracks);
}

void AnnotatedVideoWriter::close() noexcept {
    impl_->close();
}

std::uint64_t AnnotatedVideoWriter::frames_written() const noexcept {
    return impl_->frames_written();
}

const std::string& AnnotatedVideoWriter::output_path() const noexcept {
    return impl_->output_path();
}

}  // namespace edge_vision
