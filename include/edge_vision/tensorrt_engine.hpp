#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace edge_vision {

struct TensorContract {
    std::string name;
    std::vector<std::int64_t> shape;

    [[nodiscard]] std::size_t element_count() const;
};

class TensorRTEngine {
public:
    explicit TensorRTEngine(const std::string& engine_path);
    ~TensorRTEngine();

    TensorRTEngine(const TensorRTEngine&) = delete;
    TensorRTEngine& operator=(const TensorRTEngine&) = delete;
    TensorRTEngine(TensorRTEngine&&) = delete;
    TensorRTEngine& operator=(TensorRTEngine&&) = delete;

    [[nodiscard]] const TensorContract& input() const noexcept;
    [[nodiscard]] const TensorContract& output() const noexcept;
    [[nodiscard]] std::vector<float> infer(const std::vector<float>& input);

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace edge_vision
