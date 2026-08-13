#include "edge_vision/byte_tracker.hpp"

#include <algorithm>
#include <cmath>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "BYTETracker.h"

namespace edge_vision {
namespace {

void validate_probability(float value, const char* name) {
    if (!std::isfinite(value) || value < 0.0F || value > 1.0F) {
        throw std::invalid_argument(std::string(name) + " must be in [0, 1]");
    }
}

void validate_config(const ByteTrackerConfig& config) {
    if (config.frame_rate <= 0) {
        throw std::invalid_argument("frame_rate must be positive");
    }
    if (config.track_buffer <= 0) {
        throw std::invalid_argument("track_buffer must be positive");
    }

    validate_probability(config.track_threshold, "track_threshold");
    validate_probability(config.new_track_threshold, "new_track_threshold");
    validate_probability(config.match_threshold, "match_threshold");
    validate_probability(
        config.second_match_threshold,
        "second_match_threshold");
    validate_probability(
        config.unconfirmed_match_threshold,
        "unconfirmed_match_threshold");

    if (config.new_track_threshold < config.track_threshold) {
        throw std::invalid_argument(
            "new_track_threshold must be at least track_threshold");
    }
}

std::unique_ptr<::BYTETracker> make_tracker(const ByteTrackerConfig& config) {
    return std::make_unique<::BYTETracker>(
        config.frame_rate,
        config.track_buffer,
        config.track_threshold,
        config.new_track_threshold,
        config.match_threshold,
        config.second_match_threshold,
        config.unconfirmed_match_threshold);
}

}  // namespace

class ByteTracker::Impl {
public:
    explicit Impl(ByteTrackerConfig tracker_config)
        : config(std::move(tracker_config)) {
        validate_config(config);
    }

    ByteTrackerConfig config;
    std::map<int, std::unique_ptr<::BYTETracker>> trackers_by_class;
};

ByteTracker::ByteTracker(ByteTrackerConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}

ByteTracker::~ByteTracker() = default;
ByteTracker::ByteTracker(ByteTracker&&) noexcept = default;
ByteTracker& ByteTracker::operator=(ByteTracker&&) noexcept = default;

std::vector<Track> ByteTracker::update(
    const std::vector<Detection>& detections) {
    std::map<int, std::vector<::Object>> objects_by_class;

    for (const auto& detection : detections) {
        if (detection.class_id < 0 ||
            !std::isfinite(detection.confidence) ||
            detection.confidence < 0.0F ||
            detection.confidence > 1.0F ||
            !std::isfinite(detection.box.x) ||
            !std::isfinite(detection.box.y) ||
            !std::isfinite(detection.box.width) ||
            !std::isfinite(detection.box.height) ||
            detection.box.width <= 0.0F ||
            detection.box.height <= 0.0F) {
            continue;
        }

        ::Object object;
        object.rect = cv::Rect_<float>(
            detection.box.x,
            detection.box.y,
            detection.box.width,
            detection.box.height);
        object.label = detection.class_id;
        object.prob = detection.confidence;
        objects_by_class[detection.class_id].push_back(object);
    }

    for (const auto& [class_id, objects] : objects_by_class) {
        if (impl_->trackers_by_class.count(class_id) == 0U) {
            impl_->trackers_by_class.emplace(
                class_id,
                make_tracker(impl_->config));
        }
    }

    std::vector<Track> output;
    for (auto& [class_id, tracker] : impl_->trackers_by_class) {
        const auto object_iter = objects_by_class.find(class_id);
        const std::vector<::Object> empty_objects;
        const auto& objects = object_iter == objects_by_class.end()
            ? empty_objects
            : object_iter->second;

        const auto upstream_tracks = tracker->update(objects);
        for (const auto& upstream_track : upstream_tracks) {
            Track track;
            track.track_id = upstream_track.track_id;
            track.box = BoundingBox{
                upstream_track.tlwh[0],
                upstream_track.tlwh[1],
                upstream_track.tlwh[2],
                upstream_track.tlwh[3],
            };
            track.class_id = class_id;
            track.confidence = upstream_track.score;
            track.state = TrackState::Tracked;
            track.age = static_cast<std::uint32_t>(std::max(
                1,
                upstream_track.frame_id - upstream_track.start_frame + 1));
            track.missed_frames = 0;
            output.push_back(track);
        }
    }

    std::sort(
        output.begin(),
        output.end(),
        [](const Track& left, const Track& right) {
            return left.track_id < right.track_id;
        });
    return output;
}

void ByteTracker::reset() {
    impl_->trackers_by_class.clear();
}

}  // namespace edge_vision
