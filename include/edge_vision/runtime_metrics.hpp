#pragma once

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>

#include "edge_vision/jetson_telemetry.hpp"

namespace edge_vision {

struct RuntimeStatusMetrics {
    bool target_reached{false};
    std::uint64_t invalid_frames{0};
    bool source_exhausted{false};
    bool recovery_exhausted{false};
    bool continuous{false};
    bool shutdown_requested{false};
    int shutdown_signal{0};
};

struct RuntimePipelineMetrics {
    std::uint64_t produced_frames{0};
    std::uint64_t processed_frames{0};
    std::uint64_t warmup_frames{0};
    std::uint64_t measured_frames{0};
    std::uint64_t target_frames{0};
    std::uint64_t warmup_dropped_frames{0};
    std::uint64_t dropped_frames{0};
    std::uint64_t dropped_frames_total{0};
    double drop_rate_percent{0.0};
    std::size_t queue_capacity{0};
    std::size_t queue_high_watermark{0};
    std::uint64_t sequence_gaps{0};
    std::uint64_t restart_attempts{0};
    std::uint64_t restart_successes{0};
    std::uint64_t stream_generation{0};
    std::uint64_t detection_frames{0};
    std::uint64_t total_detections{0};
    std::uint64_t tracking_frames{0};
    std::uint64_t total_track_observations{0};
    std::uint64_t unique_track_ids{0};
    std::uint64_t max_active_tracks{0};
    std::uint64_t tracker_resets{0};
    std::uint64_t tracker_gap_updates{0};
    bool event_analysis_enabled{false};
    std::uint64_t event_frames{0};
    std::uint64_t total_events{0};
    std::uint64_t roi_intrusion_events{0};
    std::uint64_t line_crossing_events{0};
    std::uint64_t dwell_events{0};
    double effective_fps{0.0};
    std::size_t latency_window_capacity{0};
    std::size_t latency_window_samples{0};
};

struct RuntimeLatencyMetrics {
    double mean_ms{0.0};
    double p50_ms{0.0};
    double p95_ms{0.0};
    double maximum_ms{0.0};
    std::size_t samples{0};
};

struct RuntimeOutputMetrics {
    bool event_journal_enabled{false};
    std::uint64_t event_records_written{0};
    std::uint64_t event_duplicates_skipped{0};
    bool snapshot_output_enabled{false};
    std::uint64_t snapshots_written{0};
    std::uint64_t snapshots_reused{0};
    bool event_clip_output_enabled{false};
    std::uint64_t event_clips_started{0};
    std::uint64_t event_clips_completed{0};
    std::uint64_t event_clips_reused{0};
    std::uint64_t event_clips_skipped{0};
    std::uint64_t event_clip_frames_encoded{0};
    std::size_t event_clip_queue_high_watermark{0};
    double event_clip_encoding_total_ms{0.0};
    double event_clip_encoding_max_ms{0.0};
    double event_clip_flush_ms{0.0};
    bool annotated_video_enabled{false};
    std::string annotated_video_encoder{"disabled"};
    std::uint32_t annotated_video_bitrate_kbps{0};
    std::uint64_t video_frames_submitted{0};
    std::uint64_t video_frames_written{0};
    std::uint64_t video_frames_dropped{0};
    std::size_t video_queue_high_watermark{0};
    double video_encoding_total_ms{0.0};
    double video_encoding_max_ms{0.0};
    double video_flush_ms{0.0};
};

struct RuntimeMetricsReport {
    std::uint32_t schema_version{1};
    std::string source;
    RuntimeStatusMetrics status;
    RuntimePipelineMetrics pipeline;
    std::map<std::string, RuntimeLatencyMetrics> latency_ms;
    RuntimeOutputMetrics outputs;
    JetsonTelemetrySummary device;
    std::string device_sampler_error;
};

void write_runtime_metrics_json(
    const std::string& output_path,
    const RuntimeMetricsReport& report);

}  // namespace edge_vision
