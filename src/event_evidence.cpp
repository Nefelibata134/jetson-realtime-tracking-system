#include "edge_vision/event_evidence.hpp"

#include <opencv2/imgcodecs.hpp>

#include <filesystem>
#include <stdexcept>
#include <utility>

namespace edge_vision {

class EventEvidenceWriter::Impl {
public:
    explicit Impl(EventEvidenceWriterConfig config)
        : config_(std::move(config)) {
        if (config_.snapshot_directory.empty()) {
            throw std::invalid_argument(
                "event snapshot directory must not be empty");
        }
        if (config_.jpeg_quality < 1 || config_.jpeg_quality > 100) {
            throw std::invalid_argument(
                "event snapshot JPEG quality must be in [1, 100]");
        }
        std::filesystem::create_directories(config_.snapshot_directory);
    }

    [[nodiscard]] std::string write_snapshot(
        const EventRecord& record,
        const Frame& frame,
        const std::vector<Track>& tracks) {
        if (record.event_id.empty()) {
            throw std::invalid_argument(
                "event snapshot requires a non-empty event ID");
        }

        const std::filesystem::path final_path =
            std::filesystem::path(config_.snapshot_directory) /
            (record.event_id + ".jpg");
        if (valid_file(final_path)) {
            ++stats_.snapshots_reused;
            return final_path.generic_string();
        }

        const std::filesystem::path temporary_path =
            std::filesystem::path(config_.snapshot_directory) /
            (record.event_id + ".tmp.jpg");
        std::filesystem::remove(temporary_path);

        const Frame annotated = annotate_frame(
            frame,
            tracks,
            {record.event},
            config_.annotation);
        const cv::Mat image(
            annotated.height,
            annotated.width,
            CV_8UC3,
            const_cast<std::uint8_t*>(annotated.data.data()));
        if (!cv::imwrite(
                temporary_path.string(),
                image,
                {cv::IMWRITE_JPEG_QUALITY, config_.jpeg_quality}) ||
            !valid_file(temporary_path)) {
            std::filesystem::remove(temporary_path);
            throw std::runtime_error(
                "failed to write event snapshot: " + final_path.string());
        }

        std::filesystem::remove(final_path);
        std::filesystem::rename(temporary_path, final_path);
        if (!valid_file(final_path)) {
            throw std::runtime_error(
                "event snapshot verification failed: " +
                final_path.string());
        }
        ++stats_.snapshots_written;
        return final_path.generic_string();
    }

    [[nodiscard]] EventEvidenceWriterStats stats() const noexcept {
        return stats_;
    }

private:
    static bool valid_file(const std::filesystem::path& path) {
        return std::filesystem::exists(path) &&
               std::filesystem::is_regular_file(path) &&
               std::filesystem::file_size(path) > 0;
    }

    EventEvidenceWriterConfig config_;
    EventEvidenceWriterStats stats_;
};

EventEvidenceWriter::EventEvidenceWriter(EventEvidenceWriterConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}

EventEvidenceWriter::~EventEvidenceWriter() = default;

std::string EventEvidenceWriter::write_snapshot(
    const EventRecord& record,
    const Frame& frame,
    const std::vector<Track>& tracks) {
    return impl_->write_snapshot(record, frame, tracks);
}

EventEvidenceWriterStats EventEvidenceWriter::stats() const noexcept {
    return impl_->stats();
}

}  // namespace edge_vision
