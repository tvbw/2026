# coding=utf-8
#!/usr/bin/python
"""色播聚合 · 修复分类加载"""
# ===== 1. 先正常 import 所有模块 =====
import json
import random
import re
import sys
import threading
import time
from base64 import b64decode, b64encode
from urllib.parse import urlparse

import requests  # ✅ 先正常 import
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from pyquery import PyQuery as pq
sys.path.append('..')
from base.spider import Spider

# ===== 2. 再放加速头（不能再 import requests） =====
# =================== 极简万能加速头 ===================
import re
from functools import lru_cache

FAST_CDN = "lib.baomitu.com"
DEAD_MAP = {
    "rimg.iomycdn.com": FAST_CDN,
    "rimg.xiakee.com": FAST_CDN,
    "play.abcyun.com": FAST_CDN,
    "video.xyzcdn.com": FAST_CDN,
}

@lru_cache(maxsize=256)
def _auto_cdn(url: str) -> str:
    if not url:
        return ""
    for dead, fast in DEAD_MAP.items():
        url = url.replace(dead, fast)
    if url.startswith("//"):
        url = "https:" + url
    try:
        r = requests.head(url, allow_redirects=True, timeout=2)
        url = r.url
    except:
        pass
    return url

# 注入 requests
_real_get = requests.Session.get
def _patched_get(self, url, *a, **k):
    url = _auto_cdn(url)
    return _real_get(self, url, *a, **k)
requests.Session.get = _patched_get
# =================== 加速头结束 ===================
import sys
sys.path.append("..")
try:
    from base.spider import Spider
except ImportError:
    class Spider(object):
        def fetch(self, url, headers=None):
            import requests
            class R:
                def __init__(self, t):
                    self.text = t
                    self.content = t.encode("utf-8") if isinstance(t, str) else t

                def json(self):
                    import json
                    return json.loads(self.text)

            return R(requests.get(url, headers=headers or {}, timeout=15).text)


class Spider(Spider):
    def init(self, extend=""):
        self.base_url = "http://api.hclyz.com:81/mf"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        }

    def getName(self):
        return "色播聚合"

    def homeContent(self, filter):
        return {
            "class": [{"type_name": "色播聚合", "type_id": "all"}],
            "filters": {},
        }

    def homeVideoContent(self):
        try:
            r = self.categoryContent("all", "1", False, {})
            return {"list": (r.get("list") or [])[:24]}
        except Exception:
            return {"list": []}

    def _fix_pic(self, url):
        u = str(url or "")
        if "cdn.gcufbd.top/img/" in u:
            name = u.split("/")[-1]
            return (
                "https://slink.ltd/https://raw.githubusercontent.com/fish2018/lib/refs/heads/main/imgs/"
                + name
            )
        if u.startswith("http://"):
            return "https://" + u[7:]
        return u

    def categoryContent(self, tid, pg, filter, extend):
        videos = []
        try:
            rsp = self.fetch(self.base_url + "/json.txt", headers=self.headers)
            data = rsp.json() if hasattr(rsp, "json") else {}
            if isinstance(data, str):
                import json as _j
                data = _j.loads(data)
            raw = data.get("pingtai") or []
            # 跳过 Number=0 的空台
            items = []
            for it in raw:
                if not isinstance(it, dict):
                    continue
                try:
                    num = int(it.get("Number") or 0)
                except Exception:
                    num = 0
                if num <= 0:
                    continue
                addr = str(it.get("address") or "").strip()
                if not addr:
                    continue
                items.append(it)
            items.sort(key=lambda x: int(x.get("Number") or 0), reverse=True)
            for item in items:
                addr = str(item.get("address") or "").strip()
                if not addr.startswith("/"):
                    addr = "/" + addr
                videos.append(
                    {
                        "vod_id": addr,
                        "vod_name": item.get("title") or addr,
                        "vod_pic": self._fix_pic(item.get("xinimg")),
                        "vod_remarks": str(item.get("Number") or ""),
                        "style": {"type": "rect", "ratio": 1.33},
                    }
                )
        except Exception as e:
            print("sebo cat err", e)
        return {
            "page": int(pg or 1),
            "pagecount": 1,
            "limit": len(videos) or 1,
            "total": len(videos),
            "list": videos,
        }

    def detailContent(self, array):
        vid = str((array or [""])[0]).strip()
        if not vid.startswith("/"):
            vid = "/" + vid
        play_urls = []
        try:
            rsp = self.fetch(self.base_url + vid, headers=self.headers)
            data = rsp.json() if hasattr(rsp, "json") else {}
            if isinstance(data, str):
                import json as _j
                data = _j.loads(data)
            for z in data.get("zhubo") or []:
                title = str(z.get("title") or "直播")
                addr = str(z.get("address") or "").strip()
                if addr:
                    play_urls.append("%s$%s" % (title, addr))
        except Exception as e:
            print("sebo detail err", e)
        if not play_urls:
            play_urls = ["暂无$https://www.baidu.com"]
        return {
            "list": [
                {
                    "vod_id": vid,
                    "vod_name": vid.strip("/"),
                    "vod_content": "色播聚合",
                    "vod_play_from": "sebo",
                    "vod_play_url": "#".join(play_urls),
                    "style": {"type": "rect", "ratio": 1.33},
                }
            ]
        }

    def playerContent(self, flag, id, vipFlags):
        return {
            "parse": 0,
            "jx": 0,
            "url": str(id or "").strip(),
            "header": {
                "User-Agent": "Mozilla/5.0",
            },
        }

    def searchContent(self, key, quick, pg="1"):
        key = str(key or "").strip()
        if not key:
            return {"list": []}
        r = self.categoryContent("all", "1", False, {})
        out = []
        for v in r.get("list") or []:
            if key in str(v.get("vod_name") or ""):
                out.append(v)
        return {"list": out}

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def localProxy(self, param):
        pass
