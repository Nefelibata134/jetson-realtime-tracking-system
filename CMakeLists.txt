cmake_minimum_required(VERSION 3.16)

project(jetson_realtime_tracking_system LANGUAGES CXX)

option(
    EDGE_VISION_ENABLE_TENSORRT
    "Build the TensorRT runtime targets"
    OFF
)
option(
    EDGE_VISION_ENABLE_GSTREAMER
    "Build the GStreamer capture targets"
    OFF
)

find_package(Threads REQUIRED)

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

add_library(
    edge_vision_capture
    src/frame_capture_worker.cpp
)
target_link_libraries(
    edge_vision_capture
    PUBLIC
        edge_vision_core
    PRIVATE
        Threads::Threads
)

add_executable(
    edge_vision_frame_queue_check
    apps/frame_queue_check.cpp
)
target_link_libraries(
    edge_vision_frame_queue_check
    PRIVATE
        edge_vision_capture
)

find_package(OpenCV REQUIRED COMPONENTS core imgproc imgcodecs videoio)
find_package(Eigen3 3.3 REQUIRED NO_MODULE)

add_library(
    edge_vision_video_output
    src/annotated_video_writer.cpp
)
target_include_directories(
    edge_vision_video_output
    PRIVATE
        ${OpenCV_INCLUDE_DIRS}
)
target_link_libraries(
    edge_vision_video_output
    PUBLIC
        edge_vision_core
    PRIVATE
        ${OpenCV_LIBS}
        Threads::Threads
)

add_executable(
    edge_vision_video_writer_check
    apps/video_writer_check.cpp
)
target_link_libraries(
    edge_vision_video_writer_check
    PRIVATE
        edge_vision_video_output
)

set(
    BYTETRACK_UPSTREAM_SOURCES
    third_party/bytetrack/src/BYTETracker.cpp
    third_party/bytetrack/src/STrack.cpp
    third_party/bytetrack/src/kalmanFilter.cpp
    third_party/bytetrack/src/lapjv.cpp
    third_party/bytetrack/src/utils.cpp
)

add_library(
    edge_vision_bytetrack
    src/byte_tracker.cpp
    ${BYTETRACK_UPSTREAM_SOURCES}
)
target_include_directories(
    edge_vision_bytetrack
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/third_party/bytetrack/include
        ${OpenCV_INCLUDE_DIRS}
)
target_link_libraries(
    edge_vision_bytetrack
    PUBLIC
        edge_vision_core
    PRIVATE
        Eigen3::Eigen
        ${OpenCV_LIBS}
)

add_executable(
    edge_vision_byte_tracker_check
    apps/byte_tracker_check.cpp
)
target_link_libraries(
    edge_vision_byte_tracker_check
    PRIVATE
        edge_vision_bytetrack
)

add_library(
    edge_vision_yolox
    src/yolox_preprocessor.cpp
    src/yolox_postprocessor.cpp
)
target_include_directories(
    edge_vision_yolox
    PRIVATE
        ${OpenCV_INCLUDE_DIRS}
)
target_link_libraries(
    edge_vision_yolox
    PUBLIC
        edge_vision_core
    PRIVATE
        ${OpenCV_LIBS}
)

add_executable(
    edge_vision_preprocess_check
    apps/preprocess_check.cpp
)
target_link_libraries(
    edge_vision_preprocess_check
    PRIVATE
        edge_vision_yolox
)

