#include <cmath>
#include <iostream>
#include <string>
#include <vector>

#include "edge_vision/jetson_telemetry.hpp"

namespace {

bool near(const double left, const double right, const double tolerance) {
    return std::abs(left - right) <= tolerance;
}

bool check_parser() {
    const std::string line =
        "RAM 1585/7620MB (lfb 3x4MB) SWAP 0/3810MB (cached 0MB) "
        "CPU [0%@729,12%@1344,off,6%@1344] GR3D_FREQ 99% "
        "cpu@49.031C gpu@48.875C tj@50.5C "
        "VDD_IN 13166mW/9000mW";
    const auto sample = edge_vision::parse_tegrastats_line(line);
    return sample.has_value() && sample->ram_used_mb == 1585.0 &&
           sample->ram_total_mb == 7620.0 &&
           sample->gpu_utilization_percent == 99.0 &&
           sample->cpu_utilization_percent.has_value() &&
           near(*sample->cpu_utilization_percent, 6.0, 0.001) &&
           sample->gpu_temperature_c == 48.875 &&
           sample->junction_temperature_c == 50.5 &&
           sample->input_power_w.has_value() &&
           near(*sample->input_power_w, 13.166, 0.001);
}

bool check_summary() {
    const auto first = edge_vision::parse_tegrastats_line(
        "RAM 1000/7620MB CPU [0%@729,10%@729] GR3D_FREQ 20% "
        "cpu@45C gpu@44C tj@46C VDD_IN 5000mW/5000mW");
    const auto second = edge_vision::parse_tegrastats_line(
        "RAM 2000/7620MB CPU [20%@729,40%@729] GR3D_FREQ 80% "
        "cpu@55C gpu@54C tj@56C VDD_IN 9000mW/7000mW");
    if (!first.has_value() || !second.has_value()) {
        return false;
    }
    const auto summary = edge_vision::summarize_tegrastats({*first, *second});
    return summary.samples == 2 &&
           summary.input_power_w.samples == 2 &&
           summary.input_power_w.mean.has_value() &&
           near(*summary.input_power_w.mean, 7.0, 0.001) &&
           summary.input_power_w.maximum == 9.0 &&
           summary.ram_used_mb.mean == 1500.0 &&
           summary.gpu_utilization_percent.maximum == 80.0;
}

}  // namespace

int main() {
    const bool parser = check_parser();
    const bool summary = check_summary();
    const bool invalid_line =
        !edge_vision::parse_tegrastats_line("not telemetry").has_value();

    std::cout << "parser=" << std::boolalpha << parser << '\n';
    std::cout << "summary=" << summary << '\n';
    std::cout << "invalid_line=" << invalid_line << '\n';
    const bool passed = parser && summary && invalid_line;
    std::cout << "status=" << (passed ? "PASS" : "FAIL") << '\n';
    return passed ? 0 : 1;
}
