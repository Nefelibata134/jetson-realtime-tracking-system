#include <cmath>
#include <csignal>
#include <filesystem>
#include <fstream>
#include <iostream>

#include <nlohmann/json.hpp>

#include "edge_vision/runtime_metrics.hpp"

int main() {
    const std::filesystem::path output =
        std::filesystem::temp_directory_path() /
        "edge_vision_runtime_metrics_check.json";
    std::filesystem::remove(output);
    std::filesystem::remove(output.string() + ".tmp");

    edge_vision::RuntimeMetricsReport report;
    report.source = "csi";
    report.status.target_reached = true;
    report.status.continuous = false;
    report.status.shutdown_requested = true;
    report.status.shutdown_signal = SIGTERM;
    report.pipeline.measured_frames = 95;
    report.pipeline.dropped_frames = 5;
    report.pipeline.drop_rate_percent = 5.0;
    report.pipeline.effective_fps = 30.0;
    report.pipeline.latency_window_capacity = 4096;
    report.pipeline.latency_window_samples = 95;
    report.latency_ms["inference"] = {6.0, 5.8, 7.2, 12.0, 95};
    report.latency_ms["tensorrt_inference"] = {
        4.0, 3.8, 4.5, 6.0, 95};
    report.outputs.event_journal_enabled = true;
    report.outputs.event_records_written = 2;
    report.outputs.snapshot_output_enabled = true;
    report.outputs.snapshots_written = 2;
    report.outputs.event_clip_output_enabled = true;
    report.outputs.event_clips_completed = 2;
    report.outputs.event_clip_frames_encoded = 120;
    report.outputs.event_clip_encoding_total_ms = 80.0;
    report.outputs.annotated_video_enabled = true;
    report.outputs.video_frames_submitted = 95;
    report.outputs.video_frames_written = 95;
    report.outputs.video_encoding_total_ms = 190.0;
    report.device.samples = 2;
    report.device.input_power_w = {2, 8.0, 8.9, 9.0};

    edge_vision::write_runtime_metrics_json(output.string(), report);
    std::ifstream stream(output);
    nlohmann::json document;
    stream >> document;

    const bool schema = document.at("schema_version") == 1;
    const bool lifecycle =
        document.at("status").at("continuous") == false &&
        document.at("status").at("shutdown_requested") == true &&
        document.at("status").at("shutdown_signal") == SIGTERM &&
        document.at("pipeline").at("latency_window_capacity") == 4096 &&
        document.at("pipeline").at("latency_window_samples") == 95;
    const bool pipeline =
        document.at("pipeline").at("measured_frames") == 95 &&
        std::abs(
            document.at("pipeline").at("drop_rate_percent").get<double>() -
            5.0) < 0.001;
    const bool latency =
        document.at("latency_ms").at("inference").at("p95") == 7.2 &&
        document.at("latency_ms").at("inference").at("samples") == 95 &&
        document.at("latency_ms")
                .at("tensorrt_inference")
                .at("p95") == 4.5;
    const bool outputs =
        document.at("outputs")
                .at("event_journal")
                .at("records_written") == 2 &&
        document.at("outputs").at("snapshots").at("written") == 2 &&
        document.at("outputs")
                .at("event_clips")
                .at("frames_encoded") == 120 &&
        document.at("outputs")
                .at("annotated_video")
                .at("frames_written") == 95;
    const bool device =
        document.at("device").at("available") == true &&
        document.at("device").at("input_power_w").at("samples") == 2 &&
        document.at("device").at("input_power_w").at("mean").is_number() &&
        document.at("device").at("input_power_w").at("mean") == 8.0 &&
        document.at("device").at("sampler_error").is_null();

    report.pipeline.measured_frames = 96;
    edge_vision::write_runtime_metrics_json(output.string(), report);
    std::ifstream replacement_stream(output);
    nlohmann::json replacement;
    replacement_stream >> replacement;
    const bool replace =
        replacement.at("pipeline").at("measured_frames") == 96;
    const bool atomic = !std::filesystem::exists(output.string() + ".tmp");

    std::cout << "schema=" << std::boolalpha << schema << '\n';
    std::cout << "lifecycle=" << lifecycle << '\n';
    std::cout << "pipeline=" << pipeline << '\n';
    std::cout << "latency=" << latency << '\n';
    std::cout << "outputs=" << outputs << '\n';
    std::cout << "device=" << device << '\n';
    std::cout << "replace=" << replace << '\n';
    std::cout << "atomic=" << atomic << '\n';
    const bool passed =
        schema && lifecycle && pipeline && latency && outputs && device &&
        replace && atomic;
    std::cout << "status=" << (passed ? "PASS" : "FAIL") << '\n';

    std::filesystem::remove(output);
    return passed ? 0 : 1;
}
