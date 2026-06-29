"""iCloud 公开共享相册解析验证。可直接 python3 跑,也兼容 pytest。"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.sources import icloud_album as ia  # noqa: E402


def test_parse_token():
    assert ia.parse_token("https://www.icloud.com/sharedalbum/#B0ABCdef") == "B0ABCdef"
    assert ia.parse_token("https://www.icloud.com/sharedalbum/#A1xyz?q=1") == "A1xyz"
    assert ia.parse_token("not a url") == ""
    assert ia.parse_token("") == ""


def test_partition_host():
    # 'A' → p01, 'B' → p02 ... 首字符决定分区(A=1)
    assert ia.partition_host("A1xxx") == "p01-sharedstreams.icloud.com"
    assert ia.partition_host("B0xxx") == "p02-sharedstreams.icloud.com"


def test_parse_webstream_picks_largest():
    data = {"photos": [
        {"photoGuid": "g1", "derivatives": {
            "1": {"checksum": "cks_small", "width": "100", "height": "100"},
            "2": {"checksum": "cks_big", "width": "2000", "height": "1500"},
        }},
        {"photoGuid": "g2", "derivatives": {
            "1": {"checksum": "cks2", "width": "800", "height": "600"},
        }},
    ]}
    out = ia.parse_webstream(data)
    assert out == [
        {"guid": "g1", "checksums": ["cks_big"]},
        {"guid": "g2", "checksums": ["cks2"]},
    ]


def test_parse_asset_urls():
    data = {"items": {
        "cks_big": {"url_location": "cvws.icloud-content.com", "url_path": "/B/abc?o=1"},
    }}
    out = ia.parse_asset_urls(data)
    assert out == {"cks_big": "https://cvws.icloud-content.com/B/abc?o=1"}


def test_build_photo_list():
    stream = [{"guid": "g1", "checksums": ["cks_big"]},
              {"guid": "g2", "checksums": ["missing"]}]
    assets = {"cks_big": "https://h/p"}
    out = ia.build_photo_list({"photos_parsed": stream}, assets) if False else ia.build_photo_list(stream, assets)
    assert out == [{"guid": "g1", "checksum": "cks_big", "url": "https://h/p"}]
