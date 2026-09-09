// Exercise the production queue with a controlled sink, not a codec benchmark.
#include <chrono>
#include <condition_variable>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <mutex>
#include <stdexcept>

#include "edge_vision/event_clip_writer.hpp"
#include "video_encoder_sink.hpp"

namespace {
struct Gate {
    std::mutex mutex;
    std::condition_variable ready;
    bool entered{false};
    bool released{false};
    bool fail{false};

    void release() {
        std::lock_guard<std::mutex> lock(mutex);
        released = true;
        ready.notify_all();
    }
};
Gate* current_gate = nullptr;

class ControlledSink final : public edge_vision::detail::VideoEncoderSink {
public:
    explicit ControlledSink(std::string path) : path_(std::move(path)), gate_(*current_gate) {}
    void write(const cv::Mat&) override {
        std::unique_lock<std::mutex> lock(gate_.mutex);
        gate_.entered = true;
        gate_.ready.notify_all();
        if (!gate_.ready.wait_for(lock, std::chrono::seconds(5), [&] { return gate_.released; })) {
            throw std::runtime_error("controlled sink timed out");
        }
        if (gate_.fail) throw std::runtime_error("controlled encoder failure");
    }
    void finish() override {
        // A placeholder for the writer's atomic-path test; not a valid media artifact.
        std::ofstream(path_) << "test sink output";
    }
private:
    std::string path_;
    Gate& gate_;
};

bool run_case(const std::filesystem::path& path, bool queue_full, bool worker_failure) {
    Gate gate;
    gate.fail = worker_failure;
    current_gate = &gate;
    edge_vision::EventClipWriterConfig config;
    config.output_directory = path.string();
    config.pre_event_seconds = 0;
    config.post_event_seconds = 0;
    config.max_active_clips = queue_full ? 3 : 2;
    config.encoding_queue_capacity = queue_full ? 1 : 2;
    edge_vision::EventClipWriter writer(config);
    // Release before writer destruction even when an assertion/exception exits early.
    struct Release { Gate& gate; ~Release() { gate.release(); } } release{gate};
    auto submit = [&](std::uint64_t sequence) {
        edge_vision::Frame frame;
        frame.width = 64; frame.height = 64; frame.channels = 3;
        frame.format = edge_vision::PixelFormat::bgr8;
        frame.sequence = sequence;
        frame.pts_ns = static_cast<std::int64_t>(sequence) * 33'333'334;
        frame.data.resize(frame.expected_bytes());
        edge_vision::SafetyEvent event;
        event.type = edge_vision::SafetyEventType::LineCrossing;
        event.rule_id = "queue-test"; event.track_id = 7; event.class_id = 0;
        event.frame_sequence = sequence; event.pts_ns = frame.pts_ns;
        return writer.process(frame, {}, {edge_vision::make_event_record(event, "queue-test", "synthetic", 0)});
    };
    if (!submit(0).empty()) return false;
    {
        std::unique_lock<std::mutex> lock(gate.mutex);
        if (!gate.ready.wait_for(lock, std::chrono::seconds(5), [&] { return gate.entered; })) return false;
    }
    if (!submit(1).empty()) return false;
    const auto rejected = submit(2);
    if (rejected.size() != 1 || rejected[0].evidence.clip_path) return false;
    const auto blocked = writer.stats();
    if (blocked.clips_skipped != 1 || blocked.encoding_queue_high_watermark != 1 ||
        blocked.pending_jobs_high_watermark != (queue_full ? 3U : 2U) ||
        blocked.events_skipped_capacity != (queue_full ? 0U : 1U) ||
        blocked.events_skipped_queue != (queue_full ? 1U : 0U) ||
        blocked.events_skipped_worker_queue != 0) return false;
    gate.release();
    bool threw = false;
    std::size_t completed = 0;
    try { completed = writer.finish().size(); }
    catch (const std::runtime_error& error) {
        if (std::string(error.what()) != "controlled encoder failure") throw;
        threw = true;
    }
    const auto final = writer.stats();
    const bool passed = threw == worker_failure &&
        completed == (worker_failure ? 0U : 2U) &&
        final.events_completed == (worker_failure ? 0U : 2U) &&
        final.events_skipped_worker_queue == (worker_failure ? 1U : 0U) &&
        final.clips_skipped == 1 + final.events_skipped_worker_queue &&
        final.encoding_queue_wait_samples == (worker_failure ? 1U : 2U) &&
        final.encoding_queue_wait_total_ms >= final.encoding_queue_wait_max_ms &&
        final.encoding_queue_wait_max_ms >= 0;
    std::cout << "controlled_queue_full=" << queue_full << " worker_failure=" << worker_failure
              << " capacity_rejected=" << final.events_skipped_capacity
              << " queue_rejected=" << final.events_skipped_queue
              << " worker_queue_discarded=" << final.events_skipped_worker_queue
              << " status=" << (passed ? "PASS" : "FAIL") << '\n';
    return passed;
}
}  // namespace

namespace edge_vision::detail {
std::unique_ptr<VideoEncoderSink> make_opencv_mp4v_sink(const std::string& path, double, const cv::Size&) {
    return std::make_unique<ControlledSink>(path);
}
}  // namespace edge_vision::detail

int main() {
    const auto path = std::filesystem::temp_directory_path() /
        ("edge-vision-controlled-queue-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    try {
        const bool passed = run_case(path / "capacity", false, false) &&
                            run_case(path / "queue", true, false) &&
                            run_case(path / "failure", false, true);
        std::filesystem::remove_all(path);
        return passed ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        std::filesystem::remove_all(path);
        return 1;
    }
}
