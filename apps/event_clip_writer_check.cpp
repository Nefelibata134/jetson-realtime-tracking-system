#include <opencv2/videoio.hpp>
#include <algorithm>

#include <cstdint>
#include <filesystem>
#include <iostream>
#include <iterator>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

#include "edge_vision/event_clip_writer.hpp"

namespace {

edge_vision::Frame make_frame(const std::uint64_t sequence) {
    edge_vision::Frame frame;
    frame.width = 320;
    frame.height = 180;
    frame.channels = 3;
    frame.format = edge_vision::PixelFormat::bgr8;
    frame.sequence = sequence;
    frame.pts_ns = static_cast<std::int64_t>(sequence) * 100'000'000LL;
    frame.data.resize(
        frame.expected_bytes(), static_cast<std::uint8_t>(32 + sequence));
    return frame;
}

bool burst_check(const std::filesystem::path& directory,
                 edge_vision::AnnotatedVideoEncoder encoder,
                 std::size_t capacity, int event_count, bool reset_early,
                 bool share = false) {
    edge_vision::EventClipWriterConfig config;
    config.output_directory = directory.string();
    config.frames_per_second = 10.0;
    config.pre_event_seconds = 0.2;
    config.post_event_seconds = 0.2;
    config.encoder = encoder;
    config.max_active_clips = capacity;
    config.encoding_queue_capacity = capacity;
    config.share_overlapping = share;
    config.max_events_per_clip = 3;
    edge_vision::EventClipWriter writer(config);
    std::vector<edge_vision::EventRecord> completed;
    auto collect = [&](std::vector<edge_vision::EventRecord> ready) {
        completed.insert(completed.end(), std::make_move_iterator(ready.begin()),
                         std::make_move_iterator(ready.end()));
    };
    for (std::uint64_t sequence = 0; sequence < (reset_early ? 4U : 5U); ++sequence) {
        std::vector<edge_vision::EventRecord> records;
        if (sequence == 2) {
            for (int index = 0; index < event_count; ++index) {
                edge_vision::SafetyEvent event;
                event.type = edge_vision::SafetyEventType::RoiIntrusion;
                event.rule_id = "burst";
                event.track_id = index + 10;
                event.class_id = 0;
                event.frame_sequence = sequence;
                event.pts_ns = 200'000'000LL;
                records.push_back(edge_vision::make_event_record(event, "burst", "synthetic", 0));
            }
        }
        collect(writer.process(make_frame(sequence), {}, std::move(records)));
    }
    if (reset_early) collect(writer.reset());
    collect(writer.finish());
    const std::size_t accepted = std::min(capacity * (share ? 3 : 1), static_cast<std::size_t>(event_count));
    const std::size_t jobs = share ? (accepted + 2) / 3 : accepted;
    std::size_t files = 0;
    for (const auto& item : completed) {
        if (!item.evidence.clip_path) continue;
        cv::VideoCapture video(*item.evidence.clip_path);
        cv::Mat image;
        int decoded = 0;
        while (video.read(image)) ++decoded;
        if (decoded != (reset_early ? 4 : 5)) return false;
        ++files;
    }
    const auto stats = writer.stats();
    const bool passed = completed.size() == static_cast<std::size_t>(event_count) &&
        files == accepted && stats.clips_started == jobs && stats.clips_completed == jobs &&
        stats.events_completed == accepted && stats.events_shared == accepted - jobs &&
        stats.clips_skipped == static_cast<std::size_t>(event_count) - accepted &&
        stats.events_skipped_capacity == stats.clips_skipped &&
        stats.events_skipped_queue == 0 && stats.events_skipped_worker_queue == 0 &&
        stats.pending_jobs_high_watermark == jobs &&
        stats.encoding_queue_wait_samples == jobs &&
        stats.encoding_queue_wait_total_ms >= stats.encoding_queue_wait_max_ms &&
        stats.encoding_queue_wait_max_ms >= 0.0 &&
        stats.max_active_clips <= capacity && stats.encoding_queue_high_watermark <= capacity &&
        stats.prebuffer_bytes == 0;
    std::cout << "burst=" << event_count << " capacity=" << capacity << " reset=" << reset_early
              << " completed=" << files << " skipped=" << stats.clips_skipped
              << " status=" << (passed ? "PASS" : "FAIL") << '\n';
    return passed;
}

bool sharing_check(const std::filesystem::path& directory,
                   edge_vision::AnnotatedVideoEncoder encoder,
                   double seconds, std::size_t max_events, int discontinuity=0) {
    edge_vision::EventClipWriterConfig config;
    config.output_directory=directory.string(); config.encoder=encoder;
    config.frames_per_second=10;config.pre_event_seconds=.2;config.post_event_seconds=.3;
    config.max_active_clips=8;config.encoding_queue_capacity=8;
    config.share_overlapping=true;config.max_shared_seconds=seconds;config.max_events_per_clip=max_events;
    edge_vision::EventClipWriter writer(config);
    std::vector<edge_vision::EventRecord> completed;
    auto collect=[&](std::vector<edge_vision::EventRecord> ready) {
        completed.insert(completed.end(),std::make_move_iterator(ready.begin()),std::make_move_iterator(ready.end()));
    };
    for(std::uint64_t seq=0;seq<=20;++seq) {
        auto f=make_frame(seq);
        if(discontinuity == 1 && seq>=10) f.stream_generation=1;
        if(discontinuity == 2 && seq>=10) f.sequence += 5;
        if(discontinuity == 3 && seq>=10) f.pts_ns -= 2'000'000'000LL;
        if(discontinuity == 4 && seq>=10) { f.width=160; f.data.resize(f.expected_bytes()); }
        if(discontinuity == 5 && seq==10) collect(writer.reset());
        std::vector<edge_vision::EventRecord> records;
        if(seq>=4 && seq<=14) {
            edge_vision::SafetyEvent e;
            e.type=seq%2?edge_vision::SafetyEventType::LineCrossing:edge_vision::SafetyEventType::RoiIntrusion;
            e.track_id=42;e.rule_id="shared";e.frame_sequence=f.sequence;e.pts_ns=f.pts_ns;e.class_id=0;
            auto record=edge_vision::make_event_record(e,"shared-session","synthetic",f.stream_generation);
            records.push_back(record);
            if(seq==7) records.push_back(record); // duplicate ID is not a second member
        }
        collect(writer.process(f,{},std::move(records)));
    }
    collect(writer.finish());
    std::map<std::string,std::vector<edge_vision::EventRecord>> groups;
    std::set<std::string> ids;
    for(const auto& record:completed) {
        if(!record.evidence.clip_path || !ids.insert(record.event_id).second) return false;
        groups[*record.evidence.clip_path].push_back(record);
    }
    if(ids.size()!=11) return false;
    for(const auto& [path,records]:groups) {
        if(records.size()>max_events) return false;
        std::uint64_t first=1000,last=0;
        for(const auto& r:records) {
            const auto sequence = discontinuity == 2 && r.event.frame_sequence >= 15 ?
                r.event.frame_sequence - 5 : r.event.frame_sequence;
            first=std::min(first,sequence);last=std::max(last,sequence);
            if(r.stream_generation!=records.front().stream_generation) return false;
        }
        const auto start=discontinuity && first>=10 ? std::max(first-2,UINT64_C(10)) : first-2;
        const auto end=discontinuity && last<10 ? std::min(last+3,UINT64_C(9)) : last+3;
        cv::VideoCapture video(path);cv::Mat image;std::size_t n=0;
        while(video.read(image)) ++n;
        if(n!=end-start+1 || n>static_cast<std::size_t>(seconds*10)+1) return false;
    }
    const auto stats=writer.stats();
    const bool passed=stats.events_completed==11 && stats.clips_completed==groups.size() &&
        stats.clips_started==groups.size() && stats.events_shared==11-groups.size() &&
        stats.clips_skipped==0 && stats.clips_reused==1 && stats.max_active_clips<=8 &&
        stats.encoding_queue_high_watermark<=8 && stats.prebuffer_bytes==0 &&
        (seconds!=2 || max_events!=32 || discontinuity || groups.size()==1);
    std::cout<<"shared_clips="<<groups.size()<<" events="<<stats.events_completed
             <<" duration_limit="<<seconds<<" member_limit="<<max_events
             <<" discontinuity="<<discontinuity<<" status="<<(passed?"PASS":"FAIL")<<'\n';
    return passed;
}

}  // namespace

