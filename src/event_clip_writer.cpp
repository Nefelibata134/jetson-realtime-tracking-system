#include "edge_vision/event_clip_writer.hpp"

#include <opencv2/videoio.hpp>

#include <algorithm>
#include <cmath>
#include <deque>
#include <filesystem>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>
#include <utility>

namespace edge_vision {
namespace {

void write_frame(cv::VideoWriter& writer, const Frame& frame) {
    const cv::Mat image(
        frame.height,
        frame.width,
        CV_8UC3,
        const_cast<std::uint8_t*>(frame.data.data()));
    writer.write(image);
}

bool valid_file(const std::filesystem::path& path) {
    return std::filesystem::exists(path) &&
           std::filesystem::is_regular_file(path) &&
           std::filesystem::file_size(path) > 0;
}

}  // namespace

class EventClipWriter::Impl {
public:
    explicit Impl(EventClipWriterConfig config)
        : config_(std::move(config)),
          pre_event_frames_(frame_count(config_.pre_event_seconds)),
          post_event_frames_(frame_count(config_.post_event_seconds)) {
        if (config_.output_directory.empty()) {
            throw std::invalid_argument(
                "event clip directory must not be empty");
        }
        if (!std::isfinite(config_.frames_per_second) ||
            config_.frames_per_second <= 0.0) {
            throw std::invalid_argument("event clip FPS must be positive");
        }
        if (!std::isfinite(config_.pre_event_seconds) ||
            config_.pre_event_seconds < 0.0 ||
            !std::isfinite(config_.post_event_seconds) ||
            config_.post_event_seconds < 0.0) {
            throw std::invalid_argument(
                "event clip durations must be non-negative");
        }
        if (config_.max_active_clips == 0) {
            throw std::invalid_argument(
                "event clip active limit must be positive");
        }
        std::filesystem::create_directories(config_.output_directory);
    }

    ~Impl() {
        for (auto& clip : active_) {
            clip.writer.release();
            std::filesystem::remove(clip.temporary_path);
        }
    }

    [[nodiscard]] std::vector<EventRecord> process(
        const Frame& frame,
        const std::vector<Track>& tracks,
        std::vector<EventRecord> records) {
        std::vector<SafetyEvent> events;
        events.reserve(records.size());
        for (const EventRecord& record : records) {
            events.push_back(record.event);
        }
        const Frame annotated =
            annotate_frame(frame, tracks, events, config_.annotation);

        std::vector<EventRecord> completed;
        advance_active(annotated, completed);
        for (EventRecord& record : records) {
            start_clip(std::move(record), annotated, completed);
        }
        push_prebuffer(annotated);
        update_buffer_stats();
        return completed;
    }

    [[nodiscard]] std::vector<EventRecord> reset() {
        std::vector<EventRecord> completed = finalize_all();
        prebuffer_.clear();
        update_buffer_stats();
        return completed;
    }

    [[nodiscard]] std::vector<EventRecord> finish() {
        std::vector<EventRecord> completed = finalize_all();
        prebuffer_.clear();
        update_buffer_stats();
        return completed;
    }

    [[nodiscard]] EventClipWriterStats stats() const noexcept {
        return stats_;
    }

private:
    struct ActiveClip {
        EventRecord record;
        std::filesystem::path temporary_path;
        std::filesystem::path final_path;
        cv::VideoWriter writer;
        std::size_t post_frames_remaining{0};
    };

    [[nodiscard]] std::size_t frame_count(const double seconds) const {
        if (!std::isfinite(seconds) || seconds <= 0.0 ||
            !std::isfinite(config_.frames_per_second) ||
            config_.frames_per_second <= 0.0) {
            return 0;
        }
        return static_cast<std::size_t>(
            std::llround(seconds * config_.frames_per_second));
    }

    void advance_active(
        const Frame& frame,
        std::vector<EventRecord>& completed) {
        for (auto iterator = active_.begin(); iterator != active_.end();) {
            write_frame(iterator->writer, frame);
            if (iterator->post_frames_remaining > 0) {
                --iterator->post_frames_remaining;
            }
            if (iterator->post_frames_remaining == 0) {
                completed.push_back(finalize(*iterator));
                iterator = active_.erase(iterator);
            } else {
                ++iterator;
            }
        }
    }

