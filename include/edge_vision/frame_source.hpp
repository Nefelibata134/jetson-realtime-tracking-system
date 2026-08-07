#pragma once

#include <optional>

#include "edge_vision/frame.hpp"

namespace edge_vision {

class IFrameSource {
public:
    virtual ~IFrameSource() = default;

    virtual bool open() = 0;
    [[nodiscard]] virtual bool is_open() const noexcept = 0;
    virtual std::optional<Frame> read() = 0;
    virtual void close() noexcept = 0;
};

}  // namespace edge_vision

