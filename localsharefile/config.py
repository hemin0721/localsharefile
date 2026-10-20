"""配置文件读写：多共享目录（v2 格式）与旧版单目录配置自动迁移。"""
import json
import os
import re
import sys
from pathlib import Path

DEFAULTS = {
    "host": "0.0.0.0",          # 监听所有网卡，局域网内其他设备可访问
    "port": 8000,
    "directories": [],          # [{"name": 别名, "path": 服务器绝对路径}]，可在网页上动态增删
    "allow_upload": True,       # 是否允许网页上传文件
    "show_hidden": False,       # 是否显示隐藏文件（点开头）
    "token": "",                # 访问令牌，为空表示不启用口令校验
}


def config_dir() -> Path:
    """返回配置文件所在目录（平台感知）。"""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(base) / "LocalShareFile"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "LocalShareFile"
    return Path.home() / ".config" / "localsharefile"


def config_path() -> Path:
    return config_dir() / "config.json"


def normalize_directories(raw: list) -> list:
    """清洗目录列表：名称去非法字符并保证唯一，路径展开为绝对路径。"""
    result, used = [], set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path") or "").strip()
        if not raw_path:
            continue
        path = str(Path(raw_path).expanduser().resolve())
        name = str(item.get("name") or "").strip() or Path(path).name or "share"
        name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip() or "share"
        base, n = name, 1
        while name in used:
            n += 1
            name = f"{base} ({n})"
        used.add(name)
        if not any(d["path"] == path for d in result):
            result.append({"name": name, "path": path})
    return result


def load() -> dict:
    """读取配置并与默认值合并；自动把旧版单目录配置迁移为多目录格式。"""
    cfg = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    legacy_dir = None
    path = config_path()
    if path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            if isinstance(user_cfg, dict):
                for key in DEFAULTS:
                    if key in user_cfg:
                        cfg[key] = user_cfg[key]
                legacy_dir = user_cfg.get("directory")   # v0.1 旧字段
        except (OSError, ValueError) as exc:
            print(f"警告：配置文件损坏，使用默认配置（{exc}）")
    if not cfg["directories"] and legacy_dir:
        p = Path(str(legacy_dir)).expanduser()
        cfg["directories"] = [{"name": p.name or "share", "path": str(p.resolve())}]
    cfg["directories"] = normalize_directories(cfg["directories"])
    return cfg


def save(cfg: dict) -> Path:
    """将配置写入磁盘，返回配置文件路径。"""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {key: cfg.get(key, DEFAULTS[key]) for key in DEFAULTS}
    data["directories"] = normalize_directories(data["directories"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def add_directory(cfg: dict, name: str, path: str) -> tuple:
    """添加共享目录（就地更新 cfg），返回 (是否成功, 消息, 规范化后的目录列表)。"""
    raw = (path or "").strip()
    if not raw:
        return False, "路径不能为空", cfg["directories"]
    real = Path(raw).expanduser()
    if not real.is_dir():
        return False, f"服务器上不存在该目录：{real}", cfg["directories"]
    dirs = list(cfg["directories"])
    dirs.append({"name": (name or "").strip(), "path": str(real.resolve())})
    dirs = normalize_directories(dirs)
    cfg["directories"] = dirs
    return True, f"已添加共享目录「{dirs[-1]['name']}」", dirs


def remove_directory(cfg: dict, name: str) -> tuple:
    """按名称移除共享目录，返回 (是否成功, 消息)。"""
    before = len(cfg["directories"])
    cfg["directories"] = [d for d in cfg["directories"] if d["name"] != name]
    if len(cfg["directories"]) == before:
        return False, f"没有名为「{name}」的共享目录"
    return True, f"已移除共享目录「{name}」"
