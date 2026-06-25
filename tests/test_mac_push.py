"""Tests for standalone Mac push installers (NAS deployment, no repo clone needed)."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_install_reminders_syntax():
    r = subprocess.run(["bash", "-n", os.path.join(REPO, "installers", "mac-push", "install_reminders.sh")],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"Syntax error: {r.stderr}"


def test_install_ccusage_syntax():
    r = subprocess.run(["bash", "-n", os.path.join(REPO, "installers", "mac-push", "install_ccusage.sh")],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"Syntax error: {r.stderr}"


def test_install_quota_syntax():
    r = subprocess.run(["bash", "-n", os.path.join(REPO, "installers", "mac-push", "install_quota.sh")],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"Syntax error: {r.stderr}"


def test_install_music_syntax():
    r = subprocess.run(["bash", "-n", os.path.join(REPO, "installers", "mac-push", "install_music.sh")],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"Syntax error: {r.stderr}"


def test_agent_files_served():
    """All new agent files return 200 from the /agent/ endpoint."""
    from fastapi.testclient import TestClient
    from server.app import app

    client = TestClient(app)
    for name in ["install_reminders.sh", "install_ccusage.sh", "install_quota.sh",
                 "install_music.sh", "read_reminders.js", "read_music.js",
                 "claude_statusline.py", "codex_quota.py"]:
        resp = client.get(f"/agent/{name}")
        assert resp.status_code == 200, f"/agent/{name} returned {resp.status_code}"
        assert len(resp.text) > 10, f"/agent/{name} returned empty content"


def test_auto_enable_reminders_on_push():
    """POST /api/apple-sync with valid reminders auto-enables reminders.enabled."""
    from fastapi.testclient import TestClient
    from server.app import app, cm

    cm.force_set("reminders", "enabled", False)
    assert not cm.get().get("reminders", {}).get("enabled")

    client = TestClient(app)
    resp = client.post("/api/apple-sync", json={
        "reminders": [{"title": "Test", "completed": False, "list": "Test", "dueDate": None, "priority": 0}],
        "updated_at": "2026-06-08T00:00:00Z",
    })
    assert resp.status_code == 200
    assert cm.get().get("reminders", {}).get("enabled") is True


def test_auto_enable_ccusage_on_push():
    """POST /api/ccusage with valid data auto-enables ai_usage.enabled."""
    from fastapi.testclient import TestClient
    from server.app import app, cm

    cm.force_set("ai_usage", "enabled", False)
    assert not cm.get().get("ai_usage", {}).get("enabled")

    client = TestClient(app)
    resp = client.post("/api/ccusage", json={
        "id": "auto-enable-test",
        "cc": {"daily": [{"date": "2026-06-08", "totalTokens": 100, "totalCost": 1.0}]},
        "codex": {"daily": []},
    })
    assert resp.status_code == 200
    assert cm.get().get("ai_usage", {}).get("enabled") is True


def test_auto_enable_music_on_push():
    """POST /api/music auto-enables music.enabled and stores current track."""
    from fastapi.testclient import TestClient
    from server.app import app, cm, cache

    cm.force_set("music", "enabled", False)
    assert not cm.get().get("music", {}).get("enabled")

    client = TestClient(app)
    resp = client.post("/api/music", json={
        "has_track": True,
        "state": "playing",
        "sampled_at": 1782293400.2,
        "position": 12,
        "duration": 240,
        "shuffle": False,
        "repeat": "off",
        "name": "Song",
        "artist": "Artist",
        "album": "Album",
    })
    assert resp.status_code == 200
    assert cm.get().get("music", {}).get("enabled") is True
    assert cache.get("music", {}).get("name") == "Song"


def test_auto_enable_idempotent():
    """Pushing when already enabled doesn't error."""
    from fastapi.testclient import TestClient
    from server.app import app, cm

    cm.force_set("reminders", "enabled", True)
    client = TestClient(app)
    resp = client.post("/api/apple-sync", json={
        "reminders": [{"title": "Again", "completed": False, "list": "X", "dueDate": None, "priority": 0}],
        "updated_at": "2026-06-08T00:00:00Z",
    })
    assert resp.status_code == 200
    assert cm.get().get("reminders", {}).get("enabled") is True


def test_setup_page_has_push_commands():
    """Setup page HTML contains the curl-pipe-sh commands for Mac push."""
    from fastapi.testclient import TestClient
    from server.app import app

    client = TestClient(app)
    resp = client.get("/setup")
    assert resp.status_code == 200
    html = resp.text
    assert "install_reminders.sh" in html
    assert "install_ccusage.sh" in html
    assert "install_quota.sh" in html
    assert "install_music.sh" in html
    assert "macPushCmdBox" in html


if __name__ == "__main__":
    test_install_reminders_syntax()
    test_install_ccusage_syntax()
    test_install_quota_syntax()
    test_install_music_syntax()
    test_setup_page_has_push_commands()
    print("All Mac push tests passed (non-server tests)!")
