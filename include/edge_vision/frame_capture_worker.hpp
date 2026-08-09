#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <thread>

#include "edge_vision/bounded_frame_queue.hpp"
#include "edge_vision/frame_source.hpp"

namespace edge_vision {

struct FrameCaptureStats {
    std::uint64_t produced{0};
    FrameQueueStats queue;
    bool running{false};
    bool source_exhausted{false};
};

class FrameCaptureWorker {
public:
    FrameCaptureWorker(
        std::unique_ptr<IFrameSource> source,
        std::size_t queue_capacity);
    ~FrameCaptureWorker();

    FrameCaptureWorker(const FrameCaptureWorker&) = delete;
    FrameCaptureWorker& operator=(const FrameCaptureWorker&) = delete;

    bool start();
    void wait();
    void stop() noexcept;

    std::optional<Frame> wait_pop();
    std::optional<Frame> try_pop();
    [[nodiscard]] FrameCaptureStats stats() const;

private:
    void capture_loop() noexcept;

    std::unique_ptr<IFrameSource> source_;
    BoundedFrameQueue queue_;
    std::thread worker_;
    std::atomic<std::uint64_t> produced_{0};
    std::atomic<bool> stop_requested_{false};
    std::atomic<bool> running_{false};
    std::atomic<bool> source_exhausted_{false};
    bool started_{false};
};

}  // namespace edge_vision
