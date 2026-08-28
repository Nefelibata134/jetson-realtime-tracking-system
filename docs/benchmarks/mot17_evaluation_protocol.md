# MOT17 评估协议

## 评估范围

该基准在 MOT17 训练划分中的行人序列上评估完整的 YOLOX TensorRT 与 ByteTrack
流水线。YOLOX-Nano 和 YOLOX-Tiny 使用相同跟踪参数在校准划分上对比；选定的
YOLOX-Tiny 配置随后只在留出划分上评估一次。指标由官方 TrackEval 实现计算，并固定到
提交 `12c8791b303e0a0b50f753af204249e622d0281a`。

MOT17 以 DPM、FRCNN 和 SDP 三套公开检测结果的名称重复存储每段物理视频。本系统使用
自己的 YOLOX 检测结果，因此协议只采用每段物理视频的 FRCNN 命名副本，避免相同画面
和真值被重复统计三次。

## 数据划分

| 划分 | 序列 | 用途 |
| --- | --- | --- |
| 校准 | 02、04、05、10 | 受控跟踪参数对比 |
| 留出 | 09、11、13 | 配置选定后只报告一次最终结果 |

受版本控制的序列映射保存在 `configs/mot17/`。本地基准不使用标签未公开的测试集。
在推理或指标计算开始前，数据校验会检查所选序列的元数据、真值、图像数量和帧编号。

## 帧处理策略

- 按顺序处理每个所选序列中的全部图像。
- 不使用有界采集队列，也不丢帧。
- 仅把 COCO 类别 0（`person`）传给 ByteTrack。
- MOTChallenge 帧序号和边界框原点按 1 起始写出。
- 每条结果严格包含 10 个 MOTChallenge 字段。

## 复现方法

获取官方数据和固定版本评估器：

```bash
sudo apt-get install -y python3-numpy python3-scipy unzip wget
bash scripts/fetch_mot17.sh
bash scripts/fetch_trackeval.sh
```

固定版本评估器使用 Ubuntu 22.04 系统软件包仍保留的 NumPy API。本基准有意避免安装
未固定版本的最新 NumPy。

构建目标设备推理程序：

```bash
cmake -S . -B build-mot17 \
  -DCMAKE_BUILD_TYPE=Release \
  -DEDGE_VISION_ENABLE_TENSORRT=ON
cmake --build build-mot17 -j"$(nproc)"
```

选定配置使用 0.10 检测分数阈值、0.45 NMS 阈值、0.30 ByteTrack 轨迹阈值、0.40
新轨迹阈值、0.80 匹配阈值和 30 帧轨迹缓冲。保持这些由校准划分选出的参数不变，
生成最终留出划分跟踪文件：

```bash
bash scripts/run_mot17_inference.sh \
  --engine models/yolox_tiny_fp16.plan \
  --seqmap configs/mot17/holdout.txt \
  --output-root outputs/mot17/holdout/final_tiny/edge_vision/data \
  --report-root reports/mot17/holdout/final_tiny/inference \
  --score-threshold 0.10 \
  --nms-threshold 0.45 \
  --track-threshold 0.30 \
  --new-track-threshold 0.40 \
  --match-threshold 0.80 \
  --track-buffer 30
```

计算官方留出指标并生成精简报告：

```bash
bash scripts/run_trackeval_mot17.sh \
  --python /usr/bin/python3 \
  --seqmap configs/mot17/holdout.txt \
  --tracker-root outputs/mot17/holdout/final_tiny \
  --tracker-name edge_vision \
  --output-root reports/mot17/holdout/final_tiny/trackeval

python3 scripts/summarize_mot17.py \
  --summary reports/mot17/holdout/final_tiny/trackeval/edge_vision/pedestrian_summary.txt \
  --json reports/mot17/holdout/final_tiny/metrics.json \
  --markdown reports/mot17/holdout/final_tiny/metrics.md \
  --title "MOT17 留出划分最终 YOLOX-Tiny"
```

TrackEval 输出 HOTA、IDF1、MOTA 和 ID switches。HOTA 综合检测与关联质量，IDF1
衡量身份一致性，MOTA 综合假阳性、漏检和身份切换，ID switches 统计身份连续性失败。

包装脚本会把所选序列列表复制到
`data/mot17/train/seqmaps/MOT17-train.txt`，这是该固定版本 TrackEval 命令行程序
期望的规范路径。这样可以避免传入它的旧式 `SEQMAP_FILE` 选项；该版本会把单个路径
错误解析成列表。
