#include "video_encoder_sink.hpp"

#if defined(EDGE_VISION_HAS_GSTREAMER_X264)

#include <gst/app/gstappsrc.h>
#include <gst/gst.h>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <memory>
#include <mutex>
#include <numeric>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace edge_vision::detail {
namespace {

void initialize_gstreamer() {
    static std::once_flag initialized;
    std::call_once(initialized, [] { gst_init(nullptr, nullptr); });
}

std::pair<int, int> frame_rate_fraction(const double frames_per_second) {
    constexpr int scale = 1000;
    const double scaled = frames_per_second * scale;
    if (!std::isfinite(scaled) || scaled <= 0.0 ||
        scaled > static_cast<double>(std::numeric_limits<int>::max())) {
        throw std::invalid_argument("video output FPS is out of range");
    }
    int numerator = static_cast<int>(std::lround(scaled));
    int denominator = scale;
    const int divisor = std::gcd(numerator, denominator);
    numerator /= divisor;
    denominator /= divisor;
    return {numerator, denominator};
}

void unref_if_present(GstElement* element) noexcept {
    if (element != nullptr) {
        gst_object_unref(element);
    }
}

std::string message_error(GstMessage* message) {
    GError* error = nullptr;
    gchar* debug = nullptr;
    gst_message_parse_error(message, &error, &debug);
    std::string result = error != nullptr && error->message != nullptr
                             ? error->message
                             : "unknown GStreamer error";
    if (debug != nullptr && *debug != '\0') {
        result += " (";
        result += debug;
        result += ')';
    }
    if (error != nullptr) {
        g_error_free(error);
    }
    g_free(debug);
    return result;
}

class GStreamerX264Sink final : public VideoEncoderSink {
public:
    GStreamerX264Sink(
        std::string output_path,
        const double frames_per_second,
        const cv::Size& frame_size,
        const unsigned int bitrate_kbps)
        : output_path_(std::move(output_path)),
          frame_size_(frame_size),
          frame_rate_(frame_rate_fraction(frames_per_second)) {
        initialize_gstreamer();
        try {
            open(bitrate_kbps);
        } catch (...) {
            close_noexcept();
            throw;
        }
    }

    ~GStreamerX264Sink() override {
        close_noexcept();
    }

    void write(const cv::Mat& image) override {
        if (finished_) {
            throw std::runtime_error("x264 video encoder is already closed");
        }
        if (image.size() != frame_size_ || image.type() != CV_8UC3) {
            throw std::invalid_argument(
                "x264 video output requires fixed-size BGR frames");
        }

        const gsize row_bytes = static_cast<gsize>(image.cols) * 3U;
        const gsize buffer_bytes = row_bytes * static_cast<gsize>(image.rows);
        GstBuffer* buffer =
            gst_buffer_new_allocate(nullptr, buffer_bytes, nullptr);
        if (buffer == nullptr) {
            throw std::runtime_error("failed to allocate GStreamer video buffer");
        }

        GstMapInfo mapping{};
        if (!gst_buffer_map(buffer, &mapping, GST_MAP_WRITE)) {
            gst_buffer_unref(buffer);
            throw std::runtime_error("failed to map GStreamer video buffer");
        }
        for (int row = 0; row < image.rows; ++row) {
            std::memcpy(
                mapping.data + static_cast<gsize>(row) * row_bytes,
                image.ptr(row),
                row_bytes);
        }
        gst_buffer_unmap(buffer, &mapping);

        const auto [numerator, denominator] = frame_rate_;
        GST_BUFFER_PTS(buffer) = gst_util_uint64_scale(
            frame_index_,
            GST_SECOND * static_cast<guint64>(denominator),
            static_cast<guint64>(numerator));
        GST_BUFFER_DTS(buffer) = GST_CLOCK_TIME_NONE;
        GST_BUFFER_DURATION(buffer) = gst_util_uint64_scale(
            1,
            GST_SECOND * static_cast<guint64>(denominator),
            static_cast<guint64>(numerator));
        GST_BUFFER_OFFSET(buffer) = frame_index_;

        const GstFlowReturn flow =
            gst_app_src_push_buffer(GST_APP_SRC(app_source_), buffer);
        if (flow != GST_FLOW_OK) {
            throw std::runtime_error(
                "failed to submit frame to x264 encoder: " +
                std::string(gst_flow_get_name(flow)));
        }
        ++frame_index_;
    }

