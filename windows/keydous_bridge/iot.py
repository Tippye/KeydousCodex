"""Official IoT gRPC-Web transport, limited to reviewed NJ98 operations.

Protocol evidence: docs/protocol-research.md. This is not a general HID proxy.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import threading
import time
import urllib.request

from .models import profile_for
from .proto import check_trailer, decode, field, first, frame, read_frame, signed32

BASE_URL = "http://127.0.0.1:3814/driver.DriverGrpc/"
# Final NJ98 constants after mD overrides the generic base class.
# 0x04/0x84 are report-rate commands on NJ98 and must never be used for RGB.
NJ98_SET_LED = 0x07
NJ98_GET_LED = 0x87


@dataclass
class Device:
    path: str
    identifier: int
    vid: int
    pid: int
    connection: str
    online: bool
    battery: int | None = None
    dangle_type: int = 0

    @property
    def key(self) -> str:
        return hashlib.sha256(f"{self.path}|{self.identifier}".encode()).hexdigest()[:16]

    @property
    def profile(self) -> dict:
        return profile_for(self.vid, self.pid, self.identifier)

    def public(self) -> dict:
        profile = self.profile
        writable = self.connection == "USB" and self.online and not self.dangle_type
        return {"key": self.key, "id": self.identifier, "vid": self.vid, "pid": self.pid,
                "name": profile["name"], "connection": self.connection, "online": self.online,
                "battery": self.battery,
                "capabilities": {"upload": writable and profile["upload"],
                                 "rgb": writable and profile["rgb"],
                                 "mapping": writable and profile.get("mapping", False),
                                 "native_overlay": None, "dynamic_screen": False}}


def _battery(value) -> int | None:
    return value if isinstance(value, int) and 0 <= value <= 100 else None


def parse_devices(payload: bytes) -> tuple[int, list[Device]]:
    message = decode(payload)
    result = []
    for wrapped in message.get(1, []):
        wrapper = decode(wrapped)
        raw = first(wrapper, 1)
        if raw is not None:
            item = decode(raw)
            if first(item, 1, 0) != 0 or not first(item, 4, 0):
                continue  # Bootloaders and raw-HID duplicate endpoints are not keyboards.
            identifier = signed32(first(item, 4))
            path = first(item, 3, b"").decode("utf-8", errors="strict")
            is24 = bool(first(item, 2, 0))
            # Absence of battery is deliberately not converted to the proto default 0.
            result.append(Device(path, identifier, first(item, 7, 0), first(item, 8, 0),
                                 "2.4G" if is24 else ("无线（通道未知）" if identifier < 0 else "USB"),
                                 bool(first(item, 6, 0)), _battery(first(item, 5))))
        elif first(wrapper, 2) is not None:
            receiver = decode(first(wrapper, 2))
            identifier = first(receiver, 5, 0)
            if not identifier:
                continue
            # Receiver status is not a validated write route. Preserve discovery only.
            status = decode(first(receiver, 1, b""))
            nested = decode(first(status, 2, b""))
            result.append(Device(first(receiver, 3, b"").decode("utf-8"), -abs(identifier),
                                 first(receiver, 7, 0), first(receiver, 8, 0), "2.4G",
                                 bool(first(nested, 2, 0)), _battery(first(nested, 1)), 1))
    return first(message, 2, 0), result


class IoTClient:
    def __init__(self, timeout: float = 3.0):
        self.timeout = timeout
        self.lock = threading.RLock()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _open(self, method: str, payload: bytes = b"", timeout: float | None = None):
        request = urllib.request.Request(BASE_URL + method, data=frame(payload), headers={
            "Content-Type": "application/grpc-web+proto", "Accept": "application/grpc-web+proto",
            "X-Grpc-Web": "1",
        })
        return self.opener.open(request, timeout=self.timeout if timeout is None else min(self.timeout, timeout))

    def _rpc(self, method: str, payload: bytes = b"", timeout: float | None = None) -> bytes:
        with self._open(method, payload, timeout) as response:
            messages = []
            for _ in range(8):
                kind, data = read_frame(response)
                if kind == 128:
                    check_trailer(data)
                    if len(messages) != 1:
                        raise OSError("Unexpected IoT response count")
                    return messages[0]
                messages.append(data)
        raise OSError("IoT response missing final status")

    def discover(self) -> list[Device]:
        with self.lock, self._open("watchDevList") as response:
            for _ in range(8):
                kind, data = read_frame(response)
                if kind == 128:
                    check_trailer(data)
                    break
                change, devices = parse_devices(data)
                if change == 0:
                    return devices
        raise OSError("IoT did not provide initial device list")

    def _send(self, device: Device, message: bytes, checksum: int = 0, timeout: float | None = None) -> None:
        payload = field(1, device.path) + field(2, message) + field(3, checksum) + field(4, device.dangle_type)
        result = decode(self._rpc("sendMsg", payload, timeout))
        error = first(result, 1, b"")
        if error:
            raise OSError(error.decode("utf-8", errors="replace"))

    def _read(self, device: Device, timeout: float | None = None) -> bytes:
        result = decode(self._rpc("readMsg", field(1, device.path), timeout))
        error = first(result, 1, b"")
        if error:
            raise OSError(error.decode("utf-8", errors="replace"))
        return first(result, 2, b"")

    @staticmethod
    def _require(device: Device, capability: str) -> None:
        if not device.public()["capabilities"].get(capability):
            raise ValueError("此连接/型号尚未验证该写入能力，请使用 NJ98 USB 连接")

    def read_rgb(self, device: Device) -> bytes:
        self._require(device, "rgb")
        with self.lock:
            self._send(device, bytes([NJ98_GET_LED]) + bytes(63))
            time.sleep(0.1)
            data = self._read(device)
            if len(data) < 8 or data[0] != NJ98_GET_LED:
                raise OSError("无法取得可恢复的原始 RGB 设置")
            return data[1:8]

    def read_key_matrix(self, device: Device, bank: str, cancelled=None) -> bytes:
        self._require(device, "mapping")
        if bank not in {"normal", "fn"}:
            raise ValueError("未知按键层")
        with self.lock:
            result = bytearray()
            deadline = time.monotonic() + 15
            for block in range(8):
                if cancelled is not None and cancelled.is_set():
                    raise InterruptedError("改键操作已停止，恢复记录已保留")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("读取按键矩阵超时")
                self._send(device, bytes([0x89 if bank == "normal" else 0x90, 0, block]) + bytes(61), timeout=remaining)
                time.sleep(0.05)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("读取按键矩阵超时")
                raw = self._read(device, timeout=remaining)
                if len(raw) != 64:
                    raise OSError("按键矩阵块必须完整返回 64 字节，已停止操作")
                result.extend(raw)  # Official parser keeps the full response, no echoed header.
            return bytes(result)

    def write_key(self, device: Device, bank: str, slot: int, action: bytes) -> None:
        self._require(device, "mapping")
        if bank not in {"normal", "fn"} or type(slot) is not int or not 0 <= slot < 128 or len(action) != 4:
            raise ValueError("无效单键配置")
        with self.lock:
            packet = bytearray(64)
            packet[:3] = bytes([0x13 if bank == "normal" else 0x15, 0, slot])
            packet[8:12] = action
            primary = None
            try:
                self._send(device, bytes(packet), checksum=0)
                self._rpc("changeWirelessLoopStatus", field(1, 1))
                time.sleep(0.5)
            except Exception as exc:
                primary = exc
                raise
            finally:
                try:
                    self._rpc("changeWirelessLoopStatus", field(1, 0))
                except Exception as exc:
                    raise OSError("单键操作后恢复驱动轮询失败，请重启 IoT；恢复记录已保留") from (primary or exc)

    def write_rgb(self, device: Device, settings: bytes) -> None:
        self._require(device, "rgb")
        if len(settings) != 7:
            raise ValueError("RGB 设置长度错误")
        with self.lock:
            time.sleep(0.5)
            self._send(device, bytes([NJ98_SET_LED]) + settings + bytes(56), checksum=1)
            time.sleep(0.5)

    def upload(self, device: Device, frames: list[bytes], size: tuple[int, int], slot: int,
               delay: int, progress, cancelled: threading.Event) -> None:
        self._require(device, "upload")
        if size != (160, 80) or not 1 <= slot <= 3 or not 2 <= len(frames) <= 50:
            raise ValueError("NJ98 动画需要 160×80、2–50 帧、动画槽 1–3")
        if not 1 <= delay <= 255 or any(len(image) != 160 * 80 * 2 for image in frames):
            raise ValueError("无效图像长度或帧延迟")
        total = len(frames) * ((len(frames[0]) + 55) // 56)
        completed = 0
        with self.lock:
            if cancelled.is_set():
                raise InterruptedError("上传已取消")
            # This driver-global pause mirrors the official uploader; always resume it.
            primary_error = None
            try:
                self._rpc("changeWirelessLoopStatus", field(1, 1))
                prepare = bytearray(19)
                prepare[0] = 0xA5
                prepare[2] = len(frames)
                prepare[3] = delay
                prepare[4:6] = len(frames[0]).to_bytes(4, "little")[:2]
                prepare[16:18] = len(frames[0]).to_bytes(4, "little")[2:]
                prepare[10], prepare[11], prepare[18] = 160, 80, slot - 1
                deadline = time.monotonic() + 12
                ready = False
                for _ in range(10):
                    if cancelled.is_set():
                        raise InterruptedError("上传已取消；选定动画槽可能不完整，可重新上传恢复")
                    if time.monotonic() > deadline:
                        break
                    self._send(device, bytes(prepare), timeout=max(0.01, deadline - time.monotonic()))
                    time.sleep(0.1)
                    if time.monotonic() >= deadline:
                        break
                    answer = self._read(device, timeout=max(0.01, deadline - time.monotonic()))
                    if time.monotonic() >= deadline:
                        break
                    if len(answer) >= 2 and answer[0] == 0xA5 and answer[1] == 1:
                        ready = True
                        break
                    if len(answer) >= 2 and answer[0] == 0xA5 and answer[1] not in (0, 1):
                        raise OSError("屏幕拒绝准备上传，请确认已开启屏幕")
                    time.sleep(0.1)
                if not ready:
                    raise TimeoutError("屏幕未确认准备完成，已停止上传")
                time.sleep(0.1)
                if time.monotonic() >= deadline:
                    raise TimeoutError("屏幕准备超时，已停止上传")
                for frame_index, image in enumerate(frames):
                    for offset in range(0, len(image), 56):
                        if cancelled.is_set():
                            raise InterruptedError("上传已取消；选定动画槽可能不完整，可重新上传恢复")
                        block = image[offset:offset + 56]
                        packet = bytearray(64)
                        packet[:4] = bytes([0x25, frame_index, len(frames), delay])
                        packet[4:6] = (offset // 56).to_bytes(2, "little")
                        packet[6] = len(block)
                        packet[8:8 + len(block)] = block
                        time.sleep(0.003)
                        self._send(device, bytes(packet))
                        completed += 1
                        progress(completed / total)
                time.sleep(0.5)
            except Exception as exc:
                primary_error = exc
                raise
            finally:
                try:
                    self._rpc("changeWirelessLoopStatus", field(1, 0))
                except Exception as restore_error:
                    detail = "驱动无线轮询恢复失败，请重启官方 IoT 驱动：" + str(restore_error)
                    if primary_error is not None:
                        raise OSError(str(primary_error) + "；" + detail) from primary_error
                    raise OSError(detail) from restore_error
