#include <algorithm>
#include <cstdint>
#include <iostream>
#include <vector>

#include "edge_vision/byte_tracker.hpp"

namespace {

edge_vision::Detection detection(
    float x,
    float confidence,
    int class_id) {
    return edge_vision::Detection{
        edge_vision::BoundingBox{x, 20.0F, 80.0F, 160.0F},
        class_id,
        confidence,
    };
}

const edge_vision::Track* find_class(
    const std::vector<edge_vision::Track>& tracks,
    int class_id) {
    const auto iter = std::find_if(
        tracks.begin(),
        tracks.end(),
        [class_id](const edge_vision::Track& track) {
            return track.class_id == class_id;
        });
    return iter == tracks.end() ? nullptr : &*iter;
}

}  // namespace

int main() {
    edge_vision::ByteTracker tracker;

    const auto frame_1 = tracker.update({detection(10.0F, 0.90F, 0)});
    const auto* person_1 = find_class(frame_1, 0);
    if (person_1 == nullptr) {
        std::cerr << "high-confidence detection did not create a track\n";
        return 1;
    }
    const std::int64_t person_id = person_1->track_id;

    const auto frame_2 = tracker.update({detection(12.0F, 0.40F, 0)});
    const auto* person_2 = find_class(frame_2, 0);
    if (person_2 == nullptr || person_2->track_id != person_id) {
        std::cerr << "low-confidence second association lost the track\n";
        return 1;
    }

    const auto frame_3 = tracker.update({
        detection(14.0F, 0.90F, 0),
        detection(14.0F, 0.90F, 2),
    });
    const auto* person_3 = find_class(frame_3, 0);
    const auto* vehicle_3 = find_class(frame_3, 2);
    if (person_3 == nullptr || vehicle_3 == nullptr ||
        person_3->track_id != person_id ||
        vehicle_3->track_id == person_id) {
        std::cerr << "class-aware association failed\n";
        return 1;
    }

    tracker.reset();
    const auto after_reset = tracker.update({detection(14.0F, 0.90F, 0)});
    const auto* reset_person = find_class(after_reset, 0);
    if (reset_person == nullptr || reset_person->track_id == person_id) {
        std::cerr << "reset retained stale tracking state\n";
        return 1;
    }

    std::cout << "id_continuity=true\n";
    std::cout << "low_score_recovery=true\n";
    std::cout << "class_isolation=true\n";
    std::cout << "reset_clears_state=true\n";
    std::cout << "status=PASS\n";
    return 0;
}
