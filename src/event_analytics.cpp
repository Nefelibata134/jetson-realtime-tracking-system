#include "edge_vision/event_analytics.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>
#include <utility>

namespace edge_vision {
namespace {

constexpr float kGeometryEpsilon = 1.0e-6F;

bool finite_point(const NormalizedPoint& point) {
    return std::isfinite(point.x) && std::isfinite(point.y);
}

bool normalized_point(const NormalizedPoint& point) {
    return finite_point(point) && point.x >= 0.0F && point.x <= 1.0F &&
           point.y >= 0.0F && point.y <= 1.0F;
}

float cross(
    const NormalizedPoint& first,
    const NormalizedPoint& second,
    const NormalizedPoint& point) {
    return (second.x - first.x) * (point.y - first.y) -
           (second.y - first.y) * (point.x - first.x);
}

float polygon_area_twice(const PolygonRegion& region) {
    float area = 0.0F;
    for (std::size_t index = 0; index < region.vertices.size(); ++index) {
        const auto& current = region.vertices[index];
        const auto& next =
            region.vertices[(index + 1) % region.vertices.size()];
        area += current.x * next.y - next.x * current.y;
    }
    return area;
}

void validate_region(const PolygonRegion& region, const std::string& rule_id) {
    if (region.vertices.size() < 3) {
        throw std::invalid_argument(
            "rule " + rule_id + " requires at least three ROI vertices");
    }
    if (!std::all_of(
            region.vertices.begin(),
            region.vertices.end(),
            normalized_point)) {
        throw std::invalid_argument(
            "rule " + rule_id + " has an invalid normalized ROI vertex");
    }
    if (std::fabs(polygon_area_twice(region)) <= kGeometryEpsilon) {
        throw std::invalid_argument(
            "rule " + rule_id + " has a degenerate ROI polygon");
    }
}

void validate_rule_id(
    const std::string& rule_id,
    std::unordered_set<std::string>& rule_ids) {
    if (rule_id.empty()) {
        throw std::invalid_argument("event rule id must not be empty");
    }
    if (!rule_ids.insert(rule_id).second) {
        throw std::invalid_argument("duplicate event rule id: " + rule_id);
    }
}

bool point_on_segment(
    const NormalizedPoint& point,
    const NormalizedPoint& first,
    const NormalizedPoint& second) {
    if (std::fabs(cross(first, second, point)) > kGeometryEpsilon) {
        return false;
    }
    return point.x >= std::min(first.x, second.x) - kGeometryEpsilon &&
           point.x <= std::max(first.x, second.x) + kGeometryEpsilon &&
           point.y >= std::min(first.y, second.y) - kGeometryEpsilon &&
           point.y <= std::max(first.y, second.y) + kGeometryEpsilon;
}

bool point_in_polygon(
    const NormalizedPoint& point,
    const PolygonRegion& region) {
    bool inside = false;
    std::size_t previous = region.vertices.size() - 1;
    for (std::size_t current = 0; current < region.vertices.size(); ++current) {
        const auto& first = region.vertices[previous];
        const auto& second = region.vertices[current];
        if (point_on_segment(point, first, second)) {
            return true;
        }

        const bool crosses_y = (first.y > point.y) != (second.y > point.y);
        if (crosses_y) {
            const float intersection_x =
                (second.x - first.x) * (point.y - first.y) /
                    (second.y - first.y) +
                first.x;
            if (point.x < intersection_x) {
                inside = !inside;
            }
        }
        previous = current;
    }
    return inside;
}

std::optional<NormalizedPoint> track_anchor(
    const Track& track,
    const EventFrameContext& frame) {
    if (track.track_id <= 0 || track.state != TrackState::Tracked ||
        frame.width <= 0 || frame.height <= 0 ||
        !std::isfinite(track.box.x) || !std::isfinite(track.box.y) ||
        !std::isfinite(track.box.width) ||
        !std::isfinite(track.box.height) || track.box.width <= 0.0F ||
        track.box.height <= 0.0F) {
        return std::nullopt;
    }

    const float anchor_x = track.box.x + track.box.width * 0.5F;
    const float anchor_y = track.box.y + track.box.height;
    return NormalizedPoint{
        std::clamp(anchor_x / static_cast<float>(frame.width), 0.0F, 1.0F),
        std::clamp(anchor_y / static_cast<float>(frame.height), 0.0F, 1.0F),
    };
}

bool accepts_class(int configured_class, int track_class) {
    return configured_class < 0 || configured_class == track_class;
}

enum class OccupancyTransition {
    None,
    Entered,
    Exited,
};

struct OccupancyState {
    bool initialized{false};
    bool stable_inside{false};
    bool has_candidate{false};
    bool candidate_inside{false};
    std::uint32_t candidate_count{0};
    std::int64_t candidate_since_ns{0};
    std::uint64_t last_seen_sequence{0};
    std::int64_t last_seen_pts_ns{0};
};

OccupancyTransition update_occupancy(
    OccupancyState& state,
    bool inside,
    std::uint32_t confirmation_frames,
    std::int64_t pts_ns) {
    if (!state.has_candidate || state.candidate_inside != inside) {
        state.has_candidate = true;
        state.candidate_inside = inside;
        state.candidate_count = 1;
        state.candidate_since_ns = pts_ns;
    } else if (state.candidate_count <
               std::numeric_limits<std::uint32_t>::max()) {
        ++state.candidate_count;
    }

    if (state.candidate_count < confirmation_frames) {
        return OccupancyTransition::None;
    }

    if (!state.initialized) {
        state.initialized = true;
        state.stable_inside = inside;
        return inside ? OccupancyTransition::Entered
                      : OccupancyTransition::None;
    }
    if (state.stable_inside == inside) {
        return OccupancyTransition::None;
    }

    state.stable_inside = inside;
    return inside ? OccupancyTransition::Entered
                  : OccupancyTransition::Exited;
}

template <typename State>
void prune_stale(
    std::unordered_map<std::int64_t, State>& states,
    std::uint64_t sequence,
    std::uint64_t stale_after_frames) {
    for (auto iter = states.begin(); iter != states.end();) {
        const bool stale = sequence > iter->second.last_seen_sequence &&
                           sequence - iter->second.last_seen_sequence >
                               stale_after_frames;
        if (stale) {
            iter = states.erase(iter);
        } else {
            ++iter;
        }
    }
}

SafetyEvent make_event(
    SafetyEventType type,
    const std::string& rule_id,
    const Track& track,
    const EventFrameContext& frame,
    const NormalizedPoint& anchor,
    CrossingDirection direction = CrossingDirection::None) {
    return SafetyEvent{
        type,
        rule_id,
        track.track_id,
        track.class_id,
        frame.sequence,
        frame.pts_ns,
        anchor,
        direction,
    };
}

float signed_line_distance(
    const NormalizedPoint& start,
    const NormalizedPoint& end,
    const NormalizedPoint& point) {
    const float dx = end.x - start.x;
    const float dy = end.y - start.y;
    return cross(start, end, point) / std::sqrt(dx * dx + dy * dy);
}

bool segments_intersect(
    const NormalizedPoint& first_start,
    const NormalizedPoint& first_end,
    const NormalizedPoint& second_start,
    const NormalizedPoint& second_end) {
    const float rx = first_end.x - first_start.x;
    const float ry = first_end.y - first_start.y;
    const float sx = second_end.x - second_start.x;
    const float sy = second_end.y - second_start.y;
    const float denominator = rx * sy - ry * sx;
    if (std::fabs(denominator) <= kGeometryEpsilon) {
        return false;
    }

    const float qpx = second_start.x - first_start.x;
    const float qpy = second_start.y - first_start.y;
    const float first_t = (qpx * sy - qpy * sx) / denominator;
    const float second_t = (qpx * ry - qpy * rx) / denominator;
    return first_t >= -kGeometryEpsilon &&
           first_t <= 1.0F + kGeometryEpsilon &&
           second_t >= -kGeometryEpsilon &&
           second_t <= 1.0F + kGeometryEpsilon;
}

bool direction_allowed(
    CrossingDirection configured,
    CrossingDirection observed) {
    return configured == CrossingDirection::None || configured == observed;
}

struct RoiRuleRuntime {
    RoiIntrusionRuleConfig config;
    std::unordered_map<std::int64_t, OccupancyState> states;
};

struct LineState {
    bool has_stable_side{false};
    int stable_side{0};
    bool has_candidate{false};
    int candidate_side{0};
    std::uint32_t candidate_count{0};
    NormalizedPoint stable_point{};
    std::uint64_t last_seen_sequence{0};
};

struct LineRuleRuntime {
    LineCrossingRuleConfig config;
    std::unordered_map<std::int64_t, LineState> states;
};

struct DwellState {
    OccupancyState occupancy;
    bool dwell_emitted{false};
    std::int64_t entered_at_ns{0};

