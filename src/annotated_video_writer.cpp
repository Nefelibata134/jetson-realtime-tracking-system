#include "edge_vision/annotated_video_writer.hpp"

#include "video_encoder_sink.hpp"

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cmath>
#include <deque>
#include <exception>
#include <filesystem>
#include <iterator>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <utility>

namespace edge_vision {

class AnnotatedVideoWriter::Impl {
public:
    explicit Impl(AnnotatedVideoWriterConfig config)
        : config_(std::move(config)),
          annotation_config_{
              config_.event_regions,
              config_.event_lines,
          } {
        if (config_.output_path.empty()) {
            throw std::invalid_argument("video output path must not be empty");
        }
        if (!std::isfinite(config_.frames_per_second) ||
            config_.frames_per_second <= 0.0) {
            throw std::invalid_argument("video output FPS must be positive");
        }
        if (config_.queue_capacity == 0) {
            throw std::invalid_argument(
                "video output queue capacity must be positive");
        }
        if (!std::isfinite(config_.event_label_duration_seconds) ||
            config_.event_label_duration_seconds <= 0.0) {
            throw std::invalid_argument(
                "event label duration must be positive");
        }
        if (config_.encoder == AnnotatedVideoEncoder::GStreamerX264 &&
            config_.bitrate_kbps == 0) {
            throw std::invalid_argument("x264 bitrate must be positive");
        }
        if (config_.encoder != AnnotatedVideoEncoder::OpenCvMp4v &&
            config_.encoder != AnnotatedVideoEncoder::GStreamerX264) {
            throw std::invalid_argument("unsupported annotated video encoder");
        }
        worker_ = std::thread(&Impl::run, this);
    }

    void write(
        const Frame& frame,
        const std::vector<Track>& tracks,
        const std::vector<SafetyEvent>& events) {
        if (!frame.valid() || frame.channels != 3) {
            throw std::invalid_argument(
                "video output requires a valid three-channel frame");
        }

        Packet packet{frame, tracks, events};
        std::lock_guard<std::mutex> lock(mutex_);
        rethrow_worker_error_locked();
        if (stop_requested_) {
            throw std::runtime_error("annotated video writer is closed");
        }

        if (queue_.size() == config_.queue_capacity) {
            packet.events.insert(
                packet.events.begin(),
                std::make_move_iterator(queue_.front().events.begin()),
                std::make_move_iterator(queue_.front().events.end()));
            queue_.pop_front();
            ++stats_.frames_dropped;
        }
        queue_.push_back(std::move(packet));
        ++stats_.frames_submitted;
        stats_.queue_high_watermark =
            std::max(stats_.queue_high_watermark, queue_.size());
        ready_.notify_one();
    }

    void finish() {
        request_stop();
        join_worker();

        std::lock_guard<std::mutex> lock(mutex_);
        rethrow_worker_error_locked();
    }

    void close() noexcept {
        request_stop();
        join_worker();
    }

    [[nodiscard]] AnnotatedVideoWriterStats stats() const noexcept {
        std::lock_guard<std::mutex> lock(mutex_);
        return stats_;
    }

    [[nodiscard]] std::uint64_t frames_written() const noexcept {
        return stats().frames_written;
    }

    [[nodiscard]] const std::string& output_path() const noexcept {
        return config_.output_path;
    }

private:
    struct Packet {
        Frame frame;
        std::vector<Track> tracks;
        std::vector<SafetyEvent> events;
    };

    struct ActiveEvent {
        SafetyEvent event;
        std::uint64_t expires_after_sequence{0};
    };

    void run() noexcept {
        try {
            while (true) {
                Packet packet;
                {
                    std::unique_lock<std::mutex> lock(mutex_);
                    ready_.wait(lock, [this] {
                        return stop_requested_ || !queue_.empty();
                    });
                    if (queue_.empty()) {
                        break;
                    }
                    packet = std::move(queue_.front());
                    queue_.pop_front();
                }

                const auto encoding_started_at =
                    std::chrono::steady_clock::now();
                write_packet(packet);
                const double encoding_ms =
                    std::chrono::duration<double, std::milli>(
                        std::chrono::steady_clock::now() -
                        encoding_started_at)
                        .count();
                {
                    std::lock_guard<std::mutex> lock(mutex_);
                    ++stats_.frames_written;
                    stats_.encoding_total_ms += encoding_ms;
                    stats_.encoding_max_ms =
                        std::max(stats_.encoding_max_ms, encoding_ms);
                }
            }
            if (encoder_) {
                encoder_->finish();
            }
        } catch (...) {
            std::lock_guard<std::mutex> lock(mutex_);
            worker_error_ = std::current_exception();
            stats_.frames_dropped += queue_.size();
            queue_.clear();
            stop_requested_ = true;
        }
    }

