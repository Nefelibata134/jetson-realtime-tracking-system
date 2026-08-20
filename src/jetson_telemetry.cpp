#include "edge_vision/jetson_telemetry.hpp"

#include <fcntl.h>
#include <signal.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <mutex>
#include <numeric>
#include <regex>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>

namespace edge_vision {
namespace {

std::int64_t monotonic_time_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

std::optional<double> capture_value(
    const std::string& text,
    const std::regex& pattern,
    const std::size_t group = 1) {
    std::smatch match;
    if (!std::regex_search(text, match, pattern) || match.size() <= group) {
        return std::nullopt;
    }
    return std::stod(match[group].str());
}

double percentile(
    const std::vector<double>& ordered,
    const double fraction) {
    if (ordered.empty()) {
        return 0.0;
    }
    const double position =
        fraction * static_cast<double>(ordered.size() - 1);
    const auto lower = static_cast<std::size_t>(std::floor(position));
    const auto upper = static_cast<std::size_t>(std::ceil(position));
    const double weight = position - static_cast<double>(lower);
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight;
}

template <typename Getter>
NumericMetricSummary summarize_values(
    const std::vector<TegrastatsSample>& samples,
    Getter getter) {
    std::vector<double> values;
    values.reserve(samples.size());
    for (const auto& sample : samples) {
        const std::optional<double> value = getter(sample);
        if (value.has_value()) {
            values.push_back(*value);
        }
    }
    if (values.empty()) {
        return {};
    }

    const double total = std::accumulate(values.begin(), values.end(), 0.0);
    std::sort(values.begin(), values.end());
    return {
        values.size(),
        total / static_cast<double>(values.size()),
        percentile(values, 0.95),
        values.back(),
    };
}

}  // namespace

std::optional<TegrastatsSample> parse_tegrastats_line(
    const std::string_view line) {
    static const std::regex ram_pattern{R"(RAM\s+(\d+)/(\d+)MB)"};
    static const std::regex cpu_block_pattern{R"(CPU\s+\[([^\]]+)\])"};
    static const std::regex cpu_core_pattern{R"((\d+)%@)"};
    static const std::regex gpu_pattern{R"(GR3D_FREQ\s+(\d+)%)"};
    static const std::regex cpu_temp_pattern{R"(cpu@([\d.]+)C)"};
    static const std::regex gpu_temp_pattern{R"(gpu@([\d.]+)C)"};
    static const std::regex junction_temp_pattern{R"(tj@([\d.]+)C)"};
    static const std::regex power_pattern{R"(VDD_IN\s+(\d+)mW)"};

    const std::string text{line};
    TegrastatsSample sample;
    sample.captured_at_ns = monotonic_time_ns();
    bool matched = false;

    std::smatch ram_match;
    if (std::regex_search(text, ram_match, ram_pattern)) {
        sample.ram_used_mb = std::stod(ram_match[1].str());
        sample.ram_total_mb = std::stod(ram_match[2].str());
        matched = true;
    }

    std::smatch cpu_block_match;
    if (std::regex_search(text, cpu_block_match, cpu_block_pattern)) {
        const std::string block = cpu_block_match[1].str();
        std::sregex_iterator iterator{
            block.begin(), block.end(), cpu_core_pattern};
        const std::sregex_iterator end;
        double total = 0.0;
        std::size_t count = 0;
        for (; iterator != end; ++iterator) {
            total += std::stod((*iterator)[1].str());
            ++count;
        }
        if (count > 0) {
            sample.cpu_utilization_percent =
                total / static_cast<double>(count);
            matched = true;
        }
    }

    sample.gpu_utilization_percent = capture_value(text, gpu_pattern);
    sample.cpu_temperature_c = capture_value(text, cpu_temp_pattern);
    sample.gpu_temperature_c = capture_value(text, gpu_temp_pattern);
    sample.junction_temperature_c =
        capture_value(text, junction_temp_pattern);
    sample.input_power_w = capture_value(text, power_pattern);
    if (sample.input_power_w.has_value()) {
        *sample.input_power_w /= 1000.0;
    }
    matched = matched || sample.gpu_utilization_percent.has_value() ||
              sample.cpu_temperature_c.has_value() ||
              sample.gpu_temperature_c.has_value() ||
              sample.junction_temperature_c.has_value() ||
              sample.input_power_w.has_value();

    return matched ? std::optional<TegrastatsSample>{sample} : std::nullopt;
}

JetsonTelemetrySummary summarize_tegrastats(
    const std::vector<TegrastatsSample>& samples) {
    JetsonTelemetrySummary summary;
    summary.samples = samples.size();
    summary.ram_used_mb = summarize_values(
        samples, [](const auto& sample) { return sample.ram_used_mb; });
    summary.ram_total_mb = summarize_values(
        samples, [](const auto& sample) { return sample.ram_total_mb; });
    summary.cpu_utilization_percent = summarize_values(
        samples,
        [](const auto& sample) { return sample.cpu_utilization_percent; });
    summary.gpu_utilization_percent = summarize_values(
        samples,
        [](const auto& sample) { return sample.gpu_utilization_percent; });
    summary.cpu_temperature_c = summarize_values(
        samples,
        [](const auto& sample) { return sample.cpu_temperature_c; });
    summary.gpu_temperature_c = summarize_values(
        samples,
        [](const auto& sample) { return sample.gpu_temperature_c; });
    summary.junction_temperature_c = summarize_values(
        samples,
        [](const auto& sample) { return sample.junction_temperature_c; });
    summary.input_power_w = summarize_values(
        samples, [](const auto& sample) { return sample.input_power_w; });
    return summary;
}

class JetsonTelemetrySampler::Impl {
public:
    explicit Impl(JetsonTelemetrySamplerConfig config)
        : config_(std::move(config)) {
        if (config_.interval_ms == 0) {
            throw std::invalid_argument("tegrastats interval must be positive");
        }
    }

