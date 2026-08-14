#include <opencv2/imgcodecs.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "edge_vision/byte_tracker.hpp"
#include "edge_vision/frame.hpp"
#include "edge_vision/mot_challenge_writer.hpp"
#include "edge_vision/yolox_detector.hpp"

namespace {

struct Options {
    std::string engine_path;
    std::filesystem::path sequence_dir;
    std::string output_path;
    std::uint64_t max_frames{0};
    std::uint64_t log_interval{100};
    int class_id{0};
    int track_buffer{30};
    float score_threshold{0.1F};
    float nms_threshold{0.45F};
    float track_threshold{0.5F};
    float new_track_threshold{0.6F};
    float match_threshold{0.8F};
};

struct SequenceInfo {
    std::string name;
    std::string image_directory;
    std::string image_extension;
    int frame_rate{0};
    std::uint64_t length{0};
    int width{0};
    int height{0};
};

[[noreturn]] void usage(const char* program, int exit_code) {
    std::ostream& output = exit_code == 0 ? std::cout : std::cerr;
    output
        << "Usage: " << program
        << " --engine ENGINE --sequence SEQUENCE_DIR --output RESULT [options]\n\n"
        << "Options:\n"
        << "  --max-frames N\n"
        << "  --log-interval N\n"
        << "  --class-id N\n"
        << "  --score-threshold VALUE\n"
        << "  --nms-threshold VALUE\n"
        << "  --track-threshold VALUE\n"
        << "  --new-track-threshold VALUE\n"
        << "  --match-threshold VALUE\n"
        << "  --track-buffer N\n";
    std::exit(exit_code);
}

std::string require_value(int argc, char** argv, int& index) {
    if (index + 1 >= argc) {
        throw std::invalid_argument(
            std::string("missing value for ") + argv[index]);
    }
    return argv[++index];
}

Options parse_options(int argc, char** argv) {
    Options options;
    for (int index = 1; index < argc; ++index) {
        const std::string argument = argv[index];
        if (argument == "--help" || argument == "-h") {
            usage(argv[0], 0);
        } else if (argument == "--engine") {
            options.engine_path = require_value(argc, argv, index);
        } else if (argument == "--sequence") {
            options.sequence_dir = require_value(argc, argv, index);
        } else if (argument == "--output") {
            options.output_path = require_value(argc, argv, index);
        } else if (argument == "--max-frames") {
            options.max_frames = std::stoull(require_value(argc, argv, index));
        } else if (argument == "--log-interval") {
            options.log_interval =
                std::stoull(require_value(argc, argv, index));
        } else if (argument == "--class-id") {
            options.class_id = std::stoi(require_value(argc, argv, index));
        } else if (argument == "--score-threshold") {
            options.score_threshold =
                std::stof(require_value(argc, argv, index));
        } else if (argument == "--nms-threshold") {
            options.nms_threshold =
                std::stof(require_value(argc, argv, index));
        } else if (argument == "--track-threshold") {
            options.track_threshold =
                std::stof(require_value(argc, argv, index));
        } else if (argument == "--new-track-threshold") {
            options.new_track_threshold =
                std::stof(require_value(argc, argv, index));
        } else if (argument == "--match-threshold") {
            options.match_threshold =
                std::stof(require_value(argc, argv, index));
        } else if (argument == "--track-buffer") {
            options.track_buffer =
                std::stoi(require_value(argc, argv, index));
        } else {
            throw std::invalid_argument("unknown option: " + argument);
        }
    }

    if (options.engine_path.empty() || options.sequence_dir.empty() ||
        options.output_path.empty()) {
        throw std::invalid_argument(
            "--engine, --sequence, and --output are required");
    }
    if (options.log_interval == 0) {
        throw std::invalid_argument("log interval must be positive");
    }
    if (options.class_id < 0) {
        throw std::invalid_argument("class ID must be nonnegative");
    }
    if (options.score_threshold >= options.track_threshold) {
        throw std::invalid_argument(
            "score threshold must remain below track threshold");
    }
    return options;
}

std::string trim(std::string value) {
    const auto first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) {
        return {};
    }
    const auto last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
}

SequenceInfo read_sequence_info(const std::filesystem::path& sequence_dir) {
    const auto path = sequence_dir / "seqinfo.ini";
    std::ifstream input(path);
    if (!input) {
        throw std::runtime_error("failed to open " + path.string());
    }

    std::map<std::string, std::string> values;
    std::string line;
    while (std::getline(input, line)) {
        const std::string cleaned = trim(line);
        if (cleaned.empty() || cleaned.front() == '[' ||
            cleaned.front() == '#' || cleaned.front() == ';') {
            continue;
        }
        const auto separator = cleaned.find('=');
        if (separator == std::string::npos) {
            throw std::runtime_error("invalid seqinfo.ini line: " + cleaned);
        }
        values[trim(cleaned.substr(0, separator))] =
            trim(cleaned.substr(separator + 1));
    }

    const auto required = [&values](const std::string& key) -> std::string {
        const auto iter = values.find(key);
        if (iter == values.end() || iter->second.empty()) {
            throw std::runtime_error("seqinfo.ini is missing " + key);
        }
        return iter->second;
    };

    SequenceInfo info;
    info.name = required("name");
    info.image_directory = required("imDir");
    info.image_extension = required("imExt");
    info.frame_rate = std::stoi(required("frameRate"));
    info.length = std::stoull(required("seqLength"));
    info.width = std::stoi(required("imWidth"));
    info.height = std::stoi(required("imHeight"));
    if (info.frame_rate <= 0 || info.length == 0 || info.width <= 0 ||
        info.height <= 0) {
        throw std::runtime_error("seqinfo.ini contains invalid dimensions");
    }
    return info;
}

