#pragma once

#include <cstddef>
#include <cstdint>
#include <fstream>
#include <string>
#include <vector>

#include "edge_vision/tracker.hpp"

namespace edge_vision {

struct MotChallengeWriterStats {
    std::size_t written{0};
    std::size_t skipped{0};
};

class MotChallengeWriter {
public:
    explicit MotChallengeWriter(
        const std::string& output_path,
        int evaluated_class_id = 0);

    MotChallengeWriter(const MotChallengeWriter&) = delete;
    MotChallengeWriter& operator=(const MotChallengeWriter&) = delete;

    void write(
        std::uint64_t zero_based_frame_sequence,
        const std::vector<Track>& tracks);
    void finish();

    [[nodiscard]] const MotChallengeWriterStats& stats() const noexcept;

private:
    int evaluated_class_id_{0};
    std::ofstream output_;
    MotChallengeWriterStats stats_;
    bool finished_{false};
};

}  // namespace edge_vision