    void write_packet(const Packet& packet) {
        const auto label_frames = static_cast<std::uint64_t>(std::max(
            1.0,
            std::round(
                config_.frames_per_second *
                config_.event_label_duration_seconds)));
        for (const SafetyEvent& event : packet.events) {
            active_events_.push_back({
                event,
                packet.frame.sequence + label_frames,
            });
        }
        active_events_.erase(
            std::remove_if(
                active_events_.begin(),
                active_events_.end(),
                [&](const ActiveEvent& event) {
                    return packet.frame.sequence >
                           event.expires_after_sequence;
                }),
            active_events_.end());
        std::vector<SafetyEvent> visible_events;
        visible_events.reserve(active_events_.size());
        for (const ActiveEvent& active : active_events_) {
            visible_events.push_back(active.event);
        }

        Frame annotated = annotate_frame(
            packet.frame,
            packet.tracks,
            visible_events,
            annotation_config_);
        cv::Mat image(
            annotated.height,
            annotated.width,
            CV_8UC3,
            annotated.data.data());
        open_if_needed(image.size());
        encoder_->write(image);
    }

    void request_stop() noexcept {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            stop_requested_ = true;
        }
        ready_.notify_all();
    }

    void join_worker() noexcept {
        if (worker_.joinable()) {
            worker_.join();
        }
    }

    void rethrow_worker_error_locked() const {
        if (worker_error_) {
            std::rethrow_exception(worker_error_);
        }
    }

    void open_if_needed(const cv::Size& frame_size) {
        if (encoder_) {
            return;
        }

        const std::filesystem::path path(config_.output_path);
        if (path.has_parent_path()) {
            std::filesystem::create_directories(path.parent_path());
        }

        switch (config_.encoder) {
            case AnnotatedVideoEncoder::OpenCvMp4v:
                encoder_ = detail::make_opencv_mp4v_sink(
                    config_.output_path,
                    config_.frames_per_second,
                    frame_size);
                break;
            case AnnotatedVideoEncoder::GStreamerX264:
#if defined(EDGE_VISION_HAS_GSTREAMER_X264)
                encoder_ = detail::make_gstreamer_x264_sink(
                    config_.output_path,
                    config_.frames_per_second,
                    frame_size,
                    config_.bitrate_kbps);
#else
                throw std::runtime_error(
                    "x264 video output requires a build configured with "
                    "EDGE_VISION_ENABLE_GSTREAMER=ON");
#endif
                break;
        }
    }

    AnnotatedVideoWriterConfig config_;
    FrameAnnotationConfig annotation_config_;
    std::unique_ptr<detail::VideoEncoderSink> encoder_;
    mutable std::mutex mutex_;
    std::condition_variable ready_;
    std::deque<Packet> queue_;
    std::vector<ActiveEvent> active_events_;
    std::thread worker_;
    std::exception_ptr worker_error_;
    AnnotatedVideoWriterStats stats_;
    bool stop_requested_{false};
};

std::string_view annotated_video_encoder_name(
    const AnnotatedVideoEncoder encoder) noexcept {
    switch (encoder) {
        case AnnotatedVideoEncoder::OpenCvMp4v:
            return "mp4v";
        case AnnotatedVideoEncoder::GStreamerX264:
            return "x264";
    }
    return "unknown";
}

AnnotatedVideoWriter::AnnotatedVideoWriter(AnnotatedVideoWriterConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}

AnnotatedVideoWriter::~AnnotatedVideoWriter() {
    close();
}

void AnnotatedVideoWriter::write(
    const Frame& frame,
    const std::vector<Track>& tracks,
    const std::vector<SafetyEvent>& events) {
    impl_->write(frame, tracks, events);
}

void AnnotatedVideoWriter::finish() {
    impl_->finish();
}

void AnnotatedVideoWriter::close() noexcept {
    impl_->close();
}

AnnotatedVideoWriterStats AnnotatedVideoWriter::stats() const noexcept {
    return impl_->stats();
}

std::uint64_t AnnotatedVideoWriter::frames_written() const noexcept {
    return impl_->frames_written();
}

const std::string& AnnotatedVideoWriter::output_path() const noexcept {
    return impl_->output_path();
}

}  // namespace edge_vision
