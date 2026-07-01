"""Kindle install.sh 测试 —— 刷新间隔(INTERVAL)写入 dashboard.conf。

新功能:install.sh 支持第三参数 / 交互询问刷新秒数,写进 /mnt/us/dashboard.conf 的
INTERVAL(start.sh 早已读 INTERVAL,但旧 install.sh 从不写,故恒为默认 20)。

install.sh 主体要 SSH 到 Kindle,无真机跑不了。这里用 PATH 前置的假 ssh/scp 拦截:
假 ssh 把每次远程命令串 append 到 $SSH_DUMP,于是能断言 install 下发的远程脚本里
dashboard.conf 写入行的 INTERVAL 值正确。KINDLE_IP 用 127.0.0.1(非 USBNetwork 默认地址)
以跳过 USB 网卡自动配置分支;stdin=DEVNULL 使 [ -t 0 ] 为假,走非交互默认。
"""
import os
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(REPO, "installers/kindle/install.sh")
START = os.path.join(REPO, "installers/kindle/start.sh")
UNINSTALL = os.path.join(REPO, "installers/kindle/uninstall.sh")

# 假 ssh:跳过控制命令(-O exit),把最后一个位置参数(远程命令串)写进 dump;
# 对连通性探测 "echo connected" 回显以让 install.sh 继续。
FAKE_SSH = """#!/bin/sh
case "$*" in *"-O exit"*) exit 0 ;; esac
for last; do :; done
printf '%s\\n' "$last" >> "$SSH_DUMP"
[ "$last" = "echo connected" ] && echo connected
exit 0
"""
FAKE_TRUE = "#!/bin/sh\nexit 0\n"


def _run(tmp_path, *args):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "ssh").write_text(FAKE_SSH)
    for n in ("scp", "ping", "sudo"):
        (bindir / n).write_text(FAKE_TRUE)
    for n in ("ssh", "scp", "ping", "sudo"):
        os.chmod(bindir / n, 0o755)
    dump = tmp_path / "ssh_dump.txt"
    env = dict(os.environ,
               PATH=f"{bindir}:{os.environ['PATH']}",
               SSH_DUMP=str(dump))
    r = subprocess.run(["sh", INSTALL, *args], env=env,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return r, (dump.read_text() if dump.exists() else "")


def test_interval_arg_written(tmp_path):
    r, dump = _run(tmp_path, "127.0.0.1", "http://x:8585", "45")
    assert r.returncode == 0, r.stderr
    assert "INTERVAL=45" in dump
    assert "SERVER_URL=http://x:8585" in dump


def test_interval_default_noninteractive(tmp_path):
    """不给第三参数 + 非 tty → 默认 20。"""
    r, dump = _run(tmp_path, "127.0.0.1", "http://x:8585")
    assert r.returncode == 0, r.stderr
    assert "INTERVAL=20" in dump


def test_interval_invalid_falls_back(tmp_path):
    """非数字参数 → 回退 20,不写脏值。"""
    r, dump = _run(tmp_path, "127.0.0.1", "http://x:8585", "abc")
    assert r.returncode == 0, r.stderr
    assert "INTERVAL=20" in dump
    assert "INTERVAL=abc" not in dump


def test_interval_too_small_falls_back(tmp_path):
    """过小(<5s)→ 回退 20,防止把 Kindle 刷爆。"""
    r, dump = _run(tmp_path, "127.0.0.1", "http://x:8585", "3")
    assert r.returncode == 0, r.stderr
    assert "INTERVAL=20" in dump


def test_clear_every_written(tmp_path):
    """conf 总会写 CLEAR_EVERY=1(每次换图全刷,消残影),防止手动改的值被重装覆盖丢失。"""
    r, dump = _run(tmp_path, "127.0.0.1", "http://x:8585", "20")
    assert r.returncode == 0, r.stderr
    assert "CLEAR_EVERY=1" in dump


def test_alt_line_written(tmp_path):
    """conf 总会写 SERVER_URL_ALT 行:macOS 探测到 .local 则非空,本测试在 Linux 跑(非
    Darwin 探测不到)应为空值行,start.sh 用 ${SERVER_URL_ALT:-} 安全处理、不触发轮换、不退化。"""
    r, dump = _run(tmp_path, "127.0.0.1", "http://x:8585", "20")
    assert r.returncode == 0, r.stderr
    assert "SERVER_URL_ALT=" in dump


def test_bash_syntax_ok():
    for script in (INSTALL, START, UNINSTALL):
        r = subprocess.run(["bash", "-n", script], capture_output=True, text=True)
        assert r.returncode == 0, f"{script}: {r.stderr}"
