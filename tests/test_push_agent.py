"""push agent 安装器目录解析:家目录不可写的 NAS(飞牛/群晖等)也能装上。

起因:飞牛/群晖/威联通等 NAS 的 SSH 账号家目录常不在 /home(甚至没建),
install_agent.sh 原来死用 $HOME/.kindle-dash-agent,mkdir 直接 Permission denied。
现改为按可写性挑目录 + KDASH_AGENT_DIR 显式覆盖 + 失败给清晰指引。
"""
import os
import subprocess
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(HERE, "installers", "push-agent", "install_agent.sh")


def _run(args, env_overrides):
    env = dict(os.environ)
    env.update(env_overrides)
    return subprocess.run(["sh", SCRIPT, *args], capture_output=True, text=True, env=env)


def _resolve(env_overrides):
    return _run(["resolve-dir"], env_overrides).stdout.strip()


def test_writable_home_uses_home():
    with tempfile.TemporaryDirectory() as d:
        out = _resolve({"HOME": d, "KDASH_AGENT_DIR": "", "XDG_DATA_HOME": ""})
        assert out == os.path.join(d, ".kindle-dash-agent")


def test_explicit_override_wins():
    with tempfile.TemporaryDirectory() as d:
        # 即便 HOME 可写,KDASH_AGENT_DIR 也优先
        out = _resolve({"HOME": d, "KDASH_AGENT_DIR": "/custom/place"})
        assert out == "/custom/place"


def test_falls_back_when_home_unwritable():
    # 家目录不存在/不可写 → 回退到下一个可写候选(这里用 XDG_DATA_HOME 模拟 NAS 用户空间)
    with tempfile.TemporaryDirectory() as good:
        out = _resolve({"HOME": "/proc/nonexistent/nope",
                        "XDG_DATA_HOME": good, "KDASH_AGENT_DIR": ""})
        assert out == os.path.join(good, ".kindle-dash-agent")


def test_install_errors_clearly_when_no_writable_dir():
    # 无任何可写候选、且未显式指定 → install 应明确报错退出,并提示用 KDASH_AGENT_DIR
    r = _run(["http://127.0.0.1:1", "30"],
             {"HOME": "/proc/nonexistent/nope", "XDG_DATA_HOME": "", "KDASH_AGENT_DIR": ""})
    assert r.returncode == 1
    assert "KDASH_AGENT_DIR" in (r.stdout + r.stderr)


def test_unwritable_base_is_skipped_not_created():
    # base 已存在但不可写 → 跳过,不报错地落到下一个可写候选
    with tempfile.TemporaryDirectory() as ro, tempfile.TemporaryDirectory() as good:
        os.chmod(ro, 0o500)  # r-x:存在但不可写
        try:
            out = _resolve({"HOME": ro, "XDG_DATA_HOME": good, "KDASH_AGENT_DIR": ""})
            assert out == os.path.join(good, ".kindle-dash-agent")
        finally:
            os.chmod(ro, 0o700)  # 复原以便 TemporaryDirectory 清理
