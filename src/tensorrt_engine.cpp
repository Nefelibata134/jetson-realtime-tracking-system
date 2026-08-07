#include "edge_vision/tensorrt_engine.hpp"

#include <NvInfer.h>
#include <cuda_runtime_api.h>

#include <algorithm>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace edge_vision {
namespace {

class TensorRTLogger final : public nvinfer1::ILogger {
public:
    void log(Severity severity, const char* message) noexcept override {
        if (severity <= Severity::kWARNING) {
            std::cerr << "[TensorRT] " << message << '\n';
        }
    }
};

void check_cuda(cudaError_t status, const char* operation) {
    if (status != cudaSuccess) {
        throw std::runtime_error(
            std::string(operation) + ": " + cudaGetErrorString(status));
    }
}

std::vector<char> read_binary(const std::string& path) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream) {
        throw std::runtime_error("Failed to open TensorRT engine: " + path);
    }

    const auto end = stream.tellg();
    if (end <= 0) {
        throw std::runtime_error("TensorRT engine is empty: " + path);
    }

    std::vector<char> bytes(static_cast<std::size_t>(end));
    stream.seekg(0, std::ios::beg);
    if (!stream.read(bytes.data(), static_cast<std::streamsize>(bytes.size()))) {
        throw std::runtime_error("Failed to read TensorRT engine: " + path);
    }
    return bytes;
}

TensorContract make_contract(
    const nvinfer1::ICudaEngine& engine,
    const char* name) {
    if (engine.getTensorDataType(name) != nvinfer1::DataType::kFLOAT) {
        throw std::runtime_error(
            std::string("Only float32 engine I/O is supported: ") + name);
    }

    const auto dimensions = engine.getTensorShape(name);
    TensorContract contract;
    contract.name = name;
    contract.shape.reserve(static_cast<std::size_t>(dimensions.nbDims));

    for (int index = 0; index < dimensions.nbDims; ++index) {
        if (dimensions.d[index] <= 0) {
            throw std::runtime_error(
                std::string("Dynamic or invalid tensor dimension: ") + name);
        }
        contract.shape.push_back(dimensions.d[index]);
    }
    return contract;
}

}  // namespace

std::size_t TensorContract::element_count() const {
    std::size_t count = 1;
    for (const auto dimension : shape) {
        const auto value = static_cast<std::size_t>(dimension);
        if (value > std::numeric_limits<std::size_t>::max() / count) {
            throw std::overflow_error("Tensor element count overflow");
        }
        count *= value;
    }
    return count;
}

class TensorRTEngine::Impl {
public:
    explicit Impl(const std::string& engine_path) {
        const auto serialized_engine = read_binary(engine_path);

        runtime_.reset(nvinfer1::createInferRuntime(logger_));
        if (!runtime_) {
            throw std::runtime_error("Failed to create TensorRT runtime");
        }

        engine_.reset(runtime_->deserializeCudaEngine(
            serialized_engine.data(), serialized_engine.size()));
        if (!engine_) {
            throw std::runtime_error("Failed to deserialize TensorRT engine");
        }

        context_.reset(engine_->createExecutionContext());
        if (!context_) {
            throw std::runtime_error("Failed to create TensorRT execution context");
        }

        discover_io_contracts();
        allocate_buffers();
    }

    ~Impl() {
        if (stream_ != nullptr) {
            cudaStreamDestroy(stream_);
        }
        if (device_output_ != nullptr) {
            cudaFree(device_output_);
        }
        if (device_input_ != nullptr) {
            cudaFree(device_input_);
        }
    }

    std::vector<float> infer(const std::vector<float>& host_input) {
        if (host_input.size() != input_.element_count()) {
            std::ostringstream message;
            message << "Input element count mismatch: expected "
                    << input_.element_count() << ", received "
                    << host_input.size();
            throw std::invalid_argument(message.str());
        }

        check_cuda(
            cudaMemcpyAsync(
                device_input_, host_input.data(), input_bytes_,
                cudaMemcpyHostToDevice, stream_),
            "cudaMemcpyAsync host-to-device");

        if (!context_->enqueueV3(stream_)) {
            throw std::runtime_error("TensorRT enqueueV3 failed");
        }

        std::vector<float> host_output(output_.element_count());
        check_cuda(
            cudaMemcpyAsync(
                host_output.data(), device_output_, output_bytes_,
                cudaMemcpyDeviceToHost, stream_),
            "cudaMemcpyAsync device-to-host");
        check_cuda(cudaStreamSynchronize(stream_), "cudaStreamSynchronize");

        return host_output;
    }

    const TensorContract& input() const noexcept { return input_; }
    const TensorContract& output() const noexcept { return output_; }

private:
    void discover_io_contracts() {
        const auto tensor_count = engine_->getNbIOTensors();
        for (int index = 0; index < tensor_count; ++index) {
            const char* name = engine_->getIOTensorName(index);
            const auto mode = engine_->getTensorIOMode(name);

            if (mode == nvinfer1::TensorIOMode::kINPUT) {
                if (!input_.name.empty()) {
                    throw std::runtime_error("Multiple engine inputs are not supported");
                }
                input_ = make_contract(*engine_, name);
            } else if (mode == nvinfer1::TensorIOMode::kOUTPUT) {
                if (!output_.name.empty()) {
                    throw std::runtime_error("Multiple engine outputs are not supported");
                }
                output_ = make_contract(*engine_, name);
            }
        }

        if (input_.name.empty() || output_.name.empty()) {
            throw std::runtime_error("Expected exactly one engine input and output");
        }
    }

    void allocate_buffers() {
        input_bytes_ = input_.element_count() * sizeof(float);
        output_bytes_ = output_.element_count() * sizeof(float);

        check_cuda(cudaMalloc(&device_input_, input_bytes_), "cudaMalloc input");
        try {
            check_cuda(cudaMalloc(&device_output_, output_bytes_), "cudaMalloc output");
            check_cuda(cudaStreamCreate(&stream_), "cudaStreamCreate");

            if (!context_->setTensorAddress(input_.name.c_str(), device_input_) ||
                !context_->setTensorAddress(output_.name.c_str(), device_output_)) {
                throw std::runtime_error("Failed to bind TensorRT tensor addresses");
            }
        } catch (...) {
            if (stream_ != nullptr) {
                cudaStreamDestroy(stream_);
                stream_ = nullptr;
            }
            if (device_output_ != nullptr) {
                cudaFree(device_output_);
                device_output_ = nullptr;
            }
            cudaFree(device_input_);
            device_input_ = nullptr;
            throw;
        }
    }

    TensorRTLogger logger_;
    std::unique_ptr<nvinfer1::IRuntime> runtime_;
    std::unique_ptr<nvinfer1::ICudaEngine> engine_;
    std::unique_ptr<nvinfer1::IExecutionContext> context_;
    TensorContract input_;
    TensorContract output_;
    void* device_input_{nullptr};
    void* device_output_{nullptr};
    cudaStream_t stream_{nullptr};
    std::size_t input_bytes_{0};
    std::size_t output_bytes_{0};
};

TensorRTEngine::TensorRTEngine(const std::string& engine_path)
    : impl_(std::make_unique<Impl>(engine_path)) {}

TensorRTEngine::~TensorRTEngine() = default;

const TensorContract& TensorRTEngine::input() const noexcept {
    return impl_->input();
}

const TensorContract& TensorRTEngine::output() const noexcept {
    return impl_->output();
}

std::vector<float> TensorRTEngine::infer(const std::vector<float>& input) {
    return impl_->infer(input);
}

}  // namespace edge_vision
