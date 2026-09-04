# YOLO26s Jetson 编译与最小推理验证

## 结论与范围

2026-09-04，提交 `49876fe2480a2067725ab1884cd7d688f2c15940` 在目标 Jetson 上完成
TensorRT C++ 编译、链接、FP16 engine 构建、零张量探测与合成灰图检测，验证退出码为 `0`。
这证明候选运行路径可执行，不证明真实人物检测、跟踪、事件质量或完整流水线实时性。
默认 YOLOX-Tiny、systemd 配置和服务参数没有改变，固定 A/B 尚未执行。

## 构建条件

| 项目 | 本轮记录 |
| --- | --- |
| SoM 标识 | `P3767-0003`，Jetson Orin Nano 8GB |
| 设备树 compatible | `p3768-0000+p3767-0003-super` / `p3767-0003` / `tegra234` |
| 内核 | `5.15.148-tegra` |
| L4T | `36.4.3`，`nvidia-l4t-core 36.4.3-20250107174145` |
| CUDA 编译工具 | `12.6.68` |
| TensorRT | `10.3.0`；运行库及开发包 `10.3.0.30-1+cuda12.5` |
| 编译器 / OpenCV / GStreamer | GCC `11.4.0` / OpenCV `4.8.0` / GStreamer `1.20.x` |
| 功率 | 25W，模式 `1`，构建前后未改变 |
| 时钟 | 本轮未执行锁频；GPU 最低/最高频率为 `306/918 MHz`，EMC `FreqOverride=0` |
| 常驻服务 | 构建与候选推理期间临时停止，验证结束后恢复原服务 |
| 构建参数 | 静态 batch 1、`640x640`、`--fp16`、workspace `2048 MiB` |

设备树 `model` 显示 `NVIDIA Jetson Orin NX Engineering Reference Developer Kit Super`，
本轮按模组标识和实际 CUDA 设备记录结果，不据此把模组改称 Orin NX，也不据此确定商业
载板型号。未执行依赖安装、系统升级、BSP 修改、功率切换或服务部署。

`--fp16` 允许 TensorRT 使用 FP16；构建器报告 `FP32+FP16`，不表示所有层均强制半精度。
engine 在此目标设备构建，不是从主机移植的 plan。

## 资产与追溯

固定权重来源和主机导出工具链见[资产与导出契约](../models/yolo26s.md)。本轮使用：

| 资产 | SHA-256 |
| --- | --- |
| 官方权重 | `646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b` |
| 输入 ONNX | `82f82fb5249d2da8806ae50c4ab69761d9f447d5aaa1462535dfdca3eef83a16` |
| 板端 engine | `0a6606480b9726f0b98bf1b7a0f79d76b1635ad4d1af8d93d2b67139c595ce7c` |
| 本轮验证脚本 | `4eed0aac56d22b0479bf47983cafaf4fcf77ac83c49796e3184257406cde5b0b` |

原始运行目录为 `.cache/yolo26s-jetson-49876fe.2sggVWmr/`，包含 `validation.log`、
`engine-build.log`、`engine-probe.log`、`synthetic-smoke.log`、`tegrastats.log`、
输入/二进制/模型哈希记录及 `service-restart.log`。目录、模型和图像均不纳入 Git。
以下结论取自该轮终端日志；完整遥测尚未汇总，不报告流水线功耗、温度或内存达标结论。

## 实际验证结果

- Release 构建启用 GStreamer 与 TensorRT，所有目标编译和链接成功；动态依赖未出现
  `not found`。
- `16/16` 项 CTest、`40/40` 项 Python 测试、x264 检查、全部 Shell 语法检查、发布检查
  和 `git diff --check` 通过。这里的测试数对应上述被测提交，不代表后续评估工具的新测试数。
- engine 构建耗时 `685.843 s`，大小约 `21.4783 MiB`。
- 实际公开 I/O 为 `images:[1,3,640,640]` 与 `output0:[1,84,8400]`。C++ 探测的
  `705600/705600` 个输出值全部有限；构建日志中的内部网络张量计数不替代实际 I/O 契约。
- 单图使用 `1280x720`、RGB 三通道均为 `114` 的合成输入，显式选择 `yolo26`，score
  `0.25`、NMS `0.45`；输出 `detections=0` 并保存标注图。这两个数值仅用于连通性检查，
  不是校准结果或正式默认值，也没有验证人物框定位精度。
- 原服务恢复到 `active/running`，观察窗口内 `NRestarts=0`，有多条递增的真实帧记录。
  服务环境文件、启动脚本、已安装程序和默认 Tiny engine 的 SHA-256 前后一致；代码工作树
  检查无变化。此项是原服务恢复检查，不是 YOLO26 的 CSI/RTSP 或长期稳定性结果。

## 随机输入诊断的限制

`trtexec` 使用随机输入，预热约 `200 ms` / 20 次查询，测量 406 次查询、约 `3.01661 s`。
输出 GPU Compute Time P95 `8.14044 ms`、Latency P95 `8.95312 ms`、Throughput
`134.588 qps`，同时提示 GPU 计算时间波动系数 `4.61316%`。

这些是短时 engine 诊断，不包含视频采集、项目预处理/NMS、ByteTrack、事件或证据输出，
不能作为项目 `tensorrt_inference` / `end_to_end` 指标，也不能转换为已实现的完整视频 FPS。
本轮没有为消除该警告而更改时钟、功率或推理参数。

下一步只进入 development/calibration；真实视频正确性、固定 MOT17/CAVIAR A/B、25W
720p 约 30 FPS、功耗/温度/内存、事件 I/O、长期稳定性和 RTSP 重连均仍需独立验证。
