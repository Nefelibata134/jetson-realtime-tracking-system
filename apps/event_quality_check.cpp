// Deterministic mechanism checks, not measured model accuracy.
#include <iostream>
#include <stdexcept>
#include <string>
#include "edge_vision/event_analytics.hpp"

namespace ev = edge_vision;
namespace {
void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
ev::PolygonRegion region() { return {{{.2F,.2F},{.8F,.2F},{.8F,.8F},{.2F,.8F}}}; }
ev::Track person(float x = .5F, std::int64_t id = 1) {
    ev::Track t;
    t.track_id = id; t.class_id = 0; t.confidence = .9F;
    t.box = {x * 1000 - 50, 300, 100, 300};
    t.state = ev::TrackState::Tracked;
    return t;
}
std::vector<ev::SafetyEvent> tick(ev::SafetyEventEngine& e, std::uint64_t seq,
                                std::int64_t ms, std::vector<ev::Track> tracks = {person()},
                                std::uint64_t generation = 0) {
    return e.update({1000,1000,seq,ms * 1'000'000, generation}, tracks);
}
ev::SafetyEventEngineConfig roi(bool guarded) {
    ev::SafetyEventEngineConfig c;
    ev::RoiIntrusionRuleConfig r;
    r.rule_id = "roi"; r.region = region();
    r.entry_confirmation_ns = guarded ? 500'000'000 : 0;
    c.roi_intrusion_rules.push_back(r);
    return c;
}
ev::SafetyEventEngineConfig dwell(bool guarded) {
    ev::SafetyEventEngineConfig c;
    ev::DwellRuleConfig r;
    r.rule_id = "dwell"; r.region = region(); r.dwell_time_ns = 300'000'000;
    r.rearm_on_observed_exit = guarded;
    c.dwell_rules.push_back(r);
    return c;
}
void roi_checks() {
    ev::SafetyEventEngine legacy(roi(false)), candidate(roi(true));
    std::size_t a = 0, b = 0;
    for (int i=0; i<5; ++i) {
        a += tick(legacy,i,i*100).size(); b += tick(candidate,i,i*100).size();
    }
    require(a == 1 && b == 0, "short-lived track entry not filtered");
    const auto entry = tick(candidate,5,500);
    require(entry.size() == 1 && entry[0].pts_ns == 500'000'000 &&
            entry[0].frame_sequence == 5, "entry must use confirmation frame");
    require(tick(candidate,6,600).empty(), "stable occupancy repeated");
    tick(candidate,7,700,{person(.1F)}); tick(candidate,8,800,{person(.1F)});
    for (int i=9;i<14;++i) require(tick(candidate,i,i*100).empty(), "reentry too early");
    require(tick(candidate,14,1400).size()==1, "real reentry suppressed");
    for (int mode=0;mode<7;++mode) {
        ev::SafetyEventEngine e(roi(true));
        tick(e,0,0); tick(e,1,100); tick(e,2,200);
        std::uint64_t seq=3, gen=0; std::int64_t ms=300;
        auto t=person();
        if(mode==0) seq=4;
        if(mode==1) ms=200;
        if(mode==2) { t.state=ev::TrackState::Lost; tick(e,3,300,{t}); t=person();seq=4;ms=400; }
        if(mode==3) { t.class_id=56; tick(e,3,300,{t}); t=person();seq=4;ms=400; }
        if(mode==4) gen=1;
        if(mode==5) ms=0;
        if(mode==6) t.track_id=2;
        require(tick(e,seq,ms,{t},gen).empty(), "gap or new identity inherited entry time");
        require(tick(e,seq+1,ms+499,{t},gen).empty(), "confirmation early after discontinuity");
        require(tick(e,seq+2,ms+500,{t},gen).size()==1, "confirmation missing after discontinuity");
    }
    for (auto ns : {-1LL,60'000'000'001LL}) {
        auto c=roi(true); c.roi_intrusion_rules[0].entry_confirmation_ns=ns;
        bool threw=false; try { ev::SafetyEventEngine e(c); } catch(const std::invalid_argument&) { threw=true; }
        require(threw,"invalid entry duration accepted");
    }
    // Long-lived false detections are indistinguishable here and must NOT be claimed fixed.
    ev::SafetyEventEngine persistent(roi(true));
    tick(persistent,0,0); require(tick(persistent,1,500).size()==1,"persistent occupancy changed");
    std::cout << "roi_entry_confirmation=PASS legacy_short_events=1 candidate_short_events=0\n";
}
void dwell_checks() {
    ev::SafetyEventEngine a(dwell(false)), b(dwell(true));
    auto first = [](ev::SafetyEventEngine& e) {
        tick(e,0,0); tick(e,1,100); tick(e,2,200);
        require(tick(e,3,300).size()==1,"initial dwell missing");
    };
    first(a);first(b);
    // Same ID, no observed departure, five missing updates: legacy rearms, candidate does not.
    for(int i=4;i<9;++i){tick(a,i,i*100,{});tick(b,i,i*100,{});}
    std::size_t old_count=0,new_count=0;
    for(int i=9;i<=12;++i){old_count+=tick(a,i,i*100).size();new_count+=tick(b,i,i*100).size();}
    require(old_count==1 && new_count==0,"same-ID disappearance repeated dwell");
    tick(b,13,1300,{person(.1F)});
    tick(b,14,1400,{});
    tick(b,15,1500,{person(.1F)});
    for(int i=16;i<20;++i)require(tick(b,i,i*100).empty(),"outside observations joined across gap");
    tick(b,20,2000,{person(.1F)});tick(b,21,2100,{person(.1F)});
    for(int i=22;i<25;++i)require(tick(b,i,i*100).empty(),"second dwell too early");
    require(tick(b,25,2500).size()==1,"confirmed exit failed to rearm");
    // Before first alarm, long unseen time never completes a dwell.
    ev::SafetyEventEngine unconfirmed(dwell(true));
    tick(unconfirmed,0,0);tick(unconfirmed,1,100);
    require(tick(unconfirmed,9,900).empty(),"unseen time triggered first dwell");
    tick(unconfirmed,10,1000);tick(unconfirmed,11,1100);
    require(tick(unconfirmed,12,1200).size()==1,"fresh dwell never completed");
    // New identity, stream reset, PTS regression and expiry all have independent lifetimes.
    for(int mode=0;mode<5;++mode){
        ev::SafetyEventEngine e(dwell(true)); first(e);
        std::uint64_t seq=4,gen=0;std::int64_t ms=400;auto t=person();
        if(mode==0)t.track_id=2;
        if(mode==1)gen=1;
        if(mode==2)ms=0;
        if(mode==3){seq=304;ms=30400;}
        if(mode==4){e.reset();}
        require(tick(e,seq,ms,{t},gen).empty(),"lifetime begins with alarm");
        require(tick(e,seq+1,ms+300,{t},gen).size()==1,"old latch leaked into new lifetime");
    }
    ev::SafetyEventEngine timestamps(dwell(true));first(timestamps);
    tick(timestamps,4,400,{person(.1F)});tick(timestamps,5,400,{person(.1F)});
    for(int i=6;i<12;++i)require(tick(timestamps,i,i*100).empty(),"duplicate PTS proved exit");
    std::cout << "dwell_observed_exit_rearm=PASS legacy_duplicate_events=1 candidate_duplicate_events=0\n";
}
}
int main() {
    try { roi_checks(); dwell_checks(); return 0; }
    catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
