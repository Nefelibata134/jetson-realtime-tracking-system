#include <cmath>
#include <cstddef>
#include <exception>
#include <iostream>
#include <stdexcept>
#include <vector>

#include "edge_vision/yolox_postprocessor.hpp"

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

bool approximately_equal(float left, float right) {
    return std::fabs(left - right) < 1.0e-4F;
}

void set_candidate(
    std::vector<float>& output,
    std::size_t columns,
    std::size_t row,
    float tx,
    float ty,
    float width_in_strides,
    float height_in_strides,
    float objectness,
    int class_id,
    float class_probability) {
    const std::size_t offset = row * columns;
    output[offset] = tx;
    output[offset + 1U] = ty;
    output[offset + 2U] = std::log(width_in_strides);
    output[offset + 3U] = std::log(height_in_strides);
    output[offset + 4U] = objectness;
    output[offset + 5U + static_cast<std::size_t>(class_id)] = class_probability;
}

}  // namespace

int main() {
    try {
        const edge_vision::YoloXPostprocessor postprocessor;
        const std::size_t rows = postprocessor.expected_rows();
        const std::size_t columns = postprocessor.expected_columns();
        std::vector<float> output(rows * columns, 0.0F);

        set_candidate(output, columns, 0U, 10.0F, 10.0F, 4.0F, 2.0F, 0.9F, 5, 0.8F);
        set_candidate(output, columns, 1U, 9.0F, 10.0F, 4.0F, 2.0F, 0.8F, 5, 0.8F);

        constexpr std::size_t third_row = 20U * 52U + 20U;
        set_candidate(output, columns, third_row, 5.0F, 5.0F, 2.0F, 2.0F, 0.9F, 2, 0.7F);

        const auto detections = postprocessor.run(output, 1280, 720, 0.5F);
        require(rows == 3549U, "row count mismatch");
        require(columns == 85U, "column count mismatch");
        require(detections.size() == 2U, "NMS did not retain two detections");

        const auto& first = detections[0];
        require(first.class_id == 5, "first class mismatch");
        require(approximately_equal(first.confidence, 0.72F), "first score mismatch");
        require(approximately_equal(first.box.x, 128.0F), "first x mismatch");
        require(approximately_equal(first.box.y, 144.0F), "first y mismatch");
        require(approximately_equal(first.box.width, 64.0F), "first width mismatch");
        require(approximately_equal(first.box.height, 32.0F), "first height mismatch");

        const auto& second = detections[1];
        require(second.class_id == 2, "second class mismatch");
        require(approximately_equal(second.confidence, 0.63F), "second score mismatch");
        require(approximately_equal(second.box.x, 384.0F), "second x mismatch");
        require(approximately_equal(second.box.y, 384.0F), "second y mismatch");
        require(approximately_equal(second.box.width, 32.0F), "second width mismatch");
        require(approximately_equal(second.box.height, 32.0F), "second height mismatch");

        bool invalid_size_rejected = false;
        try {
            static_cast<void>(postprocessor.run({}, 1280, 720, 0.5F));
        } catch (const std::invalid_argument&) {
            invalid_size_rejected = true;
        }
        require(invalid_size_rejected, "invalid output size was not rejected");

        std::cout << "rows=" << rows << " columns=" << columns << '\n';
        std::cout << "candidates=3 detections=" << detections.size() << '\n';
        std::cout << "first=class:" << first.class_id
                  << ",score:" << first.confidence
                  << ",box:" << first.box.x << ',' << first.box.y << ','
                  << first.box.width << ',' << first.box.height << '\n';
        std::cout << "status=PASS\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "YOLOX postprocessing check failed: " << error.what() << '\n';
        return 1;
    }
}