    std::uint64_t last_seen_sequence{0};
};

struct DwellRuleRuntime {
    DwellRuleConfig config;
    std::unordered_map<std::int64_t, DwellState> states;
};

}  // namespace

class SafetyEventEngine::Impl {
public:
    explicit Impl(SafetyEventEngineConfig engine_config) {
        std::unordered_set<std::string> rule_ids;

        for (auto& rule : engine_config.roi_intrusion_rules) {
            validate_rule_id(rule.rule_id, rule_ids);
            validate_region(rule.region, rule.rule_id);
            if (rule.confirmation_frames == 0 ||
                rule.stale_after_frames == 0) {
                throw std::invalid_argument(
                    "ROI rule confirmation and stale limits must be positive");
            }
            roi_rules.push_back(RoiRuleRuntime{std::move(rule), {}});
        }

        for (auto& rule : engine_config.line_crossing_rules) {
            validate_rule_id(rule.rule_id, rule_ids);
            if (!normalized_point(rule.line_start) ||
                !normalized_point(rule.line_end)) {
                throw std::invalid_argument(
                    "line rule " + rule.rule_id +
                    " has invalid normalized endpoints");
            }
            const float dx = rule.line_end.x - rule.line_start.x;
            const float dy = rule.line_end.y - rule.line_start.y;
            if (dx * dx + dy * dy <= kGeometryEpsilon ||
                !std::isfinite(rule.side_epsilon) ||
                rule.side_epsilon < 0.0F ||
                rule.confirmation_frames == 0 ||
                rule.stale_after_frames == 0) {
                throw std::invalid_argument(
                    "line rule " + rule.rule_id + " has invalid geometry");
            }
            line_rules.push_back(LineRuleRuntime{std::move(rule), {}});
        }

        for (auto& rule : engine_config.dwell_rules) {
            validate_rule_id(rule.rule_id, rule_ids);
            validate_region(rule.region, rule.rule_id);
            if (rule.dwell_time_ns <= 0 || rule.confirmation_frames == 0 ||
                rule.stale_after_frames == 0 ||
                rule.max_gap_frames >= rule.stale_after_frames) {
                throw std::invalid_argument(
                    "dwell rule " + rule.rule_id + " has invalid timing");
            }
            dwell_rules.push_back(DwellRuleRuntime{std::move(rule), {}});
        }
    }

