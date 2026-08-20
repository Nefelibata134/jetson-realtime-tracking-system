#pragma once

#include <chrono>
#include <csignal>
#include <optional>
#include <string>

#include <signal.h>

namespace edge_vision {

class ShutdownSignalHandler final {
public:
    ShutdownSignalHandler();
    ~ShutdownSignalHandler();

    ShutdownSignalHandler(const ShutdownSignalHandler&) = delete;
    ShutdownSignalHandler& operator=(const ShutdownSignalHandler&) = delete;

    [[nodiscard]] static bool requested() noexcept;
    [[nodiscard]] static int signal_number() noexcept;

private:
    struct sigaction previous_sigint_ {};
    struct sigaction previous_sigterm_ {};
    bool sigint_installed_{false};
    bool sigterm_installed_{false};
};

class SystemdNotifier final {
public:
    SystemdNotifier() noexcept;

    [[nodiscard]] bool enabled() const noexcept;
    [[nodiscard]] std::optional<std::chrono::microseconds>
    watchdog_interval() const noexcept;
    [[nodiscard]] const std::string& last_error() const noexcept;

    bool notify_ready(const std::string& status) noexcept;
    bool notify_watchdog() noexcept;
    bool notify_stopping(const std::string& status) noexcept;

private:
    bool send(const std::string& state) noexcept;

    bool enabled_{false};
    std::optional<std::chrono::microseconds> watchdog_interval_;
    std::string last_error_;
};

}  // namespace edge_vision
