#include <chrono>
#include <csignal>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <string>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include "edge_vision/service_runtime.hpp"

namespace {

class NotifySocket final {
public:
    NotifySocket() {
        char directory_template[] = "/tmp/edge-vision-notify-XXXXXX";
        const char* directory = mkdtemp(directory_template);
        if (directory == nullptr) {
            return;
        }
        directory_ = directory;
        path_ = directory_ + "/notify.sock";

        descriptor_ = socket(AF_UNIX, SOCK_DGRAM, 0);
        if (descriptor_ < 0) {
            return;
        }

        struct sockaddr_un address {};
        address.sun_family = AF_UNIX;
        if (path_.size() >= sizeof(address.sun_path)) {
            return;
        }
        std::memcpy(address.sun_path, path_.c_str(), path_.size() + 1);
        if (bind(
                descriptor_,
                reinterpret_cast<const struct sockaddr*>(&address),
                sizeof(address)) != 0) {
            return;
        }

        struct timeval timeout {};
        timeout.tv_sec = 1;
        setsockopt(
            descriptor_,
            SOL_SOCKET,
            SO_RCVTIMEO,
            &timeout,
            sizeof(timeout));
        valid_ = true;
    }

    ~NotifySocket() {
        if (descriptor_ >= 0) {
            close(descriptor_);
        }
        std::error_code ignored;
        std::filesystem::remove_all(directory_, ignored);
    }

    [[nodiscard]] bool valid() const noexcept {
        return valid_;
    }

    [[nodiscard]] const std::string& path() const noexcept {
        return path_;
    }

    std::string receive() const {
        char buffer[512]{};
        const ssize_t received = recv(descriptor_, buffer, sizeof(buffer), 0);
        return received > 0
                   ? std::string(buffer, static_cast<std::size_t>(received))
                   : std::string{};
    }

private:
    int descriptor_{-1};
    bool valid_{false};
    std::string directory_;
    std::string path_;
};

bool contains(const std::string& value, const std::string& expected) {
    return value.find(expected) != std::string::npos;
}

}  // namespace

int main() {
    bool signal_requested = false;
    {
        edge_vision::ShutdownSignalHandler signals;
        raise(SIGTERM);
        signal_requested =
            signals.requested() && signals.signal_number() == SIGTERM;
    }

    NotifySocket socket;
    if (!socket.valid()) {
        std::cerr << "failed to create systemd notification socket\n";
        return 1;
    }

    setenv("NOTIFY_SOCKET", socket.path().c_str(), 1);
    setenv("WATCHDOG_USEC", "2000000", 1);
    setenv("WATCHDOG_PID", std::to_string(getpid()).c_str(), 1);

    edge_vision::SystemdNotifier notifier;
    const bool ready_sent = notifier.notify_ready("runtime ready");
    const std::string ready = socket.receive();
    const bool watchdog_sent = notifier.notify_watchdog();
    const std::string watchdog = socket.receive();
    const bool stopping_sent = notifier.notify_stopping("graceful shutdown");
    const std::string stopping = socket.receive();

    unsetenv("WATCHDOG_PID");
    unsetenv("WATCHDOG_USEC");
    unsetenv("NOTIFY_SOCKET");

    const bool ready_notification =
        ready_sent && notifier.enabled() && contains(ready, "READY=1") &&
        contains(ready, "STATUS=runtime ready");
    const bool watchdog_notification =
        watchdog_sent && contains(watchdog, "WATCHDOG=1") &&
        notifier.watchdog_interval() == std::chrono::seconds(2);
    const bool stopping_notification =
        stopping_sent && contains(stopping, "STOPPING=1") &&
        contains(stopping, "STATUS=graceful shutdown");

    std::cout << "signal_requested=" << std::boolalpha << signal_requested
              << '\n';
    std::cout << "ready_notification=" << ready_notification << '\n';
    std::cout << "watchdog_notification=" << watchdog_notification << '\n';
    std::cout << "stopping_notification=" << stopping_notification << '\n';
    const bool passed = signal_requested && ready_notification &&
                        watchdog_notification && stopping_notification;
    std::cout << "status=" << (passed ? "PASS" : "FAIL") << '\n';
    return passed ? 0 : 1;
}
