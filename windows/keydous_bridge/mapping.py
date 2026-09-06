"""NJ98 firmware mappings with full preimages and explicit, verified restoration.

The device's Fn layer is not Apple's host-side Fn/Globe. See protocol evidence
in docs/nj98-mapping-research.md. Caller owns the application mutation lock.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading

BANKS = ("normal", "fn")
FN = bytes([10, 1, 0, 0])
# Physical matrix identities from VN resolved against IHe, not screen positions.
ROWS = (
    (("Esc",0),("F1",12),("F2",18),("F3",24),("F4",30),("F5",36),("F6",42),("F7",48),("F8",54),("F9",60),("F10",66),("F11",72),("F12",78),("Delete",84),("Calculator",90),("旋钮左",109),("旋钮按下",102),("旋钮右",110)),
    (("`",1),("1",7),("2",13),("3",19),("4",25),("5",31),("6",37),("7",43),("8",49),("9",55),("0",61),("-",67),("=",73),("Backspace",79),("Page Up",85),("Num Lock",91),("Num /",97),("Num *",103),("Num -",105)),
    (("Tab",2),("Q",8),("W",14),("E",20),("R",26),("T",32),("Y",38),("U",44),("I",50),("O",56),("P",62),("[",68),("]",74),("\\",80),("Page Down",86),("Num 7",92),("Num 8",98),("Num 9",104),("Num +",106)),
    (("Caps Lock",3),("A",9),("S",15),("D",21),("F",27),("G",33),("H",39),("J",45),("K",51),("L",57),(";",63),("'",69),("Enter",81),("Num 4",87),("Num 5",93),("Num 6",99)),
    (("Left Shift",4),("Z",16),("X",22),("C",28),("V",34),("B",40),("N",46),("M",52),(",",58),(".",64),("/",70),("Right Shift",76),("↑",82),("Num 1",88),("Num 2",94),("Num 3",100),("Num Enter",107)),
    (("Left Ctrl",5),("Win / Command",17),("Left Alt",23),("Space",41),("Right Alt",59),("Fn（键盘层）",65),("Right Ctrl",71),("←",77),("↓",83),("→",89),("Num 0",95),("Num .",101)),
)
CONTROLS = [{"label": label, "slot": slot, "row": row} for row, keys in enumerate(ROWS) for label, slot in keys]
SLOTS = frozenset(item["slot"] for item in CONTROLS)
KEY_NAMES = {**{4+i: chr(65+i) for i in range(26)}, **{30+i: str((i+1) % 10) for i in range(10)},
             **dict(enumerate(("Enter", "Esc", "Backspace", "Tab", "Space", "-", "=", "[", "]", "\\", "非 US #", ";", "'", "`", ",", ".", "/", "Caps Lock"), 40)),
             **{58+i: f"F{i+1}" for i in range(12)},
             **dict(enumerate(("Print Screen", "Scroll Lock", "Pause", "Insert", "Home", "Page Up", "Delete", "End", "Page Down", "→", "←", "↓", "↑", "Num Lock", "Num /", "Num *", "Num -", "Num +", "Num Enter", "Num 1", "Num 2", "Num 3", "Num 4", "Num 5", "Num 6", "Num 7", "Num 8", "Num 9", "Num 0", "Num ."), 70)),
             **dict(enumerate(("Left Ctrl", "Left Shift", "Left Alt", "Left Win / Command", "Right Ctrl", "Right Shift", "Right Alt", "Right Win / Command"), 224))}
MEDIA = {"mute": ("静音",226), "volume-down": ("音量减",234), "volume-up": ("音量加",233),
         "play": ("播放/暂停",205), "previous": ("上一曲",182), "next": ("下一曲",181),
         "brightness-down": ("亮度减",112), "brightness-up": ("亮度加",111), "calculator": ("计算器",402)}
ACTIONS = {f"key:{key}": (label, bytes([0,0,key,0])) for key,label in KEY_NAMES.items()}
ACTIONS.update({f"media:{key}": (label, bytes([3,0,value & 255,value >> 8])) for key,(label,value) in MEDIA.items()})
ACTIONS.update({"firmware-fn": ("Fn（键盘内部层）", FN), "disabled": ("禁用", bytes(4))})


def action_token(action: str) -> bytes:
    if not isinstance(action, str) or len(action) > 50:
        raise ValueError("无效按键动作")
    if action in ACTIONS:
        return ACTIONS[action][1]
    parts = action.split(":")
    if len(parts) == 3 and parts[0] == "combo":
        try:
            modifier, key = map(int, parts[1:])
        except ValueError:
            raise ValueError("无效组合键") from None
        if modifier in {224,225,226,227} and key in KEY_NAMES and key < 224:
            return bytes([0, modifier, key, 0])
    raise ValueError("此动作尚未支持")


def label_for(raw: bytes) -> str:
    for label, token in ACTIONS.values():
        if raw == token:
            return label
    if raw[0] == 0 and raw[1] in {224,225,226,227} and raw[2] in KEY_NAMES and raw[3] == 0:
        return KEY_NAMES[raw[1]] + " + " + KEY_NAMES[raw[2]]
    return "原始动作 " + raw.hex(" ")


def revision(device_key: str, matrices: dict[str, bytes]) -> str:
    return hashlib.sha256(device_key.encode() + matrices["normal"] + matrices["fn"]).hexdigest()


class MappingService:
    def __init__(self, client, directory: Path, cancelled: threading.Event):
        self.client = client
        self.path = directory / "mapping-recovery.json"
        self.cancelled = cancelled

    @staticmethod
    def _identity(device):
        return {"path":device.path, "vid":device.vid, "pid":device.pid,
                "id":device.identifier, "connection":device.connection}

    def _read(self, device):
        result = {bank: self.client.read_key_matrix(device, bank, self.cancelled) for bank in BANKS}
        if any(len(value) != 512 for value in result.values()):
            raise OSError("不能用不完整矩阵备份或改键")
        return result

    def _load(self):
        if not self.path.exists():
            return None
        try:
            if self.path.stat().st_size > 16384:
                raise ValueError()
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError()
            digest = data.pop("sha256")
            if digest != hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest():
                raise ValueError()
            if data["version"] != 1 or type(data["pending"]) is not bool:
                raise ValueError()
            for kind in ("original", "expected", "previous"):
                for bank in BANKS:
                    if len(bytes.fromhex(data[kind][bank])) != 512:
                        raise ValueError()
            if not isinstance(data["device_key"], str) or len(data["device_key"]) != 16:
                raise ValueError()
            if not isinstance(data["identity"], dict) or set(data["identity"]) != {"path","vid","pid","id","connection"}:
                raise ValueError()
            return data
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError("改键恢复记录损坏；请保留文件，不能覆盖或继续写入") from None

    def _save(self, data):
        temporary = self.path.with_suffix(".tmp")
        signed = dict(data)
        signed["sha256"] = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(signed, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def _public(self, device, matrices):
        record = self._load()
        return {"device_key": device.key, "revision": revision(device.key, matrices),
                **{bank: [list(raw[i:i+4]) for i in range(0,512,4)] for bank,raw in matrices.items()},
                **{bank+"_labels": [label_for(raw[i:i+4]) for i in range(0,512,4)] for bank,raw in matrices.items()},
                "controls": CONTROLS, "actions": [{"id": key, "label": value[0]} for key,value in ACTIONS.items()],
                "recovery": record is not None and record["device_key"] == device.key,
                "pending": bool(record and record["pending"])}

    def read(self, device):
        with self.client.lock:
            return self._public(device, self._read(device))

    def apply(self, device, request: dict):
        if set(request) != {"revision", "bank", "slot", "action"}:
            raise ValueError("改键需要读取版本、按键层、位置和动作")
        bank, slot = request["bank"], request["slot"]
        if bank not in BANKS or type(slot) is not int or slot not in SLOTS:
            raise ValueError("请选择 NJ98 可见按键和有效层")
        token = action_token(request["action"])
        with self.client.lock:
            current = self._read(device)
            if request["revision"] != revision(device.key, current):
                raise ValueError("键盘配置已变化，请重新读取后再应用")
            record = self._load()
            if record and (record["device_key"] != device.key or record["identity"] != self._identity(device) or record["pending"]):
                raise ValueError("存在其他设备或未完成的恢复记录，请先恢复")
            if record and any(bytes.fromhex(record["expected"][b]) != current[b] for b in BANKS):
                raise ValueError("键盘被其他工具修改；原始恢复记录已保留，请先处理冲突")
            target = dict(current)
            target[bank] = current[bank][:slot*4] + token + current[bank][slot*4+4:]
            if target == current:
                return self._public(device, current)
            if bank == "normal" and FN not in [target[bank][i:i+4] for i in range(0,512,4)]:
                raise ValueError("请至少保留一个键盘 Fn 键，以便使用键盘内部功能")
            before = {b: raw.hex() for b,raw in current.items()}
            record = record or {"version":1, "device_key":device.key, "identity":self._identity(device), "original":before}
            record.update(previous=before, expected={b: raw.hex() for b,raw in target.items()}, pending=True)
            self._save(record)  # Persist before the first possibly successful hardware write.
            if self.cancelled.is_set():
                raise InterruptedError("操作已停止，恢复记录已保留")
            self.client.write_key(device, bank, slot, token)
            actual = self._read(device)
            if actual != target:
                raise OSError("改键读回不一致，已停止；请使用恢复原始按键配置")
            record["pending"] = False
            self._save(record)
            return self._public(device, actual)

    def restore(self, device):
        with self.client.lock:
            record = self._load()
            if not record or record["device_key"] != device.key or record["identity"] != self._identity(device):
                raise ValueError("当前设备没有匹配的原始备份")
            current = self._read(device)
            original = {b: bytes.fromhex(record["original"][b]) for b in BANKS}
            expected = {b: bytes.fromhex(record["expected"][b]) for b in BANKS}
            previous = {b: bytes.fromhex(record["previous"][b]) for b in BANKS}
            changes = []
            for bank in BANKS:
                for slot in range(128):
                    part = slice(slot*4,slot*4+4)
                    raw = current[bank][part]
                    permitted = {original[bank][part], expected[bank][part]}
                    if record["pending"]:
                        permitted.add(previous[bank][part])
                    if raw not in permitted:
                        raise ValueError("检测到备份之外的按键变化，恢复已中止以保留其他修改")
                    if raw != original[bank][part]:
                        changes.append((bank,slot,original[bank][part]))
            record["pending"] = True
            self._save(record)
            for bank,slot,raw in changes:
                if self.cancelled.is_set():
                    raise InterruptedError("恢复已停止；已保留备份，可下次继续")
                self.client.write_key(device, bank, slot, raw)
            actual = self._read(device)
            if actual != original:
                raise OSError("恢复读回不一致，备份已保留")
            self.path.unlink()
            return self._public(device, actual)
