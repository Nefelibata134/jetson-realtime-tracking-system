#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

#include "edge_vision/mot_challenge_writer.hpp"

namespace {

edge_vision::Track track(
    std::int64_t track_id,
    int class_id,
    edge_vision::TrackState state) {
    return edge_vision::Track{
        track_id,
        edge_vision::BoundingBox{99.0F, 49.0F, 40.0F, 80.0F},
        class_id,
        0.91F,
        state,
        5,
        0,
    };
}

}  // namespace

int main() {
    const auto output_path =
        std::filesystem::temp_directory_path() /
        "edge_vision_mot_writer_check.txt";

    edge_vision::MotChallengeWriter writer(output_path.string());
    writer.write(
        4,
        {
            track(23, 0, edge_vision::TrackState::Tracked),
            track(24, 2, edge_vision::TrackState::Tracked),
            track(25, 0, edge_vision::TrackState::Lost),
        });
    writer.finish();

    std::ifstream input(output_path);
    std::string line;
    std::getline(input, line);
    std::string extra_line;
    std::getline(input, extra_line);
    std::filesystem::remove(output_path);

    const std::string expected =
        "5,23,100.000000,50.000000,40.000000,80.000000,"
        "0.910000,-1,-1,-1";
    if (line != expected || !extra_line.empty() ||
        writer.stats().written != 1 || writer.stats().skipped != 2) {
        std::cerr << "unexpected MOT output: " << line << '\n';
        return 1;
    }

    std::cout << "line=" << line << '\n';
    std::cout << "written=" << writer.stats().written << '\n';
    std::cout << "skipped=" << writer.stats().skipped << '\n';
    std::cout << "status=PASS\n";
    return 0;
}
