#include "edge_vision/frame_capture_worker.hpp"

#include <chrono>
#include <stdexcept>
#include <thread>
#include <utility>

namespace edge_vision {

FrameCaptureWorker::FrameCaptureWorker(
    std::unique_ptr<IFrameSource> source,
    const std::size_t queue_capacity,
    const FrameCaptureRecoveryPolicy recovery_policy)
    : source_(std::move(source)),
      queue_(queue_capacity),
      recovery_policy_(recovery_policy) {
    if (!source_) {
        throw std::invalid_argument("frame source must not be null");
    }
}

FrameCaptureWorker::~FrameCaptureWorker() {
    stop();
}

bool FrameCaptureWorker::start() {
    if (started_) {
        return false;
    }

    if (!source_->open() && !restart_source()) {
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
        restart_attempts_.load(),
        restart_successes_.load(),
        stream_generation_.load(),
        queue_.stats(),
        running_.load(),
        source_exhausted_.load(),
        recovery_exhausted_.load(),
    };
}

bool FrameCaptureWorker::restart_source() noexcept {
    source_->close();
    while (!stop_requested_.load() &&
           restart_attempts_since_frame_ <
               recovery_policy_.max_restart_attempts) {
        ++restart_attempts_since_frame_;
        restart_attempts_.fetch_add(1);
        std::this_thread::sleep_for(
            std::chrono::milliseconds(recovery_policy_.restart_delay_ms));
        if (stop_requested_.load()) {
            return false;
        }
        if (source_->open()) {
            restart_successes_.fetch_add(1);
            stream_generation_.fetch_add(1);
            source_exhausted_.store(false);
            return true;
        }
    }

    if (recovery_policy_.max_restart_attempts > 0 &&
        restart_attempts_since_frame_ >=
            recovery_policy_.max_restart_attempts) {
        recovery_exhausted_.store(true);
    }
    return false;
}

void FrameCaptureWorker::capture_loop() noexcept {
    while (!stop_requested_.load()) {
        auto frame = source_->read();
        if (!frame.has_value()) {
            if (!stop_requested_.load()) {
                source_exhausted_.store(true);
            }
            if (!stop_requested_.load() && restart_source()) {
                continue;
            }
            break;
        }

        restart_attempts_since_frame_ = 0;
        recovery_exhausted_.store(false);
        frame->stream_generation = stream_generation_.load();
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