    void clear_states() {
        for (auto& rule : roi_rules) {
            rule.states.clear();
        }
        for (auto& rule : line_rules) {
            rule.states.clear();
        }
        for (auto& rule : dwell_rules) {
            rule.states.clear();
        }
    }

    std::vector<SafetyEvent> update(
        const EventFrameContext& frame,
        const std::vector<Track>& tracks) {
        if (frame.width <= 0 || frame.height <= 0 || frame.pts_ns < 0) {
            throw std::invalid_argument("invalid event frame context");
        }

        const bool timeline_restarted =
            active_stream_generation.has_value() &&
            (*active_stream_generation != frame.stream_generation ||
             frame.sequence <= last_sequence || frame.pts_ns < last_pts_ns);
        if (timeline_restarted) {
            clear_states();
        }
        active_stream_generation = frame.stream_generation;
        last_sequence = frame.sequence;
        last_pts_ns = frame.pts_ns;

        std::vector<const Track*> ordered_tracks;
        ordered_tracks.reserve(tracks.size());
        for (const auto& track : tracks) {
            ordered_tracks.push_back(&track);
        }
        std::sort(
            ordered_tracks.begin(),
            ordered_tracks.end(),
            [](const Track* left, const Track* right) {
                return left->track_id < right->track_id;
            });

        std::vector<SafetyEvent> events;
        update_roi(frame, ordered_tracks, events);
        update_lines(frame, ordered_tracks, events);
        update_dwell(frame, ordered_tracks, events);
        return events;
    }