    void start_clip(
        EventRecord record,
        const Frame& current,
        std::vector<EventRecord>& completed) {
        const auto completed_path = completed_paths_.find(record.event_id);
        if (completed_path != completed_paths_.end()) {
            record.evidence.clip_path = completed_path->second;
            ++stats_.clips_reused;
            completed.push_back(std::move(record));
            return;
        }
        if (active_ids_.find(record.event_id) != active_ids_.end()) {
            ++stats_.clips_reused;
            return;
        }
        if (active_.size() == config_.max_active_clips) {
            ++stats_.clips_skipped;
            completed.push_back(std::move(record));
            return;
        }

        const std::filesystem::path final_path =
            std::filesystem::path(config_.output_directory) /
            (record.event_id + ".mp4");
        if (valid_file(final_path)) {
            record.evidence.clip_path = final_path.generic_string();
            completed_paths_[record.event_id] = *record.evidence.clip_path;
            ++stats_.clips_reused;
            completed.push_back(std::move(record));
            return;
        }

        ActiveClip clip;
        clip.record = std::move(record);
        clip.final_path = final_path;
        clip.temporary_path =
            std::filesystem::path(config_.output_directory) /
            (clip.record.event_id + ".tmp.mp4");
        clip.post_frames_remaining = post_event_frames_;
        std::filesystem::remove(clip.temporary_path);

        const int codec = cv::VideoWriter::fourcc('m', 'p', '4', 'v');
        if (!clip.writer.open(
                clip.temporary_path.string(),
                codec,
                config_.frames_per_second,
                {current.width, current.height},
                true)) {
            throw std::runtime_error(
                "failed to open event clip: " + final_path.string());
        }
        for (const Frame& buffered : prebuffer_) {
            write_frame(clip.writer, buffered);
        }
        write_frame(clip.writer, current);
        active_ids_.insert(clip.record.event_id);
        ++stats_.clips_started;

        if (clip.post_frames_remaining == 0) {
            completed.push_back(finalize(clip));
            return;
        }
        active_.push_back(std::move(clip));
        stats_.max_active_clips =
            std::max(stats_.max_active_clips, active_.size());
    }

    [[nodiscard]] EventRecord finalize(ActiveClip& clip) {
        clip.writer.release();
        if (!valid_file(clip.temporary_path)) {
            throw std::runtime_error(
                "event clip verification failed: " +
                clip.final_path.string());
        }
        std::filesystem::remove(clip.final_path);
        std::filesystem::rename(clip.temporary_path, clip.final_path);
        if (!valid_file(clip.final_path)) {
            throw std::runtime_error(
                "event clip finalization failed: " +
                clip.final_path.string());
        }

        clip.record.evidence.clip_path = clip.final_path.generic_string();
        completed_paths_[clip.record.event_id] =
            *clip.record.evidence.clip_path;
        active_ids_.erase(clip.record.event_id);
        ++stats_.clips_completed;
        return std::move(clip.record);
    }

    [[nodiscard]] std::vector<EventRecord> finalize_all() {
        std::vector<EventRecord> completed;
        completed.reserve(active_.size());
        for (ActiveClip& clip : active_) {
            completed.push_back(finalize(clip));
        }
        active_.clear();
        return completed;
    }

    void push_prebuffer(const Frame& frame) {
        if (pre_event_frames_ == 0) {
            return;
        }
        prebuffer_.push_back(frame);
        while (prebuffer_.size() > pre_event_frames_) {
            prebuffer_.pop_front();
        }
    }

    void update_buffer_stats() {
        stats_.prebuffer_frames = prebuffer_.size();
        stats_.prebuffer_bytes = 0;
        for (const Frame& frame : prebuffer_) {
            stats_.prebuffer_bytes += frame.data.size();
        }
        stats_.prebuffer_peak_bytes =
            std::max(stats_.prebuffer_peak_bytes, stats_.prebuffer_bytes);
    }

    EventClipWriterConfig config_;
    std::size_t pre_event_frames_{0};
    std::size_t post_event_frames_{0};
    std::deque<Frame> prebuffer_;
    std::vector<ActiveClip> active_;
    std::unordered_set<std::string> active_ids_;
    std::unordered_map<std::string, std::string> completed_paths_;
    EventClipWriterStats stats_;
};

EventClipWriter::EventClipWriter(EventClipWriterConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}

EventClipWriter::~EventClipWriter() = default;

std::vector<EventRecord> EventClipWriter::process(
    const Frame& frame,
    const std::vector<Track>& tracks,
    std::vector<EventRecord> records) {
    return impl_->process(frame, tracks, std::move(records));
}

std::vector<EventRecord> EventClipWriter::reset() {
    return impl_->reset();
}

std::vector<EventRecord> EventClipWriter::finish() {
    return impl_->finish();
}

EventClipWriterStats EventClipWriter::stats() const noexcept {
    return impl_->stats();
}

}  // namespace edge_vision
