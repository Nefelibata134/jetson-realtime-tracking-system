#include "edge_vision/event_clip_writer.hpp"

#include <opencv2/videoio.hpp>

#include <algorithm>
#include <cmath>
#include <condition_variable>
#include <deque>
#include <exception>
#include <filesystem>
#include <iterator>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <utility>

namespace edge_vision {
namespace {

using SharedFrame = std::shared_ptr<const Frame>;

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
        validate_config();
        std::filesystem::create_directories(config_.output_directory);
        worker_ = std::thread(&Impl::run, this);
    }

    ~Impl() {
        close();
    }

    [[nodiscard]] std::vector<EventRecord> process(
        const Frame& frame,
        const std::vector<Track>& tracks,
        std::vector<EventRecord> records) {
        if (finished_) {
            throw std::runtime_error("event clip writer is closed");
        }
        rethrow_worker_error();

        std::vector<EventRecord> completed = take_completed();
        std::vector<SafetyEvent> events;
        events.reserve(records.size());
        for (const EventRecord& record : records) {
            events.push_back(record.event);
        }
        auto annotated = std::make_shared<Frame>(
            annotate_frame(frame, tracks, events, config_.annotation));

        advance_active(annotated, completed);
        for (EventRecord& record : records) {
            start_clip(std::move(record), annotated, completed);
        }
        push_prebuffer(std::move(annotated));
        update_buffer_stats();

        append_completed(completed, take_completed());
        rethrow_worker_error();
        return completed;
    }

    [[nodiscard]] std::vector<EventRecord> reset() {
        if (finished_) {
            return {};
        }
        std::vector<EventRecord> completed = take_completed();
        submit_all_active(completed);
        prebuffer_.clear();
        update_buffer_stats();
        append_completed(completed, take_completed());
        rethrow_worker_error();
        return completed;
    }

    [[nodiscard]] std::vector<EventRecord> finish() {
        if (finished_) {
            rethrow_worker_error();
            return take_completed();
        }

        std::vector<EventRecord> completed = take_completed();
        submit_all_active(completed);
        prebuffer_.clear();
        update_buffer_stats();
        finished_ = true;
        request_stop();
        join_worker();
        append_completed(completed, take_completed());
        rethrow_worker_error();
        return completed;
    }

    [[nodiscard]] EventClipWriterStats stats() const noexcept {
        std::lock_guard<std::mutex> lock(mutex_);
        return stats_;
    }

private:
    struct ActiveClip {
        EventRecord record;
        std::filesystem::path temporary_path;
        std::filesystem::path final_path;
        std::vector<SharedFrame> frames;
        std::size_t post_frames_remaining{0};
    };

    struct EncodeJob {
        EventRecord record;
        std::filesystem::path temporary_path;
        std::filesystem::path final_path;
        std::vector<SharedFrame> frames;
    };