    void reset() {
        clear_states();
        active_stream_generation.reset();
        last_sequence = 0;
        last_pts_ns = 0;
    }

private:
    void update_roi(
        const EventFrameContext& frame,
        const std::vector<const Track*>& tracks,
        std::vector<SafetyEvent>& events) {
        for (auto& rule : roi_rules) {
            for (const Track* track : tracks) {
                if (!accepts_class(rule.config.class_id, track->class_id)) {
                    continue;
                }
                const auto anchor = track_anchor(*track, frame);
                if (!anchor.has_value()) {
                    continue;
                }
                auto& state = rule.states[track->track_id];
                const auto transition = update_occupancy(
                    state,
                    point_in_polygon(*anchor, rule.config.region),
                    rule.config.confirmation_frames,
                    frame.pts_ns);
                state.last_seen_sequence = frame.sequence;
                state.last_seen_pts_ns = frame.pts_ns;
                if (transition == OccupancyTransition::Entered) {
                    events.push_back(make_event(
                        SafetyEventType::RoiIntrusion,
                        rule.config.rule_id,
                        *track,
                        frame,
                        *anchor));
                }
            }
            prune_stale(
                rule.states, frame.sequence, rule.config.stale_after_frames);
        }
    }

    void update_lines(
        const EventFrameContext& frame,
        const std::vector<const Track*>& tracks,
        std::vector<SafetyEvent>& events) {
        for (auto& rule : line_rules) {
            for (const Track* track : tracks) {
                if (!accepts_class(rule.config.class_id, track->class_id)) {
                    continue;
                }
                const auto anchor = track_anchor(*track, frame);
                if (!anchor.has_value()) {
                    continue;
                }

                auto& state = rule.states[track->track_id];
                state.last_seen_sequence = frame.sequence;
                const float distance = signed_line_distance(
                    rule.config.line_start, rule.config.line_end, *anchor);
                const int side = distance > rule.config.side_epsilon
                                     ? 1
                                     : (distance < -rule.config.side_epsilon
                                            ? -1
                                            : 0);
                if (side == 0) {
                    continue;
                }
                if (!state.has_candidate || state.candidate_side != side) {
                    state.has_candidate = true;
                    state.candidate_side = side;
                    state.candidate_count = 1;
                } else if (state.candidate_count <
                           std::numeric_limits<std::uint32_t>::max()) {
                    ++state.candidate_count;
                }
                if (state.candidate_count < rule.config.confirmation_frames) {
                    continue;
                }

                if (!state.has_stable_side) {
                    state.has_stable_side = true;
                    state.stable_side = side;
                    state.stable_point = *anchor;
                    continue;
                }
                if (state.stable_side == side) {
                    state.stable_point = *anchor;
                    continue;
                }

                const int previous_side = state.stable_side;
                const NormalizedPoint previous_point = state.stable_point;
                state.stable_side = side;
                state.stable_point = *anchor;
                const CrossingDirection observed =
                    previous_side < side
                        ? CrossingDirection::NegativeToPositive
                        : CrossingDirection::PositiveToNegative;
                if (segments_intersect(
                        previous_point,
                        *anchor,
                        rule.config.line_start,
                        rule.config.line_end) &&
                    direction_allowed(rule.config.direction, observed)) {
                    events.push_back(make_event(
                        SafetyEventType::LineCrossing,
                        rule.config.rule_id,
                        *track,
                        frame,
                        *anchor,
                        observed));
                }
            }
            prune_stale(
                rule.states, frame.sequence, rule.config.stale_after_frames);
        }
    }

