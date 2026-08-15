#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "edge_vision/tracker.hpp"

namespace edge_vision {

struct NormalizedPoint {
    float x{0.0F};
    float y{0.0F};
};

struct PolygonRegion {
    std::vector<NormalizedPoint> vertices;
};

enum class SafetyEventType {
    RoiIntrusion,
    LineCrossing,
    Dwell,
};

enum class CrossingDirection {
    None,
    NegativeToPositive,
    PositiveToNegative,
};

struct SafetyEvent {
    SafetyEventType type{SafetyEventType::RoiIntrusion};
    std::string rule_id;
    std::int64_t track_id{-1};
    int class_id{-1};
    std::uint64_t frame_sequence{0};
    std::int64_t pts_ns{0};
    NormalizedPoint anchor{};
    CrossingDirection direction{CrossingDirection::None};
};

struct EventFrameContext {
    int width{0};
    int height{0};
    std::uint64_t sequence{0};
    std::int64_t pts_ns{0};
    std::uint64_t stream_generation{0};
};

struct RoiIntrusionRuleConfig {
    std::string rule_id;
    PolygonRegion region;
    int class_id{0};
    std::uint32_t confirmation_frames{2};
    std::uint64_t stale_after_frames{300};
};

struct LineCrossingRuleConfig {
    std::string rule_id;
    NormalizedPoint line_start;
    NormalizedPoint line_end;
    int class_id{0};
    CrossingDirection direction{CrossingDirection::None};
    float side_epsilon{0.01F};
    std::uint32_t confirmation_frames{1};
    std::uint64_t stale_after_frames{300};
};

struct DwellRuleConfig {
    std::string rule_id;
    PolygonRegion region;
    std::int64_t dwell_time_ns{3'000'000'000LL};
    int class_id{0};
    std::uint32_t confirmation_frames{2};
    std::uint64_t max_gap_frames{3};
    std::uint64_t stale_after_frames{300};
};

struct SafetyEventEngineConfig {
    std::vector<RoiIntrusionRuleConfig> roi_intrusion_rules;
    std::vector<LineCrossingRuleConfig> line_crossing_rules;
    std::vector<DwellRuleConfig> dwell_rules;
};

class SafetyEventEngine final {
public:
    explicit SafetyEventEngine(SafetyEventEngineConfig config);
    ~SafetyEventEngine();

    SafetyEventEngine(const SafetyEventEngine&) = delete;
    SafetyEventEngine& operator=(const SafetyEventEngine&) = delete;
    SafetyEventEngine(SafetyEventEngine&&) noexcept;
    SafetyEventEngine& operator=(SafetyEventEngine&&) noexcept;

    [[nodiscard]] std::vector<SafetyEvent> update(
        const EventFrameContext& frame,
        const std::vector<Track>& tracks);

    void reset();

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace edge_vision
