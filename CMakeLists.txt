cmake_minimum_required(VERSION 3.16)

project(jetson_realtime_tracking_system LANGUAGES CXX)

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

enable_testing()
add_test(NAME edge_vision_contract_check COMMAND edge_vision_contract_check)

