#include <atomic>
#include <chrono>
#include <cstdint>
#include <future>
#include <iostream>
#include <memory>
#include <optional>
#include <thread>
#include <vector>

#include "edge_vision/bounded_frame_queue.hpp"
#include "edge_vision/frame_capture_worker.hpp"
#include "edge_vision/frame_source.hpp"

namespace {

edge_vision::Frame make_frame(const std::uint64_t sequence) {
    edge_vision::Frame frame;
    frame.width = 1;
    frame.height = 1;
    frame.channels = 3;
    frame.sequence = sequence;
    frame.pts_ns = static_cast<std::int64_t>(sequence) * 33'333'333;
    frame.data = {0, 0, 0};
    return frame;
}

class FiniteFrameSource final : public edge_vision::IFrameSource {
public:
    explicit FiniteFrameSource(const std::uint64_t frame_count)
        : frame_count_(frame_count) {}

    bool open() override {
        opened_ = true;
        return true;
    }

    [[nodiscard]] bool is_open() const noexcept override {
        return opened_;
    }

    std::optional<edge_vision::Frame> read() override {
        if (!opened_ || next_ == frame_count_) {
            return std::nullopt;
        }
        return make_frame(next_++);
    }

    void close() noexcept override {
        opened_ = false;
    }

private:
    std::uint64_t frame_count_{0};
    std::uint64_t next_{0};
    bool opened_{false};
};

class RecoveringFrameSource final : public edge_vision::IFrameSource {
public:
    bool open() override {
        if (next_ == 4) {
            opened_ = false;
            return false;
        }
        opened_ = true;
        reads_this_session_ = 0;
        return true;
    }

    [[nodiscard]] bool is_open() const noexcept override {
        return opened_;
    }

    std::optional<edge_vision::Frame> read() override {
        if (!opened_ || reads_this_session_ == 2 || next_ == 4) {
            return std::nullopt;
        }
        ++reads_this_session_;
        return make_frame(next_++);
    }

    void close() noexcept override {
        opened_ = false;
    }

private:
    std::uint64_t next_{0};
    std::uint64_t reads_this_session_{0};
    bool opened_{false};
};

class RepeatedRecoveryFrameSource final : public edge_vision::IFrameSource {
public:
    bool open() override {
        opened_.store(true);
        reads_this_session_ = 0;
        return true;
    }

    [[nodiscard]] bool is_open() const noexcept override {
        return opened_.load();
    }

    std::optional<edge_vision::Frame> read() override {
        if (!opened_.load()) {
            return std::nullopt;
        }
        if (next_ == 6) {
            while (opened_.load()) {
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }
            return std::nullopt;
        }
        if (reads_this_session_ == 2) {
            return std::nullopt;
        }
        ++reads_this_session_;
        return make_frame(next_++);
    }

    void close() noexcept override {
        opened_.store(false);
    }

private:
    std::uint64_t next_{0};
    std::uint64_t reads_this_session_{0};
    std::atomic<bool> opened_{false};
};

bool check_drop_oldest() {
    edge_vision::BoundedFrameQueue queue(2);
    const auto first = queue.push(make_frame(1));
    const auto second = queue.push(make_frame(2));
    const auto third = queue.push(make_frame(3));

    const auto popped_first = queue.try_pop();
    const auto popped_second = queue.try_pop();
    const auto stats = queue.stats();

    return first == edge_vision::QueuePushResult::pushed &&
           second == edge_vision::QueuePushResult::pushed &&
           third == edge_vision::QueuePushResult::replaced_oldest &&
           popped_first.has_value() && popped_first->sequence == 2 &&
           popped_second.has_value() && popped_second->sequence == 3 &&
           stats.dropped == 1 && stats.high_watermark == 2;
}

bool check_close_unblocks_waiter() {
    edge_vision::BoundedFrameQueue queue(1);
    auto waiting = std::async(
        std::launch::async, [&queue] { return queue.wait_pop(); });
    queue.close();
    return !waiting.get().has_value();
}

bool check_capture_worker() {
    auto source = std::make_unique<FiniteFrameSource>(5);
    edge_vision::FrameCaptureWorker worker(std::move(source), 2);
    if (!worker.start()) {
        return false;
    }
    worker.wait();

    const auto first = worker.wait_pop();
    const auto second = worker.wait_pop();
    const auto end = worker.wait_pop();
    const auto stats = worker.stats();

    return first.has_value() && first->sequence == 3 &&
           second.has_value() && second->sequence == 4 &&
           !end.has_value() && stats.produced == 5 &&
           stats.queue.dropped == 3 && stats.queue.high_watermark == 2 &&
           stats.source_exhausted && !stats.running;
}

bool check_capture_recovery() {
    auto source = std::make_unique<RecoveringFrameSource>();
    edge_vision::FrameCaptureRecoveryPolicy policy;
    policy.max_restart_attempts = 1;
    policy.restart_delay_ms = 0;
    edge_vision::FrameCaptureWorker worker(
        std::move(source), 4, policy);
    if (!worker.start()) {
        return false;
    }
    worker.wait();

    std::vector<std::uint64_t> generations;
    while (const auto frame = worker.try_pop()) {
        generations.push_back(frame->stream_generation);
    }
    const auto stats = worker.stats();
    return generations == std::vector<std::uint64_t>({0, 0, 1, 1}) &&
           stats.produced == 4 &&
           stats.restart_attempts == 2 && stats.restart_successes == 1 &&
           stats.stream_generation == 1 &&
           stats.source_exhausted && stats.recovery_exhausted;
}

bool check_recovery_budget_per_outage() {
    auto source = std::make_unique<RepeatedRecoveryFrameSource>();
    edge_vision::FrameCaptureRecoveryPolicy policy;
    policy.max_restart_attempts = 1;
    policy.restart_delay_ms = 0;
    edge_vision::FrameCaptureWorker worker(
        std::move(source), 6, policy);
    if (!worker.start()) {
        return false;
    }

    std::vector<std::uint64_t> generations;
    for (int index = 0; index < 6; ++index) {
        const auto frame = worker.wait_pop();
        if (!frame.has_value()) {
            worker.stop();
            return false;
        }
        generations.push_back(frame->stream_generation);
    }
    worker.stop();

    const auto stats = worker.stats();
    return generations ==
               std::vector<std::uint64_t>({0, 0, 1, 1, 2, 2}) &&
           stats.produced == 6 && stats.restart_attempts == 2 &&
           stats.restart_successes == 2 && stats.stream_generation == 2 &&
           !stats.recovery_exhausted;
}

}  // namespace

int main() {
    const bool drop_oldest = check_drop_oldest();
    const bool close_unblocks = check_close_unblocks_waiter();
    const bool capture_worker = check_capture_worker();
    const bool capture_recovery = check_capture_recovery();
    const bool recovery_budget_per_outage =
        check_recovery_budget_per_outage();

    std::cout << "drop_oldest=" << std::boolalpha << drop_oldest << '\n';
    std::cout << "close_unblocks=" << close_unblocks << '\n';
    std::cout << "capture_worker=" << capture_worker << '\n';
    std::cout << "capture_recovery=" << capture_recovery << '\n';
    std::cout << "recovery_budget_per_outage="
              << recovery_budget_per_outage << '\n';

    const bool passed = drop_oldest && close_unblocks && capture_worker &&
                        capture_recovery && recovery_budget_per_outage;
    std::cout << "status=" << (passed ? "PASS" : "FAIL") << '\n';
    return passed ? 0 : 1;
}
