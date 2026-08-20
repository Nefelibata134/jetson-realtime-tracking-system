#pragma once

#include <condition_variable>
#include <chrono>
#include <cstddef>
#include <deque>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <utility>

#include "edge_vision/frame.hpp"

namespace edge_vision {

enum class QueuePushResult {
    pushed,
    replaced_oldest,
    closed,
};

enum class QueuePopStatus {
    frame,
    timeout,
    closed,
};

struct FrameQueuePopResult {
    QueuePopStatus status{QueuePopStatus::closed};
    std::optional<Frame> frame;
};

struct FrameQueueStats {
    std::size_t depth{0};
    std::size_t high_watermark{0};
    std::size_t dropped{0};
    bool closed{false};
};

class BoundedFrameQueue {
public:
    explicit BoundedFrameQueue(std::size_t capacity) : capacity_(capacity) {
        if (capacity == 0) {
            throw std::invalid_argument("frame queue capacity must be positive");
        }
    }

    BoundedFrameQueue(const BoundedFrameQueue&) = delete;
    BoundedFrameQueue& operator=(const BoundedFrameQueue&) = delete;

    QueuePushResult push(Frame frame) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (closed_) {
            return QueuePushResult::closed;
        }

        QueuePushResult result = QueuePushResult::pushed;
        if (queue_.size() == capacity_) {
            queue_.pop_front();
            ++dropped_;
            result = QueuePushResult::replaced_oldest;
        }

        queue_.push_back(std::move(frame));
        if (queue_.size() > high_watermark_) {
            high_watermark_ = queue_.size();
        }
        ready_.notify_one();
        return result;
    }

    std::optional<Frame> wait_pop() {
        std::unique_lock<std::mutex> lock(mutex_);
        ready_.wait(lock, [this] { return closed_ || !queue_.empty(); });

        if (queue_.empty()) {
            return std::nullopt;
        }

        Frame frame = std::move(queue_.front());
        queue_.pop_front();
        return frame;
    }

    FrameQueuePopResult wait_pop_for(
        const std::chrono::milliseconds timeout) {
        std::unique_lock<std::mutex> lock(mutex_);
        if (!ready_.wait_for(
                lock,
                timeout,
                [this] { return closed_ || !queue_.empty(); })) {
            return {QueuePopStatus::timeout, std::nullopt};
        }

        if (queue_.empty()) {
            return {QueuePopStatus::closed, std::nullopt};
        }

        Frame frame = std::move(queue_.front());
        queue_.pop_front();
        return {QueuePopStatus::frame, std::move(frame)};
    }

    std::optional<Frame> try_pop() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (queue_.empty()) {
            return std::nullopt;
        }

        Frame frame = std::move(queue_.front());
        queue_.pop_front();
        return frame;
    }

    void close() noexcept {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            closed_ = true;
        }
        ready_.notify_all();
    }

    [[nodiscard]] std::size_t capacity() const noexcept {
        return capacity_;
    }

    [[nodiscard]] FrameQueueStats stats() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return {queue_.size(), high_watermark_, dropped_, closed_};
    }

private:
    const std::size_t capacity_;
    mutable std::mutex mutex_;
    std::condition_variable ready_;
    std::deque<Frame> queue_;
    std::size_t high_watermark_{0};
    std::size_t dropped_{0};
    bool closed_{false};
};

}  // namespace edge_vision
