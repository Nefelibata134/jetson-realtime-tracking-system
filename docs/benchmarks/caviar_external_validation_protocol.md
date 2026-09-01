# CAVIAR 公开场景外部事件验证协议

## 目标与边界

本协议使用 CAVIAR 公开固定机位视频，独立验证 ROI 入侵、有限线段穿越、停留事件以及
截图/片段证据链。它回答“系统在未参与项目开发的公开真实视频上能否产生正确事件”，
不替代以下测试：

- MOT17 留出集继续单独报告 HOTA、IDF1、MOTA、Recall 和 ID Switches。
- IMX219 持续运行继续验证 CSI/Argus、真实帧 watchdog 和 Jetson 服务恢复。
- CAVIAR 场景不是实际部署现场，结果不能表述为工厂或安防现场验收。

CAVIAR 原始视频为 384x288、25 FPS、MPEG2。数据由 EC Funded CAVIAR
project/IST 2001 37540 提供，页面标注为 CC BY-SA；仓库只保存 URL、哈希、协议和
脚本，不再分发视频与 XML。

## 固定数据划分

六段视频在任何系统推理前固定。每个事件使用相同机位的一段开发视频确定规则，再用另一段
留出视频做一次正式评估。

| 规则对 | 开发片段 | 留出片段 | 事件 | 时长 |
| --- | --- | --- | --- | ---: |
| `inria_line` | `Walk1` | `Walk2` | `line_crossing` | 24.44 / 42.20 s |
| `inria_dwell` | `Browse1` | `Browse_WhileWaiting2` | `dwell` | 41.72 / 75.80 s |
| `lisbon_front_roi` | `EnterExitCrossingPaths1front` | `EnterExitCrossingPaths2front` | `roi_intrusion` | 15.32 / 19.40 s |

总视频时长约 3 分 39 秒。固定 URL 与 SHA-256 位于
[`configs/caviar/dataset.json`](../../configs/caviar/dataset.json)。

## 防止测试泄漏

执行顺序不可交换：

1. 只观看三段开发视频，确定一条警戒线、两个矩形 ROI 和停留阈值。
2. 将 [`configs/caviar/rules.review.json`](../../configs/caviar/rules.review.json)
   复制为 `configs/caviar/rules.frozen.json`，填写复核人、UTC 时间和规则，把
   `status` 改为 `frozen`。
3. 从 CAVIAR 人工框标注生成开发片段事件表，观看原视频并确认事件时间和语义。
4. 冻结模型、TensorRT engine 哈希、检测/跟踪阈值、代码提交和匹配标准。
5. 观看三段留出视频并确认规则仍表达同一语义，但不得修改几何或阈值。
6. 先从 XML 生成并保存留出真值，再使用 `--allow-holdout` 运行系统一次。
7. 无论 PASS 或 FAIL 都保留结果。留出失败后若修改规则、模型或阈值，必须建立新的评估
   周期，不能覆盖原结果。

脚本拒绝使用 `pending_human_review` 规则生成真值，也拒绝在没有
`--allow-holdout` 时运行留出视频。

## 人工复核内容

人工不逐帧画框。CAVIAR 已提供手工边界框，脚本以边界框底边中心生成与 C++ 事件引擎
一致的轨迹真值。人工只负责：

- 确认警戒线/ROI 表达的业务语义，不是为了让系统输出更好看。
- 在开发视频上确定几何和停留秒数。
- 对照生成表中的帧号和秒数确认每个预期事件。
- 检查留出视频是否损坏、场景是否与规则对匹配。

穿线真值复刻 `0.01` 归一化侧边容差和有限线段相交；ROI 入侵复刻连续两帧确认；停留
真值复刻连续两帧入区、最多三帧轨迹缺口和基于 PTS 的停留计时。预测 track ID 不要求与
CAVIAR 标注 ID 相同。

## 下载与介质准备

在 Windows 或 Jetson 下载并校验六段原视频和 XML：

