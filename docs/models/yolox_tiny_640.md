# YOLOX-Tiny 640 候选资产与导出契约

当前默认仍为 Tiny `416x416`。Tiny `640x640` 只增加输入尺寸候选，不修改网络结构、类别、
ByteTrack 或默认命令。原 Tiny/Nano/S、YOLO26n/s 资产元数据及历史结果保持不变。

## 权重身份与 416 等价性

固定上游 [YOLOX 0.1.1rc0](https://github.com/Megvii-BaseDetection/YOLOX/releases/tag/0.1.1rc0)，
源码提交 `e1052df71842031413f6030723c3607b839c80ce`，配置 `exps/default/yolox_tiny.py`，
depth `0.33`、width `0.375`、COCO `80` 类。来源采用 Apache-2.0；第三方声明见
[许可证边界](../../THIRD_PARTY_NOTICES.md)。

| 资产 | SHA-256 |
| --- | --- |
| 原始 `yolox_tiny.pth` | `9de513de589ac98bb92d3bca53b5af7b9acfa9b0bacb831f7999d0f7afaee8f0` |
| 官方 416 ONNX | `427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7` |
| 复现 416 ONNX | `f56cf7d378c2e13c85bd8d7419ffd36f8ea2f409efdd7959c626474e25e6c2a7` |
| 候选 640 ONNX | `d19526fb64f78d0dd58c2cf0b4fa283a895356d45bc8c91068233b4295020014` |

主机核验覆盖两图的全部 83 个 Conv 层折叠权重与偏置，容差 `atol=1e-6, rtol=1e-5`；
四段 MOT17 calibration 的首帧分别固定 SHA-256 后使用同一 BGR 预处理和后处理比较。
原始输出容差 `atol=rtol=1e-4`，最大绝对差 `6.714463e-5`，无超差元素。
检测类别与数量一致，四帧分别为 `16/35/7/19` 个框（所有类别，经 NMS），坐标容差为原图
`0.05 px`，最大差 `0.0001221 px`。分数容差 `atol=rtol=1e-4`。

这是固定图像上的 CPU float32 等价证据，结合完整卷积参数核验支持同权重对照；不是所有
输入下位级等价证明，也不是 FP16 精度或 MOT17 质量结论。官方图由 PyTorch 1.7 生成，
复现图由 2.11.0 生成，因此文件哈希不同。640 重复导出两次哈希一致。

## 输入与输出

- `images`: float32 `[1,3,640,640]`，batch 1、静态尺寸、BGR、数值范围 0–255。
- 等比例双线性缩放后贴左上，右侧/底部填充 114；不除以 255、不做均值方差归一化。
- `output`: float32 `[1,8400,85]`，strides `8/16/32`，保留 objectness 和 80 类概率。
- 输出未做 grid decode，未做 NMS。沿用 C++ YOLOX 的 grid/stride 与 exp 宽高解码，
  `objectness × class_probability`、原图坐标反映射及 class-agnostic inclusive-IoU NMS。
- 从原始权重真实导出 640 图，不修改已导出 416 图的 shape 标签。

## 可复现主机导出

下例使用独立目录，不覆盖已有资产。Python 3.13.9、PyTorch `2.11.0+cpu`、ONNX `1.20.0`、
ONNX Runtime `1.24.4` 是已核验环境；其他平台/工具版本需重新核验，不能仅改记录中的哈希。
依赖只装入主机隔离环境，不替换 Jetson 平台包。

```bash
python3 -m venv .cache/tiny-export-env
.cache/tiny-export-env/bin/pip install -r requirements/yolox-tiny-export.txt
git clone --depth 1 --branch 0.1.1rc0 --single-branch \
  https://github.com/Megvii-BaseDetection/YOLOX.git .cache/tiny-export-source
git -C .cache/tiny-export-source rev-parse HEAD
bash scripts/fetch_yolox_tiny_weights.sh .cache/tiny-export/yolox_tiny.pth
bash scripts/fetch_yolox_tiny.sh .cache/tiny-export/official-416.onnx
.cache/tiny-export-env/bin/python scripts/export_yolox_tiny_onnx.py \
  --source .cache/tiny-export-source --weights .cache/tiny-export/yolox_tiny.pth \
  --size 416 --output-dir .cache/tiny-export/416
```

将既有 calibration 序列 `MOT17-02-FRCNN`、`04`、`05`、`10` 的 `img1/000001.jpg`
分别保存为 `.cache/tiny-export/images/SEQUENCE.jpg`，完整序列名用于文件名。
核验器检查四个图像的固定哈希，不接受 holdout 图像或任意替换图片。

```bash
.cache/tiny-export-env/bin/python scripts/verify_yolox_tiny_416.py \
  --reference .cache/tiny-export/official-416.onnx --export-dir .cache/tiny-export/416 \
  --images .cache/tiny-export/images --output-dir .cache/tiny-export/parity
.cache/tiny-export-env/bin/python scripts/export_yolox_tiny_onnx.py \
  --source .cache/tiny-export-source --weights .cache/tiny-export/yolox_tiny.pth \
  --size 640 --baseline-proof .cache/tiny-export/parity/parity.json \
  --output-dir .cache/tiny-export/640
```

## 目标 Jetson 构建

必须先将主机 ONNX 传输到目标 Jetson 的新目录，再在板端执行 `sha256sum` 与上述 640
哈希比较；不能假设板端已有模型。使用显式传输目标，例如
`scp .cache/tiny-export/640/yolox_tiny_640.onnx "$JETSON_HOST:$NEW_REMOTE_DIRECTORY/"`。
目标应为已核验的 Orin Nano 8GB `P3767-0003`；engine 与目标 TensorRT/CUDA/GPU 绑定。

编译启用 TensorRT 和 GStreamer 的独立构建目录，保留默认部署二进制。构建前记录系统、
源码、服务 PID、实际默认 engine、25W 和时钟控制；确认 Tiny 真实帧递增后临时停止服务。
在包含异常退出恢复保护的停服窗口内调用：

```bash
bash scripts/build_yolox_tiny_640_engine.sh \
  "$CANDIDATE_ONNX" "$NEW_ENGINE_RESULT_DIRECTORY" "$BUILD/edge_vision_trt_probe"
```

脚本只接受服务已停止、25W 和指定 ONNX 哈希，拒绝复用结果目录，不切换功率或锁频。
记录原始构建日志、退出码、plan SHA-256 与探测输出。外层执行器必须无论成功、失败或
中断均恢复 `edge-vision.service`，验证实际 Tiny416 engine、active/running、NRestarts=0
以及新真实帧递增。不能仅用进程存活证明恢复。

主机导出证据与板端结果分开记录。目标 Tiny640 engine 已完成构建、重新加载与真实开发
图像检查，SHA-256 为 `22ef7b68170e995d589c943eb8f684b2a5c9117bc5fc7de239a017f6a816760c`。
首轮25W同阈值 MOT17 calibration 的召回提高，但小目标中断条件未通过，详见
[板端对照结果](../benchmarks/tiny_resolution_results.md)。尚无 CAVIAR 或 CSI720p30 验收结论。
评估门槛和分组定义见 [Tiny 输入尺寸对照协议](../benchmarks/tiny_resolution_protocol.md)。

元数据中的 `jetson_validation` 保留上述首轮 v1 的执行快照，不是后续实验的实时状态。
后续 [CAVIAR v4](../benchmarks/tiny_resolution_caviar_v4_results.md)、
[CSI 带事件短测](../benchmarks/tiny_resolution_csi_event_retest.md)及
[近景 v6](../benchmarks/tiny_near_field_v6_results.md)已经执行，仍未形成默认晋级验收结论；
资产哈希与首轮 FAIL 保持不变。
