"""Explicit device identities; a similar marketing name never grants writes."""
from __future__ import annotations

PROFILES = {
    (12625, 16405, 1021): {"name": "NJ98", "width": 160, "height": 80, "family": "yc500-nj98", "upload": True, "rgb": True},
    (12625, 16401, -2147484669): {"name": "NJ98 无线", "width": 160, "height": 80},
    (12625, 16405, 1259): {"name": "NJ98 CP", "width": 160, "height": 80},
    (12625, 16405, 1688): {"name": "NJ98 CP UK", "width": 160, "height": 80},
    (12625, 16405, 1863): {"name": "NJ98 CP 1030", "width": 160, "height": 80},
    (12625, 20482, 2956): {"name": "NJ98-V2"},
    (12625, 20482, 3873): {"name": "NJ98-V2-D"},
    (12625, 20527, 2576): {"name": "NJ98CP-V3"},
    (12625, 20528, 3496): {"name": "NJ98-CP V4"},
}
for identifier, region in zip(range(2000, 2005), ("DE", "IT", "UK", "FR", "ES")):
    PROFILES[(12625, 16405, identifier)] = {"name": f"NJ98 EP-{region}", "width": 160, "height": 80}


def profile_for(vid: int, pid: int, identifier: int) -> dict:
    profile = dict(PROFILES.get((vid, pid, identifier), {"name": f"未验证设备 {identifier}"}))
    profile.setdefault("upload", False)
    profile.setdefault("rgb", False)
    profile["mapping"] = (vid, pid, identifier) == (12625, 16405, 1021)
    profile["native_overlay"] = None
    profile["dynamic_screen"] = False
    return profile


def model_list() -> list[dict]:
    return [{**profile_for(*identity), "notes": "支持有线资源上传；原生状态层共存与实时切页尚未验证" if value.get("upload") else "已识别型号；硬件写入尚未验证"}
            for identity, value in PROFILES.items()]
