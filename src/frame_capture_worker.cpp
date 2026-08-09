#include "edge_vision/frame_capture_worker.hpp"

#include <stdexcept>
#include <utility>

namespace edge_vision {

FrameCaptureWorker::FrameCaptureWorker(
    std::unique_ptr<IFrameSource> source,
    const std::size_t queue_capacity)
    : source_(std::move(source)), queue_(queue_capacity) {
    if (!source_) {
        throw std::invalid_argument("frame source must not be null");
    }
}

FrameCaptureWorker::~FrameCaptureWorker() {
    stop();
}

bool FrameCaptureWorker::start() {
    if (started_ || !source_->open()) {
        return false;
    }

    started_ = true;
    running_.store(true);
    worker_ = std::thread(&FrameCaptureWorker::capture_loop, this);
    return true;
}

void FrameCaptureWorker::wait() {
    if (worker_.joinable()) {
        worker_.join();
    }
}

void FrameCaptureWorker::stop() noexcept {
    stop_requested_.store(true);
    source_->close();
    wait();
    queue_.close();
    running_.store(false);
}

std::optional<Frame> FrameCaptureWorker::wait_pop() {
    return queue_.wait_pop();
}

std::optional<Frame> FrameCaptureWorker::try_pop() {
    return queue_.try_pop();
}

FrameCaptureStats FrameCaptureWorker::stats() const {
    return {
        produced_.load(),
        queue_.stats(),
        running_.load(),
        source_exhausted_.load(),
    };
}

void FrameCaptureWorker::capture_loop() noexcept {
    while (!stop_requested_.load()) {
        auto frame = source_->read();
        if (!frame.has_value()) {
            if (!stop_requested_.load()) {
                source_exhausted_.store(true);
            }
            break;
        }

        produced_.fetch_add(1);
        if (queue_.push(std::move(*frame)) == QueuePushResult::closed) {
            break;
        }
    }

    source_->close();
    queue_.close();
    running_.store(false);
}

}  // namespace edge_vision
