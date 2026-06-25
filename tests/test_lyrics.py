"""歌词源纯逻辑测试(LRC 解析 + 候选排序),不触网。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.sources import lyrics  # noqa: E402


def test_parse_basic():
    lrc = "[00:11.61]当你在穿山越岭的另一边\n[00:16.03]我在孤独的路上没有尽头"
    out = lyrics.parse_lrc(lrc)
    assert out == [
        {"t": 11.61, "text": "当你在穿山越岭的另一边"},
        {"t": 16.03, "text": "我在孤独的路上没有尽头"},
    ]


def test_parse_strips_metadata():
    lrc = ("[00:00.00] 作词 : 齐秦/张震岳\n[00:01.00] 作曲 : 齐秦\n"
           "[00:03.00] 原唱 : 齐秦\n[00:11.61]当你在穿山越岭的另一边")
    out = lyrics.parse_lrc(lrc)
    assert len(out) == 1 and out[0]["text"] == "当你在穿山越岭的另一边"


def test_parse_multi_timestamp_one_line():
    # 同一句多时间戳(副歌重复)→ 各发一条
    out = lyrics.parse_lrc("[00:10.00][01:20.50]副歌一句")
    assert out == [
        {"t": 10.0, "text": "副歌一句"},
        {"t": 80.5, "text": "副歌一句"},
    ]


def test_parse_ms_digits_normalized():
    # 两位 .61 = 0.61s;三位 .610 也 = 0.61s
    assert lyrics.parse_lrc("[00:05.61]x")[0]["t"] == 5.61
    assert lyrics.parse_lrc("[00:05.610]x")[0]["t"] == 5.61


def test_parse_garbage_returns_empty():
    assert lyrics.parse_lrc("") == []
    assert lyrics.parse_lrc("纯文本无时间轴\n第二行") == []
    assert lyrics.parse_lrc(None) == []


def test_artist_match_fuzzy():
    # 看板取到 "张震岳",候选存 "张震岳/蔡健雅" → 命中
    assert lyrics._artist_match("张震岳", "张震岳/蔡健雅")
    assert lyrics._artist_match("张震岳/蔡健雅", "蔡健雅/张震岳")
    assert not lyrics._artist_match("周杰伦", "林俊杰")
    # 空查询 → 视作命中(不过滤)
    assert lyrics._artist_match("", "任意歌手")


def test_rank_prefers_artist_then_duration():
    cands = [
        {"id": 1, "artist": "别人", "duration": 260},      # 歌手不匹配
        {"id": 2, "artist": "张震岳/蔡健雅", "duration": 320},  # 匹配但时长远
        {"id": 3, "artist": "张震岳/蔡健雅", "duration": 262},  # 匹配且时长近
    ]
    ranked = lyrics.rank_candidates(cands, "张震岳", 260)
    assert [c["id"] for c in ranked] == [3, 2, 1]


def test_rank_album_beats_duration():
    # 看板播 OK 录音室版(283s),候选里 Live 版时长更近(295)但专辑不符;
    # OK 版时长差更大(260)但专辑匹配 → 应选 OK 版(专辑 > 时长)
    cands = [
        {"id": "live", "artist": "张震岳", "album": "Live in Taipei", "duration": 295},
        {"id": "ok", "artist": "张震岳/蔡健雅", "album": "OK", "duration": 260},
    ]
    ranked = lyrics.rank_candidates(cands, "张震岳", 283, "OK")
    assert ranked[0]["id"] == "ok"


def test_album_match_fuzzy():
    assert lyrics._album_match("OK", "OK (Deluxe)")
    assert not lyrics._album_match("", "任意")
    assert not lyrics._album_match("OK", "")


def test_rank_no_duration_keeps_artist_match_first():
    cands = [
        {"id": 1, "artist": "别人", "duration": 260},
        {"id": 2, "artist": "张震岳", "duration": 999},
    ]
    ranked = lyrics.rank_candidates(cands, "张震岳", None)
    assert ranked[0]["id"] == 2


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
