# YOLO26s 资产与导出契约

## 评估状态

YOLO26s 是检测模型 A/B 评估候选，当前默认检测器仍为 YOLOX-Tiny。接入候选不会删除
YOLOX-Nano、YOLOX-Tiny、YOLOX-S 的实现或历史结果，也不会在固定评测证明质量和实时性
同时改善前修改 README 默认命令、systemd 服务或部署默认值。

首轮 A/B 采用静态 `640x640`、batch 1、`end2end=False` 的 one-to-many 检测头。官方文档
说明该检测头通常比默认 one-to-one 头具有略高精度，但输出需要独立的 YOLO26 解码和 NMS。
运行时不得复用 YOLOX grid decode，也不能把 one-to-many 输出当作 NMS-free 结果。

## 固定来源

| 项目 | 固定值 |
| --- | --- |
| 模型 | Ultralytics YOLO26s |
| 资产发布 | `ultralytics/assets` `v8.4.0` |
| 权重 URL | `https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26s.pt` |
| 权重 SHA-256 | `646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b` |
| 导出工具 | `ultralytics==8.4.138` |
| ONNX 工具 | `onnx==1.20.0` |
| 源码标签解析提交 | `dad7bb4534c95021bc14969ab25d77b77c4efdc3` |
| 上游许可证 | AGPL-3.0 或 Enterprise License；本项目使用 AGPL-3.0 路线 |

机器可读副本位于 `models/yolo26s.json`。权重采用 Pickle 序列化，只允许加载上述官方来源
且 SHA-256 已通过校验的文件。

## 获取权重

在仓库根目录执行：

```bash
bash scripts/fetch_yolo26s.sh models/yolo26s.pt
sha256sum models/yolo26s.pt
```

脚本先下载到临时文件，校验固定 SHA-256 后才替换目标路径。`*.pt` 已被 Git 忽略，不得
使用强制添加将其纳入版本控制。

## 导出静态 ONNX

ONNX 可在独立的 Linux x86_64 或 Jetson Python 环境导出；TensorRT engine 必须留到目标
Jetson 构建。以下步骤不需要系统升级或 sudo：

```bash
python3 -m venv .venv-yolo26-export
source .venv-yolo26-export/bin/activate
python -m pip install -r requirements/yolo26-export.txt
python scripts/export_yolo26s_onnx.py \
  models/yolo26s.pt \
  --output models/yolo26s.onnx
python -m pip freeze
```

导出脚本在加载权重前验证其哈希，并拒绝非 `8.4.138` 的 Ultralytics 版本。导出后还会验证
单输入、单输出和静态 shape，移除易变的导出时间元数据，并打印 ONNX SHA-256。相同工具链
的重复导出应产生相同哈希；不同 PyTorch 或平台仍可能生成不同图。每次正式导出必须把完整
`pip freeze`、Python/PyTorch/Ultralytics/ONNX 版本、命令输出和 ONNX 哈希保存到仓库外的
评估运行目录。

固定张量契约如下：

| 张量 | shape | 语义 |
| --- | --- | --- |
| 输入 | `[1, 3, 640, 640]` float32 | RGB、按 255 归一化、保持比例 letterbox |
| 输出 | `[1, 84, 8400]` float32 | 4 个 `cxcywh` 通道 + 80 个 COCO 类别分数 |

输出不含单独 objectness，人物类别为 COCO class 0。候选检测器必须先把 box 从模型坐标映射
回原图，再按类别分数过滤并执行 class-aware NMS。阈值必须在 development/calibration split
上重新校准，不能直接沿用 YOLOX-Tiny 的 confidence 分布假设。

## 主机导出验证

2026-09-04 在 Windows AMD64 主机上使用 Python `3.13.9`、PyTorch `2.11.0+cpu`、
Ultralytics `8.4.138` 和 ONNX `1.20.0` 完成两次独立导出。两次均得到输入
`images:[1,3,640,640]`、输出 `output0:[1,84,8400]`，规范化元数据后的 ONNX SHA-256
均为 `82f82fb5249d2da8806ae50c4ab69761d9f447d5aaa1462535dfdca3eef83a16`。

该结果只验证权重获取、导出参数、静态图契约和同环境可重复性，不代表 TensorRT 或 Jetson
性能。正式 A/B 必须使用实际送入 Jetson 构建的 ONNX 哈希，并另行记录 engine 哈希。

## 在目标 Jetson 构建 FP16 engine

确认设备、JetPack/TensorRT 和当前功率模式后，在目标 Jetson 上运行：

```bash
cat /proc/device-tree/model
cat /etc/nv_tegra_release
dpkg-query -W nvidia-l4t-core
/usr/src/tensorrt/bin/trtexec --version
nvpmodel -q

bash scripts/build_tensorrt_engine.sh \
  models/yolo26s.onnx \
  models/yolo26s_fp16.plan \
  2048
sha256sum models/yolo26s.onnx models/yolo26s_fp16.plan
```

构建脚本使用静态 ONNX profile 和 TensorRT FP16，并打印 ONNX 与 engine 哈希。正式记录还要
包含 Jetson SKU、JetPack/L4T、CUDA、TensorRT、功率模式、锁频状态、workspace、输入 shape
和构建日志。plan 不能跨 GPU 或 TensorRT/CUDA 软件栈复用。

本步骤不修改 APT 源、不执行系统升级，也不改变功率模式。需要 sudo 的设备操作由操作者在
远程终端明确执行。

## 纳入 A/B 的门禁

只有以下信息完整时，该 engine 才能进入 development/calibration 评估：

- 权重、ONNX 和 engine 的 SHA-256；
- 导出工具和目标 Jetson 软件栈；
- one-to-many 输出探测结果及独立后处理测试；
- 固定的输入预处理、人物类别、NMS 和跟踪参数范围；
- 与 YOLOX-Tiny 相同的 MOT17 划分和 CAVIAR development 协议。

MOT17 holdout 只能在参数冻结后执行一次。已经查看过结果的 CAVIAR 序列不得重新标记为新的
独立留出；新的 external holdout 只能在 development 与 MOT17 结果满足晋级条件后冻结。
