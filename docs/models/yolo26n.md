# YOLO26n 资产与导出契约

## 评估状态

YOLO26n 是检测模型 A/B 评估候选，当前默认检测器仍为 YOLOX-Tiny。接入 YOLO26n 不删除
YOLOX-Nano、YOLOX-Tiny、YOLOX-S 或 YOLO26s 的实现、benchmark 和历史结果，也不修改
systemd、默认运行命令或现有实时链路。

YOLO26n 与 YOLO26s 共用一个模型无关的 C++ `Yolo26Detector`、TensorRT 适配和评估入口。
模型差异只由资产元数据、权重、ONNX 和目标设备上独立构建的 engine 决定；不复制另一套
解码器或跟踪器实现。

## 固定来源

| 项目 | 固定值 |
| --- | --- |
| 模型 | Ultralytics YOLO26n |
| 资产发布 | `ultralytics/assets` `v8.4.0` |
| 权重 URL | `https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt` |
| 权重 SHA-256 | `9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef` |
| 导出工具 | `ultralytics==8.4.138` |
| ONNX 工具 | `onnx==1.20.0` |
| 源码标签解析提交 | `dad7bb4534c95021bc14969ab25d77b77c4efdc3` |
| 上游许可证 | AGPL-3.0 或 Enterprise License；本项目使用 AGPL-3.0 路线 |

机器可读副本位于 `models/yolo26n.json`。权重采用 Pickle 序列化，只允许加载上述官方来源
且 SHA-256 已通过校验的文件。YOLO26s 的原有固定契约见[YOLO26s 资产与导出契约](yolo26s.md)。

## 获取权重

在仓库根目录执行：

```bash
bash scripts/fetch_yolo26n.sh models/yolo26n.pt
sha256sum models/yolo26n.pt
```

脚本使用共享下载实现，先写入临时文件，校验固定 SHA-256 后才替换目标路径。`*.pt` 已被
Git 忽略，不得使用强制添加将其纳入版本控制。

## 导出静态 ONNX

导出使用与 YOLO26s 相同的隔离环境和参数：

```bash
python3 -m venv .venv-yolo26-export
source .venv-yolo26-export/bin/activate
python -m pip install -r requirements/yolo26-export.txt
python scripts/export_yolo26n_onnx.py \
  models/yolo26n.pt \
  --output models/yolo26n.onnx
python -m pip freeze
```

共享导出脚本会先校验权重哈希和 Ultralytics 版本，再执行 `imgsz=640`、batch 1、静态图、
opset 17、`end2end=False`、`simplify=False` 的导出。它会删除易变的导出时间元数据，验证
单输入、单输出、数据类型和静态 shape，并打印 ONNX SHA-256。权重、ONNX 和导出虚拟环境
均不纳入版本控制。

## 张量契约

官方 YOLO26 同时提供 one-to-one 和 one-to-many 检测头；默认 one-to-one 输出
`[1,300,6]`，而本项目为可比的候选检测路径固定使用需要 NMS 的 one-to-many 输出。

| 张量 | shape | 语义 |
| --- | --- | --- |
| 输入 | `[1, 3, 640, 640]` float32 | RGB、按 255 归一化、保持比例居中 letterbox |
| 输出 | `[1, 84, 8400]` float32 | 4 个 `cxcywh` 通道 + 80 个 COCO 类别分数 |

输出不含单独 objectness，人物类别为 COCO class 0。运行时按通道布局读取每个候选的最高
类别分数，映射回原图后执行 class-aware NMS；不得复用 YOLOX grid decode，也不能把
one-to-many 输出当作 NMS-free 结果。

## 主机导出验证

2026-09-04 在 Windows AMD64 主机上使用 Python `3.13.9`、PyTorch `2.11.0+cpu`、
Ultralytics `8.4.138` 和 ONNX `1.20.0` 完成两次独立导出。两次均得到输入
`images:[1,3,640,640]`、输出 `output0:[1,84,8400]`；规范化元数据后的 ONNX SHA-256
均为 `db30d55618402de2396edb7b15a8ca96b3fcd409a31cbc6269355508e555fb95`。

该结果只验证权重获取、导出参数、静态图契约和同环境可重复性，不代表 TensorRT 或 Jetson
性能。正式评估必须使用实际传输到 Jetson、重新核对哈希后构建的 ONNX，并另行记录 engine
哈希。

## C++ 候选运行时

使用目标设备上构建的 YOLO26n engine 时，应用仍显式选择：

```text
--detector yolo26
```

MOT17、CAVIAR 和实时入口都必须显式提供 `score`、`nms`、`track`、`new-track`、`match`
五个阈值。它们只能从 calibration/development 配置传入，不能静默继承 YOLOX-Tiny 阈值。
默认 `yolox`、ByteTrack、ROI、警戒线、停留规则和事件输出保持不变。

## 目标 Jetson 构建

先在主机导出 ONNX，再将该文件传输到目标 Jetson。传输完成后，必须在 Jetson 重新核对
ONNX SHA-256，不能假设模型文件已存在。以下示例使用 SSH 文件复制，主机名和用户名必须
替换为已验证的目标连接：

```bash
scp models/yolo26n.onnx <JETSON_USER>@<JETSON_HOST>:/home/<JETSON_USER>/jetson-realtime-tracking-system/models/yolo26n.onnx
cd /home/<JETSON_USER>/jetson-realtime-tracking-system
sha256sum models/yolo26n.onnx

cmake -S . -B build-yolo26n \
  -DCMAKE_BUILD_TYPE=Release \
  -DEDGE_VISION_ENABLE_GSTREAMER=ON
cmake --build build-yolo26n -j2

bash scripts/build_tensorrt_engine.sh \
  models/yolo26n.onnx \
  models/yolo26n_fp16.plan \
  2048
sha256sum models/yolo26n.onnx models/yolo26n_fp16.plan
./build-yolo26n/edge_vision_yolo26_check
```

TensorRT plan 必须在准确目标 Jetson、对应 CUDA/TensorRT 和目标 profile 上构建；plan 不提交
到仓库，也不从其他 GPU 或设备复制。构建不需要系统升级，不改变功率模式或 systemd。

## 评估门禁

主机导出可重复性和 C++ 确定性测试通过后，才进入与 Tiny 相同划分和统计口径的 MOT17
calibration/development 对照，以及三个 CAVIAR development 视频对照。MOT17 holdout、已消费
的 CAVIAR holdout 和新的 external holdout 均不在本候选接入中解锁。

只有目标 Jetson engine、MOT17/CAVIAR development 质量和 720p/30 完整实时链路同时有独立
证据后，才讨论默认模型变更。达到约 30 FPS 本身不构成模型升级验收。
