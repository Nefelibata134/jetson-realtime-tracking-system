#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
SUPPORTED_EVENTS = {"roi_intrusion", "line_crossing", "dwell"}
SUPPORTED_VALIDATION_ROLES = {"positive_evaluation", "negative_control"}
APPROVED_AUDIT_STATUSES = {"pass", "pass_negative_control"}
RULE_IDS = {
    "roi_intrusion": "restricted-area-entry",
    "line_crossing": "directional-crossing",
    "dwell": "restricted-area-dwell",
}
GEOMETRY_EPSILON = 1.0e-6


@dataclass(frozen=True)
class GroundTruthTrack:
    track_id: int
    anchor_x: float
    anchor_y: float


@dataclass(frozen=True)
class GroundTruthFrame:
    number: int
    tracks: tuple[GroundTruthTrack, ...]


@dataclass
class OccupancyState:
    initialized: bool = False
    stable_inside: bool = False
    has_candidate: bool = False
    candidate_inside: bool = False
    candidate_count: int = 0
    candidate_since_ns: int = 0
    last_seen_sequence: int = 0
    last_seen_pts_ns: int = 0


@dataclass
class LineState:
    has_stable_side: bool = False
    stable_side: int = 0
    has_candidate: bool = False
    candidate_side: int = 0
    candidate_count: int = 0
    stable_point: tuple[float, float] = (0.0, 0.0)
    last_seen_sequence: int = 0


@dataclass
class DwellState:
    occupancy: OccupancyState
    dwell_emitted: bool = False
    entered_at_ns: int = 0
    last_seen_sequence: int = 0


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON document: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_dataset_config(config: dict[str, Any]) -> None:
    if config.get("schema_version") != 1:
        raise ValueError("CAVIAR dataset config requires schema_version=1")
    dataset = config.get("dataset")
    if not isinstance(dataset, dict):
        raise ValueError("dataset metadata is missing")
    for key in ("frame_width", "frame_height", "frames_per_second"):
        if not isinstance(dataset.get(key), int) or dataset[key] <= 0:
            raise ValueError(f"dataset.{key} must be a positive integer")

    sequences = config.get("sequences")
    if not isinstance(sequences, list) or not sequences:
        raise ValueError("dataset config must select at least one sequence")

    sequence_ids: set[str] = set()
    pair_splits: dict[str, set[str]] = {}
    pair_events: dict[str, set[str]] = {}
    for sequence in sequences:
        if not isinstance(sequence, dict):
            raise ValueError("every sequence entry must be an object")
        sequence_id = sequence.get("sequence_id")
        pair_id = sequence.get("pair_id")
        split = sequence.get("split")
        validation_role = sequence.get("validation_role", "positive_evaluation")
        event_type = sequence.get("evaluation_event")
        if not isinstance(sequence_id, str) or not sequence_id:
            raise ValueError("sequence_id must be a non-empty string")
        if sequence_id in sequence_ids:
            raise ValueError(f"duplicate CAVIAR sequence: {sequence_id}")
        sequence_ids.add(sequence_id)
        if not isinstance(pair_id, str) or not pair_id:
            raise ValueError(f"invalid pair_id for {sequence_id}")
        if split not in {"development", "holdout"}:
            raise ValueError(f"invalid split for {sequence_id}: {split}")
        if validation_role not in SUPPORTED_VALIDATION_ROLES:
            raise ValueError(
                f"invalid validation role for {sequence_id}: {validation_role}"
            )
        if split != "holdout" and validation_role == "negative_control":
            raise ValueError(
                f"negative control must be a holdout sequence: {sequence_id}"
            )
        if event_type not in SUPPORTED_EVENTS:
            raise ValueError(
                f"unsupported evaluation event for {sequence_id}: {event_type}"
            )
        pair_splits.setdefault(pair_id, set()).add(split)
        pair_events.setdefault(pair_id, set()).add(event_type)

        for asset_name in ("video", "annotation"):
            asset = sequence.get(asset_name)
            if not isinstance(asset, dict):
                raise ValueError(f"missing {asset_name} asset for {sequence_id}")
            relative_path = asset.get("relative_path")
            url = asset.get("url")
            checksum = asset.get("sha256")
            if (
                not isinstance(relative_path, str)
                or not relative_path
                or Path(relative_path).is_absolute()
                or ".." in Path(relative_path).parts
            ):
                raise ValueError(f"unsafe {asset_name} relative path for {sequence_id}")
            if not isinstance(url, str) or not url.startswith("https://"):
                raise ValueError(f"invalid {asset_name} URL for {sequence_id}")
            if checksum is not None and (
                not isinstance(checksum, str)
                or SHA256_PATTERN.fullmatch(checksum) is None
            ):
                raise ValueError(f"invalid {asset_name} SHA-256 for {sequence_id}")

    for pair_id, splits in pair_splits.items():
        if splits != {"development", "holdout"}:
            raise ValueError(
                f"pair {pair_id} must contain development and holdout sequences"
            )
        if len(pair_events[pair_id]) != 1:
            raise ValueError(f"pair {pair_id} mixes multiple event types")