```bash
python3 scripts/fetch_caviar.py --root data/caviar
```

项目文件源只接受 H.264 MP4，而原视频是 MPEG2。Jetson 上执行一次确定性转码：

```bash
python3 scripts/prepare_caviar_media.py --root data/caviar
```

脚本要求 `nvvidconv`、`x264enc`、`h264parse` 和 `mp4mux`，并在发布 MP4 前重新解析
容器与 H.264 码流。原文件和转码文件分别记录在 `download-lock.json` 与
`prepared-lock.json`；二者均位于 Git 忽略的 `data/caviar/`。

## 冻结规则格式

规则坐标统一归一化到 `[0,1]`：

```json
{
  "status": "frozen",
  "reviewer": "Nefelibata134",
  "reviewed_at_utc": "YYYY-MM-DDTHH:MM:SSZ",
  "frozen_at_utc": "YYYY-MM-DDTHH:MM:SSZ",
  "rules": [
    {
      "pair_id": "inria_line",
      "event_type": "line_crossing",
      "line": [0.0, 0.0, 1.0, 1.0],
      "direction": "any"
    },
    {
      "pair_id": "inria_dwell",
      "event_type": "dwell",
      "roi": [0.0, 0.0, 1.0, 1.0],
      "dwell_seconds": 3.0
    },
    {
      "pair_id": "lisbon_front_roi",
      "event_type": "roi_intrusion",
      "roi": [0.0, 0.0, 1.0, 1.0]
    }
  ]
}
```

上例只说明字段，不是可直接采用的规则坐标。实际坐标必须来自人工观看开发视频。

## 真值生成与受控运行

先生成开发视频的独立真值和人工确认表：

```bash
python3 scripts/generate_caviar_ground_truth.py \
  --rules configs/caviar/rules.frozen.json \
  --sequence Walk1 \
  --output outputs/caviar/review/Walk1.jsonl \
  --output-markdown outputs/caviar/review/Walk1.md
```

在 Jetson 上构建运行时、停止常驻服务，然后运行开发视频：

```bash
cmake -S . -B build-caviar \
  -DCMAKE_BUILD_TYPE=Release \
  -DEDGE_VISION_ENABLE_GSTREAMER=ON \
  -DEDGE_VISION_ENABLE_TENSORRT=ON
cmake --build build-caviar -j"$(nproc)"
ctest --test-dir build-caviar --output-on-failure

sudo systemctl stop edge-vision.service

python3 scripts/run_caviar_external_validation.py \
  --sequence Walk1 \
  --rules configs/caviar/rules.frozen.json \
  --engine models/yolox_nano_fp16.plan \
  --binary build-caviar/edge_vision_realtime_detect
```

三段开发视频完成且不再修改规则、代码、模型或阈值后，显式运行留出视频：

```bash
python3 scripts/run_caviar_external_validation.py \
  --sequence Walk2 \
  --rules configs/caviar/rules.frozen.json \
  --engine models/yolox_nano_fp16.plan \
  --binary build-caviar/edge_vision_realtime_detect \
  --allow-holdout
```

运行器先生成真值，再启动本机 RTSP 实时回放，随后执行检测、ByteTrack、事件规则、截图、
事件片段和标注视频。常驻 `edge-vision.service` 活跃时会拒绝运行，避免资源竞争。

## 匹配与通过标准

相同事件类型使用一对一匹配：默认允许 50 帧时间差和 `0.20` 归一化锚点距离；穿线还必须
方向一致。留出集预先固定：

- Precision 不低于 `0.80`。
- Recall 不低于 `0.80`。
- 每条实际事件的截图与片段完整率为 `100%`。
- 运行时必须达到目标帧数，并且退出码为零。

每次运行目录包含原始日志、命令、真值 JSONL、人工确认表、实际事件、截图、片段、标注
视频、运行时指标以及 JSON/Markdown 评估报告。开发和留出结果不得与 MOT17 指标合并成
一个分数。