    ~Impl() {
        stop();
    }

    bool start() {
        if (running_.load()) {
            set_error("tegrastats sampler is already running");
            return false;
        }
        {
            std::lock_guard<std::mutex> lock(mutex_);
            samples_.clear();
            last_error_.clear();
        }
        if (!std::filesystem::is_regular_file(config_.executable)) {
            set_error("tegrastats executable was not found: " +
                      config_.executable);
            return false;
        }

        int descriptors[2];
        if (pipe(descriptors) != 0) {
            set_error("failed to create tegrastats output pipe");
            return false;
        }

        const pid_t child = fork();
        if (child < 0) {
            close(descriptors[0]);
            close(descriptors[1]);
            set_error("failed to fork tegrastats process");
            return false;
        }
        if (child == 0) {
            close(descriptors[0]);
            dup2(descriptors[1], STDOUT_FILENO);
            dup2(descriptors[1], STDERR_FILENO);
            close(descriptors[1]);
            const std::string interval = std::to_string(config_.interval_ms);
            execl(
                config_.executable.c_str(),
                config_.executable.c_str(),
                "--interval",
                interval.c_str(),
                static_cast<char*>(nullptr));
            _exit(127);
        }

        close(descriptors[1]);
        child_pid_ = child;
        read_descriptor_ = descriptors[0];
        running_.store(true);
        reader_ = std::thread(&Impl::read_loop, this);
        return true;
    }

    void stop() noexcept {
        const pid_t child = child_pid_;
        if (child > 0) {
            kill(child, SIGTERM);
        }
        if (reader_.joinable()) {
            reader_.join();
        }
        if (child > 0) {
            int status = 0;
            while (waitpid(child, &status, 0) < 0 && errno == EINTR) {
            }
        }
        child_pid_ = -1;
        read_descriptor_ = -1;
        running_.store(false);
    }

    [[nodiscard]] bool running() const noexcept {
        return running_.load();
    }

    [[nodiscard]] std::vector<TegrastatsSample> samples() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return samples_;
    }

    [[nodiscard]] std::string last_error() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return last_error_;
    }

private:
    void set_error(std::string error) {
        std::lock_guard<std::mutex> lock(mutex_);
        last_error_ = std::move(error);
    }

    void read_loop() noexcept {
        FILE* stream = fdopen(read_descriptor_, "r");
        if (stream == nullptr) {
            set_error("failed to open tegrastats output stream");
            close(read_descriptor_);
            running_.store(false);
            return;
        }

        char* line = nullptr;
        std::size_t capacity = 0;
        while (getline(&line, &capacity, stream) >= 0) {
            const auto sample = parse_tegrastats_line(line);
            if (sample.has_value()) {
                std::lock_guard<std::mutex> lock(mutex_);
                samples_.push_back(*sample);
            }
        }
        free(line);
        fclose(stream);
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (samples_.empty() && last_error_.empty()) {
                last_error_ = "tegrastats produced no valid samples";
            }
        }
        running_.store(false);
    }

    JetsonTelemetrySamplerConfig config_;
    mutable std::mutex mutex_;
    std::vector<TegrastatsSample> samples_;
    std::string last_error_;
    std::thread reader_;
    std::atomic<bool> running_{false};
    pid_t child_pid_{-1};
    int read_descriptor_{-1};
};

JetsonTelemetrySampler::JetsonTelemetrySampler(
    JetsonTelemetrySamplerConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}

JetsonTelemetrySampler::~JetsonTelemetrySampler() = default;

bool JetsonTelemetrySampler::start() {
    return impl_->start();
}

void JetsonTelemetrySampler::stop() noexcept {
    impl_->stop();
}

bool JetsonTelemetrySampler::running() const noexcept {
    return impl_->running();
}

std::vector<TegrastatsSample> JetsonTelemetrySampler::samples() const {
    return impl_->samples();
}

JetsonTelemetrySummary JetsonTelemetrySampler::summary() const {
    return summarize_tegrastats(samples());
}

std::string JetsonTelemetrySampler::last_error() const {
    return impl_->last_error();
}

}  // namespace edge_vision
