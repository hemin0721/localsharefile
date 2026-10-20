"""开机自启动管理：Linux(systemd 用户服务) / Windows(启动文件夹) / macOS(LaunchAgent)。

提供 install() / uninstall() / status() 三个跨平台统一入口。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE_ID = "localsharefile"


def _python_gui() -> str:
    """返回无控制台窗口运行时的 Python 解释器路径（Windows 用 pythonw）。"""
    exe = Path(sys.executable)
    if sys.platform.startswith("win") and exe.name.lower() == "python.exe":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return str(exe)


def _run(cmd: list) -> "subprocess.CompletedProcess | None":
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None


# ---------------------------------------------------------------- Linux

def _linux_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"{SERVICE_ID}.service"


def _linux_install(cfg: dict) -> str:
    unit = _linux_unit_path()
    unit.parent.mkdir(parents=True, exist_ok=True)
    entry = shutil.which("localsharefile")
    run_cmd = entry if entry else f"{sys.executable} -m localsharefile"
    unit.write_text(
        "[Unit]\n"
        f"Description=LocalShareFile LAN file sharing service\n"
        "After=network.target\n"
        "\n[Service]\n"
        "Type=simple\n"
        f"ExecStart={run_cmd} run\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n[Install]\n"
        "WantedBy=default.target\n",
        encoding="utf-8",
    )
    _run(["systemctl", "--user", "daemon-reload"])
    r = _run(["systemctl", "--user", "enable", "--now", SERVICE_ID])
    if r is not None and r.returncode != 0:
        return f"服务文件已写入 {unit}，但 systemctl 启用失败：{r.stderr.strip()}"
    return f"已安装 systemd 用户服务并启用自启动：{unit}"


def _linux_uninstall() -> str:
    _run(["systemctl", "--user", "disable", "--now", SERVICE_ID])
    unit = _linux_unit_path()
    if unit.exists():
        unit.unlink()
        _run(["systemctl", "--user", "daemon-reload"])
        return f"已停止并移除 systemd 用户服务：{unit}"
    return "未发现已安装的自启动服务"


def _linux_status() -> str:
    r = _run(["systemctl", "--user", "is-active", SERVICE_ID])
    active = r.stdout.strip() if r and r.returncode == 0 else "inactive"
    installed = _linux_unit_path().exists()
    return f"自启动服务：{'已安装' if installed else '未安装'}，运行状态：{active}"


# ---------------------------------------------------------------- Windows

def _win_script_path() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" \
        / "Start Menu" / "Programs" / "Startup" / f"{SERVICE_ID}.bat"


def _win_install(cfg: dict) -> str:
    script = _win_script_path()
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        f'@echo off\r\n'
        f'start "LocalShareFile" /min "" "{_python_gui()}" -m localsharefile run\r\n',
        encoding="utf-8",
    )
    return f"已写入启动文件夹脚本（登录后自动运行）：{script}"


def _win_uninstall() -> str:
    script = _win_script_path()
    if script.exists():
        script.unlink()
        return f"已移除启动项：{script}"
    return "未发现已安装的自启动项"


def _win_status() -> str:
    installed = _win_script_path().exists()
    return f"自启动项：{'已安装（下次登录生效）' if installed else '未安装'}"


# ---------------------------------------------------------------- macOS

def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"com.{SERVICE_ID}.plist"


def _mac_install(cfg: dict) -> str:
    plist = _mac_plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        '<key>Label</key><string>com.localsharefile</string>\n'
        f'<key>ProgramArguments</key><array>\n'
        f'<string>{sys.executable}</string>\n'
        f'<string>-m</string><string>localsharefile</string><string>run</string>\n'
        '</array>\n'
        '<key>RunAtLoad</key><true/>\n'
        '<key>KeepAlive</key><false/>\n'
        '</dict></plist>\n',
        encoding="utf-8",
    )
    _run(["launchctl", "unload", str(plist)])
    _run(["launchctl", "load", str(plist)])
    return f"已安装 LaunchAgent 并加载：{plist}"


def _mac_uninstall() -> str:
    plist = _mac_plist_path()
    if plist.exists():
        _run(["launchctl", "unload", str(plist)])
        plist.unlink()
        return f"已卸载 LaunchAgent：{plist}"
    return "未发现已安装的 LaunchAgent"


def _mac_status() -> str:
    installed = _mac_plist_path().exists()
    return f"LaunchAgent：{'已安装（登录后自动运行）' if installed else '未安装'}"


# ---------------------------------------------------------------- 统一入口

def install(cfg: dict) -> str:
    if sys.platform.startswith("win"):
        return _win_install(cfg)
    if sys.platform == "darwin":
        return _mac_install(cfg)
    return _linux_install(cfg)


def uninstall() -> str:
    if sys.platform.startswith("win"):
        return _win_uninstall()
    if sys.platform == "darwin":
        return _mac_uninstall()
    return _linux_uninstall()


def status() -> str:
    if sys.platform.startswith("win"):
        return _win_status()
    if sys.platform == "darwin":
        return _mac_status()
    return _linux_status()
