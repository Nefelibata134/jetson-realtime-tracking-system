#include "edge_vision/gstreamer_frame_source.hpp"

#include <gst/app/gstappsink.h>
#include <gst/gst.h>
#include <gst/video/video.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <utility>

namespace edge_vision {
namespace {

constexpr char kSinkName[] = "framesink";

std::int64_t monotonic_time_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

void initialize_gstreamer() {
    static std::once_flag initialized;
    std::call_once(initialized, [] { gst_init(nullptr, nullptr); });
}

std::string quote_property(const std::string& value) {
    gchar* escaped = g_strescape(value.c_str(), nullptr);
    if (escaped == nullptr) {
        return "\"\"";
    }
    const std::string result = std::string{"\""} + escaped + "\"";
    g_free(escaped);
    return result;
}

class GStreamerFrameSource final : public IFrameSource {
public:
    GStreamerFrameSource(std::string pipeline, std::string required_file)
        : pipeline_description_(std::move(pipeline)),
          required_file_(std::move(required_file)) {}

    ~GStreamerFrameSource() override {
        close();
    }

    bool open() override {
        if (opened_.load()) {
            return true;
        }
        if (!required_file_.empty() &&
            !std::filesystem::is_regular_file(required_file_)) {
            return false;
        }

        initialize_gstreamer();
        GError* error = nullptr;
        GstElement* pipeline =
            gst_parse_launch(pipeline_description_.c_str(), &error);
        if (error != nullptr) {
            g_error_free(error);
            if (pipeline != nullptr) {
                gst_object_unref(pipeline);
            }
            return false;
        }
        if (pipeline == nullptr) {
            return false;
        }

        GstElement* sink = gst_bin_get_by_name(GST_BIN(pipeline), kSinkName);
        if (sink == nullptr) {
            gst_object_unref(pipeline);
            return false;
        }

        const GstStateChangeReturn state =
            gst_element_set_state(pipeline, GST_STATE_PLAYING);
        if (state == GST_STATE_CHANGE_FAILURE) {
            gst_object_unref(sink);
            gst_element_set_state(pipeline, GST_STATE_NULL);
            gst_object_unref(pipeline);
            return false;
        }

        {
            std::lock_guard<std::mutex> lock(state_mutex_);
            pipeline_ = pipeline;
            sink_ = sink;
            opened_.store(true);
        }
        return true;
    }

    [[nodiscard]] bool is_open() const noexcept override {
        return opened_.load();
    }

    std::optional<Frame> read() override {
        GstElement* sink = nullptr;
        GstElement* pipeline = nullptr;
        {
            std::lock_guard<std::mutex> lock(state_mutex_);
            if (!opened_.load() || sink_ == nullptr || pipeline_ == nullptr) {
                return std::nullopt;
            }
            sink = GST_ELEMENT(gst_object_ref(sink_));
            pipeline = GST_ELEMENT(gst_object_ref(pipeline_));
        }
        GstBus* bus = gst_element_get_bus(pipeline);

        std::optional<Frame> result;
        bool terminal_message = false;
        while (opened_.load() && !terminal_message && !result.has_value()) {
            GstSample* sample = gst_app_sink_try_pull_sample(
                GST_APP_SINK(sink), 200 * GST_MSECOND);
            if (sample == nullptr) {
                if (gst_app_sink_is_eos(GST_APP_SINK(sink))) {
                    std::cerr << "GStreamer source reached EOS\n";
                    terminal_message = true;
                    continue;
                }
                if (bus != nullptr) {
                    GstMessage* message = gst_bus_pop_filtered(
                        bus,
                        static_cast<GstMessageType>(
                            GST_MESSAGE_ERROR | GST_MESSAGE_EOS));
                    if (message != nullptr) {
                        terminal_message = true;
                        if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_ERROR) {
                            GError* error = nullptr;
                            gchar* details = nullptr;
                            gst_message_parse_error(
                                message, &error, &details);
                            std::cerr << "GStreamer source error: "
                                      << (error == nullptr ? "unknown"
                                                           : error->message)
                                      << '\n';
                            g_clear_error(&error);
                            g_free(details);
                        } else {
                            std::cerr << "GStreamer pipeline reached EOS\n";
                        }
                        gst_message_unref(message);
                    }
                }
                continue;
            }

            GstCaps* caps = gst_sample_get_caps(sample);
            GstBuffer* buffer = gst_sample_get_buffer(sample);
            GstVideoInfo info;
            gst_video_info_init(&info);
            if (caps == nullptr || buffer == nullptr ||
                !gst_video_info_from_caps(&info, caps) ||
                GST_VIDEO_INFO_FORMAT(&info) != GST_VIDEO_FORMAT_BGR) {
                std::cerr << "GStreamer source skipped an invalid BGR sample\n";
                gst_sample_unref(sample);
                continue;
            }

            GstVideoFrame video_frame;
            if (!gst_video_frame_map(
                    &video_frame, &info, buffer, GST_MAP_READ)) {
                std::cerr << "GStreamer source skipped an unmappable sample\n";
                gst_sample_unref(sample);
                continue;
            }

            Frame frame;
            frame.width = GST_VIDEO_INFO_WIDTH(&info);
            frame.height = GST_VIDEO_INFO_HEIGHT(&info);
            frame.channels = 3;
            frame.format = PixelFormat::bgr8;
            frame.captured_at_ns = monotonic_time_ns();
            if (GST_BUFFER_PTS_IS_VALID(buffer)) {
                const auto raw_pts_ns = static_cast<std::int64_t>(
                    GST_BUFFER_PTS(buffer));
                std::int64_t normalized_pts_ns = raw_pts_ns + pts_offset_ns_;
                if (last_pts_ns_ >= 0 && normalized_pts_ns <= last_pts_ns_) {
                    pts_offset_ns_ = last_pts_ns_ + 1 - raw_pts_ns;
                    normalized_pts_ns = raw_pts_ns + pts_offset_ns_;
                }
                frame.pts_ns = normalized_pts_ns;
            } else {
                frame.pts_ns = frame.captured_at_ns;
            }
            last_pts_ns_ = frame.pts_ns;
            frame.sequence = sequence_++;
            frame.data.resize(frame.expected_bytes());

            const auto* source = static_cast<const std::uint8_t*>(
                GST_VIDEO_FRAME_PLANE_DATA(&video_frame, 0));
            const int source_stride =
                GST_VIDEO_FRAME_PLANE_STRIDE(&video_frame, 0);
            const std::size_t row_bytes =
                static_cast<std::size_t>(frame.width) * frame.channels;
            for (int row = 0; row < frame.height; ++row) {
                std::copy_n(
                    source + static_cast<std::ptrdiff_t>(row) * source_stride,
                    row_bytes,
                    frame.data.data() +
                        static_cast<std::size_t>(row) * row_bytes);
            }

            gst_video_frame_unmap(&video_frame);
            gst_sample_unref(sample);
            if (frame.valid()) {
                result = std::move(frame);
            } else {
                std::cerr << "GStreamer source skipped an invalid frame\n";
            }
        }

