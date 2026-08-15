#include <cstdint>
#include <iostream>
#include <vector>

#include "edge_vision/event_analytics.hpp"

namespace {

constexpr int kFrameSize = 1000;
constexpr std::int64_t kSecondNs = 1'000'000'000LL;

edge_vision::PolygonRegion test_region() {
    return edge_vision::PolygonRegion{{
        {0.30F, 0.30F},
        {0.80F, 0.30F},
        {0.80F, 0.80F},
        {0.30F, 0.80F},
    }};
}

edge_vision::Track track_at(
    float anchor_x,
    float anchor_y,
    std::int64_t track_id = 7) {
    edge_vision::Track track;
    track.track_id = track_id;
    track.box = edge_vision::BoundingBox{
        anchor_x * kFrameSize - 20.0F,
        anchor_y * kFrameSize - 80.0F,
        40.0F,
        80.0F,
    };
    track.class_id = 0;
    track.confidence = 0.9F;
    track.state = edge_vision::TrackState::Tracked;
    return track;
}

edge_vision::EventFrameContext frame(
    std::uint64_t sequence,
    std::int64_t seconds,
    std::uint64_t generation = 0) {
    return edge_vision::EventFrameContext{
        kFrameSize,
        kFrameSize,
        sequence,
        seconds * kSecondNs,
        generation,
    };
}

bool roi_intrusion_check() {
    edge_vision::RoiIntrusionRuleConfig rule;
    rule.rule_id = "restricted_area";
    rule.region = test_region();
    rule.confirmation_frames = 2;

    edge_vision::SafetyEventEngineConfig config;
    config.roi_intrusion_rules.push_back(rule);
    edge_vision::SafetyEventEngine engine(config);

    if (!engine.update(frame(0, 0), {track_at(0.20F, 0.50F)}).empty() ||
        !engine.update(frame(1, 1), {track_at(0.40F, 0.50F)}).empty()) {
        return false;
    }
    const auto entered =
        engine.update(frame(2, 2), {track_at(0.45F, 0.50F)});
    if (entered.size() != 1 ||
        entered.front().type != edge_vision::SafetyEventType::RoiIntrusion ||
        entered.front().track_id != 7 ||
        entered.front().rule_id != "restricted_area") {
        return false;
    }
    if (!engine.update(frame(3, 3), {track_at(0.50F, 0.50F)}).empty()) {
        return false;
    }

    static_cast<void>(
        engine.update(frame(4, 4), {track_at(0.20F, 0.50F)}));
    static_cast<void>(
        engine.update(frame(5, 5), {track_at(0.20F, 0.50F)}));
    static_cast<void>(
        engine.update(frame(6, 6), {track_at(0.40F, 0.50F)}));
    return engine.update(frame(7, 7), {track_at(0.45F, 0.50F)}).size() ==
           1;
}

bool line_crossing_check() {
    edge_vision::LineCrossingRuleConfig rule;
    rule.rule_id = "entry_line";
    rule.line_start = {0.50F, 0.20F};
    rule.line_end = {0.50F, 0.80F};
    rule.direction = edge_vision::CrossingDirection::PositiveToNegative;
    rule.side_epsilon = 0.02F;

    edge_vision::SafetyEventEngineConfig config;
    config.line_crossing_rules.push_back(rule);
    edge_vision::SafetyEventEngine engine(config);

    if (!engine.update(frame(0, 0), {track_at(0.40F, 0.50F)}).empty() ||
        !engine.update(frame(1, 1), {track_at(0.49F, 0.50F)}).empty()) {
        return false;
    }
    const auto crossed =
        engine.update(frame(2, 2), {track_at(0.60F, 0.50F)});
    if (crossed.size() != 1 ||
        crossed.front().type != edge_vision::SafetyEventType::LineCrossing ||
        crossed.front().direction !=
            edge_vision::CrossingDirection::PositiveToNegative) {
        return false;
    }
    if (!engine.update(frame(3, 3), {track_at(0.70F, 0.50F)}).empty() ||
        !engine.update(frame(4, 4), {track_at(0.40F, 0.50F)}).empty()) {
        return false;
    }

    edge_vision::SafetyEventEngine outside_engine(config);
    static_cast<void>(
        outside_engine.update(frame(0, 0), {track_at(0.40F, 0.90F)}));
    return outside_engine
        .update(frame(1, 1), {track_at(0.60F, 0.90F)})
        .empty();
}

bool dwell_check() {
    edge_vision::DwellRuleConfig rule;
    rule.rule_id = "three_second_dwell";
    rule.region = test_region();
    rule.dwell_time_ns = 3 * kSecondNs;
    rule.confirmation_frames = 1;
    rule.max_gap_frames = 1;

    edge_vision::SafetyEventEngineConfig config;
    config.dwell_rules.push_back(rule);
    edge_vision::SafetyEventEngine engine(config);

    if (!engine.update(frame(0, 0), {track_at(0.50F, 0.50F)}).empty() ||
        !engine.update(frame(1, 1), {track_at(0.50F, 0.50F)}).empty() ||
        !engine.update(frame(2, 2), {}).empty()) {
        return false;
    }
    const auto dwell =
        engine.update(frame(3, 3), {track_at(0.50F, 0.50F)});
    if (dwell.size() != 1 ||
        dwell.front().type != edge_vision::SafetyEventType::Dwell ||
        dwell.front().pts_ns != 3 * kSecondNs) {
        return false;
    }
    if (!engine.update(frame(4, 4), {track_at(0.50F, 0.50F)}).empty()) {
        return false;
    }

    static_cast<void>(
        engine.update(frame(5, 5), {track_at(0.20F, 0.50F)}));
    static_cast<void>(
        engine.update(frame(6, 6), {track_at(0.50F, 0.50F)}));
    return engine.update(frame(7, 9), {track_at(0.50F, 0.50F)}).size() ==
           1;
}

bool stream_reset_check() {
    edge_vision::DwellRuleConfig rule;
    rule.rule_id = "generation_reset";
    rule.region = test_region();
    rule.dwell_time_ns = 3 * kSecondNs;
    rule.confirmation_frames = 1;

    edge_vision::SafetyEventEngineConfig config;
    config.dwell_rules.push_back(rule);
    edge_vision::SafetyEventEngine engine(config);

    static_cast<void>(
        engine.update(frame(0, 0, 0), {track_at(0.50F, 0.50F)}));
    if (!engine.update(frame(0, 10, 1), {track_at(0.50F, 0.50F)}).empty()) {
        return false;
    }
    return engine.update(frame(1, 13, 1), {track_at(0.50F, 0.50F)}).size() ==
           1;
}

}  // namespace

int main() {
    const bool roi_ok = roi_intrusion_check();
    const bool line_ok = line_crossing_check();
    const bool dwell_ok = dwell_check();
    const bool reset_ok = stream_reset_check();

    std::cout << "roi_intrusion=" << std::boolalpha << roi_ok << '\n';
    std::cout << "directional_crossing=" << line_ok << '\n';
    std::cout << "timestamp_dwell=" << dwell_ok << '\n';
    std::cout << "stream_reset=" << reset_ok << '\n';

    if (!roi_ok || !line_ok || !dwell_ok || !reset_ok) {
        std::cerr << "status=FAIL\n";
        return 1;
    }
    std::cout << "status=PASS\n";
    return 0;
}