int main(int argc, char** argv) {
    const std::string mode = argc == 2 ? argv[1] : "mp4v";
    const bool x264 = mode == "x264";
    if (mode != "mp4v" && mode != "x264" && mode != "unsupported-x264") return 2;
    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() /
        ("edge-vision-event-clip-check-" + mode);
    std::filesystem::remove_all(directory);

    edge_vision::SafetyEvent event;
    event.type = edge_vision::SafetyEventType::LineCrossing;
    event.rule_id = "exit-line";
    event.track_id = 5;
    event.class_id = 0;
    event.frame_sequence = 2;
    event.pts_ns = 200'000'000LL;
    event.anchor = {0.5F, 0.9F};
    auto record = edge_vision::make_event_record(
        event, "session-test", "file:synthetic", 0);

    edge_vision::EventClipWriterConfig config;
    config.output_directory = directory.string();
    config.frames_per_second = 10.0;
    config.pre_event_seconds = 0.2;
    config.post_event_seconds = 0.2;
    if (x264 || mode == "unsupported-x264") {
        config.encoder = edge_vision::AnnotatedVideoEncoder::GStreamerX264;
    }
    if (mode == "unsupported-x264") {
        try { edge_vision::EventClipWriter unavailable(config); }
        catch (const std::invalid_argument&) {
            std::cout << "unsupported_x264_rejected=PASS\n";
            return 0;
        }
        return 1;
    }
    edge_vision::EventClipWriter writer(config);

    std::vector<edge_vision::EventRecord> completed;
    for (std::uint64_t sequence = 0; sequence < 5; ++sequence) {
        auto ready = writer.process(
            make_frame(sequence),
            {},
            sequence == 2 ? std::vector{record}
                          : std::vector<edge_vision::EventRecord>{});
        completed.insert(
            completed.end(),
            std::make_move_iterator(ready.begin()),
            std::make_move_iterator(ready.end()));
    }
    auto remaining = writer.finish();
    completed.insert(
        completed.end(),
        std::make_move_iterator(remaining.begin()),
        std::make_move_iterator(remaining.end()));

    bool clip_valid = completed.size() == 1 &&
                      completed.front().evidence.clip_path.has_value();
    int frame_count = 0;
    if (clip_valid) {
        cv::VideoCapture capture(*completed.front().evidence.clip_path);
        cv::Mat frame;
        while (capture.read(frame)) {
            ++frame_count;
        }
        clip_valid = frame_count == 5;
    }

    const auto stats = writer.stats();
    const bool bounded_buffer =
        stats.prebuffer_frames == 0 && stats.prebuffer_bytes == 0;
    const bool accounting_valid =
        stats.clips_started == 1 && stats.clips_completed == 1 &&
        stats.clips_skipped == 0 &&
        stats.encoding_queue_high_watermark == 1;
    const bool encoding_measured =
        stats.encoded_frames == 5 && stats.encoding_total_ms > 0.0 &&
        stats.encoding_max_ms > 0.0 &&
        stats.encoding_max_ms <= stats.encoding_total_ms;
    const bool bursts =
        burst_check(directory / "legacy", config.encoder, 2, 7, false) &&
        burst_check(directory / "candidate", config.encoder, 8, 7, false) &&
        burst_check(directory / "overflow", config.encoder, 8, 9, false) &&
        burst_check(directory / "reset", config.encoder, 8, 7, true) &&
        burst_check(directory / "shared-overflow", config.encoder, 1, 5, false, true) &&
        burst_check(directory / "shared-stop", config.encoder, 2, 5, true, true);
    const bool sharing = sharing_check(directory/"shared",config.encoder,2,32) &&
        sharing_check(directory/"shared-duration",config.encoder,1,32) &&
        sharing_check(directory/"shared-members",config.encoder,2,3) &&
        sharing_check(directory/"shared-generation",config.encoder,2,32,1) &&
        sharing_check(directory/"shared-gap",config.encoder,2,32,2) &&
        sharing_check(directory/"shared-pts",config.encoder,2,32,3) &&
        sharing_check(directory/"shared-dimensions",config.encoder,2,32,4) &&
        sharing_check(directory/"shared-reset",config.encoder,2,32,5);
    bool invalid_config = false;
    try {
        auto invalid = config;
        invalid.encoder = static_cast<edge_vision::AnnotatedVideoEncoder>(99);
        edge_vision::EventClipWriter rejected(invalid);
    } catch (const std::invalid_argument&) { invalid_config = true; }
    const bool passed = bursts && sharing && invalid_config &&
        clip_valid && bounded_buffer && accounting_valid && encoding_measured;

    std::cout << std::boolalpha;
    std::cout << "clip_frames=" << frame_count << '\n';
    std::cout << "bounded_buffer=" << bounded_buffer << '\n';
    std::cout << "accounting_valid=" << accounting_valid << '\n';
    std::cout << "encoding_queue_high_watermark="
              << stats.encoding_queue_high_watermark << '\n';
    std::cout << "encoded_frames=" << stats.encoded_frames << '\n';
    std::cout << "encoding_measured=" << encoding_measured << '\n';
    std::cout << "status=" << (passed ? "PASS" : "FAIL") << '\n';

    std::filesystem::remove_all(directory);
    return passed ? 0 : 1;
}
