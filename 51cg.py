# ============================================================
# 51通用模板 · 动态发布页自愈版 V6
# 专为“多级跳转发布页”设计，核心是“跟随302 + 提取链接”
# 链路：51bla18.com →(302)→ djrqnywk.cc →(页面<a>链接)→ 主站
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
        # --- 配置区 ---
        # 固定发布入口（会自动跟随302）
        self.navUrls = [
            "https://51bla18.com/",
            "https://51bla19.com/",
            "https://51bla20.com/",
        ]
        # 主站首页必须包含的特征（用于严格验证，防止把发布页误判为主站）
        self.host_check_selector = "#index article a"
        # -----------------

        self.siteUrl = ""
        self.siteName = "51通用"
        self._ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
        self.options = {}

        # 模仿参考代码：全局禁用SSL验证，避免证书问题中断跳转链
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx)
        )

        # 用于识别和排除发布页自身的域名
        self.publish_hosts = set()

    def init(self, extend=""):
        if isinstance(extend, dict):
            self.options = extend
        elif extend:
            try:
                self.options = json.loads(extend)
            except Exception:
                self.options = {}

        cached = self.getCache("51_dynamic_site_url")
        if cached and cached.startswith("http"):
            self.siteUrl = cached.strip().rstrip("/")
        else:
            # 启动时若缓存无效，则触发一次完整的发现流程
            self._refresh_site_url()
        return True

    def getName(self):
        return "51通用·动态自愈版(V6)"

    def isVideoFormat(self, url):
        low = (url or "").lower()
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".mkv", ".ts"))

    def manualVideoCheck(self):
        return False

    # ============================================================
    # 核心自愈方法：跟随跳转 -> 提取链接 -> 严格验证
    # ============================================================
    def _refresh_site_url(self):
        """遍历发布入口，发现并验证主站，成功后更新 self.siteUrl 并写入缓存"""
        for nav_url in self.navUrls:
            try:
                # 步骤1：请求入口，自动跟随所有302/301跳转，拿到最终发布页的HTML和URL
                html, final_url = self._fetch_with_redirect(nav_url)
                if not html:
                    continue

                # 记录发布页域名，后续提取时排除掉
                pub_host = urlparse(final_url).netloc
                if pub_host:
                    self.publish_hosts.add(pub_host)

                # 步骤2：从发布页HTML中提取所有可能的候选链接
                candidates = self._extract_links_from_page(html, final_url)
                if not candidates:
                    continue

                # 步骤3：对每个候选域名进行严格验证
                for candidate_url in candidates:
                    parsed = urlparse(candidate_url)
                    base_url = f"{parsed.scheme}://{parsed.netloc}"
                    # 发起请求，检查页面是否包含主站特征
                    check = self._fetch(base_url + "/", check_host=False)
                    if check.get("code") == 200 and self.host_check_selector in check.get("text", ""):
                        # 验证通过，这就是主站
                        self.siteUrl = base_url
                        self.setCache("51_dynamic_site_url", base_url)
                        print(f"[自愈成功] 主站地址: {base_url}")
                        return True

            except Exception as e:
                print(f"[发布入口异常] {nav_url}: {e}")
                continue

        print("[自愈失败] 所有发布入口均未找到有效主站")
        return False

    # ------------------------------------------------------------
    # 手动跟踪重定向（核心步骤1）
    # ------------------------------------------------------------
    def _fetch_with_redirect(self, url, max_redirects=5, timeout=10):
        """请求URL并跟随重定向，返回(最终HTML, 最终URL)"""
        headers = {"User-Agent": self._ua, "Accept-Encoding": "gzip, deflate"}
        current_url = url
        for _ in range(max_redirects + 1):
            try:
                req = urllib.request.Request(current_url, headers=headers)
                with self.opener.open(req, timeout=timeout) as resp:
                    # 成功拿到响应（urllib默认已跟随重定向，但这里显式处理以便记录）
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
                    return raw.decode("utf-8", errors="ignore"), final_url
            except urllib.error.HTTPError as e:
                # 如果是重定向状态码，urllib可能已自动处理，但部分场景会抛出异常
                if e.code in (301, 302, 303, 307, 308):
                    loc = e.headers.get("Location")
                    if loc:
                        current_url = urllib.parse.urljoin(current_url, loc)
                        continue  # 继续下一轮循环，请求新地址
                # 其他错误，尝试返回错误页面内容（可能包含线索）
                try:
                    raw = e.read()
                    return raw.decode("utf-8", errors="ignore"), current_url
                except Exception:
                    pass
                return "", current_url
            except Exception:
                return "", current_url
        return "", current_url

    # ------------------------------------------------------------
    # 从发布页提取候选链接（核心步骤2）
    # ------------------------------------------------------------
    def _extract_links_from_page(self, html, base_url):
        """从发布页HTML提取所有<a>标签的href，以及文本中的裸域名"""
        candidates = []
        seen = set()

        # 方法A：提取所有 <a href="..."> 链接
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', html, re.I):
            href = m.group(1).strip()
            url = self._normalize_url(href, base_url)
            if not url:
                continue
            host = urlparse(url).netloc.lower()
            # 排除发布页自身域名
            if host in self.publish_hosts:
                continue
            # 排除常见CDN/统计域名
            if self._is_blacklisted(host):
                continue
            base = f"{urlparse(url).scheme}://{host}"
            if base not in seen:
                seen.add(base)
                candidates.append(base)

        # 方法B：正则扫描页面文本中的裸域名（如 xxx.luwhogpx.cc）
        # 这是应对链接可能隐藏在JS或文本中的情况
        for m in re.finditer(r'([a-zA-Z0-9][a-zA-Z0-9\-\.]{3,}\.[a-zA-Z]{2,})', html):
            host = m.group(1).lower()
            if host in self.publish_hosts or self._is_blacklisted(host):
                continue
            if host.count(".") < 1:
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
        """排除常见的非主站域名"""
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
    # 统一请求方法（模仿参考代码，包含失效重试）
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
                # 关键：主站请求失败时，触发自愈刷新并重试
                if e.code in (404, 451, 502, 503) and check_host and not domain_retried:
                    old_host = urlparse(self.siteUrl).netloc
                    self.delCache("51_dynamic_site_url")
                    if self._refresh_site_url():
                        domain_retried = True
                        new_host = urlparse(self.siteUrl).netloc
                        target_url = target_url.replace(old_host, new_host)
                        continue  # 重试
                if e.code in (451, 403, 429) and attempt == 0:
                    continue
                return {"code": e.code, "text": "", "err": str(e), "final_url": target_url}
            except Exception as e:
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

        return {"code": -1, "text": "", "err": "unknown", "final_url": target_url}

    # ============================================================
    # 以下为内容解析方法，保持原51模板逻辑（需根据实际HTML结构调整）
    # ============================================================
    def homeContent(self, filter):
        """首页：获取分类和首页视频列表"""
        try:
            res = self._fetch(self.siteUrl + "/")
            if res.get("code") != 200:
                return {"class": [], "list": []}
            html = res.get("text", "")
            # 解析分类（简单正则示例，需适配实际页面）
            classes = self._parse_categories(html)
            # 解析视频列表
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
                "pagecount": 999 if videos else 1,
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
            # 解析详情页，提取播放列表（需适配实际页面结构）
            vod_play_url = self._parse_play_urls(html)
            return {"list": [{
                "vod_play_from": "51通用",
                "vod_play_url": vod_play_url or f"无源${url}",
            }]}
        except Exception as e:
            print(f"detailContent error: {e}")
            return {"list": [{"vod_play_from": "51通用", "vod_play_url": f"详情失败${ids[0] if ids else ''}"}]}

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg)
            url = f"{self.siteUrl}/search/{key}/{pg}/" if pg > 1 else f"{self.siteUrl}/search/{key}/"
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
        return {"parse": parse, "url": url, "header": getattr(self, 'headers', {})}

    # ============================================================
    # 辅助解析方法（占位，需根据51站实际HTML结构调整选择器）
    # ============================================================
    def _parse_categories(self, html):
        """解析分类列表（占位）"""
        # 示例：从 <nav> 或特定 class 中提取链接
        classes = []
        # ... 实际解析逻辑 ...
        if not classes:
            # 回退默认分类
            classes = [
                {"type_name": "首页", "type_id": "/"},
                {"type_name": "最新", "type_id": "/latest/"},
                {"type_name": "热门", "type_id": "/hot/"},
            ]
        return classes

    def _parse_video_list(self, html, tid):
        """解析视频列表（占位）"""
        videos = []
        # 示例：匹配 <article> 或特定 class 中的 <a> 和标题
        # ... 实际解析逻辑 ...
        return videos

    def _parse_play_urls(self, html):
        """解析详情页播放地址（占位）"""
        # 示例：匹配 dplayer 的 data-config 或 video/iframe src
        # ... 实际解析逻辑 ...
        return ""

    def proxy(self, data):
        """简单的代理占位"""
        return data

    # 缓存包装
    def getCache(self, key):
        return SpiderBase.getCache(self, key)

    def setCache(self, key, value):
        return SpiderBase.setCache(self, key, value)

    def delCache(self, key):
        return SpiderBase.delCache(self, key)


try:
    SpiderBase.register(Spider())
except Exception:
    pass
