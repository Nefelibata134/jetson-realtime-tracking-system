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
    std::uint64_t restart_attempts{0};
    std::uint64_t restart_successes{0};
    FrameQueueStats queue;
    bool running{false};
    bool source_exhausted{false};
    bool recovery_exhausted{false};
};

struct FrameCaptureRecoveryPolicy {
    std::uint64_t max_restart_attempts{0};
    std::uint64_t restart_delay_ms{500};
};

class FrameCaptureWorker {
public:
    FrameCaptureWorker(
        std::unique_ptr<IFrameSource> source,
        std::size_t queue_capacity,
        FrameCaptureRecoveryPolicy recovery_policy = {});
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
    bool restart_source() noexcept;
    void capture_loop() noexcept;

    std::unique_ptr<IFrameSource> source_;
    BoundedFrameQueue queue_;
    FrameCaptureRecoveryPolicy recovery_policy_;
    std::thread worker_;
    std::atomic<std::uint64_t> produced_{0};
    std::atomic<std::uint64_t> restart_attempts_{0};
    std::atomic<std::uint64_t> restart_successes_{0};
    std::atomic<std::uint64_t> stream_generation_{0};
    std::atomic<bool> stop_requested_{false};
    std::atomic<bool> running_{false};
    std::atomic<bool> source_exhausted_{false};
    std::atomic<bool> recovery_exhausted_{false};
    bool started_{false};
};

}  // namespace edge_vision
