#include "edge_vision/service_runtime.hpp"

#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <system_error>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace edge_vision {
namespace {

volatile std::sig_atomic_t shutdown_signal = 0;

void handle_shutdown_signal(const int signal_number) noexcept {
    shutdown_signal = signal_number;
}

std::string single_line(std::string value) {
    for (char& character : value) {
        if (character == '\n' || character == '\r') {
            character = ' ';
        }
    }
    return value;
}

}  // namespace

ShutdownSignalHandler::ShutdownSignalHandler() {
    shutdown_signal = 0;

    struct sigaction action {};
    action.sa_handler = handle_shutdown_signal;
    sigemptyset(&action.sa_mask);
    action.sa_flags = 0;

    if (sigaction(SIGINT, &action, &previous_sigint_) != 0) {
        throw std::system_error(
            errno, std::generic_category(), "failed to install SIGINT handler");
    }
    sigint_installed_ = true;

    if (sigaction(SIGTERM, &action, &previous_sigterm_) != 0) {
        const int error = errno;
        sigaction(SIGINT, &previous_sigint_, nullptr);
        sigint_installed_ = false;
        throw std::system_error(
            error,
            std::generic_category(),
            "failed to install SIGTERM handler");
    }
    sigterm_installed_ = true;
}

ShutdownSignalHandler::~ShutdownSignalHandler() {
    if (sigterm_installed_) {
        sigaction(SIGTERM, &previous_sigterm_, nullptr);
    }
    if (sigint_installed_) {
        sigaction(SIGINT, &previous_sigint_, nullptr);
    }
}

bool ShutdownSignalHandler::requested() noexcept {
    return shutdown_signal != 0;
}

int ShutdownSignalHandler::signal_number() noexcept {
    return static_cast<int>(shutdown_signal);
}

SystemdNotifier::SystemdNotifier() noexcept {
    const char* notify_socket = std::getenv("NOTIFY_SOCKET");
    enabled_ = notify_socket != nullptr && notify_socket[0] != '\0';

    const char* watchdog_text = std::getenv("WATCHDOG_USEC");
    const char* watchdog_pid_text = std::getenv("WATCHDOG_PID");
    if (watchdog_pid_text != nullptr && watchdog_pid_text[0] != '\0') {
        char* end = nullptr;
        errno = 0;
        const unsigned long long watchdog_pid =
            std::strtoull(watchdog_pid_text, &end, 10);
        if (errno != 0 || end == watchdog_pid_text || *end != '\0' ||
            watchdog_pid != static_cast<unsigned long long>(getpid())) {
            watchdog_text = nullptr;
        }
    }
    if (watchdog_text != nullptr && watchdog_text[0] != '\0') {
        char* end = nullptr;
        errno = 0;
        const unsigned long long microseconds =
            std::strtoull(watchdog_text, &end, 10);
        if (errno == 0 && end != watchdog_text && *end == '\0' &&
            microseconds > 0 &&
            microseconds <= static_cast<unsigned long long>(
                                std::numeric_limits<std::int64_t>::max())) {
            watchdog_interval_ = std::chrono::microseconds(microseconds);
        }
    }
}

bool SystemdNotifier::enabled() const noexcept {
    return enabled_;
}

std::optional<std::chrono::microseconds>
SystemdNotifier::watchdog_interval() const noexcept {
    return watchdog_interval_;
}

const std::string& SystemdNotifier::last_error() const noexcept {
    return last_error_;
}

bool SystemdNotifier::notify_ready(const std::string& status) noexcept {
    return send("READY=1\nSTATUS=" + single_line(status));
}

bool SystemdNotifier::notify_watchdog() noexcept {
    return send("WATCHDOG=1");
}

bool SystemdNotifier::notify_stopping(const std::string& status) noexcept {
    return send("STOPPING=1\nSTATUS=" + single_line(status));
}

bool SystemdNotifier::send(const std::string& state) noexcept {
    if (!enabled_) {
        return true;
    }

    const char* socket_path = std::getenv("NOTIFY_SOCKET");
    if (socket_path == nullptr || socket_path[0] == '\0') {
        enabled_ = false;
        return true;
    }

    const int descriptor = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    if (descriptor < 0) {
        last_error_ = std::strerror(errno);
        return false;
    }

    struct sockaddr_un address {};
    address.sun_family = AF_UNIX;
    const std::string path(socket_path);
    const bool abstract = path.front() == '@';
    const std::size_t path_bytes = abstract ? path.size() : path.size() + 1;
    if (path_bytes > sizeof(address.sun_path)) {
        close(descriptor);
        last_error_ = "NOTIFY_SOCKET path is too long";
        return false;
    }

    if (abstract) {
        address.sun_path[0] = '\0';
        std::memcpy(address.sun_path + 1, path.data() + 1, path.size() - 1);
    } else {
        std::memcpy(address.sun_path, path.c_str(), path_bytes);
    }
    const socklen_t address_size = static_cast<socklen_t>(
        offsetof(struct sockaddr_un, sun_path) + path_bytes);
    const ssize_t sent = sendto(
        descriptor,
        state.data(),
        state.size(),
        MSG_NOSIGNAL,
        reinterpret_cast<const struct sockaddr*>(&address),
        address_size);
    const int send_error = errno;
    close(descriptor);
    if (sent != static_cast<ssize_t>(state.size())) {
        last_error_ = std::strerror(send_error);
        return false;
    }
    return true;
}

}  // namespace edge_vision
