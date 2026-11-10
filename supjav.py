#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Supjav 视频爬虫 (Python 版本)
原版: Supjav.java
转换: ChatGPT (GPT-5)
功能: 抓取 https://supjav.com 视频分类、搜索、详情、播放地址等。
"""

import re
import json
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

class Supjav:
    def __init__(self):
        self.site_url = "https://supjav.pics"
        self.play_url = "https://supjav.pics/"
        self.headers = {
            "Referer": self.site_url,
            "Host": "supjav.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def get_html(self, url, referer=None):
        headers = self.headers.copy()
        if referer:
            headers["Referer"] = referer
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.encoding = resp.apparent_encoding
            return resp.text
        except Exception as e:
            print(f"[请求失败] {url} - {e}")
            return ""

    def home_content(self):
        html = self.get_html(self.site_url)
        soup = BeautifulSoup(html, "html.parser")
        classes = []
        for a in soup.select("ul.nav > li > a"):
            href = a.get("href", "")
            if len(href.split("/")) < 5:
                continue
            type_id = href.replace(self.site_url, "")
            type_name = a.text.strip()
            classes.append({"type_id": type_id, "type_name": type_name})
        return {"class": classes}

    def category_content(self, tid, pg=1):
        url = urljoin(self.site_url, f"{tid}/page/{pg}/")
        html = self.get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        videos = []
        for article in soup.select("article"):
            a = article.select_one("a")
            if not a:
                continue
            title = a.get("title", "").strip()
            href = a.get("href", "").strip()
            img = article.select_one("img")
            pic = img.get("data-src") if img else ""
            videos.append({
                "vod_id": href,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": ""
            })
        return {"list": videos}

    def search_content(self, wd, quick=False):
        url = f"{self.site_url}?s={wd}"
        html = self.get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        videos = []
        for article in soup.select("article"):
            a = article.select_one("a")
            if not a:
                continue
            title = a.get("title", "").strip()
            href = a.get("href", "").strip()
            img = article.select_one("img")
            pic = img.get("data-src") if img else ""
            videos.append({
                "vod_id": href,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": ""
            })
        return {"list": videos}

    def detail_content(self, ids):
        url = ids if ids.startswith("http") else urljoin(self.site_url, ids)
        html = self.get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        title = soup.select_one("h1.entry-title")
        vod_name = title.text.strip() if title else "Unknown"
        img = soup.select_one("img")
        pic = img.get("src") if img else ""
        content = soup.select_one("div.entry-content")
        desc = content.text.strip()[:200] if content else ""
        play_list = []
        for iframe in soup.select("iframe"):
            src = iframe.get("src", "")
            if "supremejav" in src or "supjav" in src:
                play_list.append(src)
        vod_play_url = "#".join([f"播放${u}" for u in play_list])
        return {
            "vod_id": ids,
            "vod_name": vod_name,
            "vod_pic": pic,
            "vod_content": desc,
            "vod_play_url": vod_play_url
        }

    def player_content(self, flag, id, vipFlags=None):
        url = id
        if not url.startswith("http"):
            url = urljoin(self.play_url, id)
        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": self.headers
        }


if __name__ == "__main__":
    spider = Supjav()
    print("[1] 获取首页分类")
    data = spider.home_content()
    for c in data["class"][:5]:
        print(c)

    print("\n[2] 搜索示例 ('JUL')")
    s = spider.search_content("JUL")
    for v in s["list"][:3]:
        print(v)

    if s["list"]:
        print("\n[3] 详情示例")
        detail = spider.detail_content(s["list"][0]["vod_id"])
        print(json.dumps(detail, indent=2, ensure_ascii=False))
