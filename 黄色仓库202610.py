# coding=utf-8
# !/usr/bin/python
"""黄色仓库 hsck（纯 Python）"""
from __future__ import annotations

import re
import sys
from typing import Dict, List
from urllib.parse import quote, urljoin

from base.spider import Spider

sys.path.append("..")


class Spider(Spider):
    def init(self, extend: str = ""):
        self.host = "https://hsck4.26img.com"
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
            ),
            "Referer": f"{self.host}/",
        }
        self.categories = [
            ("国产新片", "ycgc"),
            ("无码中文字幕", "wz"),
            ("有码中文字幕", "yz"),
            ("日本无码", "rw"),
            ("日本有码", "ry"),
            ("国产视频", "gc"),
            ("欧美高清", "om"),
            ("动漫剧情", "dm"),
        ]
        return self

    def getName(self) -> str:
        return "黄色仓库"

    def isVideoFormat(self, url: str) -> bool:
        return any(token in (url or "") for token in [".m3u8", ".mp4"])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def homeContent(self, filter: bool):
        return {
            "class": [{"type_name": name, "type_id": type_id} for name, type_id in self.categories],
            "list": self._parse_list(self._get(f"{self.host}/?type=ycgc&p=1")),
        }

    def homeVideoContent(self):
        return {"list": self._parse_list(self._get(f"{self.host}/?type=ycgc&p=1"))}

    def categoryContent(self, tid: str, pg: str, filter: bool, extend: dict):
        page_number = max(int(pg or "1"), 1)
        html = self._get(f"{self.host}/?type={tid}&p={page_number}")
        videos = self._parse_list(html)
        return {
            "list": videos,
            "page": page_number,
            "pagecount": page_number + (1 if videos else 0),
            "limit": 40,
            "total": page_number * 40,
        }

    def detailContent(self, array: List[str]):
        detail_url = array[0]
        if not detail_url.startswith("http"):
            detail_url = urljoin(self.host + "/", detail_url)
        html = self._get(detail_url)
        title = self._first(
            [
                r"<h1[^>]*>(.*?)</h1>",
                r'property="og:title"\s+content="([^"]+)"',
                r"<title>(.*?)</title>",
            ],
            html,
            "黄色仓库",
        )
        title = re.sub(r"<[^>]+>", "", title).strip()
        pic = self._first(
            [
                r'property="og:image"\s+content="([^"]+)"',
                r'data-original="(https?://[^"]+)"',
            ],
            html,
            "",
        )
        m3u8_list = re.findall(r"https?://[^\"'\s]+\.m3u8[^\"'\s]*", html)
        if not m3u8_list:
            m3u8_list = re.findall(r'src="(https?://[^"]+\.m3u8[^"]*)"', html)
        play_urls = []
        seen = set()
        for index, url in enumerate(m3u8_list):
            cleaned = url.replace("\\/", "/")
            if cleaned in seen:
                continue
            seen.add(cleaned)
            play_urls.append(f"线路{index + 1}${cleaned}")
        if not play_urls:
            play_urls = [f"原页${detail_url}"]
        return {
            "list": [
                {
                    "vod_id": detail_url,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_play_from": "黄色仓库",
                    "vod_play_url": "#".join(play_urls),
                }
            ]
        }

    def searchContent(self, key: str, quick: bool, pg: str = "1"):
        html = self._get(f"{self.host}/?search2=ndafeoafa&search={quote(key)}")
        return {"list": self._parse_list(html), "page": 1}

    def playerContent(self, flag: str, play_id: str, vipFlags: List[str]):
        return {"parse": 0, "url": play_id, "header": self.headers}

    def localProxy(self, param: dict):
        return None

    def _get(self, url: str) -> str:
        response = self.fetch(url, headers=self.headers, timeout=15)
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text

    def _parse_list(self, html: str) -> List[Dict[str, str]]:
        videos: List[Dict[str, str]] = []
        pattern = re.compile(
            r'<a[^>]+href="([^"]+)"[^>]*title="([^"]+)"[^>]*data-original="([^"]+)"',
            flags=re.S,
        )
        for href, title, pic in pattern.findall(html):
            detail_url = urljoin(self.host + "/", href)
            videos.append(
                {
                    "vod_id": detail_url,
                    "vod_name": title.strip(),
                    "vod_pic": pic.strip(),
                    "vod_remarks": "黄色仓库",
                }
            )
        unique: List[Dict[str, str]] = []
        seen = set()
        for item in videos:
            if item["vod_id"] in seen:
                continue
            seen.add(item["vod_id"])
            unique.append(item)
        return unique

    @staticmethod
    def _first(patterns: List[str], text: str, default: str = "") -> str:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.S | re.I)
            if match:
                return match.group(1).strip()
        return default
