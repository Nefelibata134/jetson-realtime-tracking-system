cmake_minimum_required(VERSION 3.16)

project(jetson_realtime_tracking_system LANGUAGES CXX)

option(
    EDGE_VISION_ENABLE_TENSORRT
    "Build the TensorRT runtime targets"
    OFF
)

add_library(edge_vision_core INTERFACE)
target_include_directories(
    edge_vision_core
    INTERFACE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)
target_compile_features(edge_vision_core INTERFACE cxx_std_17)

add_executable(
    edge_vision_contract_check
    apps/contract_check.cpp
)
target_link_libraries(edge_vision_contract_check PRIVATE edge_vision_core)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(
        edge_vision_contract_check
        PRIVATE
            -Wall
            -Wextra
            -Wpedantic
    )
endif()

if(EDGE_VISION_ENABLE_TENSORRT)
    find_package(CUDAToolkit REQUIRED)

    find_path(
        TENSORRT_INCLUDE_DIR
        NvInfer.h
        HINTS
            /usr/include/aarch64-linux-gnu
            /usr/include/x86_64-linux-gnu
    )
    find_library(
        TENSORRT_LIBRARY
        nvinfer
        HINTS
            /usr/lib/aarch64-linux-gnu
            /usr/lib/x86_64-linux-gnu
    )

    if(NOT TENSORRT_INCLUDE_DIR OR NOT TENSORRT_LIBRARY)
        message(FATAL_ERROR "TensorRT headers or runtime library were not found")
    endif()

    add_library(
        edge_vision_tensorrt
        src/tensorrt_engine.cpp
    )
    target_include_directories(
        edge_vision_tensorrt
        PRIVATE
            ${TENSORRT_INCLUDE_DIR}
    )
    target_link_libraries(
        edge_vision_tensorrt
        PUBLIC
            edge_vision_core
        PRIVATE
            CUDA::cudart
            ${TENSORRT_LIBRARY}
    )

    add_executable(
        edge_vision_trt_probe
        apps/trt_engine_probe.cpp
    )
    target_link_libraries(
        edge_vision_trt_probe
        PRIVATE
            edge_vision_tensorrt
    )

    if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(
            edge_vision_tensorrt
            PRIVATE
                -Wall
                -Wextra
                -Wpedantic
        )
        target_compile_options(
            edge_vision_trt_probe
            PRIVATE
                -Wall
                -Wextra
                -Wpedantic
        )
    endif()
endif()

enable_testing()
add_test(NAME edge_vision_contract_check COMMAND edge_vision_contract_check)
