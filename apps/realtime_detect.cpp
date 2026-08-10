#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

#include "edge_vision/frame_capture_worker.hpp"
#include "edge_vision/gstreamer_frame_source.hpp"
#include "edge_vision/yolox_detector.hpp"

namespace {

struct Options {
    enum class SourceType {
        none,
        file,
        csi,
    };

    SourceType source_type{SourceType::none};
    std::string engine_path;
    std::string file_path;
    std::uint64_t frame_limit{300};
    std::size_t queue_capacity{2};
    std::uint64_t log_interval{30};
    float score_threshold{0.3F};
    float nms_threshold{0.45F};
    std::uint64_t reconnect_attempts{3};
    std::uint64_t reconnect_delay_ms{1000};
    edge_vision::CsiCameraConfig camera;
};

struct LatencySummary {
    double mean_ms{0.0};
    double p50_ms{0.0};
    double p95_ms{0.0};
    double maximum_ms{0.0};
};

void print_usage(const char* program) {
    std::cerr
        << "Usage:\n"
        << "  " << program << " --engine ENGINE --file VIDEO [options]\n"
        << "  " << program << " --engine ENGINE --csi [options]\n\n"
        << "Options:\n"
        << "  --frames N\n"
        << "  --queue-capacity N\n"
        << "  --score-threshold VALUE\n"
        << "  --nms-threshold VALUE\n"
        << "  --log-interval N\n"
        << "  --reconnect-attempts N --reconnect-delay-ms N\n"
        << "  --sensor-id N\n"
        << "  --sensor-mode N\n"
        << "  --capture-width N --capture-height N --capture-fps N\n"
        << "  --width N --height N --fps N\n";
}

template <typename Value>
Value parse_number(const char* text, const std::string& option) {
    const std::string value{text};
    if (value.empty() || value.front() == '-') {
        throw std::invalid_argument("invalid value for " + option);
    }
    std::size_t parsed = 0;
    const unsigned long long number = std::stoull(value, &parsed);
    if (parsed != value.size() ||
        number > static_cast<unsigned long long>(
                     std::numeric_limits<Value>::max())) {
        throw std::invalid_argument("invalid value for " + option);
    }
    return static_cast<Value>(number);
}

float parse_probability(const char* text, const std::string& option) {
    const std::string value{text};
    std::size_t parsed = 0;
    const float probability = std::stof(value, &parsed);
    if (parsed != value.size() || !std::isfinite(probability) ||
        probability <= 0.0F || probability > 1.0F) {
        throw std::invalid_argument(option + " must be in (0, 1]");
    }
    return probability;
}

void select_source(
    Options& options,
    const Options::SourceType source_type,
    const std::string& file_path = {}) {
    if (options.source_type != Options::SourceType::none) {
        throw std::invalid_argument("exactly one input source is required");
    }
    options.source_type = source_type;
    options.file_path = file_path;
}

Options parse_options(const int argc, char** argv) {
    Options options;
    for (int index = 1; index < argc; ++index) {
        const std::string argument = argv[index];
        auto require_value = [&](const std::string& option) -> const char* {
            if (++index >= argc) {
                throw std::invalid_argument("missing value for " + option);
            }
            return argv[index];
        };

        if (argument == "--engine") {
            options.engine_path = require_value(argument);
        } else if (argument == "--file") {
            select_source(
                options,
                Options::SourceType::file,
                require_value(argument));
        } else if (argument == "--csi") {
            select_source(options, Options::SourceType::csi);
        } else if (argument == "--frames") {
            options.frame_limit =
                parse_number<std::uint64_t>(require_value(argument), argument);
        } else if (argument == "--queue-capacity") {
            options.queue_capacity =
                parse_number<std::size_t>(require_value(argument), argument);
        } else if (argument == "--score-threshold") {
            options.score_threshold =
                parse_probability(require_value(argument), argument);
        } else if (argument == "--nms-threshold") {
            options.nms_threshold =
                parse_probability(require_value(argument), argument);
        } else if (argument == "--log-interval") {
            options.log_interval =
                parse_number<std::uint64_t>(require_value(argument), argument);
        } else if (argument == "--reconnect-attempts") {
            options.reconnect_attempts = parse_number<std::uint64_t>(
                require_value(argument), argument);
        } else if (argument == "--reconnect-delay-ms") {
            options.reconnect_delay_ms = parse_number<std::uint64_t>(
                require_value(argument), argument);
        } else if (argument == "--sensor-id") {
            options.camera.sensor_id =
                parse_number<int>(require_value(argument), argument);
        } else if (argument == "--sensor-mode") {
            options.camera.sensor_mode =
                parse_number<int>(require_value(argument), argument);
        } else if (argument == "--capture-width") {
            options.camera.capture_width =
                parse_number<int>(require_value(argument), argument);
        } else if (argument == "--capture-height") {
            options.camera.capture_height =
                parse_number<int>(require_value(argument), argument);
        } else if (argument == "--capture-fps") {
            options.camera.capture_frames_per_second =
                parse_number<int>(require_value(argument), argument);
        } else if (argument == "--width") {
            options.camera.width =
                parse_number<int>(require_value(argument), argument);
        } else if (argument == "--height") {
            options.camera.height =
                parse_number<int>(require_value(argument), argument);
        } else if (argument == "--fps") {
            options.camera.frames_per_second =
                parse_number<int>(require_value(argument), argument);
        } else {
            throw std::invalid_argument("unknown option: " + argument);
        }
    }

    if (options.engine_path.empty() ||
        options.source_type == Options::SourceType::none ||
        options.frame_limit == 0 || options.queue_capacity == 0 ||
        options.log_interval == 0 || options.camera.width <= 0 ||
        options.camera.height <= 0 ||
        options.camera.frames_per_second <= 0) {
        throw std::invalid_argument(
            "engine, source, frame limit, queue capacity, and log interval "
            "must be specified");
    }
    return options;
}

std::int64_t monotonic_time_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

double percentile(const std::vector<double>& sorted_values, const double rank) {
    if (sorted_values.empty()) {
        return 0.0;
    }

    const double position = rank * static_cast<double>(sorted_values.size() - 1);
    const auto lower = static_cast<std::size_t>(std::floor(position));
    const auto upper = static_cast<std::size_t>(std::ceil(position));
    const double fraction = position - static_cast<double>(lower);
    return sorted_values[lower] * (1.0 - fraction) +
           sorted_values[upper] * fraction;
}

LatencySummary summarize(std::vector<double> values) {
    if (values.empty()) {
        return {};
    }

    const double total = std::accumulate(values.begin(), values.end(), 0.0);
    std::sort(values.begin(), values.end());
    return {
        total / static_cast<double>(values.size()),
        percentile(values, 0.50),
        percentile(values, 0.95),
        values.back(),
    };
}

void print_latency(const std::string& name, const LatencySummary& summary) {
    std::cout << name << "_mean_ms=" << summary.mean_ms << '\n';
    std::cout << name << "_p50_ms=" << summary.p50_ms << '\n';
    std::cout << name << "_p95_ms=" << summary.p95_ms << '\n';
    std::cout << name << "_max_ms=" << summary.maximum_ms << '\n';
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parse_options(argc, argv);

        edge_vision::YoloXDetectorConfig detector_config;
        detector_config.score_threshold = options.score_threshold;
        detector_config.nms_threshold = options.nms_threshold;
        edge_vision::YoloXDetector detector(
            options.engine_path, detector_config);

        std::unique_ptr<edge_vision::IFrameSource> source;
        std::string source_name;
        if (options.source_type == Options::SourceType::file) {
            source = edge_vision::make_gstreamer_file_source(options.file_path);
            source_name = "file";
        } else {
            source = edge_vision::make_gstreamer_csi_source(options.camera);
            source_name = "csi";
        }

        edge_vision::FrameCaptureRecoveryPolicy recovery_policy;
        if (options.source_type == Options::SourceType::csi) {
            recovery_policy.max_restart_attempts =
                options.reconnect_attempts;
            recovery_policy.restart_delay_ms = options.reconnect_delay_ms;
        }
        edge_vision::FrameCaptureWorker worker(
            std::move(source), options.queue_capacity, recovery_policy);
        if (!worker.start()) {
            std::cerr << "failed to start frame source\n";
            return 1;
        }

        std::uint64_t processed = 0;
        std::uint64_t invalid_frames = 0;
        std::uint64_t sequence_gaps = 0;
        std::uint64_t detection_frames = 0;
        std::uint64_t total_detections = 0;
        std::uint64_t previous_sequence = 0;
        bool has_previous = false;
        std::vector<double> queue_wait_ms;
        std::vector<double> inference_ms;
        std::vector<double> end_to_end_ms;
        queue_wait_ms.reserve(options.frame_limit);
        inference_ms.reserve(options.frame_limit);
        end_to_end_ms.reserve(options.frame_limit);
        const auto started_at = std::chrono::steady_clock::now();

        while (processed < options.frame_limit) {
            auto frame = worker.wait_pop();
            if (!frame.has_value()) {
                break;
            }
            if (!frame->valid()) {
                ++invalid_frames;
                continue;
            }

            if (has_previous && frame->sequence > previous_sequence + 1) {
                sequence_gaps += frame->sequence - previous_sequence - 1;
            }
            previous_sequence = frame->sequence;
            has_previous = true;

            const std::int64_t inference_started_ns = monotonic_time_ns();
            const double queue_ms = static_cast<double>(
                inference_started_ns - frame->captured_at_ns) / 1'000'000.0;
            const auto detections = detector.infer(*frame);
            const std::int64_t inference_finished_ns = monotonic_time_ns();
            const double infer_ms = static_cast<double>(
                inference_finished_ns - inference_started_ns) / 1'000'000.0;
            const double e2e_ms = static_cast<double>(
                inference_finished_ns - frame->captured_at_ns) / 1'000'000.0;

            queue_wait_ms.push_back(queue_ms);
            inference_ms.push_back(infer_ms);
            end_to_end_ms.push_back(e2e_ms);
            total_detections += detections.size();
            if (!detections.empty()) {
                ++detection_frames;
            }

            ++processed;
            if (processed <= 5 || processed % options.log_interval == 0) {
                std::cout << "frame=" << frame->sequence
                          << " detections=" << detections.size()
                          << " queue_ms=" << std::fixed << std::setprecision(3)
                          << queue_ms << " infer_ms=" << infer_ms
                          << " e2e_ms=" << e2e_ms << '\n';
            }
        }

        const auto processing_finished_at = std::chrono::steady_clock::now();
        worker.stop();
        const edge_vision::FrameCaptureStats stats = worker.stats();
        const double elapsed_seconds = std::chrono::duration<double>(
            processing_finished_at - started_at)
                                           .count();
        const LatencySummary queue_summary = summarize(queue_wait_ms);
        const LatencySummary inference_summary = summarize(inference_ms);
        const LatencySummary e2e_summary = summarize(end_to_end_ms);
        const bool target_reached = processed == options.frame_limit;

        std::cout << std::fixed << std::setprecision(3);
        std::cout << "source=" << source_name << '\n';
        std::cout << "produced=" << stats.produced << '\n';
        std::cout << "processed=" << processed << '\n';
        std::cout << "target_frames=" << options.frame_limit << '\n';
        std::cout << "target_reached=" << std::boolalpha << target_reached
                  << '\n';
        std::cout << "restart_attempts=" << stats.restart_attempts << '\n';
        std::cout << "restart_successes=" << stats.restart_successes << '\n';
        std::cout << "dropped=" << stats.queue.dropped << '\n';
        std::cout << "queue_capacity=" << options.queue_capacity << '\n';
        std::cout << "queue_high_watermark=" << stats.queue.high_watermark
                  << '\n';
        std::cout << "sequence_gaps=" << sequence_gaps << '\n';
        std::cout << "invalid_frames=" << invalid_frames << '\n';
        std::cout << "detection_frames=" << detection_frames << '\n';
        std::cout << "total_detections=" << total_detections << '\n';
        std::cout << "source_exhausted=" << std::boolalpha
                  << stats.source_exhausted << '\n';
        std::cout << "recovery_exhausted=" << stats.recovery_exhausted
                  << '\n';
        print_latency("queue_wait", queue_summary);
        print_latency("inference", inference_summary);
        print_latency("end_to_end", e2e_summary);
        std::cout << "effective_fps="
                  << (elapsed_seconds == 0.0
                          ? 0.0
                          : static_cast<double>(processed) / elapsed_seconds)
                  << '\n';

        return target_reached && invalid_frames == 0 ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        print_usage(argv[0]);
        return 2;
    }
}
