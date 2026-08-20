#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>

#include <nlohmann/json.hpp>

#include "edge_vision/runtime_metrics.hpp"

int main() {
    const std::filesystem::path output =
        std::filesystem::temp_directory_path() /
        "edge_vision_runtime_metrics_check.json";
    std::filesystem::remove(output);
    std::filesystem::remove(output.string() + ".tmp");

    edge_vision::RuntimeMetricsReport report;
    report.source = "csi";
    report.status.target_reached = true;
    report.pipeline.measured_frames = 95;
    report.pipeline.dropped_frames = 5;
    report.pipeline.drop_rate_percent = 5.0;
    report.pipeline.effective_fps = 30.0;
    report.latency_ms["inference"] = {6.0, 5.8, 7.2, 12.0};
    report.device.samples = 2;
    report.device.input_power_w = {2, 8.0, 8.9, 9.0};

    edge_vision::write_runtime_metrics_json(output.string(), report);
    std::ifstream stream(output);
    nlohmann::json document;
    stream >> document;

    const bool schema = document.at("schema_version") == 1;
    const bool pipeline =
        document.at("pipeline").at("measured_frames") == 95 &&
        std::abs(
            document.at("pipeline").at("drop_rate_percent").get<double>() -
            5.0) < 0.001;
    const bool latency =
        document.at("latency_ms").at("inference").at("p95") == 7.2;
    const bool device =
        document.at("device").at("available") == true &&
        document.at("device").at("input_power_w").at("samples") == 2;

    report.pipeline.measured_frames = 96;
    edge_vision::write_runtime_metrics_json(output.string(), report);
    std::ifstream replacement_stream(output);
    nlohmann::json replacement;
    replacement_stream >> replacement;
    const bool replace =
        replacement.at("pipeline").at("measured_frames") == 96;
    const bool atomic = !std::filesystem::exists(output.string() + ".tmp");

    std::cout << "schema=" << std::boolalpha << schema << '\n';
    std::cout << "pipeline=" << pipeline << '\n';
    std::cout << "latency=" << latency << '\n';
    std::cout << "device=" << device << '\n';
    std::cout << "replace=" << replace << '\n';
    std::cout << "atomic=" << atomic << '\n';
    const bool passed =
        schema && pipeline && latency && device && replace && atomic;
    std::cout << "status=" << (passed ? "PASS" : "FAIL") << '\n';

    std::filesystem::remove(output);
    return passed ? 0 : 1;
}
