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
回原图的未裁剪坐标，按类别分数过滤并执行 class-aware NMS，最后裁剪到图像边界。阈值必须
在 development/calibration split 上重新校准，不能直接沿用 YOLOX-Tiny 的 confidence 分布假设。

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

## C++ 候选运行时

`IProfiledDetector` 扩展既有 `IDetector`，返回相同的检测结果和预处理、TensorRT、后处理、
总耗时。应用只通过 `make_detector` 装配实现；File/CSI/RTSP、ByteTrack、事件状态和输出
队列共用原有链路。YOLOX-Nano/Tiny/S 的数值预处理和后处理未改变，默认选择仍是 `yolox`。

YOLO26 实现只接受上述静态 one-to-many shape。输入为 RGB float32 NCHW，双线性缩放、
允许放大、固定居中补边；缩放尺寸采用 nearest-even 舍入，奇数补边多出的一个像素放在右侧
或底部，补边值为 `114/255`。输出每个候选只保留最高分的类别，不再做 sigmoid 或乘
objectness；使用连续坐标的按类别 NMS，最后裁剪，最多选择 300 个框。相同分数按原候选
顺序处理。NMS-free `[1,300,6]`、转置输出及 YOLOX 输出均直接拒绝，不自动猜测或转换。

实时入口和 MOT 序列入口在 `--detector yolo26` 下要求显式指定 score、NMS、track、
new-track、match 五个阈值。单图入口要求 score 和 NMS。这样不会把旧命令中的隐含
YOLOX 预设当作候选已校准配置。下列命令仅用于目标 Jetson 上的有限连通性检查，变量应
由开发/校准配置提供，不是已冻结的 A/B 配方：

```bash
./build/edge_vision_realtime_detect \
  --detector yolo26 --engine models/yolo26s_fp16.plan \
  --file development.mp4 --frames 300 --warmup-frames 30 \
  --score-threshold "${SCORE:?set calibration score}" \
  --nms-threshold "${NMS:?set calibration NMS}" \
  --track-threshold "${TRACK:?set calibration track}" \
  --new-track-threshold "${NEW_TRACK:?set calibration new-track}" \
  --match-threshold "${MATCH:?set calibration match}"
```

MOT 序列工具新增 `detector_preprocess_p95_ms`、`tensorrt_inference_p95_ms` 和
`detector_postprocess_p95_ms`。既有 `inference_p50_ms` / `inference_p95_ms` 保留原语义：
它们包含帧封装与整个检测路径，不能当作纯 TensorRT 耗时。新的 TensorRT 阶段计时与实时
入口一致，包含主机/设备传输、执行及同步，不等同于仅 GPU kernel 时间；后续 A/B 必须
比较同名、同定义字段，不重写历史数值。

主机测试使用 `edge_vision_yolo26_check` 验证公共接口、RGB/BGR、归一化、横竖帧补边、
奇数补边、半整数舍入、坐标还原、按类别 NMS、阈值与非法输入。默认无 TensorRT 的 CMake
构建也包含该测试。提交 `49876fe` 随后在目标 Jetson 完成 TensorRT 编译、链接、engine
构建、反序列化、CUDA 零张量执行和合成灰图检测，engine SHA-256 为
`0a6606480b9726f0b98bf1b7a0f79d76b1635ad4d1af8d93d2b67139c595ce7c`；完整范围、
原始记录及恢复检查见[板端最小验证](../benchmarks/yolo26s_jetson_smoke.md)。
主机导出元数据中的验证边界仍描述导出当时，不替代这份独立板端记录。
真实检测/事件效果、25W 720p 吞吐和候选恢复尚未验证。固定 A/B 尚未执行，不能认定升级完成。

## 开发集评估入口

