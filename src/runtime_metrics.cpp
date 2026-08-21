#include "edge_vision/runtime_metrics.hpp"

#include <filesystem>
#include <fstream>
#include <optional>
#include <stdexcept>
#include <system_error>

#include <nlohmann/json.hpp>

namespace edge_vision {
namespace {

nlohmann::json optional_number(const std::optional<double>& value) {
    return value.has_value() ? nlohmann::json(*value) : nlohmann::json(nullptr);
}

nlohmann::json numeric_summary(const NumericMetricSummary& summary) {
    return {
        {"samples", summary.samples},
        {"mean", optional_number(summary.mean)},
        {"p95", optional_number(summary.p95)},
        {"max", optional_number(summary.maximum)},
    };
}

nlohmann::json latency_summary(const RuntimeLatencyMetrics& summary) {
    return {
        {"samples", summary.samples},
        {"mean", summary.mean_ms},
        {"p50", summary.p50_ms},
        {"p95", summary.p95_ms},
        {"max", summary.maximum_ms},
    };
}

nlohmann::json make_json(const RuntimeMetricsReport& report) {
    nlohmann::json latencies = nlohmann::json::object();
    for (const auto& [name, summary] : report.latency_ms) {
        latencies[name] = latency_summary(summary);
    }

    const auto& pipeline = report.pipeline;
    const auto& outputs = report.outputs;
    const auto& device = report.device;
    return {
        {"schema_version", report.schema_version},
        {"source", report.source},
        {"status",
         {
             {"target_reached", report.status.target_reached},
             {"invalid_frames", report.status.invalid_frames},
             {"source_exhausted", report.status.source_exhausted},
             {"recovery_exhausted", report.status.recovery_exhausted},
             {"continuous", report.status.continuous},
             {"shutdown_requested", report.status.shutdown_requested},
             {"shutdown_signal", report.status.shutdown_signal},
         }},
        {"pipeline",
         {
             {"produced_frames", pipeline.produced_frames},
             {"processed_frames", pipeline.processed_frames},
             {"warmup_frames", pipeline.warmup_frames},
             {"measured_frames", pipeline.measured_frames},
             {"target_frames", pipeline.target_frames},
             {"warmup_dropped_frames", pipeline.warmup_dropped_frames},
             {"dropped_frames", pipeline.dropped_frames},
             {"dropped_frames_total", pipeline.dropped_frames_total},
             {"drop_rate_percent", pipeline.drop_rate_percent},
             {"queue_capacity", pipeline.queue_capacity},
             {"queue_high_watermark", pipeline.queue_high_watermark},
             {"sequence_gaps", pipeline.sequence_gaps},
             {"restart_attempts", pipeline.restart_attempts},
             {"restart_successes", pipeline.restart_successes},
             {"stream_generation", pipeline.stream_generation},
             {"detection_frames", pipeline.detection_frames},
             {"total_detections", pipeline.total_detections},
             {"tracking_frames", pipeline.tracking_frames},
             {"total_track_observations",
              pipeline.total_track_observations},
             {"unique_track_ids", pipeline.unique_track_ids},
             {"max_active_tracks", pipeline.max_active_tracks},
             {"tracker_resets", pipeline.tracker_resets},
             {"tracker_gap_updates", pipeline.tracker_gap_updates},
             {"event_analysis_enabled",
              pipeline.event_analysis_enabled},
             {"event_frames", pipeline.event_frames},
             {"total_events", pipeline.total_events},
             {"roi_intrusion_events", pipeline.roi_intrusion_events},
             {"line_crossing_events", pipeline.line_crossing_events},
             {"dwell_events", pipeline.dwell_events},
             {"effective_fps", pipeline.effective_fps},
             {"latency_window_capacity", pipeline.latency_window_capacity},
             {"latency_window_samples", pipeline.latency_window_samples},
         }},
        {"latency_ms", std::move(latencies)},
        {"outputs",
         {
             {"event_journal",
              {
                  {"enabled", outputs.event_journal_enabled},
                  {"records_written", outputs.event_records_written},
                  {"duplicates_skipped",
                   outputs.event_duplicates_skipped},
              }},
             {"snapshots",
              {
                  {"enabled", outputs.snapshot_output_enabled},
                  {"written", outputs.snapshots_written},
                  {"reused", outputs.snapshots_reused},
              }},
             {"event_clips",
              {
                  {"enabled", outputs.event_clip_output_enabled},
                  {"started", outputs.event_clips_started},
                  {"completed", outputs.event_clips_completed},
                  {"reused", outputs.event_clips_reused},
                  {"skipped", outputs.event_clips_skipped},
                  {"frames_encoded",
                   outputs.event_clip_frames_encoded},
                  {"queue_high_watermark",
                   outputs.event_clip_queue_high_watermark},
                  {"encoding_total_ms",
                   outputs.event_clip_encoding_total_ms},
                  {"encoding_max_ms",
                   outputs.event_clip_encoding_max_ms},
                  {"flush_ms", outputs.event_clip_flush_ms},
              }},
             {"annotated_video",
              {
                  {"enabled", outputs.annotated_video_enabled},
                  {"frames_submitted",
                   outputs.video_frames_submitted},
                  {"frames_written", outputs.video_frames_written},
                  {"frames_dropped", outputs.video_frames_dropped},
                  {"queue_high_watermark",
                   outputs.video_queue_high_watermark},
                  {"encoding_total_ms",
                   outputs.video_encoding_total_ms},
                  {"encoding_max_ms",
                   outputs.video_encoding_max_ms},
                  {"flush_ms", outputs.video_flush_ms},
              }},
         }},
        {"device",
         {
             {"available", device.samples > 0},
             {"samples", device.samples},
             {"sampler_error",
              report.device_sampler_error.empty()
                  ? nlohmann::json(nullptr)
                  : nlohmann::json(report.device_sampler_error)},
             {"ram_used_mb", numeric_summary(device.ram_used_mb)},
             {"ram_total_mb", numeric_summary(device.ram_total_mb)},
             {"cpu_utilization_percent",
              numeric_summary(device.cpu_utilization_percent)},
             {"gpu_utilization_percent",
              numeric_summary(device.gpu_utilization_percent)},
             {"cpu_temperature_c",
              numeric_summary(device.cpu_temperature_c)},
             {"gpu_temperature_c",
              numeric_summary(device.gpu_temperature_c)},
             {"junction_temperature_c",
              numeric_summary(device.junction_temperature_c)},
             {"input_power_w", numeric_summary(device.input_power_w)},
         }},
    };
}

}  // namespace

void write_runtime_metrics_json(
    const std::string& output_path,
    const RuntimeMetricsReport& report) {
    if (output_path.empty()) {
        throw std::invalid_argument("metrics output path must not be empty");
    }

    const std::filesystem::path path{output_path};
    if (!path.parent_path().empty()) {
        std::filesystem::create_directories(path.parent_path());
    }
    std::filesystem::path temporary = path;
    temporary += ".tmp";

    try {
        std::ofstream stream(temporary, std::ios::out | std::ios::trunc);
        if (!stream) {
            throw std::runtime_error(
                "failed to open metrics output: " + temporary.string());
        }
        stream << make_json(report).dump(2) << '\n';
        stream.close();
        if (!stream) {
            throw std::runtime_error(
                "failed to write metrics output: " + temporary.string());
        }

        std::error_code error;
        std::filesystem::rename(temporary, path, error);
        if (error) {
            throw std::runtime_error(
                "failed to publish metrics output: " + error.message());
        }
    } catch (...) {
        std::error_code ignored;
        std::filesystem::remove(temporary, ignored);
        throw;
    }
}

}  // namespace edge_vision
