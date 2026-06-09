"""Microsoft To Do 采集器测试(全程 mock httpx,不打真网络)。

覆盖:字段归一化、降级、flagged 过滤、分页、token 刷新+轮换、合并。
登录端点的设备码交互(login_start/poll)依赖真实微软服务,不在单测覆盖。
"""
import json
import time
import importlib

import pytest

from server.sources import mstodo
from server.render.build_context import prep_context
from datetime import datetime


# ---------- 假 httpx ----------
class FakeResp:
    def __init__(self, data):
        self._d = data
    def json(self):
        return self._d
    def raise_for_status(self):
        pass


def make_fake_httpx(get=None, post=None):
    class FakeClient:
        def __init__(self, *a, **k):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def get(self, url, **k):
            return get(url, **k)
        def post(self, url, **k):
            return post(url, **k)
    class M:
        Client = FakeClient
    return M


# ---------- 归一化 ----------
def test_normalize_field_mapping():
    t = {"title": "交报告", "status": "notStarted",
         "dueDateTime": {"dateTime": "2026-06-10T00:00:00.000", "timeZone": "UTC"},
         "importance": "high", "id": "TID"}
    lst = {"displayName": "任务", "id": "LID"}
    r = mstodo._normalize(t, lst)
    assert r["title"] == "交报告"
    assert r["completed"] is False
    assert r["dueDate"].startswith("2026-06-10")
    assert r["priority"] == 1
    assert r["list"] == "任务"
    assert r["source"] == "mstodo"
    assert r["id"] == "TID" and r["list_id"] == "LID"


def test_normalize_completed_and_no_due():
    r = mstodo._normalize({"title": "x", "status": "completed", "importance": "normal"},
                          {"displayName": "L", "id": "1"})
    assert r["completed"] is True
    assert r["dueDate"] is None
    assert r["priority"] == 0


# ---------- collect ----------
def test_collect_disabled_returns_none():
    assert mstodo.collect({"mstodo": {"enabled": False}}) is None
    assert mstodo.collect({}) is None


def test_collect_no_token_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(mstodo, "TOKEN_FILE", str(tmp_path / "none.json"))
    assert mstodo.collect({"mstodo": {"enabled": True}}) is None


def test_collect_merges_and_skips_flagged(monkeypatch):
    monkeypatch.setattr(mstodo, "_ensure_access_token", lambda cfg: "AT")
    lists = {"value": [
        {"displayName": "任务", "id": "L1"},
        {"displayName": "Flagged Emails", "id": "L2", "wellknownListName": "flaggedEmails"},
    ]}
    monkeypatch.setattr(mstodo, "_graph_get", lambda path, at: lists)
    tasks = {"L1": [{"title": "a", "status": "notStarted"}],
             "L2": [{"title": "mail", "status": "notStarted"}]}
    monkeypatch.setattr(mstodo, "_graph_get_all",
                        lambda path, at: tasks["L1"] if "L1" in path else tasks["L2"])

    # flagged 关闭 → 只剩 L1
    out = mstodo.collect({"mstodo": {"enabled": True}})
    titles = [r["title"] for r in out["reminders_mstodo"]]
    assert titles == ["a"]

    # flagged 打开 → 两个都在
    out = mstodo.collect({"mstodo": {"enabled": True, "include_flagged_emails": True}})
    assert sorted(r["title"] for r in out["reminders_mstodo"]) == ["a", "mail"]


def test_collect_lists_error_degrades(monkeypatch):
    monkeypatch.setattr(mstodo, "_ensure_access_token", lambda cfg: "AT")
    def boom(path, at):
        raise RuntimeError("graph 500")
    monkeypatch.setattr(mstodo, "_graph_get", boom)
    assert mstodo.collect({"mstodo": {"enabled": True}}) is None


# ---------- 分页 ----------
def test_graph_get_all_follows_pagination(monkeypatch):
    def fake_get(url, **k):
        if "nextpage" in url:
            return FakeResp({"value": [{"title": "p2"}]})
        return FakeResp({"value": [{"title": "p1"}],
                         "@odata.nextLink": "https://graph.microsoft.com/nextpage"})
    monkeypatch.setattr(mstodo, "httpx", make_fake_httpx(get=fake_get))
    items = mstodo._graph_get_all("/me/todo/lists/X/tasks", "AT")
    assert [i["title"] for i in items] == ["p1", "p2"]