    void update_dwell(
        const EventFrameContext& frame,
        const std::vector<const Track*>& tracks,
        std::vector<SafetyEvent>& events) {
        for (auto& rule : dwell_rules) {
            for (const Track* track : tracks) {
                if (!accepts_class(rule.config.class_id, track->class_id)) {
                    continue;
                }
                const auto anchor = track_anchor(*track, frame);
                if (!anchor.has_value()) {
                    continue;
                }

                auto& state = rule.states[track->track_id];
                if (state.occupancy.initialized &&
                    frame.sequence > state.last_seen_sequence + 1 &&
                    frame.sequence - state.last_seen_sequence - 1 >
                        rule.config.max_gap_frames) {
                    state = DwellState{};
                }
                if (state.occupancy.initialized &&
                    frame.pts_ns < state.occupancy.last_seen_pts_ns) {
                    state = DwellState{};
                }

                const auto transition = update_occupancy(
                    state.occupancy,
                    point_in_polygon(*anchor, rule.config.region),
                    rule.config.confirmation_frames,
                    frame.pts_ns);
                state.last_seen_sequence = frame.sequence;
                state.occupancy.last_seen_sequence = frame.sequence;
                state.occupancy.last_seen_pts_ns = frame.pts_ns;

                if (transition == OccupancyTransition::Entered) {
                    state.entered_at_ns =
                        state.occupancy.candidate_since_ns;
                    state.dwell_emitted = false;
                } else if (transition == OccupancyTransition::Exited) {
                    state.entered_at_ns = 0;
                    state.dwell_emitted = false;
                }

                if (state.occupancy.initialized &&
                    state.occupancy.stable_inside &&
                    !state.dwell_emitted &&
                    frame.pts_ns - state.entered_at_ns >=
                        rule.config.dwell_time_ns) {
                    events.push_back(make_event(
                        SafetyEventType::Dwell,
                        rule.config.rule_id,
                        *track,
                        frame,
                        *anchor));
                    state.dwell_emitted = true;
                }
            }
            prune_stale(
                rule.states, frame.sequence, rule.config.stale_after_frames);
        }
    }

    std::vector<RoiRuleRuntime> roi_rules;
    std::vector<LineRuleRuntime> line_rules;
    std::vector<DwellRuleRuntime> dwell_rules;
    std::optional<std::uint64_t> active_stream_generation;
    std::uint64_t last_sequence{0};
    std::int64_t last_pts_ns{0};
};

SafetyEventEngine::SafetyEventEngine(SafetyEventEngineConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}

SafetyEventEngine::~SafetyEventEngine() = default;
SafetyEventEngine::SafetyEventEngine(SafetyEventEngine&&) noexcept = default;
SafetyEventEngine& SafetyEventEngine::operator=(SafetyEventEngine&&) noexcept =
    default;

std::vector<SafetyEvent> SafetyEventEngine::update(
    const EventFrameContext& frame,
    const std::vector<Track>& tracks) {
    return impl_->update(frame, tracks);
}

void SafetyEventEngine::reset() {
    impl_->reset();
}

}  // namespace edge_vision