add_executable(
    edge_vision_postprocess_check
    apps/postprocess_check.cpp
)
target_link_libraries(
    edge_vision_postprocess_check
    PRIVATE
        edge_vision_yolox
)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    set_source_files_properties(
        ${BYTETRACK_UPSTREAM_SOURCES}
        PROPERTIES COMPILE_OPTIONS -w
    )
    target_compile_options(
        edge_vision_bytetrack
        PRIVATE
            -Wall
            -Wextra
            -Wpedantic
    )
    target_compile_options(
        edge_vision_byte_tracker_check
        PRIVATE
            -Wall
            -Wextra
            -Wpedantic
    )
    target_compile_options(
        edge_vision_contract_check
        PRIVATE
            -Wall
            -Wextra
            -Wpedantic
    )
    target_compile_options(
        edge_vision_yolox
        PRIVATE
            -Wall
            -Wextra
            -Wpedantic
    )
    target_compile_options(
        edge_vision_capture
        PRIVATE
            -Wall
            -Wextra
            -Wpedantic
    )
    target_compile_options(
        edge_vision_frame_queue_check
        PRIVATE
            -Wall
            -Wextra
            -Wpedantic
    )
    target_compile_options(
        edge_vision_preprocess_check
        PRIVATE
            -Wall
            -Wextra
            -Wpedantic
    )
    target_compile_options(
        edge_vision_postprocess_check
        PRIVATE
            -Wall
            -Wextra
            -Wpedantic
    )
    target_compile_options(
        edge_vision_video_output
        PRIVATE
            -Wall
            -Wextra
            -Wpedantic
    )
    target_compile_options(
        edge_vision_video_writer_check
        PRIVATE
            -Wall
            -Wextra
            -Wpedantic
    )
endif()

if(EDGE_VISION_ENABLE_GSTREAMER)
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(
        GSTREAMER
        REQUIRED
        IMPORTED_TARGET
        gstreamer-1.0
        gstreamer-app-1.0
        gstreamer-video-1.0
    )

    add_library(
        edge_vision_gstreamer
        src/gstreamer_frame_source.cpp
    )
    target_link_libraries(
        edge_vision_gstreamer
        PUBLIC
            edge_vision_core
        PRIVATE
            PkgConfig::GSTREAMER
    )

    add_executable(
        edge_vision_capture_stream
        apps/capture_stream.cpp
    )
    target_link_libraries(
        edge_vision_capture_stream
        PRIVATE
            edge_vision_capture
            edge_vision_gstreamer
    )

    if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(
            edge_vision_gstreamer
            PRIVATE
                -Wall
                -Wextra
                -Wpedantic
        )
        target_compile_options(
            edge_vision_capture_stream
            PRIVATE
                -Wall
                -Wextra
                -Wpedantic
        )
    endif()
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

    add_library(
        edge_vision_detector
        src/yolox_detector.cpp
    )
    target_link_libraries(
        edge_vision_detector
        PUBLIC
            edge_vision_core
        PRIVATE
            edge_vision_tensorrt
            edge_vision_yolox
    )

    add_executable(
        edge_vision_detect_image
        apps/detect_image.cpp
    )
    target_include_directories(
        edge_vision_detect_image
        PRIVATE
            ${OpenCV_INCLUDE_DIRS}
    )
    target_link_libraries(
        edge_vision_detect_image
        PRIVATE
            edge_vision_detector
            ${OpenCV_LIBS}
    )

    if(EDGE_VISION_ENABLE_GSTREAMER)
        add_executable(
            edge_vision_realtime_detect
            apps/realtime_detect.cpp
        )
        target_link_libraries(
            edge_vision_realtime_detect
            PRIVATE
                edge_vision_capture
                edge_vision_bytetrack
                edge_vision_detector
                edge_vision_gstreamer
                edge_vision_video_output
        )
    endif()

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
        target_compile_options(
            edge_vision_detector
            PRIVATE
                -Wall
                -Wextra
                -Wpedantic
        )
        target_compile_options(
            edge_vision_detect_image
            PRIVATE
                -Wall
                -Wextra
                -Wpedantic
        )
        if(EDGE_VISION_ENABLE_GSTREAMER)
            target_compile_options(
                edge_vision_realtime_detect
                PRIVATE
                    -Wall
                    -Wextra
                    -Wpedantic
            )
        endif()
    endif()
endif()

enable_testing()
add_test(NAME edge_vision_contract_check COMMAND edge_vision_contract_check)
add_test(NAME edge_vision_frame_queue_check COMMAND edge_vision_frame_queue_check)
add_test(NAME edge_vision_preprocess_check COMMAND edge_vision_preprocess_check)
add_test(NAME edge_vision_postprocess_check COMMAND edge_vision_postprocess_check)
add_test(NAME edge_vision_byte_tracker_check COMMAND edge_vision_byte_tracker_check)
add_test(NAME edge_vision_video_writer_check COMMAND edge_vision_video_writer_check)