def allows_empty_ground_truth(sequence: dict[str, Any]) -> bool:
    return sequence.get("validation_role", "positive_evaluation") == "negative_control"


def _require_holdout_audit(
    dataset_config: dict[str, Any],
    sequence: dict[str, Any],
    *,
    audit_name: str,
    audit_label: str,
) -> None:
    if sequence.get("split") != "holdout":
        return
    selection_policy = dataset_config.get("selection_policy")
    audit = (
        selection_policy.get(audit_name) if isinstance(selection_policy, dict) else None
    )
    status = audit.get(sequence.get("sequence_id")) if isinstance(audit, dict) else None
    expected = (
        "pass_negative_control" if allows_empty_ground_truth(sequence) else "pass"
    )
    if status not in APPROVED_AUDIT_STATUSES or status != expected:
        raise ValueError(
            f"holdout {audit_label} is not approved for "
            f"{sequence.get('sequence_id')}: {status}"
        )


def require_holdout_semantic_audit(
    dataset_config: dict[str, Any], sequence: dict[str, Any]
) -> None:
    _require_holdout_audit(
        dataset_config,
        sequence,
        audit_name="semantic_audit",
        audit_label="semantic audit",
    )


def require_holdout_truth_audit(
    dataset_config: dict[str, Any], sequence: dict[str, Any]
) -> None:
    _require_holdout_audit(
        dataset_config,
        sequence,
        audit_name="truth_audit",
        audit_label="truth audit",
    )


def _normalized(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1


def _validate_roi(value: Any, pair_id: str) -> None:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or not all(_normalized(item) for item in value)
    ):
        raise ValueError(f"rule {pair_id} requires normalized ROI [L,T,R,B]")
    left, top, right, bottom = value
    if left >= right or top >= bottom:
        raise ValueError(f"rule {pair_id} has an empty ROI")


def _validate_line(value: Any, pair_id: str) -> None:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or not all(_normalized(item) for item in value)
    ):
        raise ValueError(f"rule {pair_id} requires normalized line [X1,Y1,X2,Y2]")
    x1, y1, x2, y2 = value
    if math.hypot(x2 - x1, y2 - y1) <= GEOMETRY_EPSILON:
        raise ValueError(f"rule {pair_id} has a degenerate line")


