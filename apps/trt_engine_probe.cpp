#include <algorithm>
#include <cmath>
#include <exception>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

#include "edge_vision/tensorrt_engine.hpp"

namespace {

void print_contract(
    const char* role,
    const edge_vision::TensorContract& contract) {
    std::cout << role << "=" << contract.name << " shape=";
    for (std::size_t index = 0; index < contract.shape.size(); ++index) {
        if (index != 0) {
            std::cout << 'x';
        }
        std::cout << contract.shape[index];
    }
    std::cout << " elements=" << contract.element_count() << '\n';
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "Usage: " << argv[0] << " ENGINE_PATH\n";
        return 2;
    }

    try {
        edge_vision::TensorRTEngine engine(argv[1]);
        print_contract("input", engine.input());
        print_contract("output", engine.output());

        const std::vector<float> input(engine.input().element_count(), 0.0F);
        const auto output = engine.infer(input);
        const auto [minimum, maximum] =
            std::minmax_element(output.begin(), output.end());
        const auto finite_count = static_cast<std::size_t>(std::count_if(
            output.begin(), output.end(),
            [](float value) { return std::isfinite(value); }));

        std::cout << std::fixed << std::setprecision(6);
        std::cout << "output_min=" << *minimum << '\n';
        std::cout << "output_max=" << *maximum << '\n';
        std::cout << "finite=" << finite_count << '/' << output.size() << '\n';

        return finite_count == output.size() ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << "TensorRT probe failed: " << error.what() << '\n';
        return 1;
    }
}