`scripts/run_mot17_inference.sh` 支持显式 `--detector yolo26`，只接受既有校准划分
02/04/05/10 的 FRCNN 序列或其子集；完整比较仍须覆盖全部四段。YOLO26 必须显式提供
score、NMS、track、new-track、match 和独立的输出/报告路径。参数在运行前检查有限性和
`score < track <= new-track`；两个目录均不得已经存在，失败轮次也不覆盖或自动重跑。
旧 YOLOX 入口和数值默认值不变，Tiny 基线继续使用既有校准选定的阈值，而不是把脚本默认
track `0.50` / new-track `0.60` 误作已选定的 MOT17 基线 `0.30` / `0.40`。

下列变量必须来自明确的开发配置；这不是已选定或冻结的 YOLO26 参数：

```bash
bash scripts/run_mot17_inference.sh \
  --detector yolo26 --engine "${ENGINE:?set target-built engine}" \
  --binary "${MOT_BINARY:?set verified binary}" \
  --seqmap configs/mot17/calibration.txt \
  --output-root "${MOT_OUTPUT:?set unused output directory}" \
  --report-root "${MOT_REPORT:?set unused report directory}" \
  --score-threshold "${SCORE:?set calibration score}" \
  --nms-threshold "${NMS:?set calibration NMS}" \
  --track-threshold "${TRACK:?set calibration track}" \
  --new-track-threshold "${NEW_TRACK:?set calibration new-track}" \
  --match-threshold "${MATCH:?set calibration match}"
```

MOT 目录记录实际命令、代码提交、工作树状态、engine/程序/seqmap/运行脚本哈希。
推理成功不等于完成 TrackEval，也不自动解锁 holdout；计算开发指标时仍须显式选择
`configs/mot17/calibration.txt`，不能使用 TrackEval 包装脚本的 holdout 默认值。

`scripts/run_caviar_external_validation.py` 同样支持检测器和阈值显式参数，仅在
`Walk1`、`Browse1`、`EnterExitCrossingPaths1front` 上允许 YOLO26 或运行参数覆盖。
原冻结规则文件不修改，覆盖值只用于本轮运行，并写入独立目录的 `run-manifest.json`。
该文件记录实际检测器、参数、划分，以及 engine、程序、配置、视频、标注和脚本的哈希；
事件几何、真值生成和匹配标准仍来自原冻结文件。没有新参数时，旧 YOLOX 命令保持相同。

```bash
python3 scripts/run_caviar_external_validation.py \
  --sequence Walk1 --rules configs/caviar/rules.frozen.json \
  --detector yolo26 --engine "${ENGINE:?set target-built engine}" \
  --binary "${RUNTIME_BINARY:?set verified binary}" \
  --output-root "${CAVIAR_OUTPUT:?set development output directory}" \
  --score-threshold "${SCORE:?set calibration score}" \
  --nms-threshold "${NMS:?set calibration NMS}" \
  --track-threshold "${TRACK:?set calibration track}" \
  --new-track-threshold "${NEW_TRACK:?set calibration new-track}" \
  --match-threshold "${MATCH:?set calibration match}"
```

CAVIAR 在事件计分前检查完整目标帧数、零预热、零丢帧、零序列缺口及无输入重启，标注
SHA-256 也必须与原数据清单一致。违反帧完整性的轮次保留原始产物并退出，不生成事件得分。
即使提供 `--allow-holdout`，候选或覆盖参数也不能运行旧留出片段。
候选正式 MOT17 holdout 与新 external holdout 的冻结、批准和单次执行机制不在这些
开发入口中放行；本轮没有选择正式阈值、改变任何默认项或执行数据集评估。

## 纳入 A/B 的门禁

只有以下信息完整时，该 engine 才能进入 development/calibration 评估：

- 权重、ONNX 和 engine 的 SHA-256；
- 导出工具和目标 Jetson 软件栈；
- one-to-many 输出探测结果及独立后处理测试；
- 固定的输入预处理、人物类别、NMS 和跟踪参数范围；
- 与 YOLOX-Tiny 相同的 MOT17 划分和 CAVIAR development 协议。

MOT17 holdout 只能在参数冻结后执行一次。已经查看过结果的 CAVIAR 序列不得重新标记为新的
独立留出；新的 external holdout 只能在 development 与 MOT17 结果满足晋级条件后冻结。