def validate_rules_config(
    config: dict[str, Any],
    dataset_config: dict[str, Any],
    *,
    require_frozen: bool,
) -> None:
    if config.get("schema_version") != 1:
        raise ValueError("CAVIAR rules config requires schema_version=1")
    status = config.get("status")
    if status not in {"pending_human_review", "frozen"}:
        raise ValueError(f"unsupported CAVIAR review status: {status}")
    if require_frozen and status != "frozen":
        raise ValueError("CAVIAR rules are not frozen after human review")
    if status == "frozen":
        if not isinstance(config.get("reviewer"), str) or not config["reviewer"]:
            raise ValueError("frozen CAVIAR rules require a reviewer")
        for field in ("reviewed_at_utc", "frozen_at_utc"):
            if not isinstance(config.get(field), str) or not config[field]:
                raise ValueError(f"frozen CAVIAR rules require {field}")

    matching = config.get("matching_policy")
    if not isinstance(matching, dict):
        raise ValueError("matching_policy is missing")
    if (
        not isinstance(matching.get("frame_tolerance"), int)
        or matching["frame_tolerance"] < 0
    ):
        raise ValueError("frame_tolerance must be a nonnegative integer")
    anchor_tolerance = matching.get("anchor_distance_tolerance")
    if (
        not isinstance(anchor_tolerance, (int, float))
        or not math.isfinite(anchor_tolerance)
        or anchor_tolerance < 0
    ):
        raise ValueError("anchor_distance_tolerance must be nonnegative")
    for field in ("minimum_holdout_precision", "minimum_holdout_recall"):
        if not _normalized(matching.get(field)):
            raise ValueError(f"{field} must be between zero and one")

    expected_pairs = {
        sequence["pair_id"]: sequence["evaluation_event"]
        for sequence in dataset_config["sequences"]
    }
    rules = config.get("rules")
    if not isinstance(rules, list):
        raise ValueError("rules must be a list")
    rules_by_pair: dict[str, dict[str, Any]] = {}
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("every rule must be an object")
        pair_id = rule.get("pair_id")
        if pair_id in rules_by_pair:
            raise ValueError(f"duplicate rule pair: {pair_id}")
        if pair_id not in expected_pairs:
            raise ValueError(f"rule references an unknown pair: {pair_id}")
        event_type = rule.get("event_type")
        if event_type != expected_pairs[pair_id]:
            raise ValueError(f"rule {pair_id} has the wrong event type")
        rules_by_pair[pair_id] = rule

        if status != "frozen" and not require_frozen:
            continue
        if event_type == "line_crossing":
            _validate_line(rule.get("line"), pair_id)
            if rule.get("direction") not in {
                "any",
                "negative-to-positive",
                "positive-to-negative",
            }:
                raise ValueError(f"rule {pair_id} has an invalid direction")
        else:
            _validate_roi(rule.get("roi"), pair_id)
        if event_type == "dwell":
            dwell_seconds = rule.get("dwell_seconds")
            if (
                not isinstance(dwell_seconds, (int, float))
                or not math.isfinite(dwell_seconds)
                or dwell_seconds <= 0
            ):
                raise ValueError(f"rule {pair_id} requires dwell_seconds > 0")

    if set(rules_by_pair) != set(expected_pairs):
        missing = sorted(set(expected_pairs) - set(rules_by_pair))
        raise ValueError("missing rules for pairs: " + ", ".join(missing))


