# -*- coding: utf-8 -*-
"""
黑料718 TVBox 爬虫 - 图片全自动诊断版
=========================================================
图片加载全自动策略：
  1. init 时探测本地常见代理端口（7890 / 7897 / 1080 等）
  2. 首次请求图片时，依次尝试：3 种请求头 × 3 种代理组合
  3. 找到第一个能返回有效图片的组合后固化，后续图片直接用
  4. 全部失败 → weserv.nl 第三方图片代理兜底
  5. 仍失败 → 1x1 透明 PNG（不显示放大镜）

【看日志找答案】
  TVBox 里看 py 输出，会有类似：
    [init] 配置代理: 无
    [init] 自动探测到本地代理: {'http':'http://127.0.0.1:7890','https':...}
    [detect] image-cors+direct: HTTP 200 ct=image/webp len=72950 valid=True
    [detect] ✅ 有效策略: image-cors+direct
    [img] ✅ 使用 image-cors+direct -> len=72950

  如果全部打印 ❌，说明盒子网络彻底访问不了 pass.saxinx.cn，
  需要给盒子配代理或者接受 weserv 中转。
"""

import base64
import json
import re
import sys
import threading
import time
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
      "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36")

IMG_BASE = "https://pass.saxinx.cn/"

# 1x1 透明 PNG
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


