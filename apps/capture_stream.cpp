#include <chrono>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <iomanip>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>

#include "edge_vision/frame_capture_worker.hpp"
#include "edge_vision/gstreamer_frame_source.hpp"

namespace {

struct Options {
    enum class SourceType {
        none,
        file,
        csi,
    };

    SourceType source_type{SourceType::none};
    std::string file_path;
    std::uint64_t frame_limit{300};
    std::size_t queue_capacity{4};
    int consumer_delay_ms{0};
    edge_vision::CsiCameraConfig camera;
};

void print_usage(const char* program) {
    std::cerr
        << "Usage:\n"
        << "  " << program << " --file VIDEO [options]\n"
        << "  " << program << " --csi [options]\n\n"
        << "Options:\n"
        << "  --frames N\n"
        << "  --queue-capacity N\n"
        << "  --consumer-delay-ms N\n"
        << "  --sensor-id N\n"
        << "  --width N --height N --fps N\n";
}

template <typename Value>
Value parse_number(const char* text, const std::string& option) {
    const std::string value{text};
    std::size_t parsed = 0;
    const unsigned long long number = std::stoull(value, &parsed);
    if (parsed != value.size()) {
        throw std::invalid_argument("invalid value for " + option);
    }
    return static_cast<Value>(number);
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

        if (argument == "--file") {
            options.source_type = Options::SourceType::file;
            options.file_path = require_value(argument);
        } else if (argument == "--csi") {
            options.source_type = Options::SourceType::csi;
        } else if (argument == "--frames") {
            options.frame_limit =
                parse_number<std::uint64_t>(require_value(argument), argument);
        } else if (argument == "--queue-capacity") {
            options.queue_capacity =
                parse_number<std::size_t>(require_value(argument), argument);
        } else if (argument == "--consumer-delay-ms") {
            options.consumer_delay_ms =
                parse_number<int>(require_value(argument), argument);
        } else if (argument == "--sensor-id") {
            options.camera.sensor_id =
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

    if (options.source_type == Options::SourceType::none ||
        options.frame_limit == 0 || options.queue_capacity == 0) {
        throw std::invalid_argument("source, frame limit, and capacity are required");
    }
    return options;
}

std::int64_t monotonic_time_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parse_options(argc, argv);
        std::unique_ptr<edge_vision::IFrameSource> source;
        std::string source_name;
        if (options.source_type == Options::SourceType::file) {
            source = edge_vision::make_gstreamer_file_source(options.file_path);
            source_name = "file";
        } else {
            source = edge_vision::make_gstreamer_csi_source(options.camera);
            source_name = "csi";
        }

        edge_vision::FrameCaptureWorker worker(
            std::move(source), options.queue_capacity);
        if (!worker.start()) {
            std::cerr << "failed to start frame source\n";
            return 1;
        }

        std::uint64_t consumed = 0;
        std::uint64_t sequence_gaps = 0;
        std::uint64_t invalid_frames = 0;
        std::uint64_t previous_sequence = 0;
        std::int64_t previous_pts = 0;
        bool has_previous = false;
        bool pts_monotonic = true;
        double queue_wait_total_ms = 0.0;
        double queue_wait_max_ms = 0.0;
        const auto started_at = std::chrono::steady_clock::now();

        while (consumed < options.frame_limit) {
            auto frame = worker.wait_pop();
            if (!frame.has_value()) {
                break;
            }

            if (!frame->valid()) {
                ++invalid_frames;
                continue;
            }
            if (has_previous) {
                if (frame->sequence > previous_sequence + 1) {
                    sequence_gaps += frame->sequence - previous_sequence - 1;
                }
                if (frame->pts_ns < previous_pts) {
                    pts_monotonic = false;
                }
            }

            const double queue_wait_ms = static_cast<double>(
                monotonic_time_ns() - frame->captured_at_ns) / 1'000'000.0;
            queue_wait_total_ms += queue_wait_ms;
            if (queue_wait_ms > queue_wait_max_ms) {
                queue_wait_max_ms = queue_wait_ms;
            }

            previous_sequence = frame->sequence;
            previous_pts = frame->pts_ns;
            has_previous = true;
            ++consumed;
            if (consumed <= 5) {
                std::cout << "frame=" << frame->sequence
                          << " size=" << frame->width << 'x' << frame->height
                          << " pts_ms=" << std::fixed << std::setprecision(3)
                          << static_cast<double>(frame->pts_ns) / 1'000'000.0
                          << " queue_wait_ms=" << queue_wait_ms << '\n';
            }

            if (options.consumer_delay_ms > 0) {
                std::this_thread::sleep_for(
                    std::chrono::milliseconds(options.consumer_delay_ms));
            }
        }

        worker.stop();
        const auto stats = worker.stats();
        const double elapsed_seconds =
            std::chrono::duration<double>(
                std::chrono::steady_clock::now() - started_at)
                .count();

        std::cout << "source=" << source_name << '\n';
        std::cout << "produced=" << stats.produced << '\n';
        std::cout << "consumed=" << consumed << '\n';
        std::cout << "dropped=" << stats.queue.dropped << '\n';
        std::cout << "queue_capacity=" << options.queue_capacity << '\n';
        std::cout << "queue_high_watermark=" << stats.queue.high_watermark
                  << '\n';
        std::cout << "sequence_gaps=" << sequence_gaps << '\n';
        std::cout << "invalid_frames=" << invalid_frames << '\n';
        std::cout << "pts_monotonic=" << std::boolalpha << pts_monotonic
                  << '\n';
        std::cout << "queue_wait_mean_ms="
                  << (consumed == 0 ? 0.0
                                    : queue_wait_total_ms /
                                          static_cast<double>(consumed))
                  << '\n';
        std::cout << "queue_wait_max_ms=" << queue_wait_max_ms << '\n';
        std::cout << "effective_fps="
                  << (elapsed_seconds == 0.0
                          ? 0.0
                          : static_cast<double>(consumed) / elapsed_seconds)
                  << '\n';
        return consumed > 0 && invalid_frames == 0 && pts_monotonic ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        print_usage(argv[0]);
        return 2;
    }
}
