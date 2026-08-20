#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace edge_vision {

struct TegrastatsSample {
    std::int64_t captured_at_ns{0};
    std::optional<double> ram_used_mb;
    std::optional<double> ram_total_mb;
    std::optional<double> cpu_utilization_percent;
    std::optional<double> gpu_utilization_percent;
    std::optional<double> cpu_temperature_c;
    std::optional<double> gpu_temperature_c;
    std::optional<double> junction_temperature_c;
    std::optional<double> input_power_w;
};

struct NumericMetricSummary {
    std::size_t samples{0};
    std::optional<double> mean;
    std::optional<double> p95;
    std::optional<double> maximum;
};

struct JetsonTelemetrySummary {
    std::size_t samples{0};
    NumericMetricSummary ram_used_mb;
    NumericMetricSummary ram_total_mb;
    NumericMetricSummary cpu_utilization_percent;
    NumericMetricSummary gpu_utilization_percent;
    NumericMetricSummary cpu_temperature_c;
    NumericMetricSummary gpu_temperature_c;
    NumericMetricSummary junction_temperature_c;
    NumericMetricSummary input_power_w;
};

std::optional<TegrastatsSample> parse_tegrastats_line(
    std::string_view line);
JetsonTelemetrySummary summarize_tegrastats(
    const std::vector<TegrastatsSample>& samples);

struct JetsonTelemetrySamplerConfig {
    std::string executable{"/usr/bin/tegrastats"};
    std::uint64_t interval_ms{500};
};

class JetsonTelemetrySampler {
public:
    explicit JetsonTelemetrySampler(
        JetsonTelemetrySamplerConfig config = {});
    ~JetsonTelemetrySampler();

    JetsonTelemetrySampler(const JetsonTelemetrySampler&) = delete;
    JetsonTelemetrySampler& operator=(const JetsonTelemetrySampler&) = delete;

    bool start();
    void stop() noexcept;

    [[nodiscard]] bool running() const noexcept;
    [[nodiscard]] std::vector<TegrastatsSample> samples() const;
    [[nodiscard]] JetsonTelemetrySummary summary() const;
    [[nodiscard]] std::string last_error() const;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace edge_vision