# ============================ Spider 类 ============================
class Spider(_BaseSpider):

    def __init__(self):
        self.name = "黑料718"
        self.host = SITE
        self.timeout = 15
        self.categories = [{"type_id": slug, "type_name": name} for name, slug in CATEGORIES]

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Referer": SITE + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "keep-alive",
        })
        self.session.verify = False
        try:
            import urllib3
            urllib3.disable_warnings()
        except Exception:
            pass

        self.proxies = {}
        self._home_html = ""
        self._home_ts = 0
        self._img_base_cache = ""

        # 图片策略缓存
        self._img_strategy = None
        self._img_lock = threading.Lock()

    # ---------------- 生命周期 ----------------
    def init(self, extend=""):
        try:
            self.proxies = json.loads(extend) if extend else {}
        except Exception:
            self.proxies = {}
        print(f"[init] 配置代理: {self.proxies or '无'}")

        # 未配置代理时自动探测本地常见端口
        if not self.proxies:
            detected = self._detect_local_proxy()
            if detected:
                self.proxies = detected
                print(f"[init] 自动探测到本地代理: {detected}")
            else:
                print(f"[init] 未探测到本地代理，将直连")

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

    # ==================== 本地代理探测 ====================
    def _detect_local_proxy(self):
        """尝试常见的本地代理端口"""
        test_url = "https://pass.saxinx.cn/usr/themes/Mirages/images/logo.webp"
        ports = [7890, 7897, 1080, 10808, 1087, 8889, 8080, 8118, 8081]
        for port in ports:
            p = f"http://127.0.0.1:{port}"
            try:
                r = requests.get(test_url,
                                 proxies={"http": p, "https": p},
                                 timeout=2, verify=False)
                if r.status_code == 200 and len(r.content) > 100:
                    print(f"[init] 端口 {port} 有效（返回 {len(r.content)} 字节）")
                    return {"http": p, "https": p}
            except Exception:
                pass
        return None

    # ==================== 加速：GET ====================
    def _fetch(self, url, retries=2):
        for i in range(retries):
            try:
                r = self.session.get(url, timeout=self.timeout,
                                     proxies=self.proxies or None)
                if r.status_code == 200:
                    return r.text
            except Exception:
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

    # ==================== 图片 CDN 探测 ====================
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

    # ==================== 图片 URL 规范化 ====================
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
        # 一律走本地代理
        return f"{self.getProxyUrl()}&url={self.e64(url)}&type=img"

    # ==================== 列表解析 ====================
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

    # ==================== TVBox 接口 ====================
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

    # ==================== 图片代理（全自动探测） ====================
    def localProxy(self, param):
        t = param.get("type")
        if t == "img":
            return self._img_proxy(param)
        if t == "m3u8":
            return self.m3Proxy(param["url"])
        return self.tsProxy(param["url"])

    def _img_proxy(self, param):
        # 1. 解码真实 URL
        real_url = param.get("url") or ""
        if not real_url.startswith("http"):
            try:
                real_url = self.d64(real_url) or real_url
            except Exception:
                pass
        if not real_url.startswith("http"):
            print(f"[img] 无效URL: {real_url[:80]}")
            return [200, "image/png", _TRANSPARENT_PNG]

        # 2. 用已缓存的策略
        with self._img_lock:
            strategy = self._img_strategy

        if strategy:
            content = self._fetch_with_strategy(real_url, strategy)
            if content:
                print(f"[img] ✅ 使用 {strategy['label']} -> len={len(content)}")
                return [200, "image/webp", content]
            print(f"[img] 缓存策略 {strategy['label']} 失效，重新探测")
            with self._img_lock:
                self._img_strategy = None

        # 3. 首次或策略失效，全策略探测
        content, strategy = self._detect_strategy(real_url)
        if content:
            with self._img_lock:
                self._img_strategy = strategy
            print(f"[img] ✅ 新策略 {strategy['label']} -> len={len(content)}")
            return [200, "image/webp", content]

        # 4. 全部失败
        print(f"[img] ❌ 全部策略失败，返回透明占位")
        return [200, "image/png", _TRANSPARENT_PNG]

    def _detect_strategy(self, url):
        """依次尝试 3 种请求头 × 多种代理组合 + weserv 兜底"""
        header_sets = [
            ("img-cors", self._h_img_cors()),
            ("fetch-cors", self._h_fetch_cors()),
            ("minimal", self._h_minimal()),
        ]
        # 代理组合去重
        proxy_candidates = [("direct", None)]
        if self.proxies:
            proxy_candidates.append(("configured", self.proxies))
        proxy_candidates.append(
            ("local7890", {"http": "http://127.0.0.1:7890",
                           "https": "http://127.0.0.1:7890"})
        )
        seen = set()
        proxy_sets = []
        for name, p in proxy_candidates:
            key = str(p) if p else "None"
            if key in seen:
                continue
            seen.add(key)
            proxy_sets.append((name, p))

        for hname, headers in header_sets:
            for pname, proxies in proxy_sets:
                label = f"{hname}+{pname}"
                try:
                    r = requests.get(url, headers=headers, proxies=proxies,
                                     timeout=8, verify=False)
                    ct = r.headers.get("content-type", "")
                    size = len(r.content)
                    valid = self._is_image(r.content)
                    print(f"[detect] {label}: HTTP {r.status_code} ct={ct} "
                          f"len={size} valid={valid}")
                    if r.status_code == 200 and valid:
                        print(f"[detect] ✅ 有效策略: {label}")
                        return r.content, {"headers": headers,
                                           "proxies": proxies, "label": label}
                except Exception as e:
                    print(f"[detect] {label}: {type(e).__name__}: {str(e)[:60]}")

        # weserv 兜底
        try:
            wurl = f"https://images.weserv.nl/?url={urllib.parse.quote(url, safe='')}"
            print(f"[detect] weserv: 尝试 {wurl[:100]}")
            r = requests.get(wurl, timeout=15, verify=False,
                             proxies=self.proxies or None)
            if r.status_code == 200 and self._is_image(r.content):
                print(f"[detect] ✅ weserv 成功: len={len(r.content)}")
                return r.content, {"is_weserv": True, "label": "weserv"}
        except Exception as e:
            print(f"[detect] weserv: {type(e).__name__}: {str(e)[:60]}")

        return None, None

    def _fetch_with_strategy(self, url, strategy):
        try:
            if strategy.get("is_weserv"):
                wurl = f"https://images.weserv.nl/?url={urllib.parse.quote(url, safe='')}"
                r = requests.get(wurl, timeout=15, verify=False,
                                 proxies=self.proxies or None)
            else:
                r = requests.get(url,
                                 headers=strategy["headers"],
                                 proxies=strategy["proxies"],
                                 timeout=10, verify=False)
            if r.status_code == 200 and self._is_image(r.content):
                return r.content
        except Exception as e:
            print(f"[img] 策略异常: {type(e).__name__}: {str(e)[:60]}")
        return None

    def _is_image(self, content):
        if not content or len(content) < 100:
            return False
        if content[:4] == b'RIFF' and content[8:12] == b'WEBP':
            return True
        if content[:8] == b'\x89PNG\r\n\x1a\n':
            return True
        if content[:3] == b'\xff\xd8\xff':
            return True
        if content[:6] in (b'GIF87a', b'GIF89a'):
            return True
        return False

    def _h_img_cors(self):
        return {
            "User-Agent": UA,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": SITE,
            "Referer": SITE + "/",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
        }

    def _h_fetch_cors(self):
        return {
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": SITE,
            "Referer": SITE + "/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
        }

    def _h_minimal(self):
        return {
            "User-Agent": UA,
            "Referer": SITE + "/",
        }

    # ==================== M3U8/TS 代理 ====================
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

    # ==================== Base64 ====================
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


if __name__ == "__main__":
    _sp = Spider()
    _sp.init()
    print("== homeContent ==")
    _h = _sp.homeContent()
    print(f"   分类: {len(_h.get('class', []))}  推荐: {len(_h.get('list', []))}")
    if _h.get("list"):
        v = _h["list"][0]
        print(f"   封面代理URL: {v['vod_pic'][:120]}")
        m = re.search(r'url=([A-Za-z0-9+/=]+)', v["vod_pic"])
        if m:
            real = _sp.d64(m.group(1))
            print(f"   真实URL: {real}")
            r = _sp.localProxy({"url": real, "type": "img"})
            print(f"   代理返回: ct={r[1]}, len={len(r[2])}")