# ---------- token 刷新 + 轮换 ----------
def test_refresh_rotates_and_caches(monkeypatch, tmp_path):
    tok_file = tmp_path / "tok.json"
    tok_file.write_text(json.dumps({"refresh_token": "R1"}), encoding="utf-8")
    monkeypatch.setattr(mstodo, "TOKEN_FILE", str(tok_file))

    calls = {"n": 0}
    def fake_post(url, **k):
        calls["n"] += 1
        return FakeResp({"access_token": "AT1", "expires_in": 3600, "refresh_token": "R2"})
    monkeypatch.setattr(mstodo, "httpx", make_fake_httpx(post=fake_post))

    at = mstodo._ensure_access_token({"mstodo": {}})
    assert at == "AT1"
    saved = json.loads(tok_file.read_text(encoding="utf-8"))
    assert saved["refresh_token"] == "R2"        # 轮换已保存
    assert saved["access_token"] == "AT1"

    # 第二次:access token 未过期 → 不再调网络
    def boom(url, **k):
        raise AssertionError("不该再刷新")
    monkeypatch.setattr(mstodo, "httpx", make_fake_httpx(post=boom))
    assert mstodo._ensure_access_token({"mstodo": {}}) == "AT1"
    assert calls["n"] == 1


def test_refresh_failure_returns_none(monkeypatch, tmp_path):
    tok_file = tmp_path / "tok.json"
    tok_file.write_text(json.dumps({"refresh_token": "BAD"}), encoding="utf-8")
    monkeypatch.setattr(mstodo, "TOKEN_FILE", str(tok_file))
    monkeypatch.setattr(mstodo, "httpx",
                        make_fake_httpx(post=lambda url, **k: FakeResp({"error": "invalid_grant"})))
    assert mstodo._ensure_access_token({"mstodo": {}}) is None


# ---------- 合并(build_context) ----------
def test_build_context_merges_apple_and_mstodo():
    cache = {
        "reminders": [{"title": "苹果事", "completed": False, "dueDate": None}],
        "reminders_mstodo": [{"title": "兔兔事", "completed": False, "dueDate": None},
                             {"title": "已完成", "completed": True, "dueDate": None}],
    }
    ctx = prep_context(datetime(2026, 6, 7, 9, 0), cache, {})
    rem = ctx["home"]["reminders"]
    assert rem["total"] == 2          # 两条未完成(已完成的不计)
    allt = [x["title"] for x in rem["overdue"] + rem["today"] + rem["upcoming"]]
    assert "苹果事" in allt and "兔兔事" in allt and "已完成" not in allt


# ---------- token 持久化(Docker 卷)----------
def _token_path_with_env(**env_over):
    """子进程里 import mstodo,回显解析出的 TOKEN_FILE(模块加载即定,故用子进程控 env)。"""
    import os
    import subprocess
    import sys
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env.pop("KINDLE_DATA_DIR", None)
    env.pop("KINDLE_MSTODO_TOKEN", None)
    env.update(env_over)
    r = subprocess.run([sys.executable, "-c",
                        "from server.sources import mstodo; print(mstodo.TOKEN_FILE)"],
                       capture_output=True, text=True, env=env, cwd=repo)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_token_follows_data_dir():
    # token 默认跟随 KINDLE_DATA_DIR → Docker 落 /data 卷,容器 rebuild 不丢登录
    assert _token_path_with_env(KINDLE_DATA_DIR="/tmp/kd-x") == "/tmp/kd-x/mstodo_token.json"


def test_token_explicit_override_wins():
    # KINDLE_MSTODO_TOKEN 显式指定仍优先(向后兼容)
    assert _token_path_with_env(KINDLE_DATA_DIR="/tmp/kd-x",
                                KINDLE_MSTODO_TOKEN="/custom/tok.json") == "/custom/tok.json"


# ---------- 时区:微软 dueDateTime 是 UTC,不能当本地时间直接取日期 ----------
def _local_day(due):
    from server.render.build_context import reminder_due_date
    from datetime import timezone, timedelta
    return reminder_due_date(due, timezone(timedelta(hours=8))).isoformat()


def test_utc_due_evening_not_counted_a_day_early():
    """北京 6-09 00:00 截止 = UTC 6-08T16:00:应算 6-09,不能算成 6-08 提前过期。"""
    r = mstodo._normalize(
        {"title": "x", "status": "notStarted",
         "dueDateTime": {"dateTime": "2026-06-08T16:00:00.0000000", "timeZone": "UTC"}},
        {"displayName": "L", "id": "L1"})
    assert _local_day(r["dueDate"]) == "2026-06-09"


def test_utc_due_daytime_stays_same_day():
    """UTC 日期与北京同日的不受影响。"""
    r = mstodo._normalize(
        {"title": "x", "status": "notStarted",
         "dueDateTime": {"dateTime": "2026-06-10T02:00:00.0000000", "timeZone": "UTC"}},
        {"displayName": "L", "id": "L1"})
    assert _local_day(r["dueDate"]) == "2026-06-10"   # UTC 02:00 = 北京 10:00
