# Safety Event Record Schema

Safety events are persisted as JSON Lines. Each non-empty line is one complete
event record and can be parsed independently.

## Version 1.0

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

| Field | Meaning |
| --- | --- |
| `schema_version` | Consumer compatibility contract. |
| `event_id` | Stable ID derived from the event identity within one session. |
| `session_id` | Unique runtime invocation ID. |
| `source_id` | Input source, such as `csi:0` or `file:input.mp4`. |
| `stream_generation` | Increments after a successful source restart. |
| `recorded_at_utc` | Wall-clock time when the record was created. |
| `event_type` | `roi_intrusion`, `line_crossing`, or `dwell`. |
| `rule_id` | Stable rule configuration identifier. |
| `track_id` / `class_id` | ByteTrack identity and detector class. |
| `frame_sequence` | Capture sequence that triggered the event. |
| `pts_ns` | Source presentation timestamp in nanoseconds. |
| `anchor` | Normalized bottom-center track position. |
| `direction` | Crossing direction, or `none` for non-crossing events. |
| `evidence` | Verified artifact paths; absent artifacts are JSON `null`. |

## Identity And Deduplication

`event_id` is a deterministic FNV-1a digest of `session_id`, source ID,
`stream_generation`, event type, rule ID, track ID, class ID, and trigger frame.
The journal loads existing IDs before opening the file for append, so duplicate
submissions are rejected both within the current process and after the journal
is reopened. A new process receives a new `session_id`; reused tracker IDs from
a later invocation therefore cannot collide with earlier events.

## Evidence Commit Order

Artifacts are committed in this order:

1. Render the annotated trigger frame.
2. Write a temporary JPEG or MP4.
3. Close, verify, and atomically rename the artifact.
4. Append the record containing the verified path to the JSONL journal.
5. Flush the journal stream.

This ordering prevents records from advertising artifact paths that were never
created. A process interruption can leave an unreferenced artifact, but it
cannot create a successfully appended record with a fabricated path.

## Event Clips

Event clips are optional. The recorder keeps a bounded raw-frame ring buffer
for the configured pre-event duration and finalizes each clip after the
configured post-event duration. JSONL publication is delayed until the clip is
closed and verified. Pending clips are finalized early during shutdown or a
stream-generation reset, preventing frames from two source generations from
being mixed.

The raw prebuffer upper bound is:

```text
width * height * 3 bytes * application FPS * pre-event seconds
```

At 1280x720, 30 FPS, and two pre-event seconds, the bound is 165,888,000 bytes
(about 158 MiB). At 1920x1080 with the same settings it is about 356 MiB.
`event_clip_prebuffer_peak_bytes` reports the observed high-water mark.
