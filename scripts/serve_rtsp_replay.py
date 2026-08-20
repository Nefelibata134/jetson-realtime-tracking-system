#!/usr/bin/env python3

import argparse
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0")
from gi.repository import GLib, Gst, GstRtspServer  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve an H.264 MP4 file over RTSP for recovery tests."
    )
    parser.add_argument("video", type=Path)
    parser.add_argument("--port", type=int, default=8554)
    parser.add_argument("--mount", default="/replay")
    return parser.parse_args()


def quote_gstreamer_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def main() -> None:
    args = parse_args()
    video = args.video.expanduser().resolve()
    if not video.is_file():
        raise SystemExit(f"video does not exist: {video}")
    if not 1 <= args.port <= 65535:
        raise SystemExit("port must be between 1 and 65535")
    if not args.mount.startswith("/") or args.mount == "/":
        raise SystemExit("mount must start with '/' and include a path")

    Gst.init(None)
    server = GstRtspServer.RTSPServer()
    server.set_service(str(args.port))

    factory = GstRtspServer.RTSPMediaFactory()
    factory.set_shared(False)
    factory.set_launch(
        '( filesrc location="'
        + quote_gstreamer_path(video)
        + '" ! qtdemux ! h264parse ! rtph264pay name=pay0 pt=96 '
        + "config-interval=1 )"
    )
    server.get_mount_points().add_factory(args.mount, factory)

    if server.attach(None) == 0:
        raise SystemExit("failed to attach RTSP server")

    print(f"rtsp://0.0.0.0:{args.port}{args.mount}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