std::filesystem::path image_path(
    const std::filesystem::path& sequence_dir,
    const SequenceInfo& info,
    std::uint64_t one_based_frame) {
    std::ostringstream name;
    name << std::setfill('0') << std::setw(6) << one_based_frame
         << info.image_extension;
    return sequence_dir / info.image_directory / name.str();
}

edge_vision::Frame make_frame(
    const cv::Mat& image,
    std::uint64_t zero_based_sequence) {
    const cv::Mat contiguous = image.isContinuous() ? image : image.clone();
    edge_vision::Frame frame;
    frame.width = contiguous.cols;
    frame.height = contiguous.rows;
    frame.channels = contiguous.channels();
    frame.format = edge_vision::PixelFormat::bgr8;
    frame.sequence = zero_based_sequence;
    frame.data.assign(
        contiguous.data,
        contiguous.data + contiguous.total() * contiguous.elemSize());
    return frame;
}

double percentile(std::vector<double> values, double fraction) {
    if (values.empty()) {
        return 0.0;
    }
    std::sort(values.begin(), values.end());
    const double position = fraction * static_cast<double>(values.size() - 1);
    const auto lower = static_cast<std::size_t>(std::floor(position));
    const auto upper = static_cast<std::size_t>(std::ceil(position));
    const double weight = position - static_cast<double>(lower);
    return values[lower] * (1.0 - weight) + values[upper] * weight;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parse_options(argc, argv);
        const SequenceInfo sequence = read_sequence_info(options.sequence_dir);
        const std::uint64_t frame_limit = options.max_frames == 0
            ? sequence.length
            : std::min(options.max_frames, sequence.length);

        edge_vision::YoloXDetectorConfig detector_config;
        detector_config.score_threshold = options.score_threshold;
        detector_config.nms_threshold = options.nms_threshold;
        edge_vision::YoloXDetector detector(
            options.engine_path,
            detector_config);

        edge_vision::ByteTrackerConfig tracker_config;
        tracker_config.frame_rate = sequence.frame_rate;
        tracker_config.track_buffer = options.track_buffer;
        tracker_config.track_threshold = options.track_threshold;
        tracker_config.new_track_threshold = options.new_track_threshold;
        tracker_config.match_threshold = options.match_threshold;
        edge_vision::ByteTracker tracker(tracker_config);
        edge_vision::MotChallengeWriter writer(
            options.output_path,
            options.class_id);

        std::vector<double> inference_ms;
        std::vector<double> tracking_ms;
        inference_ms.reserve(frame_limit);
        tracking_ms.reserve(frame_limit);
        std::set<std::int64_t> unique_ids;
        std::uint64_t detections_total = 0;
        std::uint64_t track_observations = 0;

        const auto run_started = std::chrono::steady_clock::now();
        for (std::uint64_t one_based_frame = 1;
             one_based_frame <= frame_limit;
             ++one_based_frame) {
            const auto path = image_path(
                options.sequence_dir,
                sequence,
                one_based_frame);
            const cv::Mat image = cv::imread(path.string(), cv::IMREAD_COLOR);
            if (image.empty()) {
                throw std::runtime_error("failed to read " + path.string());
            }
            if (image.cols != sequence.width || image.rows != sequence.height) {
                throw std::runtime_error(
                    "image dimensions do not match seqinfo.ini: " +
                    path.string());
            }

            const auto inference_started = std::chrono::steady_clock::now();
            auto detections = detector.infer(
                make_frame(image, one_based_frame - 1));
            const auto inference_finished = std::chrono::steady_clock::now();
            detections.erase(
                std::remove_if(
                    detections.begin(),
                    detections.end(),
                    [&options](const edge_vision::Detection& detection) {
                        return detection.class_id != options.class_id;
                    }),
                detections.end());

            const auto tracks = tracker.update(detections);
            const auto tracking_finished = std::chrono::steady_clock::now();
            writer.write(one_based_frame - 1, tracks);

            inference_ms.push_back(std::chrono::duration<double, std::milli>(
                                       inference_finished - inference_started)
                                       .count());
            tracking_ms.push_back(std::chrono::duration<double, std::milli>(
                                      tracking_finished - inference_finished)
                                      .count());
            detections_total += detections.size();
            track_observations += tracks.size();
            for (const auto& track : tracks) {
                unique_ids.insert(track.track_id);
            }

            if (one_based_frame <= 3 ||
                one_based_frame % options.log_interval == 0 ||
                one_based_frame == frame_limit) {
                std::cout << "frame=" << one_based_frame
                          << " detections=" << detections.size()
                          << " tracks=" << tracks.size() << '\n';
            }
        }
        writer.finish();
        const double elapsed_seconds =
            std::chrono::duration<double>(
                std::chrono::steady_clock::now() - run_started)
                .count();

        std::cout << std::fixed << std::setprecision(3);
        std::cout << "sequence=" << sequence.name << '\n';
        std::cout << "frames=" << frame_limit << '\n';
        std::cout << "detections=" << detections_total << '\n';
        std::cout << "track_observations=" << track_observations << '\n';
        std::cout << "unique_track_ids=" << unique_ids.size() << '\n';
        std::cout << "mot_rows=" << writer.stats().written << '\n';
        std::cout << "inference_p50_ms="
                  << percentile(inference_ms, 0.50) << '\n';
        std::cout << "inference_p95_ms="
                  << percentile(inference_ms, 0.95) << '\n';
        std::cout << "tracking_p95_ms="
                  << percentile(tracking_ms, 0.95) << '\n';
        std::cout << "effective_fps="
                  << static_cast<double>(frame_limit) / elapsed_seconds << '\n';
        std::cout << "output=" << options.output_path << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "MOT sequence inference failed: " << error.what() << '\n';
        return 1;
    }
}
