# coding=utf-8
# !/usr/bin/python
"""黄色仓库 hsck（纯 Python）- 多域名自动选优 · 内容验证版"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
import tempfile
import time
from typing import Dict, List, Optional
from urllib.parse import quote, urljoin

import requests

from base.spider import Spider

sys.path.append("..")


UA = (
    "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)


class Spider(Spider):
    # 候选域名（列表顺序即兜底优先级）
    HOSTS = [
        "https://hsck4.26img.com",
        "https://333.aggck.cc",
        "https://888.aggck.cc",
        "https://999.agmck.cc",
        "https://666.aggck.cc",
        "https://888.0kck.cc",
        "https://999.0kck.cc",
        "https://111.0kck.cc",
    ]

    CACHE_TTL = 3600          # 域名缓存有效期（秒）
    PROBE_TIMEOUT = 5.0       # 单域名探测超时
    PROBE_RETRY = 2           # 探测重试次数
    MAX_SWITCH_RETRY = 1      # 请求失败自动换域名重试

    CACHE_FILE = os.path.join(tempfile.gettempdir(), ".hsck_host_cache.json")

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def init(self, extend: str = ""):
        self.host = self._pick_fastest_host()
        self._refresh_headers()
        self.categories = [
            ("国产新片", "ycgc"),
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

    # ------------------------------------------------------------------ #
    # 域名选优（内容验证）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalize(url: str) -> str:
        return (url or "").rstrip("/")

    def _refresh_headers(self):
        self.headers = {
            "User-Agent": UA,
            "Referer": f"{self.host}/",
        }

    def _pick_fastest_host(self) -> str:
        cached = self._read_cache()
        if cached and self._domain_has_content(cached):
            return cached

        best = self._probe_all()
        self._write_cache(best)
        return best

    def _read_cache(self) -> Optional[str]:
        try:
            if not os.path.exists(self.CACHE_FILE):
                return None
            with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if time.time() - data.get("ts", 0) > self.CACHE_TTL:
                return None
            host = data.get("host", "")
            return self._normalize(host) if host else None
        except Exception:
            return None

    def _write_cache(self, host: str):
        try:
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"host": host, "ts": time.time()}, f)
        except Exception:
            pass

    def _fetch_page(self, url: str, timeout: float) -> Optional[str]:
        """探测用：直接 requests 获取页面文本，失败返回 None"""
        try:
            resp = requests.get(
                f"{url}/?type=ycgc&p=1",
                timeout=timeout,
                headers={"User-Agent": UA, "Referer": f"{url}/"},
                allow_redirects=True,
            )
            if resp.status_code >= 400:
                return None
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except Exception:
            return None

    def _domain_has_content(self, url: str) -> bool:
        """校验域名能否真正解析出影视条目"""
        html = self._fetch_page(url, timeout=self.PROBE_TIMEOUT)
        if not html:
            return False
        return bool(self._parse_list(html, host=url))

    def _probe_one(self, url: str):
        """探测单个域名：必须能返回可解析的影视列表才算有效"""
        url = self._normalize(url)
        for _ in range(self.PROBE_RETRY):
            start = time.perf_counter()
            html = self._fetch_page(url, timeout=self.PROBE_TIMEOUT)
            elapsed = time.perf_counter() - start
            if html and self._parse_list(html, host=url):
                return (url, elapsed)
        return (url, float("inf"))

    def _probe_all(self) -> str:
        results = []
        try:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(self.HOSTS)
            ) as executor:
                futures = [executor.submit(self._probe_one, u) for u in self.HOSTS]
                for future in concurrent.futures.as_completed(
                    futures, timeout=self.PROBE_TIMEOUT * 4
                ):
                    try:
                        results.append(future.result())
                    except Exception:
                        continue
        except Exception:
            pass

        valid = [(u, t) for u, t in results if t < float("inf")]
        if valid:
            valid.sort(key=lambda x: x[1])
            return valid[0][0]

        return self._normalize(self.HOSTS[0])

    # ------------------------------------------------------------------ #
    # 内容接口
    # ------------------------------------------------------------------ #
    def homeContent(self, filter: bool):
        return {
            "class": [
                {"type_name": name, "type_id": type_id}
                for name, type_id in self.categories
            ],
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

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #
    def _get(self, url: str) -> str:
        last_err = None
        for attempt in range(self.MAX_SWITCH_RETRY + 1):
            try:
                response = self.fetch(url, headers=self.headers, timeout=15)
                response.encoding = response.apparent_encoding or "utf-8"
                return response.text
            except Exception as e:
                last_err = e
                if attempt >= self.MAX_SWITCH_RETRY:
                    break
                new_host = self._pick_fastest_host()
                if new_host != self.host:
                    old_host = self.host
                    self.host = new_host
                    self._refresh_headers()
                    if url.startswith(old_host):
                        url = new_host + url[len(old_host):]
                else:
                    break
        if last_err:
            raise last_err
        return ""

    def _parse_list(self, html: str, host: Optional[str] = None) -> List[Dict[str, str]]:
        """
        兼容两种常见结构：
        1) <a href="..." title="..." data-original="...">...</a>
        2) <a href="..." title="..."><img data-original="..."></a>
        """
        base_host = self._normalize(host or self.host)

        matches: List[tuple] = []

        # 结构 1：三属性同在一处
        pattern1 = re.compile(
            r'<a[^>]+href="([^"]+)"[^>]*title="([^"]+)"[^>]*data-original="([^"]+)"',
            flags=re.S | re.I,
        )
        matches.extend(pattern1.findall(html))

        # 结构 2：逐个 <a>...</a> 块内查找
        if not matches:
            pattern2 = re.compile(r"<a\s[^>]*>.*?</a>", flags=re.S | re.I)
            for block in pattern2.findall(html):
                m_href = re.search(r'href="([^"]+)"', block, re.I)
                m_title = re.search(r'title="([^"]+)"', block, re.I)
                m_pic = re.search(r'data-original="([^"]+)"', block, re.I)
                if m_href and m_title and m_pic:
                    matches.append(
                        (m_href.group(1), m_title.group(1), m_pic.group(1))
                    )

        videos: List[Dict[str, str]] = []
        seen = set()
        for href, title, pic in matches:
            detail_url = urljoin(base_host + "/", href)
            if detail_url in seen:
                continue
            seen.add(detail_url)
            videos.append(
                {
                    "vod_id": detail_url,
                    "vod_name": title.strip(),
                    "vod_pic": pic.strip(),
                    "vod_remarks": "黄色仓库",
                }
            )
        return videos

    @staticmethod
    def _first(patterns: List[str], text: str, default: str = "") -> str:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.S | re.I)
            if match:
                return match.group(1).strip()
        return default