    void finish() override {
        if (finished_) {
            return;
        }
        finished_ = true;
        try {
            const GstFlowReturn flow =
                gst_app_src_end_of_stream(GST_APP_SRC(app_source_));
            if (flow != GST_FLOW_OK) {
                throw std::runtime_error(
                    "failed to finish x264 input stream: " +
                    std::string(gst_flow_get_name(flow)));
            }

            GstBus* bus = gst_element_get_bus(pipeline_);
            GstMessage* message = gst_bus_timed_pop_filtered(
                bus,
                30 * GST_SECOND,
                static_cast<GstMessageType>(GST_MESSAGE_EOS | GST_MESSAGE_ERROR));
            gst_object_unref(bus);
            if (message == nullptr) {
                throw std::runtime_error(
                    "timed out while finalizing x264 MP4 output");
            }
            if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_ERROR) {
                const std::string error = message_error(message);
                gst_message_unref(message);
                throw std::runtime_error(
                    "x264 MP4 pipeline failed: " + error);
            }
            gst_message_unref(message);
        } catch (...) {
            close_noexcept();
            throw;
        }
        close_noexcept();
    }

private:
    void open(const unsigned int bitrate_kbps) {
        GstElement* source = gst_element_factory_make("appsrc", "frames");
        GstElement* convert = gst_element_factory_make("videoconvert", "convert");
        GstElement* filter = gst_element_factory_make("capsfilter", "i420-filter");
        GstElement* encoder = gst_element_factory_make("x264enc", "encoder");
        GstElement* parser = gst_element_factory_make("h264parse", "parser");
        GstElement* muxer = gst_element_factory_make("mp4mux", "muxer");
        GstElement* sink = gst_element_factory_make("filesink", "sink");
        pipeline_ = gst_pipeline_new("annotated-video-x264");

        std::vector<std::string> missing_elements;
        const auto record_missing = [&](GstElement* element, const char* name) {
            if (element == nullptr) {
                missing_elements.emplace_back(name);
            }
        };
        record_missing(source, "appsrc");
        record_missing(convert, "videoconvert");
        record_missing(filter, "capsfilter");
        record_missing(encoder, "x264enc");
        record_missing(parser, "h264parse");
        record_missing(muxer, "mp4mux");
        record_missing(sink, "filesink");
        if (pipeline_ == nullptr || !missing_elements.empty()) {
            unref_if_present(source);
            unref_if_present(convert);
            unref_if_present(filter);
            unref_if_present(encoder);
            unref_if_present(parser);
            unref_if_present(muxer);
            unref_if_present(sink);
            std::string message = pipeline_ == nullptr
                                      ? "failed to allocate GStreamer pipeline"
                                      : "missing GStreamer elements:";
            for (const std::string& name : missing_elements) {
                message += ' ';
                message += name;
            }
            message +=
                "; install gstreamer1.0-plugins-base, "
                "gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, and "
                "gstreamer1.0-plugins-ugly";
            throw std::runtime_error(message);
        }

        const auto [numerator, denominator] = frame_rate_;
        GstCaps* source_caps = gst_caps_new_simple(
            "video/x-raw",
            "format",
            G_TYPE_STRING,
            "BGR",
            "width",
            G_TYPE_INT,
            frame_size_.width,
            "height",
            G_TYPE_INT,
            frame_size_.height,
            "framerate",
            GST_TYPE_FRACTION,
            numerator,
            denominator,
            nullptr);
        GstCaps* i420_caps = gst_caps_new_simple(
            "video/x-raw", "format", G_TYPE_STRING, "I420", nullptr);
        g_object_set(
            source,
            "caps",
            source_caps,
            "format",
            GST_FORMAT_TIME,
            "is-live",
            FALSE,
            "block",
            TRUE,
            "max-buffers",
            static_cast<guint64>(1),
            nullptr);
        g_object_set(filter, "caps", i420_caps, nullptr);
        gst_caps_unref(source_caps);
        gst_caps_unref(i420_caps);

        gst_util_set_object_arg(G_OBJECT(encoder), "speed-preset", "ultrafast");
        gst_util_set_object_arg(G_OBJECT(encoder), "tune", "zerolatency");
        g_object_set(
            encoder,
            "bitrate",
            bitrate_kbps,
            "key-int-max",
            std::max(1, static_cast<int>(std::lround(
                            static_cast<double>(numerator) / denominator))),
            "bframes",
            static_cast<guint>(0),
            "ref",
            static_cast<guint>(1),
            "option-string",
            "aq-mode=0:scenecut=0",
            nullptr);
        g_object_set(sink, "location", output_path_.c_str(), "sync", FALSE, nullptr);

        gst_bin_add_many(
            GST_BIN(pipeline_),
            source,
            convert,
            filter,
            encoder,
            parser,
            muxer,
            sink,
            nullptr);
        app_source_ = source;
        if (!gst_element_link_many(
                source,
                convert,
                filter,
                encoder,
                parser,
                muxer,
                sink,
                nullptr)) {
            throw std::runtime_error("failed to link the x264 MP4 pipeline");
        }
        if (gst_element_set_state(pipeline_, GST_STATE_PLAYING) ==
            GST_STATE_CHANGE_FAILURE) {
            throw std::runtime_error("failed to start the x264 MP4 pipeline");
        }
    }

    void close_noexcept() noexcept {
        if (pipeline_ != nullptr) {
            gst_element_set_state(pipeline_, GST_STATE_NULL);
            gst_object_unref(pipeline_);
            pipeline_ = nullptr;
            app_source_ = nullptr;
        }
    }

    std::string output_path_;
    cv::Size frame_size_;
    std::pair<int, int> frame_rate_;
    GstElement* pipeline_{nullptr};
    GstElement* app_source_{nullptr};
    guint64 frame_index_{0};
    bool finished_{false};
};

}  // namespace

std::unique_ptr<VideoEncoderSink> make_gstreamer_x264_sink(
    const std::string& output_path,
    const double frames_per_second,
    const cv::Size& frame_size,
    const unsigned int bitrate_kbps) {
    return std::make_unique<GStreamerX264Sink>(
        output_path,
        frames_per_second,
        frame_size,
        bitrate_kbps);
}

}  // namespace edge_vision::detail

#endif
