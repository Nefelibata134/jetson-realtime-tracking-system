#include <algorithm>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>
#include <opencv2/imgcodecs.hpp>
#include "edge_vision/byte_tracker.hpp"
#include "edge_vision/event_analytics.hpp"
#ifdef EDGE_VISION_SOURCE_REPLAY_TENSORRT
#include "edge_vision/detector_factory.hpp"
#include "edge_vision/tensorrt_engine.hpp"
#endif

namespace {
using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;
namespace ev = edge_vision;
void require(bool ok, const std::string& message) {
    if (!ok) throw std::runtime_error(message);
}
Json read(const std::filesystem::path& path) {
    std::ifstream stream(path);
    require(bool(stream), "cannot read " + path.string());
    Json value; stream >> value; return value;
}
[[maybe_unused]] double ms(Clock::time_point start, Clock::time_point end) {
    return std::chrono::duration<double, std::milli>(end - start).count();
}
void validate_job(const Json& job) {
    const bool near_field = job.at("protocol_id") == "tiny-near-field-development-v6";
    require(job.at("schema_version") == 1 &&
            job.at("kind") == (near_field ? "near_field_job_v6" : "source_resolution_job_v5"), "job schema");
    require(near_field || job.at("protocol_id") == "tiny-source-resolution-development-v5", "protocol mismatch");
    require(job.at("thresholds") == Json::parse(R"({"score":0.1,"nms":0.45,"track":0.3,"new_track":0.4,"match":0.8})"), "five explicit thresholds required");
    require(job.at("bytetrack") == Json::parse(R"({"frame_rate":30,"buffer":30,"second_match":0.5,"unconfirmed_match":0.7})"), "tracker mismatch");
    const std::string source = job.at("source"), model = job.at("model");
    require(near_field ? source == "derived720" : source == "native" || source == "low", "source mismatch");
    require(model == "tiny416" || model == "tiny640", "model mismatch");
    require(job.at("group_id") == source + "_" + model, "group mismatch");
    require(job.at("width") == (source == "low" ? 384 : 1280) &&
            job.at("height") == (source == "low" ? 216 : 720), "dimensions mismatch");
    if (near_field) {
        require(job.at("timeline_basis") == "decoded_presentation_ordinal_CFR_30_not_original_capture_PTS", "derived timeline mismatch");
    }
    require(job.at("engine_input_shape") == Json({1,3,model == "tiny416" ? 416 : 640,model == "tiny416" ? 416 : 640}), "engine shape mismatch");
    for (const auto* key : {"roi", "line"}) {
        const auto& coords = job.at("geometry").at(key);
        require(coords.is_array() && coords.size() == 4, "geometry length");
        for (const auto& c : coords) {
            const double x = c.get<double>();
            require(std::isfinite(x) && x >= 0 && x <= 1, "geometry coordinate");
        }
    }
    const auto& geo = job.at("geometry");
    require(geo.at("roi")[0] < geo.at("roi")[2] && geo.at("roi")[1] < geo.at("roi")[3], "degenerate ROI");
    require(geo.at("line")[0] != geo.at("line")[2] || geo.at("line")[1] != geo.at("line")[3], "degenerate line");
    require(geo.at("dwell_roi") == geo.at("roi") && geo.at("dwell_seconds") == 3, "dwell mismatch");
    const auto& rows = job.at("frames");
    require(rows.is_array() && !rows.empty(), "empty frames");
    std::set<std::string> paths;
    const auto initial_pts = rows[0].at("pts_ns").get<std::int64_t>();
    std::int64_t previous = -1;
    for (std::size_t i = 0; i < rows.size(); ++i) {
        const auto& row = rows[i];
        require(row.at("sequence").is_number_integer() && row.at("sequence") == i, "frame sequence gap");
        require(row.at("pts_ns").is_number_integer(), "noninteger PTS");
        const auto pts = row.at("pts_ns").get<std::int64_t>();
        require(pts >= 0 && pts > previous, "nonmonotonic PTS");
        require(std::abs(double(pts-initial_pts)-double(i)*1e9/30) <= 1e6, "PTS grid");
        if (near_field) {
            require(pts == std::int64_t(i)*1'000'000'000LL/30, "derived PTS floor grid");
        }
        previous = pts;
        const std::string path = row.at("path");
        require(paths.insert(path).second && std::filesystem::is_regular_file(path), "missing/repeated frame file");
    }
}
ev::ByteTrackerConfig tracker_config() {
    ev::ByteTrackerConfig c;
    c.frame_rate = 30; c.track_buffer = 30; c.track_threshold = .3F;
    c.new_track_threshold = .4F; c.match_threshold = .8F;
    c.second_match_threshold = .5F; c.unconfirmed_match_threshold = .7F;
    return c;
}
ev::SafetyEventEngineConfig event_config(const Json& geometry) {
    const auto r = geometry.at("roi").get<std::vector<float>>();
    const auto l = geometry.at("line").get<std::vector<float>>();
    const ev::PolygonRegion region{{{r[0],r[1]},{r[2],r[1]},{r[2],r[3]},{r[0],r[3]}}};
    ev::SafetyEventEngineConfig c;
    c.roi_intrusion_rules.push_back({"restricted-area-entry", region, 0, 2, 300});
    c.line_crossing_rules.push_back({"directional-crossing",{l[0],l[1]},{l[2],l[3]},0,ev::CrossingDirection::None,.01F,1,300});
    c.dwell_rules.push_back({"restricted-area-dwell",region,3'000'000'000LL,0,2,3,300});
    return c;
}
const char* event_name(ev::SafetyEventType type) {
    switch(type) {
        case ev::SafetyEventType::RoiIntrusion: return "roi_intrusion";
        case ev::SafetyEventType::LineCrossing: return "line_crossing";
        case ev::SafetyEventType::Dwell: return "dwell";
    }
    throw std::runtime_error("unknown event type");
}
Json event_json(const ev::SafetyEvent& e) {
    const char* direction = e.direction == ev::CrossingDirection::NegativeToPositive ? "negative_to_positive" :
        e.direction == ev::CrossingDirection::PositiveToNegative ? "positive_to_negative" : "none";
    return Json{{"event_type",event_name(e.type)},{"rule_id",e.rule_id},{"track_id",e.track_id},
        {"class_id",e.class_id},{"frame_sequence",e.frame_sequence},{"pts_ns",e.pts_ns},
        {"anchor",{{"x",e.anchor.x},{"y",e.anchor.y}}},{"direction",direction}};
}
[[maybe_unused]] Json box_json(const ev::BoundingBox& b) { return Json::array({b.x,b.y,b.width,b.height}); }
void self_test() {
    ev::ByteTracker tracker(tracker_config());
    const auto geometry = Json::parse(R"({"roi":[0.2,0.2,0.8,0.9],"line":[0.5,0.2,0.5,0.9]})");
    ev::SafetyEventEngine engine(event_config(geometry));
    std::set<std::string> types;
    for (std::uint64_t i=0;i<240;++i) {
        // 合成观测只验证真实跟踪/事件实现及 PTS，不产生模型质量结果。
        const float x = i < 120 ? 30.F : 30.F + float(i-120)*.3F;
        const std::vector<ev::Detection> detections{{{x,30,10,30},0,.9F}};
        const auto tracks = tracker.update(detections);
        for(const auto& e:engine.update({100,100,i,std::int64_t(i)*1'000'000'000LL/30,0},tracks)) {
            const auto row=event_json(e); types.insert(row.at("event_type").get<std::string>());
            require(e.frame_sequence==i, "event sequence");
            if(e.type==ev::SafetyEventType::Dwell) require(e.pts_ns>=3'000'000'000LL,"premature dwell");
        }
    }
    require(types==std::set<std::string>{"roi_intrusion","line_crossing","dwell"},"three synthetic event types");
    std::cout << "synthetic_host_check=PASS device_inference=false\n";
}

#ifdef EDGE_VISION_SOURCE_REPLAY_TENSORRT
void replay(const Json& job, const std::filesystem::path& output) {
    require(!std::filesystem::exists(output), "output directory already exists");
    require(std::filesystem::create_directory(output), "cannot reserve output directory");
    const std::string engine_path = job.at("engine_path");
    {
        ev::TensorRTEngine contract(engine_path);
        require(contract.input().shape == job.at("engine_input_shape").get<std::vector<std::int64_t>>(), "actual engine input shape mismatch");
        const int n = job.at("model") == "tiny416" ? 3549 : 8400;
        require(contract.output().shape == std::vector<std::int64_t>{1,n,85}, "actual raw YOLOX output shape mismatch");
    }
    auto detector = ev::make_detector(engine_path,{ev::DetectorKind::YoloX,.1F,.45F});
    ev::ByteTracker tracker(tracker_config());
    ev::SafetyEventEngine events(event_config(job.at("geometry")));
    std::ofstream trace(output/"trace.jsonl");
    trace.exceptions(std::ios::badbit|std::ios::failbit);
    const auto started=Clock::now();
    for(const auto& row:job.at("frames")) {
        const auto frame_start=Clock::now();
        const cv::Mat image=cv::imread(row.at("path").get<std::string>(),cv::IMREAD_UNCHANGED);
        require(!image.empty() && image.type()==CV_8UC3 && image.cols==job.at("width") && image.rows==job.at("height"),"decoded frame contract");
        const cv::Mat contiguous=image.isContinuous()?image:image.clone();
        ev::Frame frame;
        frame.width=image.cols;frame.height=image.rows;frame.channels=3;frame.format=ev::PixelFormat::bgr8;
        frame.sequence=row.at("sequence");frame.pts_ns=row.at("pts_ns");frame.stream_generation=0;
        frame.data.assign(contiguous.data,contiguous.data+contiguous.total()*contiguous.elemSize());
        const auto loaded=Clock::now();
        const auto detected=detector->infer_profiled(frame);
        std::vector<ev::Detection> people;
        for(const auto& d:detected.detections) if(d.class_id==0) people.push_back(d);
        const auto track_start=Clock::now();
        const auto tracks=tracker.update(people);
        const auto tracked=Clock::now();
        const auto event_rows=events.update({frame.width,frame.height,frame.sequence,frame.pts_ns,0},tracks);
        const auto analysed=Clock::now();
        Json ds=Json::array(),ts=Json::array(),es=Json::array();
        for(const auto& d:detected.detections) ds.push_back({{"box",box_json(d.box)},{"class_id",d.class_id},{"confidence",d.confidence}});
        for(const auto& t:tracks) ts.push_back({{"track_id",t.track_id},{"box",box_json(t.box)},
            {"class_id",t.class_id},{"confidence",t.confidence},{"state","tracked"},{"age",t.age},{"missed_frames",t.missed_frames},
            {"anchor",{std::clamp((t.box.x+.5F*t.box.width)/frame.width,0.F,1.F),std::clamp((t.box.y+t.box.height)/frame.height,0.F,1.F)}}});
        for(const auto& e:event_rows) es.push_back(event_json(e));
        const auto& timing=detected.timing;
        trace << Json({{"sequence",frame.sequence},{"pts_ns",frame.pts_ns},{"stream_generation",0},
            {"detections",ds},{"tracks",ts},{"events",es},
            {"timing_ms",{{"load",ms(frame_start,loaded)},{"preprocess",timing.preprocess_ms},
                {"trt",timing.tensorrt_inference_ms},{"postprocess",timing.postprocess_ms},
                {"bytetrack",ms(track_start,tracked)},{"event_rules",ms(tracked,analysed)},
                {"sequential_processing",ms(frame_start,analysed)}}}}).dump() << '\n';
    }
    trace.flush(); trace.close();
    const auto elapsed=ms(started,Clock::now())/1000.;
    Json summary={{"schema_version",1},{"status","COMPLETE"},{"backend","jetson_tensorrt"},
        {"job",job},{"frames",job.at("frames").size()},{"target_reached",true},{"dropped_frames",0},{"sequence_gaps",0},
        {"warmup_frames",0},{"wall_seconds",elapsed},{"replay_fps",job.at("frames").size()/elapsed},
        {"fps_boundary","first_PNG_read_to_trace_flush_excludes_engine_initialization"},
        {"e2e_p95_ms",nullptr},{"event_io_ms",nullptr},{"telemetry",nullptr},
        {"media_evidence_status","NOT_PRODUCED_trace_only"},{"csi_acceptance",false}};
    std::ofstream report(output/"summary.json"); report.exceptions(std::ios::badbit|std::ios::failbit);
    report << summary.dump(2) << '\n'; report.flush();
    std::cout << "replay=COMPLETE frames=" << job.at("frames").size() << '\n';
}
#endif
} // namespace

int main(int argc,char** argv) {
    try {
        if(argc==2 && std::string(argv[1])=="--self-test") {self_test();return 0;}
        if(argc==3 && std::string(argv[1])=="--validate-job") {
            validate_job(read(argv[2])); std::cout<<"job_structure=PASS no_device_operation=true\n";return 0;
        }
        require(argc==5 && std::string(argv[1])=="--job" && std::string(argv[3])=="--output",
            "Usage: edge_vision_source_resolution_replay --job JOB.json --output NEW_DIR | --validate-job JOB.json | --self-test");
        const auto job=read(argv[2]);validate_job(job);
#ifdef EDGE_VISION_SOURCE_REPLAY_TENSORRT
        replay(job,argv[4]);return 0;
#else
        throw std::runtime_error("TensorRT backend not compiled; host checks cannot run device inference");
#endif
    } catch(const std::exception& e) {std::cerr<<"replay=FAIL "<<e.what()<<'\n';return 1;}
}