        if (bus != nullptr) {
            gst_object_unref(bus);
        }
        gst_object_unref(pipeline);
        gst_object_unref(sink);
        return result;
    }

    void close() noexcept override {
        opened_.store(false);

        GstElement* pipeline = nullptr;
        GstElement* sink = nullptr;
        {
            std::lock_guard<std::mutex> lock(state_mutex_);
            pipeline = pipeline_;
            sink = sink_;
            pipeline_ = nullptr;
            sink_ = nullptr;
        }

        if (pipeline != nullptr) {
            gst_element_set_state(pipeline, GST_STATE_NULL);
        }
        if (sink != nullptr) {
            gst_object_unref(sink);
        }
        if (pipeline != nullptr) {
            gst_object_unref(pipeline);
        }
    }

private:
    std::string pipeline_description_;
    std::string required_file_;
    mutable std::mutex state_mutex_;
    GstElement* pipeline_{nullptr};
    GstElement* sink_{nullptr};
    std::atomic<bool> opened_{false};
    std::uint64_t sequence_{0};
    std::int64_t pts_offset_ns_{0};
    std::int64_t last_pts_ns_{-1};
};

std::string sink_fragment() {
    return " ! video/x-raw,format=BGR"
           " ! appsink name=framesink sync=false max-buffers=1 drop=true";
}

}  // namespace

std::unique_ptr<IFrameSource> make_gstreamer_file_source(
    const std::string& path) {
    std::ostringstream pipeline;
    pipeline << "filesrc location=" << quote_property(path)
             << " ! qtdemux ! h264parse ! nvv4l2decoder ! nvvidconv"
             << " ! video/x-raw,format=BGRx ! videoconvert"
             << sink_fragment();
    return std::make_unique<GStreamerFrameSource>(pipeline.str(), path);
}

std::unique_ptr<IFrameSource> make_gstreamer_csi_source(
    const CsiCameraConfig& config) {
    const int capture_width = config.capture_width > 0
                                  ? config.capture_width
                                  : config.width;
    const int capture_height = config.capture_height > 0
                                   ? config.capture_height
                                   : config.height;
    const int capture_fps = config.capture_frames_per_second > 0
                                ? config.capture_frames_per_second
                                : config.frames_per_second;

    std::ostringstream pipeline;
    pipeline << "nvarguscamerasrc sensor-id=" << config.sensor_id;
    if (config.sensor_mode >= 0) {
        pipeline << " sensor-mode=" << config.sensor_mode;
    }
    pipeline << " ! video/x-raw(memory:NVMM),width=" << capture_width
             << ",height=" << capture_height
             << ",framerate=" << capture_fps
             << "/1,format=NV12 ! nvvidconv"
             << " ! video/x-raw,format=BGRx,width=" << config.width
             << ",height=" << config.height;
    if (capture_fps != config.frames_per_second) {
        pipeline << " ! videorate ! video/x-raw,format=BGRx,framerate="
                 << config.frames_per_second << "/1";
    }
    pipeline << " ! videoconvert"
             << sink_fragment();
    return std::make_unique<GStreamerFrameSource>(pipeline.str(), "");
}

}  // namespace edge_vision