    void validate_config() const {
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
        if (config_.encoding_queue_capacity == 0) {
            throw std::invalid_argument(
                "event clip encoding queue capacity must be positive");
        }
    }

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
        const SharedFrame& frame,
        std::vector<EventRecord>& completed) {
        for (auto iterator = active_.begin(); iterator != active_.end();) {
            iterator->frames.push_back(frame);
            if (iterator->post_frames_remaining > 0) {
                --iterator->post_frames_remaining;
            }
            if (iterator->post_frames_remaining == 0) {
                ActiveClip clip = std::move(*iterator);
                iterator = active_.erase(iterator);
                submit(std::move(clip), completed);
            } else {
                ++iterator;
            }
        }
    }

    void start_clip(
        EventRecord record,
        const SharedFrame& current,
        std::vector<EventRecord>& completed) {
        if (const auto path = completed_path(record.event_id);
            path.has_value()) {
            record.evidence.clip_path = *path;
            increment_reused();
            completed.push_back(std::move(record));
            return;
        }
        if (active_ids_.find(record.event_id) != active_ids_.end() ||
            encoding_id_exists(record.event_id)) {
            increment_reused();
            return;
        }
        if (active_.size() + encoding_count() >=
            config_.max_active_clips) {
            increment_skipped();
            completed.push_back(std::move(record));
            return;
        }

        const std::filesystem::path final_path =
            std::filesystem::path(config_.output_directory) /
            (record.event_id + ".mp4");
        if (valid_file(final_path)) {
            record.evidence.clip_path = final_path.generic_string();
            remember_completed(record.event_id, *record.evidence.clip_path);
            increment_reused();
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
        clip.frames.reserve(
            prebuffer_.size() + 1 + post_event_frames_);
        clip.frames.insert(
            clip.frames.end(), prebuffer_.begin(), prebuffer_.end());
        clip.frames.push_back(current);
        active_ids_.insert(clip.record.event_id);
        increment_started();

        if (clip.post_frames_remaining == 0) {
            submit(std::move(clip), completed);
            return;
        }
        active_.push_back(std::move(clip));
        update_max_active();
    }

    void submit(
        ActiveClip clip,
        std::vector<EventRecord>& completed) {
        active_ids_.erase(clip.record.event_id);
        EncodeJob job{
            std::move(clip.record),
            std::move(clip.temporary_path),
            std::move(clip.final_path),
            std::move(clip.frames),
        };

        {
            std::lock_guard<std::mutex> lock(mutex_);
            rethrow_worker_error_locked();
            if (queue_.size() == config_.encoding_queue_capacity) {
                ++stats_.clips_skipped;
                completed.push_back(std::move(job.record));
                return;
            }
            encoding_ids_.insert(job.record.event_id);
            queue_.push_back(std::move(job));
            stats_.encoding_queue_high_watermark = std::max(
                stats_.encoding_queue_high_watermark, queue_.size());
        }
        ready_.notify_one();
    }

    void submit_all_active(std::vector<EventRecord>& completed) {
        for (ActiveClip& clip : active_) {
            submit(std::move(clip), completed);
        }
        active_.clear();
        active_ids_.clear();
    }

    void push_prebuffer(SharedFrame frame) {
        if (pre_event_frames_ == 0) {
            return;
        }
        prebuffer_.push_back(std::move(frame));
        while (prebuffer_.size() > pre_event_frames_) {
            prebuffer_.pop_front();
        }
    }

    void update_buffer_stats() {
        std::size_t bytes = 0;
        for (const SharedFrame& frame : prebuffer_) {
            bytes += frame->data.size();
        }
        std::lock_guard<std::mutex> lock(mutex_);
        stats_.prebuffer_frames = prebuffer_.size();
        stats_.prebuffer_bytes = bytes;
        stats_.prebuffer_peak_bytes =
            std::max(stats_.prebuffer_peak_bytes, bytes);
    }

    void update_max_active() {
        std::lock_guard<std::mutex> lock(mutex_);
        stats_.max_active_clips =
            std::max(stats_.max_active_clips, active_.size());
    }

    void run() noexcept {
        try {
            while (true) {
                EncodeJob job;
                {
                    std::unique_lock<std::mutex> lock(mutex_);
                    ready_.wait(lock, [this] {
                        return stop_requested_ || !queue_.empty();
                    });
                    if (queue_.empty()) {
                        break;
                    }
                    job = std::move(queue_.front());
                    queue_.pop_front();
                }

                EventRecord record = encode(std::move(job));
                {
                    std::lock_guard<std::mutex> lock(mutex_);
                    encoding_ids_.erase(record.event_id);
                    completed_paths_[record.event_id] =
                        *record.evidence.clip_path;
                    completed_.push_back(std::move(record));
                    ++stats_.clips_completed;
                }
            }
        } catch (...) {
            std::lock_guard<std::mutex> lock(mutex_);
            worker_error_ = std::current_exception();
            stats_.clips_skipped += queue_.size();
            for (const EncodeJob& job : queue_) {
                encoding_ids_.erase(job.record.event_id);
            }
            queue_.clear();
            stop_requested_ = true;
        }
    }

    [[nodiscard]] EventRecord encode(EncodeJob job) const {
        std::filesystem::remove(job.temporary_path);
        if (job.frames.empty()) {
            throw std::runtime_error(
                "event clip has no frames: " + job.final_path.string());
        }

        const Frame& first = *job.frames.front();
        cv::VideoWriter writer;
        const int codec = cv::VideoWriter::fourcc('m', 'p', '4', 'v');
        if (!writer.open(
                job.temporary_path.string(),
                codec,
                config_.frames_per_second,
                {first.width, first.height},
                true)) {
            throw std::runtime_error(
                "failed to open event clip: " + job.final_path.string());
        }
        for (const SharedFrame& frame : job.frames) {
            if (frame->width != first.width ||
                frame->height != first.height) {
                throw std::invalid_argument(
                    "event clip frame dimensions changed");
            }
            write_frame(writer, *frame);
        }
        writer.release();

        if (!valid_file(job.temporary_path)) {
            throw std::runtime_error(
                "event clip verification failed: " +
                job.final_path.string());
        }
        std::filesystem::remove(job.final_path);
        std::filesystem::rename(job.temporary_path, job.final_path);
        if (!valid_file(job.final_path)) {
            throw std::runtime_error(
                "event clip finalization failed: " +
                job.final_path.string());
        }

        job.record.evidence.clip_path = job.final_path.generic_string();
        return std::move(job.record);
    }

    [[nodiscard]] std::optional<std::string> completed_path(
        const std::string& event_id) const {
        std::lock_guard<std::mutex> lock(mutex_);
        const auto iterator = completed_paths_.find(event_id);
        return iterator == completed_paths_.end()
                   ? std::nullopt
                   : std::optional<std::string>(iterator->second);
    }

    [[nodiscard]] bool encoding_id_exists(
        const std::string& event_id) const {
        std::lock_guard<std::mutex> lock(mutex_);
        return encoding_ids_.find(event_id) != encoding_ids_.end();
    }

    [[nodiscard]] std::size_t encoding_count() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return encoding_ids_.size();
    }

    void remember_completed(
        const std::string& event_id,
        const std::string& path) {
        std::lock_guard<std::mutex> lock(mutex_);
        completed_paths_[event_id] = path;
    }

    void increment_started() {
        std::lock_guard<std::mutex> lock(mutex_);
        ++stats_.clips_started;
    }

    void increment_reused() {
        std::lock_guard<std::mutex> lock(mutex_);
        ++stats_.clips_reused;
    }

    void increment_skipped() {
        std::lock_guard<std::mutex> lock(mutex_);
        ++stats_.clips_skipped;
    }

    [[nodiscard]] std::vector<EventRecord> take_completed() {
        std::vector<EventRecord> completed;
        std::lock_guard<std::mutex> lock(mutex_);
        completed.reserve(completed_.size());
        while (!completed_.empty()) {
            completed.push_back(std::move(completed_.front()));
            completed_.pop_front();
        }
        return completed;
    }

    static void append_completed(
        std::vector<EventRecord>& destination,
        std::vector<EventRecord> source) {
        destination.insert(
            destination.end(),
            std::make_move_iterator(source.begin()),
            std::make_move_iterator(source.end()));
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

    void close() noexcept {
        request_stop();
        join_worker();
        for (const ActiveClip& clip : active_) {
            std::filesystem::remove(clip.temporary_path);
        }
    }

    void rethrow_worker_error() const {
        std::lock_guard<std::mutex> lock(mutex_);
        rethrow_worker_error_locked();
    }

    void rethrow_worker_error_locked() const {
        if (worker_error_) {
            std::rethrow_exception(worker_error_);
        }
    }

    EventClipWriterConfig config_;
    std::size_t pre_event_frames_{0};
    std::size_t post_event_frames_{0};
    std::deque<SharedFrame> prebuffer_;
    std::vector<ActiveClip> active_;
    std::unordered_set<std::string> active_ids_;
    mutable std::mutex mutex_;
    std::condition_variable ready_;
    std::deque<EncodeJob> queue_;
    std::deque<EventRecord> completed_;
    std::unordered_set<std::string> encoding_ids_;
    std::unordered_map<std::string, std::string> completed_paths_;
    std::thread worker_;
    std::exception_ptr worker_error_;
    EventClipWriterStats stats_;
    bool stop_requested_{false};
    bool finished_{false};
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
