#!/usr/bin/env python3
"""Claude Code status line:显示 上下文 / 5h / 周额度,并把额度上报给看板(push)。

Claude Code 会把一份 JSON 从 stdin 喂给本脚本(见 settings.json 的 statusLine),
其中 rate_limits.five_hour / seven_day 就是 5 小时 / 周额度(used_percentage + resets_at)。
这是 Claude Code 官方机制,稳定。本脚本顺手把它存本地 + POST 到看板 /api/rate-limits(source=claude)。

零硬编码:上报地址/节流从环境变量 KINDLE_RATELIMIT_URL / KINDLE_QUOTA_PUSH_INTERVAL 读,
读不到则从同目录 quota.conf 读(由 enable_quota.sh 写入),再读不到用本机默认。

—— 已经有自己 statusLine 的用户:不必换成本脚本,把下面「>>> 上报额度」那一段抄进你自己的
   脚本即可(它只依赖 stdin 里的 rate_limits,与你的状态栏显示互不干扰)。
"""
import sys, json, time, os

R = '\033[0m'
D = '\033[2m'


def color(pct: int) -> str:
    if pct >= 80:
        return '\033[31m'
    if pct >= 50:
        return '\033[33m'
    return '\033[32m'


def fmt_min(secs_left: int) -> str:
    if secs_left <= 0:
        return 'now'
    h, m = divmod(secs_left // 60, 60)
    return f'{h}h{m:02d}m' if h else f'{m}m'


def fmt_hour(secs_left: int) -> str:
    if secs_left <= 0:
        return 'now'
    h = (secs_left + 1800) // 3600
    if h >= 24:
        d, rem = divmod(h, 24)
        return f'{d}d{rem}h' if rem else f'{d}d'
    return f'{h}h'


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f'{n/1_000_000:.1f}M'
    if n >= 1000:
        return f'{n/1000:.1f}k'
    return str(n)


def _conf():
    """上报地址 + 节流秒数:环境变量优先,其次同目录 quota.conf,最后本机默认。"""
    url = os.environ.get("KINDLE_RATELIMIT_URL")
    interval = os.environ.get("KINDLE_QUOTA_PUSH_INTERVAL")
    if not url or not interval:
        try:
            confp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quota.conf")
            for line in open(confp):
                k, _, v = line.strip().partition("=")
                if k == "KINDLE_RATELIMIT_URL" and not url:
                    url = v
                elif k == "KINDLE_QUOTA_PUSH_INTERVAL" and not interval:
                    interval = v
        except Exception:
            pass
    try:
        interval = int(interval)
    except (TypeError, ValueError):
        interval = 300
    return url or "http://127.0.0.1:8585/api/rate-limits", interval


try:
    data = json.loads(sys.stdin.read() or '{}')
except Exception:
    print('statusline: parse error')
    sys.exit(0)

now = int(time.time())
cw = data.get('context_window') or {}
rl = data.get('rate_limits') or {}
five = rl.get('five_hour') or {}
week = rl.get('seven_day') or {}

# >>> 上报额度(把这段抄进你自己的 statusLine 即可让它顺便上报 Claude 额度)
if five or week:
    try:
        import subprocess
        url, push_interval = _conf()
        cache_data = {"timestamp": now, "rate_limits": rl}
        # 本地缓存(可选,便于排查)
        try:
            with open(os.path.expanduser("~/.claude/rate-limits.json"), "w") as f:
                json.dump(cache_data, f)
        except Exception:
            pass
        # 按 push_interval 节流,避免每次刷新都打服务
        marker = os.path.expanduser("~/.claude/.kindle-quota-pushed")
        should_push = True
        try:
            if os.path.exists(marker) and (now - int(os.path.getmtime(marker))) < push_interval:
                should_push = False
        except Exception:
            pass
        if should_push:
            open(marker, "w").close()
            subprocess.Popen(
                ["curl", "-s", "-m", "10", "-X", "POST", url,
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({"source": "claude", "rate_limits": rl})],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
# <<< 上报额度

# ---- 状态栏显示 ----
ctx_pct = int(cw.get('used_percentage') or 0)
ctx_used = (cw.get('total_input_tokens') or 0) + (cw.get('total_output_tokens') or 0)
ctx_size = cw.get('context_window_size') or 0
ctx_tag = fmt_tokens(ctx_used) + (f'/{fmt_tokens(ctx_size)}' if ctx_size else '')

parts = [f'{D}Ctx{R} {color(ctx_pct)}{ctx_pct}%{R} {D}({ctx_tag}){R}']
if five:
    p = int(five.get('used_percentage') or 0)
    parts.append(f'{D}5h{R} {color(p)}{p}%{R} {D}↻{R}{fmt_min((five.get("resets_at") or 0) - now)}')
else:
    parts.append(f'{D}5h ?{R}')
if week:
    p = int(week.get('used_percentage') or 0)
    parts.append(f'{D}周{R} {color(p)}{p}%{R} {D}↻{R}{fmt_hour((week.get("resets_at") or 0) - now)}')
else:
    parts.append(f'{D}周 ?{R}')

print(' · '.join(parts))
