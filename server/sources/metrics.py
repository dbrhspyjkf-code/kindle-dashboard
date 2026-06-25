"""设备监控分发器:本机直读(local);推(push)模式由主服务的 API 端点接收,不在此处。

一份平台脚本两处复用:
  - 本机直读:本地 subprocess 跑对应脚本(看板所在这台机器自己的指标)。
  - 推 agent:installers 把脚本+上报 wrapper 装到被监控机(远程机统一走 push,见 installers/)。

采集失败/超时 → 跳过该机器(诚实降级),不抛到主循环。
"""
import json
import os
import platform
import subprocess

_CDIR = os.path.join(os.path.dirname(__file__), "collectors")
_SCRIPTS = {
    "linux": "collect_linux.sh",
    "macos": "collect_macos.sh",
    "windows": "collect_windows.ps1",
}


def detect_local_platform() -> str:
    s = platform.system().lower()
    if s == "darwin":
        return "macos"
    if s == "windows":
        return "windows"
    return "linux"


def _resolve(plat: str) -> str:
    return detect_local_platform() if (not plat or plat == "auto") else plat


def _parse(out: str) -> dict:
    out = (out or "").strip()
    if not out:
        raise ValueError("采集脚本无输出")
    # 取最后一行非空(防 shell 噪声),解析 JSON
    line = [l for l in out.splitlines() if l.strip()][-1]
    return json.loads(line)


def read_local(plat: str = "auto", timeout: int = 15) -> dict:
    plat = _resolve(plat)
    script = os.path.join(_CDIR, _SCRIPTS[plat])
    if plat == "windows":
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script]
    else:
        cmd = ["sh", script]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return _parse(r.stdout)


def collect(cfg: dict):
    """遍历配置的机器,采集本机直读(local);push 跳过(由 API 端点接收)。
    返回 {"devices_metrics": {机器名: 指标}};主循环对 devices_metrics 深合并。"""
    machines = ((cfg or {}).get("devices", {}) or {}).get("machines", []) or []
    out = {}
    for m in machines:
        name = (m.get("name") or "").strip()
        mode = m.get("mode") or "local"
        if not name or mode == "push":   # push 走 API 上报,不在此处采集
            continue
        try:
            metrics = read_local(m.get("platform"))
            if metrics:
                out[name] = metrics
        except Exception as e:
            print(f"[metrics] {name}({mode}): {type(e).__name__}: {e}")
    return {"devices_metrics": out} if out else None
