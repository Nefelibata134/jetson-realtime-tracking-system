# Third-Party Notices

The runtime is designed to interoperate with the following upstream projects.
Their source code and pretrained artifacts remain subject to their respective
licenses.

| Component | Upstream | License |
| --- | --- | --- |
| YOLOX | https://github.com/Megvii-BaseDetection/YOLOX | Apache-2.0 |
| ByteTrack | https://github.com/FoundationVision/ByteTrack | MIT |
| GStreamer | https://gstreamer.freedesktop.org/ | LGPL-2.1-or-later |
| NVIDIA TensorRT | https://developer.nvidia.com/tensorrt | NVIDIA SDK terms |
| TrackEval | https://github.com/JonathonLuiten/TrackEval | MIT |
| JSON for Modern C++ | https://github.com/nlohmann/json | MIT |

No third-party model weights or generated TensorRT engines are stored in this
repository.

The ByteTrack C++ runtime is adapted from upstream commit
`d1bf0191adff59bc8fcfeaa0b33d3d1642552a99`. Its license is preserved at
`third_party/bytetrack/LICENSE`.

MOTChallenge metrics are computed with TrackEval commit
`12c8791b303e0a0b50f753af204249e622d0281a`. The evaluation tool is fetched
into an ignored external directory and is not redistributed by this
repository.
