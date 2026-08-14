#include "edge_vision/mot_challenge_writer.hpp"

#include <cmath>
#include <filesystem>
#include <iomanip>
#include <stdexcept>

namespace edge_vision {
namespace {

bool valid_track(const Track& track) {
    return track.track_id > 0 && track.state == TrackState::Tracked &&
           std::isfinite(track.box.x) && std::isfinite(track.box.y) &&
           std::isfinite(track.box.width) &&
           std::isfinite(track.box.height) &&
           std::isfinite(track.confidence) && track.box.width > 0.0F &&
           track.box.height > 0.0F;
}

}  // namespace

MotChallengeWriter::MotChallengeWriter(
    const std::string& output_path,
    int evaluated_class_id)
    : evaluated_class_id_(evaluated_class_id) {
    if (output_path.empty()) {
        throw std::invalid_argument("MOT output path must not be empty");
    }
    if (evaluated_class_id_ < 0) {
        throw std::invalid_argument("evaluated class ID must be nonnegative");
    }

    const std::filesystem::path path(output_path);
    if (path.has_parent_path()) {
        std::filesystem::create_directories(path.parent_path());
    }
    output_.open(path, std::ios::out | std::ios::trunc);
    if (!output_) {
        throw std::runtime_error("failed to open MOT output: " + output_path);
    }
    output_ << std::fixed << std::setprecision(6);
}

void MotChallengeWriter::write(
    std::uint64_t zero_based_frame_sequence,
    const std::vector<Track>& tracks) {
    if (finished_) {
        throw std::logic_error("cannot write after MOT output is finished");
    }

    const std::uint64_t mot_frame = zero_based_frame_sequence + 1;
    for (const auto& track : tracks) {
        if (track.class_id != evaluated_class_id_ || !valid_track(track)) {
            ++stats_.skipped;
            continue;
        }

        output_ << mot_frame << ',' << track.track_id << ','
                << track.box.x + 1.0F << ',' << track.box.y + 1.0F << ','
                << track.box.width << ',' << track.box.height << ','
                << track.confidence << ",-1,-1,-1\n";
        if (!output_) {
            throw std::runtime_error("failed while writing MOT output");
        }
        ++stats_.written;
    }
}

void MotChallengeWriter::finish() {
    if (finished_) {
        return;
    }
    output_.flush();
    if (!output_) {
        throw std::runtime_error("failed to flush MOT output");
    }
    output_.close();
    finished_ = true;
}

const MotChallengeWriterStats& MotChallengeWriter::stats() const noexcept {
    return stats_;
}

}  // namespace edge_vision
