# 第三方声明

第三方文件本身未被重新许可，各自的原始许可证和版权声明继续保留。从许可证迁移提交
开始，包含兼容第三方组件的整体项目分发按 `AGPL-3.0-only` 提供，并须满足其相应义务。
保留第三方原许可不豁免整体组合程序的 AGPL 发布条件；使用者还须遵守适用的第三方条款。

| 组件 | 用途与分发方式 | 上游版本或固定点 | 许可证 |
| --- | --- | --- | --- |
| Ultralytics YOLO26 / YOLO26s | 评估候选；仅在仓库外获取权重并导出 ONNX | Ultralytics `8.4.138`；Assets `v8.4.0` | AGPL-3.0 或另行取得的 Enterprise License；本项目选择 AGPL-3.0 路线 |
| [YOLOX](https://github.com/Megvii-BaseDetection/YOLOX) | 当前检测器及外部 ONNX 模型来源；上游代码和模型不复制进仓库 | `0.1.1rc0` 发布资产 | Apache-2.0 |
| [ByteTrack](https://github.com/FoundationVision/ByteTrack) | 仓库内包含经适配的 C++ 跟踪实现 | `d1bf0191adff59bc8fcfeaa0b33d3d1642552a99` | MIT |
| [GStreamer](https://gstreamer.freedesktop.org/) | 系统安装的视频输入和编码依赖 | 由目标系统提供 | LGPL-2.1-or-later |
| [OpenCV](https://opencv.org/) | 系统安装的图像处理依赖 | 由构建环境提供 | Apache-2.0 |
| [Eigen](https://gitlab.com/libeigen/eigen) | 系统安装的线性代数依赖 | 由构建环境提供 | MPL-2.0 |
| [NVIDIA CUDA Toolkit](https://developer.nvidia.com/cuda-toolkit) | 目标设备上的外部构建和运行依赖 | 由 JetPack 提供 | NVIDIA CUDA EULA / SDK terms |
| [NVIDIA TensorRT](https://developer.nvidia.com/tensorrt) | 目标设备上的外部推理运行时 | 由 JetPack 提供 | NVIDIA SDK terms |
| [TrackEval](https://github.com/JonathonLuiten/TrackEval) | 在忽略的 `external/` 目录获取并用于 MOTChallenge 指标计算 | `12c8791b303e0a0b50f753af204249e622d0281a` | MIT |
| [JSON for Modern C++](https://github.com/nlohmann/json) | 系统或构建环境提供的 JSON 依赖 | 由构建环境提供 | MIT |
| [CAVIAR Test Case Scenarios](https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1/) | 在忽略的 `data/` 目录获取并用于事件评估 | 数据提供方发布版本 | CC BY-SA |

## 仓库内第三方源码

仓库内复制的第三方源码仅位于 `third_party/bytetrack/`。该实现适配自上述 ByteTrack
固定提交，原始 MIT 许可证和版权声明完整保留在
`third_party/bytetrack/LICENSE`。项目根目录的 AGPL 许可证不替换该文件，也不改变这些
第三方文件本身的 MIT 授权；包含该兼容实现的整体项目仍按 `AGPL-3.0-only` 分发。

## YOLO26s 来源与完整性

- 官方模型系列和许可说明：<https://docs.ultralytics.com/models/yolo26/>
- 官方资产版本：`ultralytics/assets` 的 `v8.4.0`
- 权重文件：`yolo26s.pt`
- 官方下载地址：
  <https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26s.pt>
- SHA-256：`646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b`
- 导出工具：`ultralytics==8.4.138`，源码标签解析到
  `dad7bb4534c95021bc14969ab25d77b77c4efdc3`

权重是可执行反序列化格式，只应从上述固定来源获取并在哈希校验通过后加载。获取、导出
和 Jetson engine 构建步骤见 `docs/models/yolo26s.md`。

## 资产和二进制边界

本仓库不分发模型权重、ONNX、TensorRT engine、CAVIAR/MOT17 数据、
原视频、凭据或运行目录。TensorRT engine 与目标 GPU、CUDA/TensorRT 版本和构建 profile
绑定，必须在准确目标设备上生成并记录哈希。

CUDA、TensorRT、GStreamer、OpenCV 和 Eigen 由目标系统或构建环境独立安装，不属于项目
源码，也不因项目采用 AGPL 而被重新许可。本仓库不分发 CUDA/TensorRT 等外部专有 SDK 或
运行库。未来发布项目二进制、容器或捆绑运行库前，必须重新审计实际组合、NVIDIA 条款及
AGPL 源码提供和分发义务；当前源码发布不构成二进制分发授权，也不增加专有链接例外。

CAVIAR 视频和人工标注 XML 只下载到忽略的 `data/` 目录，不由本仓库再分发。评估结果按
数据提供方要求注明 EC Funded CAVIAR project/IST 2001 37540。
已有派生截图作为独立文档资产按原始 CC BY-SA 要求保留，见
[截图许可说明](docs/assets/caviar_external/README.md)。
