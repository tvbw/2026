# -*- coding: utf-8 -*-
"""
黑料718 TVBox 爬虫 - 海报代理修复版
参照 51 模板的 localProxy 写法：
  - 图片请求走 self.headers（含 Origin/Referer）+ self.proxies
  - 失败返回 1x1 透明 PNG（不再显示放大镜）
"""

import re
import json
import sys
import time
import base64
import urllib.parse

import requests

try:
    if '..' not in sys.path:
        sys.path.append('..')
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object


# ============================ 基础配置 ============================
SITE = "https://clash.windowheiliao.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ===== 图片配置 =====
IMG_BASE = "https://pass.saxinx.cn/"     # 真实图片 CDN
IMG_AES = False                           # 黑料718=False; 51bl=True
AES_KEY = b"f5d965df75336270"
AES_IV = b"97b60394abc2fbe1"

_TRANSPARENT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)

CATEGORIES = [
    ("每日黑料", "daily-gossip"),
    ("黑料热榜", "top-stories"),
    ("娱乐黑料", "entertainment-news"),
    ("明星黑料", "celebrity-scandals"),
    ("黑料精华", "hljh"),
    ("网黄合集", "wanghuang"),
    ("网红吃瓜", "internet-celebrities"),
    ("福利姬料", "model-photos"),
    ("每日大赛", "daily-contest"),
    ("社会吃瓜", "trending-news"),
    ("反差婊们", "contrast-reveal"),
    ("真实乱伦", "zsll"),
    ("AI短剧成人", "AICG"),
]


def _clean(text):
    t = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", t).strip()


def _from_pyquery(html):
    try:
        from pyquery import PyQuery as pq
        return pq(html)
    except Exception:
        return None


