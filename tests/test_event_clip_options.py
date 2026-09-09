"""直接编译实际参数解析器，不加载模型、不打开输入源。"""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('g++'),
                     '实际C++解析器检查需要Linux/g++；Windows不替代此检查')
class EventClipOptionsTests(unittest.TestCase):
    def test_actual_parser_defaults_candidate_and_invalid_bounds(self):
        source = r'''
#define main original_realtime_main
#include "realtime_detect.cpp"
#undef main
Options parse(std::vector<std::string> extra) {
    std::vector<std::string> args{"check", "--engine", "not-loaded.plan", "--csi"};
    args.insert(args.end(), extra.begin(), extra.end());
    std::vector<char*> argv;
    for (auto& arg : args) argv.push_back(arg.data());
    return parse_options(static_cast<int>(argv.size()), argv.data());
}
int main() {
    auto baseline = parse({});
    if (baseline.event_roi_entry_seconds != 0 || baseline.event_dwell_rearm_on_exit ||
        baseline.event_clip_share_overlap || baseline.event_roi_exit_margin != 0 || baseline.event_roi_exit_seconds != 0 ||
        baseline.event_line_confirm_seconds != 0 || baseline.event_clip_capacity != 2 || baseline.event_clip_encoder !=
        edge_vision::AnnotatedVideoEncoder::OpenCvMp4v) return 1;
    auto candidate = parse({"--event-clip-encoder", "x264", "--event-clip-capacity", "8",
                            "--event-clip-bitrate-kbps", "10000"});
    if (candidate.event_clip_capacity != 8 || candidate.event_clip_encoder !=
        edge_vision::AnnotatedVideoEncoder::GStreamerX264 || candidate.event_clip_bitrate_kbps != 10000) return 2;
    if (candidate.score_threshold != baseline.score_threshold || candidate.nms_threshold != baseline.nms_threshold ||
        candidate.track_threshold != baseline.track_threshold || candidate.new_track_threshold != baseline.new_track_threshold ||
        candidate.match_threshold != baseline.match_threshold || candidate.track_buffer != baseline.track_buffer ||
        candidate.queue_capacity != baseline.queue_capacity || candidate.output_queue_capacity != baseline.output_queue_capacity ||
        candidate.event_clip_pre_seconds != baseline.event_clip_pre_seconds || candidate.event_clip_post_seconds != baseline.event_clip_post_seconds) return 3;
    auto guarded=parse({"--event-roi","0.2","0.35","0.8","0.95","--event-roi-exit-margin","0.02",
                       "--event-roi-exit-seconds","0.5","--event-jsonl","not-written.jsonl",
                       "--event-clip-dir","not-created","--event-clip-share-overlap",
                       "--event-clip-max-shared-seconds","10","--event-clip-max-shared-events","32"});
    if(!guarded.event_clip_share_overlap || guarded.event_roi_exit_margin!=.02F || guarded.event_roi_exit_seconds!=.5F ||
       guarded.event_clip_max_shared_events!=32 || guarded.event_clip_max_shared_seconds!=10) return 5;
    auto rules=make_event_config(guarded);
    if(rules.roi_intrusion_rules[0].exit_confirmation_ns!=500000000LL || rules.roi_intrusion_rules[0].exit_margin!=.02F) return 6;
    auto line = parse({"--event-line", "0.5", "0.2", "0.5", "0.8", "--event-line-confirm-seconds", "0.2"});
    if (make_event_config(line).line_crossing_rules[0].confirmation_ns != 200000000LL) return 7;
    auto legacy_line = parse({"--event-line", "0.5", "0.2", "0.5", "0.8"});
    if (make_event_config(legacy_line).line_crossing_rules[0].confirmation_ns != 0) return 8;
    for (auto value : {"-0.1", "nan", "inf", "61", "0.2junk", "0.0000000001"}) {
        try { parse({"--event-line", "0.5", "0.2", "0.5", "0.8", "--event-line-confirm-seconds", value}); return 9; }
        catch (const std::exception&) {}
    }
    auto max_line = parse({"--event-line", "0.5", "0.2", "0.5", "0.8", "--event-line-confirm-seconds", "60"});
    auto min_line = parse({"--event-line", "0.5", "0.2", "0.5", "0.8", "--event-line-confirm-seconds", "0.000000001"});
    if (make_event_config(max_line).line_crossing_rules[0].confirmation_ns != 60000000000LL ||
        make_event_config(min_line).line_crossing_rules[0].confirmation_ns != 1) return 10;
    auto quality = parse({"--event-roi", "0.2", "0.2", "0.8", "0.8", "--event-roi-entry-seconds", "0.5",
                          "--event-dwell-seconds", "3", "--event-dwell-rearm-on-exit"});
    const auto quality_rules = make_event_config(quality);
    if (quality_rules.roi_intrusion_rules[0].entry_confirmation_ns != 500000000LL ||
        !quality_rules.dwell_rules[0].rearm_on_observed_exit) return 11;
    for (auto value : {"-0.1", "nan", "inf", "61", "0.5junk", "0.0000000001"}) {
        try { parse({"--event-roi", "0.2", "0.2", "0.8", "0.8", "--event-roi-entry-seconds", value}); return 12; }
        catch (const std::exception&) {}
    }
    const std::vector<std::vector<std::string>> invalid{
        {"--event-roi-entry-seconds", "0.5"}, {"--event-roi-entry-seconds", "0"},
        {"--event-roi-entry-seconds"}, {"--event-dwell-rearm-on-exit"},
        {"--event-line-confirm-seconds", "0.2"}, {"--event-line-confirm-seconds", "0"},
        {"--event-line-confirm-seconds"}, {"--event-clip-capacity", "0"}, {"--event-clip-capacity", "9"},
        {"--event-clip-capacity", "-1"}, {"--event-clip-capacity", "1.5"},
        {"--event-clip-capacity", "18446744073709551616"},
        {"--event-clip-share-overlap"}, {"--event-clip-max-shared-events","0"},
        {"--event-clip-max-shared-seconds","61"}, {"--event-roi-exit-margin","0.02"},
        {"--event-roi-exit-seconds","nan"}, {"--event-roi-exit-margin","-0.02"},
        {"--event-clip-encoder", "invalid"}, {"--event-clip-bitrate-kbps", "0"},
        {"--event-clip-bitrate-kbps", "4294967296"}, {"--event-clip-capacity"}};
    for (const auto& args : invalid) {
        try { parse(args); return 4; } catch (const std::exception&) {}
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='event-clip-options-') as work:
            cpp = pathlib.Path(work) / 'check.cpp'
            cpp.write_text(source, encoding='utf-8')
            binary = pathlib.Path(work) / 'check'
            built = subprocess.run(['g++', '-std=c++17', '-O1', '-ffunction-sections',
                                    '-fdata-sections', '-Wl,--gc-sections', '-I' + str(ROOT / 'apps'),
                                    '-I' + str(ROOT / 'include'), '-I/usr/include/opencv4',
                                    str(cpp), '-o', str(binary)], capture_output=True, text=True, timeout=180)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == '__main__':
    unittest.main()
