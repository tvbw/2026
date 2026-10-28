# ============================================================
# 51通用模板 · 动态发布页自愈版 V5（彻底对齐参考代码原理）
# 专为链路：51bla18.com → 302 → djrqnywk.cc → 页面链接 → 主站
# 核心：urllib引擎 + 多级跳转跟踪 + 严格主站验证
# ============================================================
import sys
import os
import re
import json
import base64
import urllib.request
import urllib.parse
import http.cookiejar
import gzip
import zlib
import ssl
import time
from urllib.parse import urlparse, quote, unquote

sys.path.append('..')
from base.spider import Spider

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        def getCache(self, key): return None
        def setCache(self, key, value): return "fail"
        def delCache(self, key): return "fail"


class Spider(SpiderBase):
    def __init__(self):
        super(Spider, self).__init__()
        # 发布页入口（会自动跟踪302跳转）
        self.navUrls = [
            "https://51bla18.com/",
            "https://51bla19.com/",
            "https://51bla20.com/",
        ]
        # 无默认兜底，完全依赖自愈
        self.defaultHost = ""
        self.siteUrl = self.defaultHost
        self.siteName = "51通用"
        self._ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/134.0.0.0 Safari/537.36"
        )
        self.options = {}

        # 模仿参考代码：全局禁用SSL验证，避免证书导致的跳转失败
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx)
        )

        # 主站验证选择器（必须是主站首页独有的结构）
        self.host_check_selector = "#index article a"
        # 发布页自身的域名（用于排除）
        self.publish_hosts = {"51bla18.com", "51bla19.com", "51bla20.com"}

    def init(self, extend=""):
        if isinstance(extend, dict):
            self.options = extend
        elif extend:
            try:
                self.options = json.loads(extend)
            except Exception:
                self.options = {}

        # 从缓存读取，否则刷新
        cached = self.getCache("51_dynamic_site_url")
        if cached and cached.startswith("http"):
            self.siteUrl = cached.strip().rstrip("/")
        else:
            self._refresh_site_url()
        return True

    def getName(self):
        return "51通用·动态自愈版"

    def isVideoFormat(self, url):
        low = (url or "").lower()
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".mkv", ".ts", ".mpd"))

    def manualVideoCheck(self):
        return False

    # ============================================================
    # 核心：刷新主站URL（完全模仿参考代码的urllib引擎）
    # ============================================================
    def _refresh_site_url(self):
        headers = {
            "User-Agent": self._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        }

        for nav in self.navUrls:
            # 1. 请求发布入口，手动跟踪所有重定向，拿到最终发布页HTML
            text, final_url = self._fetch_with_redirect(nav, headers, timeout=10)
            if not text:
                continue

            # 记录跳转后的发布页域名（如 djrqnywk.cc），用于后续排除
            publish_host = urlparse(final_url).netloc
            if publish_host:
                self.publish_hosts.add(publish_host)

            # 2. 从发布页HTML中提取所有候选链接
            candidates = self._extract_candidate_urls(text, final_url)
            if not candidates:
                continue

            # 3. 对每个候选域名进行严格验证
            for cand in candidates:
                base = "%s://%s" % (urlparse(cand).scheme, urlparse(cand).netloc)
                # 严格验证：请求首页，检查是否包含主站特有的文章列表
                chk = self._fetch(base + "/", check_host=False)
                if chk.get("code") == 200 and self.host_check_selector in chk.get("text", ""):
                    self.siteUrl = base
                    self.setCache("51_dynamic_site_url", base)
                    print(f"[自愈成功] 主站: {base}")
                    return True

        print("[自愈失败] 未找到可用主站")
        return False

    # ------------------------------------------------------------
    # 手动跟踪重定向（urllib默认会跟踪，但这里显式处理）
    # ------------------------------------------------------------
    def _fetch_with_redirect(self, url, headers, timeout=10, max_redirects=5):
        """请求URL，跟随最多max_redirects次重定向，返回(最终HTML, 最终URL)"""
        for _ in range(max_redirects + 1):
            try:
                req = urllib.request.Request(url, headers=headers)
                with self.opener.open(req, timeout=timeout) as resp:
                    final_url = resp.geturl()
                    raw = resp.read()
                    enc = (resp.headers.get("Content-Encoding", "") or "").lower()
                    if raw.startswith(b"\x1f\x8b") or enc == "gzip":
                        raw = gzip.decompress(raw)
                    elif enc == "deflate":
                        try:
                            raw = zlib.decompress(raw)
                        except Exception:
                            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                    text = raw.decode("utf-8", errors="ignore")
                    return text, final_url
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303, 307, 308):
                    loc = e.headers.get("Location")
                    if loc:
                        url = urllib.parse.urljoin(url, loc)
                        continue
                # 其他错误，尝试读取响应体（可能包含有用信息）
                try:
                    raw = e.read()
                    if raw.startswith(b"\x1f\x8b"):
                        raw = gzip.decompress(raw)
                    text = raw.decode("utf-8", errors="ignore")
                    return text, url
                except Exception:
                    pass
                return "", url
            except Exception:
                return "", url
        return "", url

    # ------------------------------------------------------------
    # 从发布页HTML中提取所有候选URL
    # ------------------------------------------------------------
    def _extract_candidate_urls(self, html, base_url):
        """提取页面中所有<a>标签的href，以及文本中的裸域名，过滤掉发布页自身和CDN"""
        candidates = []
        seen = set()

        # 方法1：提取所有<a href>
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', html, re.I):
            href = m.group(1).strip()
            url = self._normalize_url(href, base_url)
            if url:
                host = urlparse(url).netloc.lower()
                if host in self.publish_hosts:
                    continue
                if self._is_blacklisted(host):
                    continue
                base = f"{urlparse(url).scheme}://{host}"
                if base not in seen:
                    seen.add(base)
                    candidates.append(base)

        # 方法2：正则扫描文本中的裸域名（如 xxx.luwhogpx.cc）
        for m in re.finditer(r'([a-zA-Z0-9][a-zA-Z0-9\-\.]{2,}\.[a-zA-Z]{2,})', html):
            host = m.group(1).lower()
            if host in self.publish_hosts:
                continue
            if self._is_blacklisted(host):
                continue
            if "." not in host or host.count(".") < 1:
                continue
            base = "https://" + host
            if base not in seen:
                seen.add(base)
                candidates.append(base)

        return candidates

    def _normalize_url(self, u, base):
        if not u:
            return ""
        u = u.strip()
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/") and base:
            p = urlparse(base)
            u = f"{p.scheme}://{p.netloc}{u}"
        if not u.startswith("http") or "." not in u:
            return ""
        if any(x in u for x in ["javascript:", "mailto:", "tel:", "#"]):
            return ""
        return u

    def _is_blacklisted(self, host):
        blacklist = [
            "google", "facebook", "twitter", "cloudflare", "gstatic",
            "googletagmanager", "doubleclick", "jsdelivr", "cdnjs", "unpkg",
            "jquery", "fontawesome", "baidu", "51.la", "cnzz", "umeng",
            "w3.org", "schema.org", "telegram", "t.me", "youtube",
            "instagram", "tiktok", "weibo", "qq.com", "weixin",
        ]
        host_l = host.lower()
        return any(kw in host_l for kw in blacklist)

    # ============================================================
    # 统一请求方法（完全模仿参考代码的_fetch，包含失效重试）
    # ============================================================
    def _fetch(self, target_url, referer="", check_host=True):
        if not target_url:
            return {"code": 0, "text": "", "err": "", "final_url": ""}
        if target_url.startswith("//"):
            target_url = "https:" + target_url
        elif target_url.startswith("/"):
            target_url = self.siteUrl + target_url

        headers = {
            "User-Agent": self._ua,
            "Referer": referer if referer else (self.siteUrl + "/"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

        last_err = ""
        domain_retried = False

        for attempt in range(2):
            try:
                req = urllib.request.Request(target_url, headers=headers)
                with self.opener.open(req, timeout=12) as resp:
                    code = resp.getcode()
                    final_url = resp.geturl()
                    raw = resp.read()
                    enc = (resp.headers.get("Content-Encoding", "") or "").lower()
                    if raw.startswith(b"\x1f\x8b") or enc == "gzip":
                        raw = gzip.decompress(raw)
                    elif enc == "deflate":
                        try:
                            raw = zlib.decompress(raw)
                        except Exception:
                            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                    text = raw.decode("utf-8", errors="ignore")
                    return {"code": code, "text": text, "err": "", "final_url": final_url}
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}"
                # 关键：遇到主站失效，自动触发刷新并重试
                if e.code in (404, 451, 502, 503) and check_host and not domain_retried:
                    old_host = urlparse(self.siteUrl).netloc
                    self.delCache("51_dynamic_site_url")
                    if self._refresh_site_url():
                        domain_retried = True
                        new_host = urlparse(self.siteUrl).netloc
                        target_url = target_url.replace(old_host, new_host)
                        continue
                if e.code in (451, 403, 429) and attempt == 0:
                    continue
                return {"code": e.code, "text": "", "err": str(e), "final_url": target_url}
            except Exception as e:
                last_err = str(e)
                if check_host and not domain_retried:
                    old_host = urlparse(self.siteUrl).netloc
                    self.delCache("51_dynamic_site_url")
                    if self._refresh_site_url():
                        domain_retried = True
                        new_host = urlparse(self.siteUrl).netloc
                        target_url = target_url.replace(old_host, new_host)
                        continue
                if attempt == 0:
                    continue
                return {"code": -1, "text": "", "err": str(e), "final_url": target_url}

        return {"code": -1, "text": "", "err": last_err, "final_url": target_url}

    # ============================================================
    # 首页 / 分类 / 详情 / 搜索（保持原模板逻辑，仅将请求替换为_fetch）
    # ============================================================
    def homeContent(self, filter):
        try:
            res = self._fetch(self.siteUrl + "/")
            if res.get("code") != 200:
                return {"class": [], "list": []}
            html = res.get("text", "")
            # 提取分类（保持原逻辑）
            classes = []
            for selector in [".category-list ul li", ".nav-menu li", ".menu li", "nav ul li"]:
                # 这里用简单的正则替代PyQuery，减少依赖
                pattern = r'<li[^>]*>\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>'
                for m in re.finditer(pattern, html):
                    href, name = m.group(1).strip(), m.group(2).strip()
                    if href and href != "#" and name:
                        classes.append({"type_name": name, "type_id": href})
                if classes:
                    break
            if not classes:
                classes = [
                    {"type_name": "首页", "type_id": "/"},
                    {"type_name": "最新", "type_id": "/latest/"},
                    {"type_name": "热门", "type_id": "/hot/"},
                ]
            # 首页视频列表
            videos = self._parse_video_list(html, "")
            return {"class": classes, "list": videos}
        except Exception as e:
            print(f"homeContent error: {e}")
            return {"class": [], "list": []}

    def homeVideoContent(self):
        try:
            res = self._fetch(self.siteUrl + "/")
            if res.get("code") != 200:
                return {"list": []}
            return {"list": self._parse_video_list(res.get("text", ""), "")}
        except Exception as e:
            print(f"homeVideoContent error: {e}")
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
            tid = tid.rstrip("/")
            url = f"{self.siteUrl}{tid}/{pg}/" if pg > 1 else f"{self.siteUrl}{tid}/"
            res = self._fetch(url)
            if res.get("code") != 200:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 90, "total": 0}
            html = res.get("text", "")
            videos = self._parse_video_list(html, tid)
            return {
                "list": videos,
                "page": pg,
                "pagecount": 999 if len(videos) > 0 else 1,
                "limit": 90,
                "total": 9999,
            }
        except Exception as e:
            print(f"categoryContent error: {e}")
            return {"list": [], "page": pg, "pagecount": 1, "limit": 90, "total": 0}

    def detailContent(self, ids):
        try:
            raw_id = ids[0] if ids else ""
            url = raw_id if raw_id.startswith("http") else f"{self.siteUrl}{raw_id}"
            res = self._fetch(url)
            if res.get("code") != 200:
                return {"list": [{"vod_play_from": "51通用", "vod_play_url": f"加载失败${url}"}]}
            html = res.get("text", "")
            doc = self.getpq(html)
            # 标题
            title = ""
            t = doc(".post-title").text() or doc("h1").text()
            if t:
                title = t.strip()
            # 播放器
            plist = self._parse_players(doc)
            vod = {
                "vod_play_from": "51通用",
                "vod_play_url": "#".join(plist) if plist else f"无源${url}",
                "vod_name": title,
            }
            return {"list": [vod]}
        except Exception as e:
            print(f"detailContent error: {e}")
            return {"list": [{"vod_play_from": "51通用", "vod_play_url": f"详情失败${ids[0] if ids else ''}"}]}

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg)
            if pg > 1:
                url = f"{self.siteUrl}/search/{key}/{pg}/"
            else:
                url = f"{self.siteUrl}/search/{key}/"
            res = self._fetch(url)
            if res.get("code") != 200:
                return {"list": [], "page": pg}
            videos = self._parse_video_list(res.get("text", ""), "")
            return {"list": videos, "page": pg}
        except Exception as e:
            print(f"searchContent error: {e}")
            return {"list": [], "page": pg}

    def playerContent(self, flag, id, vipFlags):
        url = id
        parse = 1
        if self.isVideoFormat(url):
            if ".m3u8" in url:
                url = self.proxy(url)
            parse = 0
        return {"parse": parse, "url": url, "header": self.headers if hasattr(self, 'headers') else {}}

    # ============================================================
    # 辅助解析方法（简化版，使用正则替代PyQuery以减少依赖）
    # ============================================================
    def _parse_video_list(self, html, tid=""):
        """从列表页HTML解析视频条目（模仿原模板的getlist）"""
        videos = []
        # 匹配 article 标签内的链接和标题
        pattern = r'<article[^>]*>.*?<a[^>]+href=["\']([^"\']+)["\'][^>]*>.*?<h2[^>]*>([^<]+)</h2>.*?</article>'
        for m in re.finditer(pattern, html, re.I | re.S):
            href = m.group(1).strip()
            name = m.group(2).strip()
            if href and name:
                videos.append({
                    "vod_id": href,
                    "vod_name": name,
                    "vod_pic": "",
                    "vod_remarks": "",
                })
        # 如果article没匹配到，尝试更宽松的模式
        if not videos:
            pattern2 = r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>.*?<h2[^>]*>([^<]+)</h2>'
            for m in re.finditer(pattern2, html, re.I | re.S):
                href = m.group(1).strip()
                name = m.group(2).strip()
                if href and name and "/mrdg" not in href:
                    videos.append({
                        "vod_id": href,
                        "vod_name": name,
                        "vod_pic": "",
                        "vod_remarks": "",
                    })
        return videos

    def _parse_players(self, doc):
        """解析播放器（保持原模板逻辑，但使用简单正则）"""
        plist = []
        html = doc.html() if hasattr(doc, 'html') else str(doc)
        # 匹配 dplayer 的 data-config
        for m in re.finditer(r'<div[^>]+class=["\'][^"\']*dplayer[^"\']*["\'][^>]+data-config=["\']([^"\']+)["\']', html):
            try:
                cfg = json.loads(m.group(1))
                video_url = cfg.get("video", {}).get("url", "")
                if video_url:
                    plist.append(f"视频{len(plist)+1}${video_url}")
            except Exception:
                pass
        # 回退：匹配 video/iframe src
        if not plist:
            for m in re.finditer(r'<(?:video|iframe)[^>]+src=["\']([^"\']+)["\']', html):
                src = m.group(1).strip()
                if src:
                    plist.append(f"视频{len(plist)+1}${src}")
        return plist

    def getpq(self, data):
        """简单包装，用于兼容"""
        try:
            from pyquery import PyQuery as pq
            return pq(data)
        except Exception:
            return data

    # ============================================================
    # 缓存方法（框架自带，保持原样）
    # ============================================================
    def getCache(self, key):
        return SpiderBase.getCache(self, key)

    def setCache(self, key, value):
        return SpiderBase.setCache(self, key, value)

    def delCache(self, key):
        return SpiderBase.delCache(self, key)


# 注册
try:
    SpiderBase.register(Spider())
except Exception:
    pass