class Spider(_BaseSpider):

    def __init__(self):
        self.name = "黑料718"
        self.host = SITE
        self.ua = UA
        self.timeout = 15
        self.categories = [{"type_id": slug, "type_name": name} for name, slug in CATEGORIES]

        # 和 51 模板一致：session 复用 + 常用 headers
        self.session = requests.Session()
        self.headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
            "Origin": SITE,
            "Referer": SITE + "/",
        }
        self.session.headers.update(self.headers)
        self.session.verify = False

        # 用户通过 TVBox extend 传入的代理，默认空
        self.proxies = {}

        self._home_html = ""
        self._home_ts = 0
        self._img_base_cache = ""

    # ---------------- 元信息 / 生命周期 ----------------
    def init(self, extend=""):
        # 参考 51 模板：解析 extend 得到用户配置的代理
        try:
            self.proxies = json.loads(extend) if extend else {}
        except Exception:
            self.proxies = {}
        print(f"[init] proxies = {self.proxies or '直连'}")

    def getName(self):
        return "黑料718"

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass

    def getDependence(self):
        return []

    def isVideoFormat(self, url):
        return any(ext in (url or "") for ext in [".m3u8", ".mp4", ".ts"])

    def manualVideoCheck(self):
        return False

    # ---------------- 加速：缓存 GET ----------------
    def _fetch(self, url, retries=2):
        for i in range(retries):
            try:
                r = self.session.get(url, timeout=self.timeout,
                                     proxies=self.proxies or None)
                if r.status_code == 200:
                    return r.text
            except Exception as e:
                if i < retries - 1:
                    time.sleep(0.3)
        return ""

    def _get_home(self):
        now = time.time()
        if self._home_html and now - self._home_ts < 300:
            return self._home_html
        self._home_html = self._fetch(SITE + "/")
        self._home_ts = now
        return self._home_html

    # ---------------- 图片 CDN 探测 ----------------
    def _img_base(self):
        if self._img_base_cache:
            return self._img_base_cache
        html = self._home_html or ""
        m = re.search(r'https?://([a-z0-9.-]+\.saxinx\.cn)', html, re.I)
        if m:
            self._img_base_cache = "https://" + m.group(1) + "/"
            return self._img_base_cache
        m = re.search(r'https?://([a-z0-9.-]+)/hl718/', html, re.I)
        if m:
            self._img_base_cache = "https://" + m.group(1) + "/"
            return self._img_base_cache
        self._img_base_cache = IMG_BASE
        return self._img_base_cache

    # ---------------- 图片 URL 规范化（一律走代理） ----------------
    def _normalize_img(self, url):
        url = (url or "").strip()
        if not url or "${" in url:
            return ""

        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("http"):
            pass
        elif url.startswith("/hl718/") or url.startswith("hl718/"):
            url = self._img_base().rstrip("/") + "/" + url.lstrip("/")
        elif url.startswith("/"):
            url = self.host.rstrip("/") + url
        else:
            url = self._img_base().rstrip("/") + "/" + url

        # 强制走代理（参照 51 模板，把真实 URL base64 后交给 localProxy 拉）
        return f"{self.getProxyUrl()}&url={self.e64(url)}&type=img"

    # ---------------- 列表解析 ----------------
    def _parse_list(self, html):
        vods = []
        seen = set()
        if not html:
            return vods
        doc = _from_pyquery(html)
        if doc is None:
            return vods
        self._img_base()

        for art in doc("article").items():
            try:
                art_html = art.html() or ""
            except Exception:
                continue
            if 'rel="sponsored' in art_html:
                continue

            mid = re.search(r"/archives/(\d+)", art_html)
            if not mid:
                continue
            aid = mid.group(1)
            if aid in seen:
                continue

            h2 = art("h2.post-card-title").eq(0)
            if not h2 or not h2.text():
                h2 = art("h2").eq(0)
            if not h2 or not h2.text():
                continue
            name = _clean(h2.text())
            if not name:
                continue

            pic = ""
            for sel, attr in (
                ('meta[itemprop="image"]', 'content'),
                ('[data-pic]', 'data-pic'),
                ('img[data-src]', 'data-src'),
                ('img[src]', 'src'),
            ):
                el = art(sel).eq(0)
                if not el:
                    continue
                v = (el.attr(attr) or "").strip()
                if v and "${" not in v and not v.startswith("data:"):
                    pic = self._normalize_img(v)
                    break

            seen.add(aid)
            vods.append({
                "vod_id": aid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": "",
            })
        return vods

    # ---------------- TVBox 五大接口 ----------------
    def homeContent(self, filter=True):
        try:
            html = self._get_home()
            vods = self._parse_list(html)
        except Exception as e:
            print(f"homeContent error: {e}")
            vods = []
        return {"class": self.categories, "list": vods[:30]}

    def homeVideoContent(self):
        try:
            html = self._get_home()
            return {"list": self._parse_list(html)[:30]}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg=1, filter=1, extend=None):
        try:
            pg = int(pg)
        except Exception:
            pg = 1

        if not tid or tid == "home":
            url = SITE + ("/page/%d/" % pg if pg > 1 else "/")
        else:
            url = SITE + ("/category/%s/" % tid if pg == 1
                          else "/category/%s/%d/" % (tid, pg))

        html = ""
        try:
            html = self._fetch(url)
            vods = self._parse_list(html)
        except Exception as e:
            print(f"categoryContent error: {e}")
            vods = []

        total_pages = 999
        if html:
            doc = _from_pyquery(html)
            if doc is not None:
                pinfo = doc('.page-jump .page-info').text() or ''
                if '/' in pinfo:
                    try:
                        total_pages = int(pinfo.split('/')[-1].strip())
                    except Exception:
                        pass
                if total_pages == 999:
                    mx = (doc('#pageNum').attr('max') or '').strip()
                    if mx.isdigit():
                        total_pages = int(mx)

        return {
            "list": vods,
            "page": pg,
            "pagecount": total_pages,
            "total": total_pages * 30 if total_pages > 0 else 0,
            "limit": 30,
        }

    def detailContent(self, ids):
        aid = ids[0] if isinstance(ids, (list, tuple)) else str(ids)
        aid = str(aid)
        html = ""
        try:
            html = self._fetch(SITE + "/archives/%s" % aid)
        except Exception:
            pass

        if not html:
            return {"list": [{
                "vod_id": aid, "vod_name": "详情获取失败", "vod_pic": "",
                "vod_play_from": "黑料", "vod_play_url": "",
                "vod_remarks": "详情页无法访问",
            }]}

        title = ""
        tm = re.search(r"<title>([^<]+)</title>", html)
        if tm:
            title = _clean(tm.group(1)).split(" - ")[0]

        pic = ""
        for pat in (r'itemprop="image" content="([^"]+)"',
                    r'data-pic=["\']([^"\']+)["\']'):
            im = re.search(pat, html)
            if im and "${" not in im.group(1):
                pic = self._normalize_img(im.group(1))
                break

        sources = []
        for cfg in re.findall(r"data-config='(\{.*?\})'", html, re.S):
            try:
                d = json.loads(cfg)
            except Exception:
                continue
            v = d.get("video", {}) or {}
            url = v.get("url2") or v.get("url")
            if url and url not in sources:
                sources.append(url)
        if not sources:
            sources = re.findall(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', html)

        if not sources:
            return {"list": [{
                "vod_id": aid, "vod_name": title or "图文内容", "vod_pic": pic,
                "vod_play_url": "", "vod_remarks": "该条为图文, 无视频源",
            }]}

        episodes = ["第%d集$%s" % (i, s) for i, s in enumerate(sources, 1)]
        return {"list": [{
            "vod_id": aid, "vod_name": title, "vod_pic": pic,
            "vod_play_from": "黑料",
            "vod_play_url": "#".join(episodes),
            "vod_remarks": "%d个视频" % len(sources),
        }]}

    def searchContent(self, key, quick=False, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        q = urllib.parse.quote(key)
        url = (SITE + "/search/%s/" % q) if pg == 1 else (SITE + "/search/%s/%d/" % (q, pg))
        try:
            html = self._fetch(url)
            vods = self._parse_list(html)
        except Exception:
            vods = []
        return {"list": vods, "page": pg, "pagecount": 50, "total": 50 * 30, "limit": 30}

    def playerContent(self, flag, id, vipFlags=None):
        return {
            "parse": 0,
            "url": id,
            "header": {
                "User-Agent": UA,
                "Referer": SITE + "/",
            },
        }

    # ================= 图片代理（参照 51 模板核心修复） =================
    def localProxy(self, param):
        t = param.get("type")
        if t == "img":
            # 完全参照 51 模板：用 self.headers（含 Origin/Referer）+ self.proxies
            real_url = param.get("url") or ""
            # 如果框架没解码 base64，就手动解一次（双保险）
            if real_url.startswith("aHR0") or not real_url.startswith("http"):
                try:
                    real_url = self.d64(real_url) or real_url
                except Exception:
                    pass
            print(f"[img] 请求: {real_url[:100]}")

            for attempt in range(2):
                try:
                    res = requests.get(
                        real_url,
                        headers=self.headers,          # 含 Origin/Referer
                        proxies=self.proxies or None,  # ← 关键：走用户代理
                        timeout=10,
                        verify=False,
                    )
                    ct = res.headers.get("Content-Type", "")
                    print(f"[img] HTTP {res.status_code}, ct={ct}, "
                          f"len={len(res.content)}")
                    if res.status_code == 200 and len(res.content) > 100:
                        if "html" in ct.lower():
                            print(f"[img] 返回 HTML（被拦截）")
                        else:
                            content = res.content
                            if IMG_AES:
                                try:
                                    content = self.aesimg(content)
                                except Exception as e:
                                    print(f"[img] AES 解密失败: {e}")
                            return [200, ct or "image/webp", content]
                except Exception as e:
                    print(f"[img] 异常: {e}")
                if attempt == 0:
                    time.sleep(0.2)

            print(f"[img] 最终失败，返回透明 PNG")
            return [200, "image/png", _TRANSPARENT_PNG]

        if t == "m3u8":
            return self.m3Proxy(param["url"])
        return self.tsProxy(param["url"])

    def proxy(self, data, type="m3u8"):
        if type == "img":
            return f"{self.getProxyUrl()}&url={self.e64(data)}&type=img"
        if data and len(getattr(self, "proxies", {})) > 0:
            return f"{self.getProxyUrl()}&url={self.e64(data)}&type={type}"
        return data

    def m3Proxy(self, url):
        url = self.d64(url)
        try:
            ydata = self.session.get(url, allow_redirects=False, timeout=15,
                                     proxies=self.proxies or None)
            data = ydata.content.decode("utf-8", "ignore")
            if ydata.headers.get("Location"):
                url = ydata.headers["Location"]
                data = self.session.get(url, timeout=15,
                                        proxies=self.proxies or None).content.decode("utf-8", "ignore")
        except Exception:
            return [500, "text/plain", b""]

        from urllib.parse import urlparse
        lines = data.strip().split("\n")
        last_r = url[:url.rfind("/")]
        parsed = urlparse(url)
        durl = parsed.scheme + "://" + parsed.netloc
        iskey = True
        for i, s in enumerate(lines):
            if iskey and "URI" in s:
                m = re.search(r'URI="([^"]*)"', s)
                if m:
                    lines[i] = re.sub(r'URI="([^"]*)"',
                                      f'URI="{self.proxy(m.group(1), "mkey")}"', s)
                    iskey = False
                    continue
            if "#EXT" not in s:
                if "http" not in s:
                    domain = last_r if s.count("/") < 2 else durl
                    s = domain + ("" if s.startswith("/") else "/") + s
                lines[i] = self.proxy(s, s.split(".")[-1].split("?")[0])
        return [200, "application/vnd.apple.mpegur", "\n".join(lines)]

    def tsProxy(self, url):
        url = self.d64(url)
        try:
            r = self.session.get(url, timeout=15, proxies=self.proxies or None)
            return [200, r.headers.get("Content-Type", "video/mp2t"), r.content]
        except Exception:
            return [500, "text/plain", b""]

    # ---------------- Base64 / AES ----------------
    def e64(self, text):
        try:
            return base64.b64encode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def d64(self, text):
        try:
            return base64.b64decode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def aesimg(self, word):
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
        cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        return unpad(cipher.decrypt(word), AES.block_size)


if __name__ == "__main__":
    _sp = Spider()
    _sp.init()
    print("== homeContent ==")
    _h = _sp.homeContent()
    print("   分类:", len(_h.get("class", [])), "推荐:", len(_h.get("list", [])))
    if _h.get("list"):
        v = _h["list"][0]
        print("   封面代理URL:", v["vod_pic"][:120])
        # 模拟 localProxy 拉图
        m = re.search(r'url=([A-Za-z0-9+/=]+)', v["vod_pic"])
        if m:
            real = _sp.d64(m.group(1))
            print("   真实URL:", real)
            r = _sp.localProxy({"url": real, "type": "img"})
            print(f"   代理返回: status={r[0]}, ct={r[1]}, len={len(r[2])}")
            if r[1] == "image/png" and len(r[2]) < 200:
                print("   ❌ 代理失败（返回透明 PNG）")
            else:
                print("   ✅ 代理成功")