def rules_by_pair(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {rule["pair_id"]: rule for rule in config["rules"]}


def sequence_by_id(config: dict[str, Any], sequence_id: str) -> dict[str, Any]:
    for sequence in config["sequences"]:
        if sequence["sequence_id"] == sequence_id:
            return sequence
    raise ValueError(f"unknown CAVIAR sequence: {sequence_id}")


def read_ground_truth_frames(
    path: Path,
    *,
    frame_width: int,
    frame_height: int,
) -> tuple[str, list[GroundTruthFrame]]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise ValueError(f"invalid CAVIAR annotation XML: {path}: {error}") from error
    if root.tag != "dataset":
        raise ValueError(f"unexpected CAVIAR XML root: {root.tag}")
    dataset_name = root.get("name", "")
    if not dataset_name:
        raise ValueError(f"CAVIAR XML has no dataset name: {path}")

    frames: list[GroundTruthFrame] = []
    previous_frame = -1
    for frame_element in root.findall("frame"):
        try:
            frame_number = int(frame_element.attrib["number"])
        except (KeyError, ValueError) as error:
            raise ValueError(f"invalid frame number in {path}") from error
        if frame_number <= previous_frame:
            raise ValueError(
                f"CAVIAR frame numbers are not strictly increasing: {path}"
            )
        previous_frame = frame_number

        tracks: list[GroundTruthTrack] = []
        object_list = frame_element.find("objectlist")
        if object_list is not None:
            for object_element in object_list.findall("object"):
                box = object_element.find("box")
                if box is None:
                    raise ValueError(
                        f"object without bounding box in {path}, frame {frame_number}"
                    )
                try:
                    track_id = int(object_element.attrib["id"])
                    center_x = float(box.attrib["xc"])
                    center_y = float(box.attrib["yc"])
                    height = float(box.attrib["h"])
                    width = float(box.attrib["w"])
                except (KeyError, ValueError) as error:
                    raise ValueError(
                        f"invalid object box in {path}, frame {frame_number}"
                    ) from error
                if width <= 0 or height <= 0:
                    raise ValueError(
                        f"nonpositive object box in {path}, frame {frame_number}"
                    )
                anchor_x = min(max(center_x / frame_width, 0.0), 1.0)
                anchor_y = min(max((center_y + height * 0.5) / frame_height, 0.0), 1.0)
                tracks.append(GroundTruthTrack(track_id, anchor_x, anchor_y))
        tracks.sort(key=lambda item: item.track_id)
        frames.append(GroundTruthFrame(frame_number, tuple(tracks)))
    if not frames:
        raise ValueError(f"CAVIAR XML has no frames: {path}")
    return dataset_name, frames


def _point_in_roi(point: tuple[float, float], roi: list[float]) -> bool:
    left, top, right, bottom = roi
    return left <= point[0] <= right and top <= point[1] <= bottom


def _update_occupancy(
    state: OccupancyState,
    inside: bool,
    confirmation_frames: int,
    pts_ns: int,
) -> str | None:
    if not state.has_candidate or state.candidate_inside != inside:
        state.has_candidate = True
        state.candidate_inside = inside
        state.candidate_count = 1
        state.candidate_since_ns = pts_ns
    else:
        state.candidate_count += 1
    if state.candidate_count < confirmation_frames:
        return None
    if not state.initialized:
        state.initialized = True
        state.stable_inside = inside
        return "entered" if inside else None
    if state.stable_inside == inside:
        return None
    state.stable_inside = inside
    return "entered" if inside else "exited"


def _cross(
    first: tuple[float, float],
    second: tuple[float, float],
    point: tuple[float, float],
) -> float:
    return (second[0] - first[0]) * (point[1] - first[1]) - (second[1] - first[1]) * (
        point[0] - first[0]
    )


def _signed_line_distance(
    start: tuple[float, float],
    end: tuple[float, float],
    point: tuple[float, float],
) -> float:
    return _cross(start, end, point) / math.hypot(end[0] - start[0], end[1] - start[1])


def _segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    rx = first_end[0] - first_start[0]
    ry = first_end[1] - first_start[1]
    sx = second_end[0] - second_start[0]
    sy = second_end[1] - second_start[1]
    denominator = rx * sy - ry * sx
    if abs(denominator) <= GEOMETRY_EPSILON:
        return False
    qpx = second_start[0] - first_start[0]
    qpy = second_start[1] - first_start[1]
    first_t = (qpx * sy - qpy * sx) / denominator
    second_t = (qpx * ry - qpy * rx) / denominator
    return (
        -GEOMETRY_EPSILON <= first_t <= 1.0 + GEOMETRY_EPSILON
        and -GEOMETRY_EPSILON <= second_t <= 1.0 + GEOMETRY_EPSILON
    )


def _make_event(
    sequence: dict[str, Any],
    event_type: str,
    track: GroundTruthTrack,
    frame_number: int,
    pts_ns: int,
    *,
    direction: str = "none",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "CAVIAR hand-labelled XML",
        "sequence_id": sequence["sequence_id"],
        "split": sequence["split"],
        "pair_id": sequence["pair_id"],
        "event_type": event_type,
        "rule_id": RULE_IDS[event_type],
        "ground_truth_track_id": track.track_id,
        "frame_sequence": frame_number,
        "pts_ns": pts_ns,
        "anchor": {"x": track.anchor_x, "y": track.anchor_y},
        "direction": direction,
    }


def generate_events(
    sequence: dict[str, Any],
    rule: dict[str, Any],
    frames: Iterable[GroundTruthFrame],
    *,
    frames_per_second: int,
) -> list[dict[str, Any]]:
    event_type = sequence["evaluation_event"]
    if event_type != rule["event_type"]:
        raise ValueError(f"rule type does not match sequence {sequence['sequence_id']}")
    events: list[dict[str, Any]] = []

    if event_type == "roi_intrusion":
        states: dict[int, OccupancyState] = {}
        for frame in frames:
            pts_ns = round(frame.number * 1_000_000_000 / frames_per_second)
            for track in frame.tracks:
                state = states.setdefault(track.track_id, OccupancyState())
                transition = _update_occupancy(
                    state,
                    _point_in_roi((track.anchor_x, track.anchor_y), rule["roi"]),
                    2,
                    pts_ns,
                )
                state.last_seen_sequence = frame.number
                state.last_seen_pts_ns = pts_ns
                if transition == "entered":
                    events.append(
                        _make_event(sequence, event_type, track, frame.number, pts_ns)
                    )
            states = {
                track_id: state
                for track_id, state in states.items()
                if frame.number - state.last_seen_sequence <= 300
            }
        return events

    if event_type == "line_crossing":
        states: dict[int, LineState] = {}
        x1, y1, x2, y2 = rule["line"]
        line_start = (x1, y1)
        line_end = (x2, y2)
        configured_direction = rule["direction"]
        for frame in frames:
            pts_ns = round(frame.number * 1_000_000_000 / frames_per_second)
            for track in frame.tracks:
                point = (track.anchor_x, track.anchor_y)
                state = states.setdefault(track.track_id, LineState())
                state.last_seen_sequence = frame.number
                distance = _signed_line_distance(line_start, line_end, point)
                side = 1 if distance > 0.01 else (-1 if distance < -0.01 else 0)
                if side == 0:
                    continue
                if not state.has_candidate or state.candidate_side != side:
                    state.has_candidate = True
                    state.candidate_side = side
                    state.candidate_count = 1
                else:
                    state.candidate_count += 1
                if state.candidate_count < 1:
                    continue
                if not state.has_stable_side:
                    state.has_stable_side = True
                    state.stable_side = side
                    state.stable_point = point
                    continue
                if state.stable_side == side:
                    state.stable_point = point
                    continue

                previous_side = state.stable_side
                previous_point = state.stable_point
                state.stable_side = side
                state.stable_point = point
                direction = (
                    "negative_to_positive"
                    if previous_side < side
                    else "positive_to_negative"
                )
                allowed = (
                    configured_direction == "any"
                    or configured_direction.replace("-", "_") == direction
                )
                if allowed and _segments_intersect(
                    previous_point, point, line_start, line_end
                ):
                    events.append(
                        _make_event(
                            sequence,
                            event_type,
                            track,
                            frame.number,
                            pts_ns,
                            direction=direction,
                        )
                    )
            states = {
                track_id: state
                for track_id, state in states.items()
                if frame.number - state.last_seen_sequence <= 300
            }
        return events

    states: dict[int, DwellState] = {}
    dwell_time_ns = round(rule["dwell_seconds"] * 1_000_000_000)
    for frame in frames:
        pts_ns = round(frame.number * 1_000_000_000 / frames_per_second)
        for track in frame.tracks:
            state = states.setdefault(
                track.track_id, DwellState(occupancy=OccupancyState())
            )
            if (
                state.occupancy.initialized
                and frame.number > state.last_seen_sequence + 1
                and frame.number - state.last_seen_sequence - 1 > 3
            ):
                state = DwellState(occupancy=OccupancyState())
                states[track.track_id] = state
            if (
                state.occupancy.initialized
                and pts_ns < state.occupancy.last_seen_pts_ns
            ):
                state = DwellState(occupancy=OccupancyState())
                states[track.track_id] = state

            transition = _update_occupancy(
                state.occupancy,
                _point_in_roi((track.anchor_x, track.anchor_y), rule["roi"]),
                2,
                pts_ns,
            )
            state.last_seen_sequence = frame.number
            state.occupancy.last_seen_sequence = frame.number
            state.occupancy.last_seen_pts_ns = pts_ns
            if transition == "entered":
                state.entered_at_ns = state.occupancy.candidate_since_ns
                state.dwell_emitted = False
            elif transition == "exited":
                state.entered_at_ns = 0
                state.dwell_emitted = False
            if (
                state.occupancy.initialized
                and state.occupancy.stable_inside
                and not state.dwell_emitted
                and pts_ns - state.entered_at_ns >= dwell_time_ns
            ):
                events.append(
                    _make_event(sequence, event_type, track, frame.number, pts_ns)
                )
                state.dwell_emitted = True
        states = {
            track_id: state
            for track_id, state in states.items()
            if frame.number - state.last_seen_sequence <= 300
        }
    return events


def runtime_rule_arguments(rule: dict[str, Any]) -> list[str]:
    event_type = rule["event_type"]
    if event_type == "line_crossing":
        return [
            "--event-line",
            *(str(value) for value in rule["line"]),
            "--event-line-direction",
            rule["direction"],
        ]
    arguments = ["--event-roi", *(str(value) for value in rule["roi"])]
    if event_type == "dwell":
        arguments.extend(["--event-dwell-seconds", str(rule["dwell_seconds"])])
    return arguments


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read JSONL file: {path}: {error}") from error
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"invalid JSONL record at {path}:{line_number}: {error}"
            ) from error
        if not isinstance(record, dict):
            raise ValueError(f"JSONL record must be an object at {path}:{line_number}")
        records.append(record)
    return records
