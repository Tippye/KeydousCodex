"""Metadata-only state projection for explicitly selected Codex JSONL files."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import time

STATES = {"idle", "thinking", "working", "waiting", "success", "error", "unknown"}
MAX_LINE = 1024 * 1024
STALE_SECONDS = 180


class EventState:
    def __init__(self, source: str):
        self.source = source
        self.state = "unknown"
        self.reason = "等待所选任务的新事件"
        self.observed_at = 0.0
        self.active_turn = None
        self.active = False
        self.terminal_at = 0.0

    def _set(self, state: str, reason: str, timestamp: float):
        self.state, self.reason, self.observed_at = state, reason, timestamp

    def accept(self, event: dict, now: float, bootstrap: bool = False):
        if not isinstance(event, dict):
            return
        timestamp = now
        raw_stamp = event.get("timestamp")
        if isinstance(raw_stamp, str):
            try:
                timestamp = datetime.fromisoformat(raw_stamp.replace("Z", "+00:00")).timestamp()
            except (ValueError, OverflowError):
                return
        if timestamp > now + 60 or timestamp < self.observed_at:
            return
        if self.source == "desktop":
            payload = event.get("payload")
            if event.get("type") != "event_msg" or not isinstance(payload, dict):
                return
            kind, turn = payload.get("type"), payload.get("turn_id")
            if kind == "task_started" and isinstance(turn, str) and turn:
                self.active_turn, self.active = turn, True
                self.terminal_at = 0
                self._set("working", "观察到桌面回合开始", timestamp)
            elif turn and turn == self.active_turn and self.active:
                if kind == "task_complete":
                    self.active = False
                    self.terminal_at = timestamp
                    self._set("idle" if bootstrap else "success", "桌面回合已结束（不等于目标已完成）", timestamp)
                elif kind == "item_completed":
                    item = payload.get("item")
                    activity = item.get("type") if isinstance(item, dict) else None
                    labels = {"Reasoning": "推理", "CommandExecution": "命令", "McpToolCall": "工具", "FileChange": "文件修改", "SubAgentActivity": "子任务"}
                    self._set("working", "回合进行中；最近完成" + labels.get(activity, "一项活动"), timestamp)
                elif kind == "turn_aborted":
                    self.active = False
                    self._set("unknown", "回合中断，结果未知", timestamp)
        elif self.source == "jsonl":
            kind = event.get("type")
            if kind == "turn.started":
                self.active = True
                self.terminal_at = 0
                self._set("thinking", "CLI 回合开始", timestamp)
            elif kind in {"turn.completed", "turn.failed"} and self.active:
                self.active = False
                self.terminal_at = timestamp
                state = "success" if kind == "turn.completed" else "error"
                self._set("idle" if bootstrap else state, "CLI 回合已结束" if state == "success" else "CLI 明确报告回合失败", timestamp)
            elif kind == "error":
                self.active = False
                self.terminal_at = timestamp
                self._set("idle" if bootstrap else "error", "CLI 明确报告错误", timestamp)
            elif kind in {"item.started", "item.updated", "item.completed"} and self.active:
                item = event.get("item")
                activity = item.get("type") if isinstance(item, dict) else None
                state = "thinking" if activity == "reasoning" else "working"
                self._set(state, "CLI 活动事件", timestamp)

    def snapshot(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        state, validity = self.state, "observed"
        reason = self.reason
        if not self.observed_at:
            validity = "unknown"
        elif self.active and now - self.observed_at > STALE_SECONDS:
            state, validity, reason = "unknown", "stale", "暂未收到新事件，无法判断是否等待输入"
        elif self.terminal_at and state in {"success", "error"} and now - self.terminal_at > 6:
            state, reason = "idle", "所选回合已结束"
        return {"state": state, "source": self.source, "source_detail": reason,
                "validity": validity, "observed_at": self.observed_at, "turn_id": self.active_turn}


class FileSource:
    def __init__(self, path: Path, source: str):
        self.path = path.resolve()
        if self.path.suffix.lower() != ".jsonl" or not self.path.is_file():
            raise ValueError("请选择存在的 .jsonl 任务文件")
        if source not in {"desktop", "jsonl"}:
            raise ValueError("未知文件事件格式")
        self.source = source
        self.state = EventState(source)
        self.position = 0
        self.identity = None
        self.buffer = b""
        self.dropping = False
        self.error = ""
        self._initialize()

    def _initialize(self):
        stat = self.path.stat()
        self.identity = (stat.st_dev, stat.st_ino)
        self.state = EventState(self.source)
        self.buffer = b""
        self.dropping = False
        start = max(0, stat.st_size - MAX_LINE)
        with self.path.open("rb") as stream:
            stream.seek(start)
            data = stream.read(MAX_LINE)
            self.position = stream.tell()
        if start:
            _, separator, data = data.partition(b"\n")
            if not separator:
                data = b""
                self.dropping = True
        self._consume(data, bootstrap=True, observed_at=min(time.time(), stat.st_mtime))

    def _consume(self, data: bytes, bootstrap: bool = False, observed_at=None):
        if self.dropping:
            _, separator, data = data.partition(b"\n")
            if not separator:
                return
            self.dropping = False
        combined = self.buffer + data
        lines = combined.split(b"\n")
        self.buffer = lines.pop()
        if len(self.buffer) > MAX_LINE:
            self.buffer = b""
            self.dropping = True
        for line in lines:
            if len(line) > MAX_LINE:
                continue
            try:
                event = json.loads(line)
                self.state.accept(event, time.time() if observed_at is None else observed_at, bootstrap)
            except (ValueError, TypeError, UnicodeError):
                continue

    def poll(self) -> dict:
        try:
            stat = self.path.stat()
            if (stat.st_dev, stat.st_ino) != self.identity or stat.st_size < self.position:
                self._initialize()
            else:
                with self.path.open("rb") as stream:
                    stream.seek(self.position)
                    # Bounded work, including when a large tool output was appended.
                    data = stream.read(MAX_LINE)
                    self.position = stream.tell()
                self._consume(data)
            self.error = ""
        except OSError:
            self.error = "所选任务文件不可读，等待恢复"
        result = self.state.snapshot()
        if self.error:
            result.update(state="unknown", validity="unknown", source_detail=self.error)
        return result


def recent_sessions(codex_home: Path) -> list[dict]:
    """List recent filenames only; do not open other tasks' conversation contents."""
    found = []
    now = datetime.now()
    for days in range(3):
        date = now - timedelta(days=days)
        directory = codex_home / "sessions" / date.strftime("%Y/%m/%d")
        try:
            for path in directory.glob("rollout-*.jsonl"):
                stat = path.stat()
                found.append({"path": str(path), "name": path.stem, "modified_at": stat.st_mtime})
        except OSError:
            continue
    return sorted(found, key=lambda item: item["modified_at"], reverse=True)[:40]
