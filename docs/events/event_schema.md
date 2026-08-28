# 安全事件记录 Schema

安全事件以 JSON Lines 格式持久化。每个非空行都是一条完整事件记录，可以独立解析。

## 版本 1.0

```json
{
  "schema_version": "1.0",
  "event_id": "evt-36f29680b4d78226",
  "session_id": "20260817T110500.123Z-a19c73e2",
  "source_id": "csi:0",
  "stream_generation": 0,
  "recorded_at_utc": "2026-08-17T11:05:04.411Z",
  "event_type": "line_crossing",
  "rule_id": "directional-crossing",
  "track_id": 2,
  "class_id": 0,
  "frame_sequence": 131,
  "pts_ns": 4366667000,
  "anchor": {"x": 0.516, "y": 0.992},
  "direction": "positive_to_negative",
  "evidence": {
    "snapshot_path": "outputs/events/snapshots/evt-36f29680b4d78226.jpg",
    "clip_path": "outputs/events/clips/evt-36f29680b4d78226.mp4"
  }
}
```

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 消费端兼容性契约。 |
| `event_id` | 从同一会话内的事件身份字段确定性生成的稳定 ID。 |
| `session_id` | 每次运行调用的唯一 ID。 |
| `source_id` | 输入源，例如 `csi:0` 或 `file:input.mp4`。 |
| `stream_generation` | 输入源成功重启后递增。 |
| `recorded_at_utc` | 创建记录时的 UTC 墙钟时间。 |
| `event_type` | `roi_intrusion`、`line_crossing` 或 `dwell`。 |
| `rule_id` | 稳定的规则配置标识。 |
| `track_id` / `class_id` | ByteTrack 身份与检测类别。 |
| `frame_sequence` | 触发事件的采集帧序号。 |
| `pts_ns` | 输入源显示时间戳，单位为纳秒。 |
| `anchor` | 归一化后的轨迹框底边中心位置。 |
| `direction` | 穿线方向；非穿线事件为 `none`。 |
| `evidence` | 已验证的证据文件路径；缺失文件使用 JSON `null`。 |

## 身份与去重

`event_id` 是以下字段的确定性 FNV-1a 摘要：`session_id`、输入源 ID、
`stream_generation`、事件类型、规则 ID、轨迹 ID、类别 ID 和触发帧。日志以追加模式
打开前会加载已有 ID，因此既能拒绝当前进程内的重复提交，也能在重新打开同一日志后继续
去重。新进程会获得新的 `session_id`，后续调用即使复用了跟踪 ID，也不会与早期事件冲突。

## 证据提交顺序

证据按以下顺序提交：

1. 渲染带标注的触发帧。
2. 写入临时 JPEG 或 MP4。
3. 关闭并验证文件，然后原子重命名。
4. 向 JSONL 日志追加包含已验证路径的事件记录。
5. 刷新日志流。

该顺序可以防止记录声明一个从未创建的证据路径。进程中断可能留下未被引用的文件，但不会
生成一条已经成功追加、路径却是伪造的记录。

## 事件片段

事件片段为可选功能。记录器为配置的事件前时长维护有界原始帧环形缓冲，并在事件后时长
结束时完成片段。只有片段关闭且验证通过后才发布 JSONL。关机或流代次重置时，待完成片段
会提前收尾，从而避免混入两个输入流代次的帧。

原始预缓冲理论上限为：

```text
width * height * 3 bytes * application FPS * pre-event seconds
```

在 1280x720、30 FPS、事件前 2 秒的配置下，上限为 165,888,000 字节，约 158 MiB。
相同设置下的 1920x1080 约为 356 MiB。`event_clip_prebuffer_peak_bytes` 报告实际
观测到的高水位。
