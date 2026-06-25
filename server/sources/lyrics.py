"""歌词采集源:按 歌名 + 歌手(+ 时长)查带时间轴歌词(LRC)。

诚实降级:任何网络/解析失败都返回 [],绝不抛错(上层据空判定无歌词、回退播放器)。

源优先级(中文歌实测网易云更准、字简体、歌手名格式与 Apple Music 一致):
  1. 网易云音乐  search → 按歌手模糊 + 时长最近挑 → 拉词 → 解析 LRC(剥元信息行)
  2. LRCLIB     search → 同样策略(syncedLyrics 直接带在搜索结果里)

不走代理(面向普罗大众,默认直连;代理日后再议)。
统一输出 [{"t": 秒(float), "text": 该行}],按 t 升序,已剥掉「作词/作曲」等元信息行。
"""
import re

import httpx

_TS = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")
# 元信息行(网易云常见把这些塞进 [00:00.00] 开头):作词/作曲/编曲… 形如 "作词 : 某某"
_META = re.compile(
    r"^\s*(作词|作曲|编曲|制作|出品|监制|混音|母带|和声|配唱|录音|演唱|原唱|歌手|"
    r"专辑|词|曲|制作人|吉他|贝斯|鼓|键盘|弦乐|提琴|Producer|Composer|Lyricist|"
    r"Arranger|Mixing|Mastering|Written|Music|Lyrics?)\s*[:：]",
    re.IGNORECASE,
)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
_TIMEOUT = 6.0


# ---------------- 纯逻辑(可离线测试) ----------------

def parse_lrc(text):
    """LRC 文本 → [{t, text}],按 t 升序。一行可带多个时间戳(重复句)→ 各发一条。
    剥掉纯元信息行(作词/作曲…)与空行。解析不出时间轴 → []。"""
    if not text or not isinstance(text, str):
        return []
    out = []
    for line in text.splitlines():
        stamps = list(_TS.finditer(line))
        if not stamps:
            continue
        lyric = line[stamps[-1].end():].strip()
        if not lyric or _META.match(lyric):
            continue
        for m in stamps:
            mm = int(m.group(1))
            ss = int(m.group(2))
            frac = m.group(3) or "0"
            # 毫秒位数不定(.xx / .xxx),按位归一
            ms = int(frac) / (10 ** len(frac))
            t = round(mm * 60 + ss + ms, 2)
            out.append({"t": t, "text": lyric})
    out.sort(key=lambda x: x["t"])
    return out


def _artist_tokens(artist):
    """歌手串拆成片段集合:'张震岳/蔡健雅' → {'张震岳','蔡健雅'}。"""
    if not artist:
        return set()
    parts = re.split(r"[/&,，、x×\s]+", artist)
    return {p.strip().lower() for p in parts if p.strip()}


def _artist_match(query_artist, cand_artist):
    """歌手模糊匹配:任一片段互相包含即算命中(空查询→视作命中)。"""
    q = _artist_tokens(query_artist)
    if not q:
        return True
    c = cand_artist.lower()
    ctoks = _artist_tokens(cand_artist)
    for qt in q:
        if qt in c or any(qt in ct or ct in qt for ct in ctoks):
            return True
    return False


def _album_match(query_album, cand_album):
    """专辑模糊匹配(互相包含,大小写无关)。空查询/空候选 → 不算命中。"""
    if not query_album or not cand_album:
        return False
    q = query_album.strip().lower()
    c = cand_album.strip().lower()
    return q in c or c in q


def rank_candidates(cands, query_artist, duration, album=""):
    """候选排序:歌手命中 > 专辑命中 > 时长最接近。cand = {artist, album, duration, ...}。
    专辑是比时长更强的版本信号(Live/录音室/重制时长各异,但同专辑=同版本=对的歌词)。
    duration/album 为空时该维度不参与。返回排序后的列表。"""
    def key(c):
        artist_miss = 0 if _artist_match(query_artist, c.get("artist", "")) else 1
        album_miss = 0 if _album_match(album, c.get("album", "")) else 1
        cd = c.get("duration") or 0
        diff = abs(cd - duration) if (duration and cd) else 0
        return (artist_miss, album_miss, diff)
    return sorted(cands, key=key)


# ---------------- 网络(失败即降级) ----------------

def _get_json(client, url, params, headers=None):
    try:
        r = client.get(url, params=params, headers=headers or {}, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _netease(client, name, artist, duration, album):
    d = _get_json(
        client, "https://music.163.com/api/search/get/",
        {"s": f"{name} {artist}".strip(), "type": 1, "limit": 8},
        {"Referer": "https://music.163.com", "User-Agent": _UA},
    )
    songs = ((d or {}).get("result") or {}).get("songs") or []
    cands = [{
        "id": s.get("id"),
        "artist": "/".join(a.get("name", "") for a in (s.get("artists") or [])),
        "album": (s.get("album") or {}).get("name", ""),
        "duration": (s.get("duration") or 0) / 1000.0,
    } for s in songs if s.get("id")]
    for c in rank_candidates(cands, artist, duration, album)[:4]:
        ly = _get_json(
            client, "https://music.163.com/api/song/lyric",
            {"id": c["id"], "lv": 1, "kv": 1, "tv": -1},
            {"Referer": "https://music.163.com", "User-Agent": _UA},
        )
        parsed = parse_lrc(((ly or {}).get("lrc") or {}).get("lyric") or "")
        if len(parsed) >= 2:
            return parsed
    return []


def _lrclib(client, name, artist, duration, album):
    arr = _get_json(
        client, "https://lrclib.net/api/search",
        {"q": name}, {"User-Agent": "kindle-dashboard (lyrics)"},
    )
    if not isinstance(arr, list):
        return []
    cands = [{
        "synced": it.get("syncedLyrics") or "",
        "artist": it.get("artistName") or "",
        "album": it.get("albumName") or "",
        "duration": it.get("duration") or 0,
    } for it in arr if it.get("syncedLyrics")]
    for c in rank_candidates(cands, artist, duration, album)[:4]:
        parsed = parse_lrc(c["synced"])
        if len(parsed) >= 2:
            return parsed
    return []


def fetch_lyrics(name, artist="", duration=None, album=""):
    """主入口:返回 [{t,text}] 或 [](查不到/出错)。网易云优先,LRCLIB 兜底。
    album 有值时优先选同专辑版本(比时长更可靠地区分 Live/录音室/重制)。"""
    if not name:
        return []
    try:
        with httpx.Client(follow_redirects=True) as client:
            for src in (_netease, _lrclib):
                try:
                    out = src(client, name, artist or "", duration, album or "")
                except Exception:
                    out = []
                if out:
                    return out
    except Exception:
        pass
    return []
