#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
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

bool line_confirmation_check() {
    auto config = [](std::int64_t ns, std::uint32_t observations = 1) {
        edge_vision::SafetyEventEngineConfig cfg;
        edge_vision::LineCrossingRuleConfig rule;
        rule.rule_id = "confirmed_line";
        rule.line_start = {.5F, .2F};
        rule.line_end = {.5F, .8F};
        rule.confirmation_ns = ns;
        rule.confirmation_frames = observations;
        cfg.line_crossing_rules.push_back(rule);
        return cfg;
    };
    auto update = [](edge_vision::SafetyEventEngine& engine, std::uint64_t seq,
                     std::int64_t ms, float x, float y = .5F, int id = 7,
                     std::uint64_t generation = 0) {
        auto f = frame(seq, 0, generation);
        f.pts_ns = ms * 1'000'000LL;
        return engine.update(f, {track_at(x, y, id)});
    };
    auto arm = [&](edge_vision::SafetyEventEngine& engine, float y = .5F) {
        return update(engine, 0, 0, .4F, y).empty() &&
               update(engine, 1, 100, .4F, y).empty() &&
               update(engine, 2, 200, .4F, y).empty();
    };
    // Deterministic synthetic oscillation, not a replay of measured trajectories.
    edge_vision::SafetyEventEngine legacy(config(0)), guarded(config(200'000'000));
    if (!arm(legacy) || !arm(guarded)) return false;
    std::size_t legacy_count = 0, guarded_count = 0;
    for (std::uint64_t i = 3; i < 123; ++i) {
        const float x = i % 2 ? .6F : .4F;
        legacy_count += update(legacy, i, 200 + (i - 2) * 33, x).size();
        guarded_count += update(guarded, i, 200 + (i - 2) * 33, x).size();
    }
    if (legacy_count != 120 || guarded_count != 0) return false;
    std::cout << "synthetic_line_legacy_events=" << legacy_count
              << " confirmed_events=" << guarded_count << '\n';

    // Ordinary crossing and return: events use the confirmation frame, not a backdated PTS.
    edge_vision::SafetyEventEngine normal(config(200'000'000));
    if (!arm(normal) || !update(normal, 3, 300, .6F).empty() ||
        !update(normal, 4, 499, .6F).empty()) return false;
    const auto crossed = update(normal, 5, 500, .65F);
    if (crossed.size() != 1 || crossed[0].pts_ns != 500'000'000 ||
        crossed[0].frame_sequence != 5 ||
        crossed[0].direction != edge_vision::CrossingDirection::PositiveToNegative) return false;
    if (!update(normal, 6, 600, .4F).empty()) return false;
    const auto returned = update(normal, 7, 800, .4F);
    if (returned.size() != 1 ||
        returned[0].direction != edge_vision::CrossingDirection::NegativeToPositive) return false;

    // The first opposite-side chord must cross the finite segment. Confirmation may occur elsewhere.
    edge_vision::SafetyEventEngine outside(config(200'000'000)), inside(config(200'000'000));
    if (!arm(outside, .9F) || !update(outside, 3, 300, .6F, .9F).empty() ||
        !update(outside, 4, 500, .6F, .5F).empty() || !arm(inside) ||
        !update(inside, 3, 300, .6F).empty() ||
        update(inside, 4, 500, .6F, .9F).size() != 1) return false;

    // Neutral band cancels pending duration; it cannot contribute confirmation time.
    edge_vision::SafetyEventEngine neutral(config(200'000'000));
    if (!arm(neutral) || !update(neutral, 3, 300, .6F).empty() ||
        !update(neutral, 4, 400, .5F).empty() || !update(neutral, 5, 500, .6F).empty() ||
        !update(neutral, 6, 699, .6F).empty() || update(neutral, 7, 700, .6F).size() != 1) return false;

    // Missing observations, duplicate PTS, new identities and generation changes cannot invent a crossing.
    for (int reset_kind = 0; reset_kind < 6; ++reset_kind) {
        edge_vision::SafetyEventEngine reset(config(200'000'000));
        if (!arm(reset) || !update(reset, 3, 300, .6F).empty()) return false;
        std::uint64_t seq = 4, generation = 0;
        std::int64_t ms = 500;
        int id = 7;
        if (reset_kind == 0) seq = 5;  // sequence gap
        if (reset_kind == 1) ms = 300;  // duplicate PTS
        if (reset_kind == 2) id = 8;
        if (reset_kind == 3) generation = 1;
        if (reset_kind == 4) {
            auto f = frame(4, 0); f.pts_ns = 400'000'000;
            auto lost = track_at(.6F, .5F); lost.state = edge_vision::TrackState::Lost;
            if (!reset.update(f, {lost}).empty()) return false;
            seq = 5;
        }
        if (reset_kind == 5) ms = 100;  // PTS regression
        if (!update(reset, seq, ms, .6F, .5F, id, generation).empty() ||
            !update(reset, seq + 1, ms + 200, .6F, .5F, id, generation).empty() ||
            !update(reset, seq + 2, ms + 300, .4F, .5F, id, generation).empty() ||
            update(reset, seq + 3, ms + 500, .4F, .5F, id, generation).size() != 1) return false;
    }
    auto directional_config = config(200'000'000);
    directional_config.line_crossing_rules[0].direction = edge_vision::CrossingDirection::NegativeToPositive;
    edge_vision::SafetyEventEngine directional(directional_config);
    if (!arm(directional) || !update(directional, 3, 300, .6F).empty() ||
        !update(directional, 4, 500, .6F).empty() || !update(directional, 5, 600, .4F).empty() ||
        update(directional, 6, 800, .4F).size() != 1) return false;
    edge_vision::SafetyEventEngine counted(config(200'000'000, 3));
    if (!arm(counted) || !update(counted, 3, 300, .6F).empty() ||
        !update(counted, 4, 500, .6F).empty() || update(counted, 5, 501, .6F).size() != 1) return false;
    for (auto ns : {-1LL, 60'000'000'001LL}) {
        try { edge_vision::SafetyEventEngine invalid(config(ns)); return false; }
        catch (const std::invalid_argument&) {}
    }
    return true;
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

bool roi_rearm_guard_check() {
    auto check = [](float margin, std::int64_t duration) {
        edge_vision::SafetyEventEngineConfig cfg;
        cfg.roi_intrusion_rules.push_back({"guard", test_region(), 0, 2, 300, margin, duration});
        return cfg;
    };
    edge_vision::SafetyEventEngine legacy(check(0,0)), guarded(check(.02F,500'000'000LL));
    int legacy_count=0, guarded_count=0;
    for (std::uint64_t i=0;i<120;++i) {
        auto f=frame(i,0); f.pts_ns=static_cast<std::int64_t>(i)*33'333'334LL;
        const auto tracks=std::vector{track_at(.6F,i%4<2?.799F:.801F)};
        legacy_count+=static_cast<int>(legacy.update(f,tracks).size());
        guarded_count+=static_cast<int>(guarded.update(f,tracks).size());
    }
    if (legacy_count!=30 || guarded_count!=1) return false;
    auto tick=[&](std::uint64_t seq,std::int64_t ms,float y,int id=7) {
        auto f=frame(seq,0); f.pts_ns=ms*1'000'000LL;
        return guarded.update(f,{track_at(.6F,y,id)}).size();
    };
    // Real continuous departure rearms; first entry remains the original two observations.
    for (int i=0;i<=5;++i) if(tick(120+i,4000+100*i,.84F)!=0) return false;
    if(tick(126,4600,.7F)!=0 || tick(127,4700,.7F)!=1) return false;
    // Missing observations cannot stand in for half a second outside.
    if(tick(128,4800,.84F)!=0 || tick(140,5500,.84F)!=0 ||
       tick(141,5600,.7F)!=0 || tick(142,5700,.7F)!=0) return false;
    // A new identity has its own state, and generation changes clear old occupancy.
    if(tick(143,5800,.7F,8)!=0 || tick(144,5900,.7F,8)!=1) return false;
    auto f=frame(0,10,1);
    if(!guarded.update(f,{track_at(.6F,.7F)}).empty()) return false;
    f.sequence=1; f.pts_ns+=33'333'334;
    if(guarded.update(f,{track_at(.6F,.7F)}).size()!=1) return false;
    // Sustained observations near the boundary do not count as definite departure.
    for(int i=2;i<30;++i) {f.sequence=i;f.pts_ns+=100'000'000;
        if(!guarded.update(f,{track_at(.6F,.81F)}).empty()) return false;}
    f.sequence=30;f.pts_ns+=100'000'000;
    if(!guarded.update(f,{track_at(.6F,.7F)}).empty()) return false;
    // Invalid opt-in parameters fail before accepting any input.
    for(float margin:{-.01F,.26F,std::numeric_limits<float>::quiet_NaN()}) {
        try {edge_vision::SafetyEventEngine invalid(check(margin,0));return false;}
        catch(const std::invalid_argument&) {}
    }
    std::cout << "roi_guard_legacy_events="<<legacy_count<<" guarded_events="<<guarded_count<<'\n';
    return true;
}

}  // namespace

int main() {
    const bool roi_ok = roi_intrusion_check();
    const bool line_ok = line_crossing_check();
    const bool dwell_ok = dwell_check();
    const bool reset_ok = stream_reset_check();
    const bool rearm_ok = roi_rearm_guard_check();
    const bool confirmed_line_ok = line_confirmation_check();

    std::cout << "roi_intrusion=" << std::boolalpha << roi_ok << '\n';
    std::cout << "directional_crossing=" << line_ok << '\n';
    std::cout << "timestamp_dwell=" << dwell_ok << '\n';
    std::cout << "stream_reset=" << reset_ok << '\n';
    std::cout << "roi_rearm_guard=" << rearm_ok << '\n';
    std::cout << "line_pts_confirmation=" << confirmed_line_ok << '\n';

    if (!roi_ok || !line_ok || !dwell_ok || !reset_ok || !rearm_ok || !confirmed_line_ok) {
        std::cerr << "status=FAIL\n";
        return 1;
    }
    std::cout << "status=PASS\n";
    return 0;
}
