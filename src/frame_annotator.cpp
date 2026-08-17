#include "edge_vision/frame_annotator.hpp"

#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>

namespace edge_vision {
namespace {

cv::Mat frame_to_bgr(const Frame& frame) {
    if (!frame.valid() || frame.channels != 3) {
        throw std::invalid_argument(
            "frame annotation requires a valid three-channel frame");
    }

    const cv::Mat view(
        frame.height,
        frame.width,
        CV_8UC3,
        const_cast<std::uint8_t*>(frame.data.data()));
    if (frame.format == PixelFormat::bgr8) {
        return view.clone();
    }

    cv::Mat bgr;
    cv::cvtColor(view, bgr, cv::COLOR_RGB2BGR);
    return bgr;
}

cv::Rect to_rectangle(const BoundingBox& box, const cv::Size& image_size) {
    const int x = std::clamp(
        static_cast<int>(std::lround(box.x)), 0, image_size.width - 1);
    const int y = std::clamp(
        static_cast<int>(std::lround(box.y)), 0, image_size.height - 1);
    const int right = std::clamp(
        static_cast<int>(std::lround(box.x + box.width)),
        x + 1,
        image_size.width);
    const int bottom = std::clamp(
        static_cast<int>(std::lround(box.y + box.height)),
        y + 1,
        image_size.height);
    return {x, y, right - x, bottom - y};
}

cv::Scalar track_color(const std::int64_t track_id) {
    const auto seed = static_cast<std::uint64_t>(track_id) * 2'654'435'761ULL;
    return {
        static_cast<double>(64U + (seed & 0x7FU)),
        static_cast<double>(64U + ((seed >> 8U) & 0x7FU)),
        static_cast<double>(64U + ((seed >> 16U) & 0x7FU)),
    };
}

std::string track_label(const Track& track) {
    std::ostringstream label;
    label << "ID " << track.track_id << " class " << track.class_id << ' '
          << std::fixed << std::setprecision(2) << track.confidence;
    return label.str();
}

cv::Point normalized_to_pixel(
    const NormalizedPoint& point,
    const cv::Size& image_size) {
    return {
        std::clamp(
            static_cast<int>(std::lround(
                point.x * static_cast<float>(image_size.width - 1))),
            0,
            image_size.width - 1),
        std::clamp(
            static_cast<int>(std::lround(
                point.y * static_cast<float>(image_size.height - 1))),
            0,
            image_size.height - 1),
    };
}

cv::Scalar event_color(const SafetyEventType type) {
    switch (type) {
        case SafetyEventType::RoiIntrusion:
            return {0, 165, 255};
        case SafetyEventType::LineCrossing:
            return {255, 0, 255};
        case SafetyEventType::Dwell:
            return {0, 0, 255};
    }
    return {255, 255, 255};
}

std::string event_label(const SafetyEvent& event) {
    std::ostringstream label;
    switch (event.type) {
        case SafetyEventType::RoiIntrusion:
            label << "ROI INTRUSION";
            break;
        case SafetyEventType::LineCrossing:
            label << "LINE CROSSING";
            break;
        case SafetyEventType::Dwell:
            label << "DWELL";
            break;
    }
    label << " ID " << event.track_id;
    return label.str();
}

void draw_rule_geometry(
    cv::Mat& image,
    const FrameAnnotationConfig& config) {
    for (const PolygonRegion& region : config.event_regions) {
        std::vector<cv::Point> points;
        points.reserve(region.vertices.size());
        for (const NormalizedPoint& point : region.vertices) {
            points.push_back(normalized_to_pixel(point, image.size()));
        }
        if (points.size() >= 3) {
            cv::polylines(
                image,
                points,
                true,
                cv::Scalar(0, 165, 255),
                2,
                cv::LINE_AA);
            cv::putText(
                image,
                "ROI",
                points.front() + cv::Point(4, -6),
                cv::FONT_HERSHEY_SIMPLEX,
                0.6,
                cv::Scalar(0, 165, 255),
                2,
                cv::LINE_AA);
        }
    }
    for (const NormalizedLineSegment& line : config.event_lines) {
        const cv::Point start = normalized_to_pixel(line.start, image.size());
        const cv::Point end = normalized_to_pixel(line.end, image.size());
        cv::line(
            image,
            start,
            end,
            cv::Scalar(255, 0, 255),
            3,
            cv::LINE_AA);
        cv::putText(
            image,
            "LINE",
            start + cv::Point(4, -6),
            cv::FONT_HERSHEY_SIMPLEX,
            0.6,
            cv::Scalar(255, 0, 255),
            2,
            cv::LINE_AA);
    }
}

void draw_label(
    cv::Mat& image,
    const cv::Rect& rectangle,
    const std::string& label,
    const cv::Scalar& color) {
    constexpr double font_scale = 0.5;
    constexpr int thickness = 1;
    int baseline = 0;
    const cv::Size text_size = cv::getTextSize(
        label,
        cv::FONT_HERSHEY_SIMPLEX,
        font_scale,
        thickness,
        &baseline);

    const int label_x = rectangle.x;
    const int label_top = std::max(0, rectangle.y - text_size.height - 8);
    const int label_right = std::min(
        image.cols - 1, label_x + text_size.width + 8);
    const int label_bottom = std::min(
        image.rows - 1, label_top + text_size.height + baseline + 8);

    cv::rectangle(
        image,
        cv::Point(label_x, label_top),
        cv::Point(label_right, label_bottom),
        color,
        cv::FILLED);
    cv::putText(
        image,
        label,
        cv::Point(label_x + 4, label_bottom - baseline - 4),
        cv::FONT_HERSHEY_SIMPLEX,
        font_scale,
        cv::Scalar(255, 255, 255),
        thickness,
        cv::LINE_AA);
}

}  // namespace

Frame annotate_frame(
    const Frame& frame,
    const std::vector<Track>& tracks,
    const std::vector<SafetyEvent>& events,
    const FrameAnnotationConfig& config) {
    cv::Mat image = frame_to_bgr(frame);
    draw_rule_geometry(image, config);

    for (const Track& track : tracks) {
        if (track.box.width <= 0.0F || track.box.height <= 0.0F) {
            continue;
        }
        const cv::Rect rectangle = to_rectangle(track.box, image.size());
        const cv::Scalar color = track_color(track.track_id);
        cv::rectangle(image, rectangle, color, 2, cv::LINE_AA);
        draw_label(image, rectangle, track_label(track), color);
        const cv::Point anchor{
            rectangle.x + rectangle.width / 2,
            rectangle.y + rectangle.height,
        };
        cv::circle(image, anchor, 5, color, cv::FILLED, cv::LINE_AA);
    }

    int label_y = 12;
    for (const SafetyEvent& event : events) {
        const std::string label = event_label(event);
        const cv::Scalar color = event_color(event.type);
        int baseline = 0;
        const cv::Size text_size = cv::getTextSize(
            label,
            cv::FONT_HERSHEY_SIMPLEX,
            0.7,
            2,
            &baseline);
        cv::rectangle(
            image,
            cv::Point(12, label_y),
            cv::Point(
                24 + text_size.width,
                label_y + text_size.height + baseline + 10),
            color,
            cv::FILLED);
        cv::putText(
            image,
            label,
            cv::Point(18, label_y + text_size.height + 3),
            cv::FONT_HERSHEY_SIMPLEX,
            0.7,
            cv::Scalar(255, 255, 255),
            2,
            cv::LINE_AA);
        cv::circle(
            image,
            normalized_to_pixel(event.anchor, image.size()),
            8,
            color,
            2,
            cv::LINE_AA);
        label_y += text_size.height + baseline + 16;
    }

    Frame annotated = frame;
    annotated.format = PixelFormat::bgr8;
    annotated.data.assign(image.datastart, image.dataend);
    return annotated;
}

}  // namespace edge_vision
