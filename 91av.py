#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用站点爬虫模板 v1.0
=======================================================================
设计目标
  1. 域名发现与页面解析解耦（SiteProfile + Provider + HostManager）
  2. 域名自动发现、自动轮换、失败自动切换
  3. 分类目录自动抓取（无需手工维护）
  4. 可被 TVBox 加载，也可独立运行做自检

学习要点（按顺序看注释）
  - 依赖可选导入：try/except ImportError
  - 策略模式（Provider）：不同来源的域名发现
  - 依赖注入：HostManager 接收 Provider 列表
  - 单一职责：HostManager 只管"哪个域名能用"
  - @property：把动态 host 做成只读视图
  - unittest.mock：离线验证状态机逻辑
=======================================================================
"""

import json
import re
import time
from urllib.parse import urljoin, urlparse, urlunparse

import requests

# ---------------------------------------------------------------------
# 【知识点 1】可选依赖
#   PyQuery 解析 HTML 更顺手，但不是必须。没有它就退化为纯正则。
#   Crypto 只在 51 站图片解密时需要。
# ---------------------------------------------------------------------
try:
    from pyquery import PyQuery as pq
    _HAS_PQ = True
except ImportError:
    pq = None
    _HAS_PQ = False

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

try:
    from base.spider import Spider as _TVBoxSpider
    _HAS_TVBOX = True
except ImportError:
    # 独立运行时，给一个"最小实现"，让代码能跑
    class _TVBoxSpider:
        def getProxyUrl(self):
            return "http://127.0.0.1:9978/proxy"
        def log(self, msg):
            print("[TVBox]", msg)
    _HAS_TVBOX = False


# =====================================================================
# 第 1 部分：常量与工具函数
# =====================================================================

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

AES_KEY = b"f5d965df75336270"
AES_IV = b"97b60394abc2fbe1"


def e64(text: str) -> str:
    """URL 安全的 base64 编码（供本地代理使用）"""
    from base64 import b64encode
    return b64encode(text.encode("utf-8")).decode("utf-8")


def d64(text: str) -> str:
    """base64 解码"""
    from base64 import b64decode
    try:
        return b64decode(text.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""


def aes_decrypt(data: bytes) -> bytes:
    """AES-CBC 解密，失败返回空"""
    if not _HAS_CRYPTO or not data:
        return b""
    try:
        return unpad(AES.new(AES_KEY, AES.MODE_CBC, AES_IV).decrypt(data), AES.block_size)
    except Exception:
        return b""


def get_pq(html: str):
    """PyQuery 兼容封装：没有 pyquery 时返回一个可调用空对象"""
    if _HAS_PQ:
        return pq(html)
    # 兜底：返回一个永远为空的 lambda
    return lambda *a, **kw: _EmptyQuery()


class _EmptyQuery:
    """无 PyQuery 时的空查询占位，保证接口一致"""
    def __call__(self, *_a, **_kw):
        return self
    def items(self):
        return []
    def attr(self, *_a, **_kw):
        return None
    def text(self, *_a, **_kw):
        return ""
    def __bool__(self):
        return False


# =====================================================================
# 第 2 部分：HostManager —— 域名生命周期管理器
# =====================================================================
# 【核心设计】它不关心页面长什么样，只关心：
#   1. 我有哪些候选域名（来自 Provider）
#   2. 哪个域名当前可用（探测）
#   3. 当前域名挂了，下一个是谁（轮换）
# =====================================================================

class HostManager:
    """
    用法：
        hm = HostManager(providers, headers, host_check=fn)
        hm.refresh()                # 收集 + 探测首个可用
        hm.current                  # 当前域名
        hm.switch_next()            # 切到下一个可用域名
    """

    def __init__(self, providers, headers, proxies=None,
                 timeout=15, probe_timeout=10,
                 host_check=None, refresh_interval=300):
        # providers: [(name, callable, priority), ...]
        self.providers = providers
        self.headers = headers
        self.proxies = proxies or {}
        self.timeout = timeout
        self.probe_timeout = probe_timeout
        # host_check(html) -> bool：判断"这个域名是不是目标站"
        self.host_check = host_check or (lambda html: True)
        self.refresh_interval = refresh_interval

        self._candidates = []   # 去重后的候选列表
        self._index = -1        # 当前在候选列表中的位置
        self.current = None
        self._last_refresh = 0

    # ---------------- 刷新候选 ----------------
    def refresh(self, force=False):
        """
        【知识点 2】节流（throttle）
        短时间内重复调用不重新抓取，避免每次请求都打发布页。
        """
        now = time.time()
        if not force and self._candidates and now - self._last_refresh < self.refresh_interval:
            return self.current

        seen = set()
        ordered = []
        # 按 priority 升序，小数字优先
        for name, provider, priority in sorted(self.providers, key=lambda x: x[2]):
            try:
                for url in provider():
                    url = (url or "").rstrip("/")
                    if url.startswith("http") and url not in seen:
                        seen.add(url)
                        ordered.append(url)
            except Exception as exc:
                print(f"[HostManager] provider {name} 失败: {exc}")

        self._candidates = ordered
        self._index = -1
        self._last_refresh = now
        print(f"[HostManager] 收集到 {len(ordered)} 个候选")
        return self._probe_next()

    # ---------------- 探测下一个 ----------------
    def _probe_next(self):
        """从当前位置往后循环探测，找一个可用的"""
        n = len(self._candidates)
        if not n:
            self.current = None
            return None
        for _ in range(n):
            self._index = (self._index + 1) % n
            url = self._candidates[self._index]
            if self._probe(url):
                self.current = url
                print(f"[HostManager] 选用: {url}")
                return url
        self.current = None
        return None

    def _probe(self, url):
        """HTTP 200 + host_check 通过，即视为可用"""
        try:
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=self.probe_timeout, allow_redirects=True)
            if r.status_code != 200:
                return False
            return bool(self.host_check(r.text))
        except Exception:
            return False

    def switch_next(self):
        """请求失败时调用：清空当前，继续探测"""
        self.current = None
        return self._probe_next()


# =====================================================================
# 第 3 部分：Provider —— 域名来源策略
# =====================================================================
# 【知识点 3】策略模式：每个 provider 是无参 callable，返回 url 列表。
# 新增来源只需写一个函数，不用改 HostManager。
# =====================================================================

# ---------- 3.1 静态列表 Provider ----------
def static_provider(urls):
    """最朴素：写死的兜底域名"""
    def provider():
        return list(urls)
    return provider


# ---------- 3.2 HTML 发布页 Provider（51 风格） ----------
def _decode_publish(text, mode):
    """发布页可能把链接用 Base64 / atob 藏起来"""
    if mode == "js_base64":
        m = re.search(r"Base64\.decode\(['\"]([^'\"]+)['\"]\)", text)
        if m:
            try:
                return d64(m.group(1))
            except Exception:
                return text
    if mode == "js_atob":
        m = re.search(r"atob\(['\"]([^'\"]+)['\"]\)", text)
        if m:
            try:
                return d64(m.group(1))
            except Exception:
                return text
    return text


def _find_meta_refresh(html):
    """解析 <meta http-equiv="refresh" content="0;url=...">"""
    m = re.search(
        r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+'
        r'content=["\'][^"\']*url=([^"\'>\s]+)',
        html or "", re.I,
    )
    return m.group(1).strip("'\"") if m else ""


def _find_js_location(html):
    """解析 window.location / location.replace 等跳转"""
    patterns = [
        r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
        r'document\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
        r'location\.replace\(\s*["\']([^"\']+)["\']',
        r'location\.assign\(\s*["\']([^"\']+)["\']',
    ]
    for p in patterns:
        m = re.search(p, html or "")
        if m:
            return m.group(1)
    return ""


def _pick_anchor_links(html, base):
    """从 HTML 中提取所有 <a href> 的绝对 URL"""
    links = re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', html or "", re.I)
    out = []
    for href in links:
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = base.rstrip("/") + href
        if not href.startswith("http") or "." not in href:
            continue
        if any(x in href for x in ("javascript:", "mailto:", "#")):
            continue
        out.append(href)
    return out


def publish_provider(publish_url, decode_mode, headers, proxies, timeout=15):
    """
    51 风格：请求发布页 → 解出链接 → 若为空，尝试 meta/JS 跳转再抓一次
    """
    def provider():
        try:
            r = requests.get(publish_url, headers=headers, proxies=proxies,
                             timeout=timeout, allow_redirects=True)
            if r.status_code != 200:
                return []
        except Exception:
            return []

        html = _decode_publish(r.text, decode_mode)
        links = _pick_anchor_links(html, publish_url)
        if links:
            return links

        # 跳转补丁：meta refresh
        target = _find_meta_refresh(r.text)
        if not target:
            target = _find_js_location(r.text)
        if not target:
            return []

        if target.startswith("//"):
            target = "https:" + target
        elif target.startswith("/"):
            target = urlparse(publish_url).scheme + "://" + urlparse(publish_url).netloc + target
        elif not target.startswith("http"):
            return []

        try:
            r2 = requests.get(target, headers=headers, proxies=proxies,
                              timeout=timeout, allow_redirects=True)
            if r2.status_code == 200:
                return _pick_anchor_links(_decode_publish(r2.text, decode_mode), target)
        except Exception:
            pass
        return []
    return provider


# ---------- 3.3 README Provider（91av 风格） ----------
def _expand_redirect(url, headers, proxies, timeout, verify_terms):
    """91av 的备用地址是跳转链：跟到最终域名，并用关键词校验"""
    try:
        r = requests.get(url, headers=headers, proxies=proxies,
                         timeout=timeout, verify=False, allow_redirects=True)
        final = f"{urlparse(r.url).scheme}://{urlparse(r.url).netloc}"
        if r.status_code == 200 and any(t in r.text for t in verify_terms):
            return final
    except Exception:
        pass
    return ""


def readme_provider(readme_urls, headers, proxies, timeout=15,
                    verify_terms=("/videos/", "bind_video_img")):
    """
    91av 风格：GitLab README 里用固定句式暴露地址
      - 国内备用地址 → 跟跳转
      - 国内最新网址 → 直接当发布页再抓 <a>
      - 海外永久地址 → 直接加入候选
    """
    patterns = [
        (r'国内备用地址\s*[：:]\s*(https?://[^\s<>"\'\)]+)', "redirect"),
        (r'国内最新网址\s+(https?://[^\s<>"\'\)]+)', "publish"),
        (r'海外永久地址[^v]*?（需要VPN）\s*(https?://[^\s<>"\'\)]+)', "direct"),
    ]

    def provider():
        out = []
        for ru in readme_urls:
            try:
                r = requests.get(ru, headers=headers, proxies=proxies,
                                 timeout=timeout, verify=False)
                if r.status_code != 200:
                    continue
                txt = r.text
                for pat, typ in patterns:
                    for m in re.finditer(pat, txt):
                        u = m.group(1).rstrip("/")
                        if typ == "redirect":
                            expanded = _expand_redirect(u, headers, proxies, timeout, verify_terms)
                            if expanded:
                                out.append(expanded)
                        elif typ == "publish":
                            try:
                                p = requests.get(u, headers=headers, proxies=proxies,
                                                 timeout=timeout, verify=False)
                                if p.status_code == 200:
                                    out.extend(_pick_anchor_links(p.text, u))
                            except Exception:
                                pass
                        else:
                            out.append(u)
            except Exception:
                continue
        return out
    return provider


# =====================================================================
# 第 4 部分：UnifiedSpider 基类 —— 请求路由
# =====================================================================
# 【核心】所有解析代码都不直接 requests.get，而是走 self._request()。
#   - _request 失败时自动 switch_next 重试
#   - 这样站点解析代码完全不用关心"域名挂了怎么办"
# =====================================================================

class UnifiedSpider(_TVBoxSpider):

    profile = None  # 子类必须覆盖

    def init(self, extend=""):
        self.proxies = {}
        try:
            self.proxies = json.loads(extend) if extend else {}
        except Exception:
            pass

        p = self.profile
        self.headers = dict(p.get("headers", DEFAULT_HEADERS))

        self.host_manager = HostManager(
            providers=p["providers"],
            headers=self.headers,
            proxies=self.proxies,
            timeout=p.get("timeout", 15),
            probe_timeout=p.get("probe_timeout", 10),
            host_check=p.get("host_check"),
        )
        self.host_manager.refresh(force=True)
        if not self.host_manager.current:
            print(f"[{p['name']}] 警告：未找到可用域名")

    # ---------------- 关键：动态 host ----------------
    @property
    def host(self):
        """【知识点 4】@property 让 host 成为只读视图，永远反映当前可用域名"""
        return self.host_manager.current or ""

    # ---------------- 统一请求入口 ----------------
    def _request(self, path, method="get", **kwargs):
        """
        支持三种入参：
          "/new/2/"        → 拼到当前 host
          "https://x/y"    → 保留路径，替换 host
          "new"            → 相对 host 根目录
        失败自动轮换域名重试。
        """
        url = self._build_url(path)
        max_attempts = max(len(self.host_manager._candidates), 1) * 2
        attempts = 0

        while attempts < max_attempts:
            if not self.host_manager.current:
                self.host_manager.refresh(force=True)
            h = self.host_manager.current
            if not h:
                break

            target = self._replace_host(url, h)
            try:
                r = requests.request(
                    method, target, headers=self.headers,
                    proxies=self.proxies,
                    timeout=self.profile.get("timeout", 15),
                    **kwargs,
                )
                if r.status_code == 200:
                    return r
                if r.status_code in (403, 429, 502, 503, 504):
                    print(f"[_request] {target} -> {r.status_code}，切换域名")
                    self.host_manager.switch_next()
                    attempts += 1
                    continue
                return r  # 404 等非域名问题，直接返回
            except (requests.ConnectionError, requests.Timeout) as exc:
                print(f"[_request] 连接失败 {target}: {exc}")
                self.host_manager.switch_next()
                attempts += 1

        return None

    def _build_url(self, p):
        p = (p or "").strip()
        if p.startswith("http"):
            return p
        if p.startswith("/"):
            return (self.host or "") + p
        return urljoin((self.host or "") + "/", p)

    @staticmethod
    def _replace_host(url, new_host):
        """
        【知识点 5】urlparse / urlunparse 安全地替换 scheme+netloc，
        保留 path / query / fragment，避免字符串替换踩坑。
        """
        if not url.startswith("http"):
            return new_host.rstrip("/") + "/" + url.lstrip("/")
        old = urlparse(url)
        new = urlparse(new_host)
        return urlunparse((new.scheme, new.netloc, old.path,
                           old.params, old.query, old.fragment))

    # ---------------- 通用小工具 ----------------
    def isVideoFormat(self, url):
        return any(x in (url or "") for x in (".m3u8", ".mp4", ".ts"))

    def proxy(self, url, type_="m3u8"):
        if not url:
            return url
        try:
            base = self.getProxyUrl()
        except Exception:
            return url
        return f"{base}&url={e64(url)}&type={type_}"


# =====================================================================
# 第 5 部分：51 站点解析器
# =====================================================================
# 直接把 01.txt 的解析逻辑搬过来，唯一改动是 host 通过 self.host 动态获取。
# =====================================================================

def _parse_51_list(doc, is_folder=False):
    """从 PyQuery 结果中提取视频卡片列表"""
    videos = []
    for k in doc.items():
        href = k.attr("href")
        name = k("h2").text()
        remark = (k("span[itemprop='datePublished']").text()
                  or k(".post-meta, .entry-meta, time").text())
        if not (href and name):
            continue
        # 封面：<script>loadBannerDirect('...')</script>
        pic = ""
        m = re.search(r"loadBannerDirect\('([^']+)'", k("script").text() or "")
        if m:
            pic = m.group(1)
        videos.append({
            "vod_id": href + ("@folder" if is_folder else ""),
            "vod_name": name.replace("\n", " ").strip(),
            "vod_pic": pic,
            "vod_remarks": remark or "",
            "vod_tag": "folder" if is_folder else "",
        })
    return videos


class Spider51(UnifiedSpider):
    """51 吃瓜/爆料"""

    profile = {
        "name": "51通用",
        "timeout": 15,
        "probe_timeout": 10,
        "headers": DEFAULT_HEADERS,
        "providers": [
            # priority 小的优先
            # publish_provider 在下面工厂里生成，这里先用占位
        ],
        # 判断域名是否为目标站
        "host_check": lambda html: bool(re.search(r'#index\s+article', html or "")),
    }

    # 分类目录抓取选择器（自动抓，不用手工配）
    CATEGORY_SELECTORS = [
        ".category-list ul li", ".nav-menu li", ".menu li", "nav ul li",
    ]
    DEFAULT_CLASSES = [
        {"type_name": "首页", "type_id": "/"},
        {"type_name": "最新", "type_id": "/latest/"},
        {"type_name": "热门", "type_id": "/hot/"},
    ]

    def init(self, extend=""):
        # 构造 provider 后交给父类
        self.profile = dict(self.profile)
        self.profile["providers"] = [
            ("publish", publish_provider(
                "https://51bla20.com/", "js_base64",
                DEFAULT_HEADERS, {}, 15,
            ), 10),
            ("static", static_provider([
                "https://blind.luwhogpx.cc",
                "https://and.luwhogpx.cc",
                "https://but.luwhogpx.cc",
            ]), 99),
        ]
        super().init(extend)

    def getName(self):
        return "51通用"

    # ---------- 首页 ----------
    def homeContent(self, filter):
        r = self._request("/")
        if not r:
            return {"class": [], "list": []}
        doc = get_pq(r.text)

        # 自动抓分类目录
        classes = []
        for sel in self.CATEGORY_SELECTORS:
            for item in doc(sel).items():
                a = item("a")
                href = (a.attr("href") or "").strip()
                name = (a.text() or "").strip()
                if href and href != "#" and name:
                    classes.append({"type_name": name, "type_id": href})
            if classes:
                break
        if not classes:
            classes = list(self.DEFAULT_CLASSES)

        return {
            "class": classes,
            "list": _parse_51_list(doc("#index article a")),
        }

    def homeVideoContent(self):
        r = self._request("/")
        if not r:
            return {"list": []}
        doc = get_pq(r.text)
        return {"list": _parse_51_list(doc("#index article a, #archive article a"))}

    # ---------- 分类 ----------
    def categoryContent(self, tid, pg, filter, extend):
        if "@folder" in tid:
            return self._folder_content(tid.replace("@folder", ""), pg)

        pg = int(pg)
        tid = tid.rstrip("/")
        url = f"{tid}/{pg}/" if pg > 1 else f"{tid}/"

        r = self._request(url)
        if not r:
            return {"list": [], "page": pg, "pagecount": pg, "limit": 90, "total": 0}

        doc = get_pq(r.text)
        videos = _parse_51_list(doc("#archive article a, #index article a"))

        # 页数判定：优先 ul.page-navigator
        total_pages, has_next = 1, False
        pagenav = doc("ul.page-navigator")
        if pagenav:
            max_page = 0
            for a in pagenav("li a").items():
                t = (a.text() or "").strip()
                if t.isdigit():
                    max_page = max(max_page, int(t))
            total_pages = max_page or 1
            if pagenav("li.next a").attr("href"):
                has_next = True
        if total_pages <= 1:
            info = doc(".pagination .pages, .page-nav, .pagenavi").text() or ""
            m = re.search(r"共\s*(\d+)\s*页", info)
            if m:
                total_pages = int(m.group(1))
        if not has_next:
            nxt = doc("li.next a, a.next, a:contains('下一页')").attr("href")
            has_next = bool(nxt)

        pagecount = total_pages if total_pages > 1 else (pg + 1 if has_next else pg)
        return {
            "list": videos, "page": pg,
            "pagecount": pagecount, "limit": 90,
            "total": pagecount * 90 if pagecount > 1 else len(videos),
        }

    def _folder_content(self, folder_id, pg):
        """合集页：从详情页里拆出子项"""
        r = self._request(folder_id)
        if not r:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 0, "total": 0}
        doc = get_pq(r.text)
        body = doc(".post-content[itemprop='articleBody']")
        for sel in (".txt-apps", ".line", "blockquote", ".tags", ".content-tabs"):
            body.remove(sel)
        p = body("p")
        videos = []
        for i, h in enumerate(body("h2").items()):
            c = i * 2
            videos.append({
                "vod_id": p.eq(c)("a").attr("href"),
                "vod_name": p.eq(c).text(),
                "vod_pic": self.proxy(p.eq(c + 1)("img").attr("data-xkrkllgl"), "img"),
                "vod_remarks": h.text(),
            })
        return {"list": videos, "page": 1, "pagecount": 1,
                "limit": len(videos), "total": len(videos)}

    # ---------- 详情 ----------
    def detailContent(self, ids):
        vid = ids[0] if ids else ""
        r = self._request(vid)
        if not r:
            return {"list": [{
                "vod_play_from": "51",
                "vod_play_url": f"页面加载失败${vid}",
            }]}
        doc = get_pq(r.text)
        vod = {"vod_play_from": "51"}

        tags = []
        for k in doc(".tags .keywords a").items():
            t, h = k.text(), k.attr("href")
            if t and h:
                tags.append(f"[a=cr:{json.dumps({'id': h, 'name': t})}/]{t}[/a]")
        vod["vod_content"] = " ".join(tags) or doc(".post-title").text()

        players = []
        for i, node in enumerate(doc(".dplayer").items(), 1):
            raw = node.attr("data-config")
            if not raw:
                continue
            try:
                cfg = json.loads(raw)
                url = cfg.get("video", {}).get("url", "")
            except Exception:
                continue
            if url:
                players.append(f"视频{i}${url}")
        vod["vod_play_url"] = "#".join(players) or f"未找到视频源${self._build_url(vid)}"
        return {"list": [vod]}

    # ---------- 搜索 ----------
    def searchContent(self, key, quick, pg="1"):
        if str(pg) != "1":
            path = f"/search/{key}/{pg}/"
        else:
            path = f"/search/{key}/"
        r = self._request(path)
        if not r:
            return {"list": [], "page": pg}
        doc = get_pq(r.text)
        return {"list": _parse_51_list(doc("#index article a, #archive article a")),
                "page": pg}

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags):
        url = id
        parse = 1
        if self.isVideoFormat(url):
            if ".m3u8" in url:
                url = self.proxy(url)
            parse = 0
        return {"parse": parse, "url": url, "header": self.headers}


# =====================================================================
# 第 6 部分：91av 站点解析器
# =====================================================================
# 关键差异：
#   1. 列表解析依赖 "bind_video_img" 分隔符
#   2. 详情可能有 heiliao / 普通视频两种结构
#   3. 播放地址需要额外请求才能拿到 m3u8
# =====================================================================

def _parse_91_list(html, host, pic_fn):
    """从 91 页面中抽卡片。用 bind_video_img 作为卡片切分锚点。"""
    out, seen = [], set()
    for block in re.split(r"bind_video_img", html or "")[1:]:
        m = re.search(r'<a\s+href="([^"]*videos/[^"]+)"[^>]*>', block)
        if not m:
            continue
        href = m.group(1)
        if href.startswith("/"):
            href = host.rstrip("/") + href
        if href in seen:
            continue
        seen.add(href)

        im = re.search(r'(?:z-image-loader-url|data-src|src)="([^"]*)"', block)
        pic = pic_fn(im.group(1)) if im else ""

        nm = re.search(r'<h3[^>]*class="[^"]*title[^"]*"[^>]*>\s*<a[^>]*>([^<]+)</a>', block)
        name = nm.group(1).strip() if nm else ""
        if not name:
            am = re.search(r'<img[^>]*alt="([^"]*)"', block)
            name = am.group(1) if am else href.rsplit("/", 1)[-1]

        rm = re.search(r'<span class="label">([^<]+)</span>', block)
        remarks = "" if (rm and "广告" in rm.group(1)) else (rm.group(1) if rm else "")

        out.append({"vod_id": href, "vod_name": name,
                    "vod_pic": pic, "vod_remarks": remarks})
    return out


def _parse_91_heiliao_list(html, host, pic_fn):
    """黑料卡片结构不同于普通视频"""
    out, seen = [], set()
    for m in re.finditer(r'<a class="heiliao-card" href="([^"]+)"(.*?)</a>',
                         html or "", re.S):
        href = m.group(1)
        if href.startswith("/"):
            href = host.rstrip("/") + href
        if href in seen:
            continue
        seen.add(href)
        seg = m.group(2)
        im = (re.search(r'z-image-loader-url="([^"]*)"', seg)
              or re.search(r'(?:data-src|src)="([^"]*)"', seg))
        pic = pic_fn(im.group(1)) if im else ""
        nm = re.search(r'heiliao-card-title">([^<]+)', seg)
        name = nm.group(1).strip() if nm else href.rsplit("/", 1)[-1]
        rm = re.search(r'heiliao-date">([^<]+)', seg)
        out.append({"vod_id": href, "vod_name": name,
                    "vod_pic": pic, "vod_remarks": (rm.group(1).strip() if rm else "")})
    return out


class Spider91(UnifiedSpider):
    """91JAV"""

    profile = {
        "name": "91JAV",
        "timeout": 20,
        "probe_timeout": 12,
        "headers": DEFAULT_HEADERS,
        # host_check：页面里出现这些词，说明是目标站
        "host_check": lambda html: ("bind_video_img" in (html or "")
                                     or "/videos/" in (html or "")),
    }

    THEMES = [
        ("2", "角色剧情"), ("3", "中文字幕"), ("4", "制服诱惑"),
        ("5", "直接开啪"), ("6", "丝袜美腿"), ("7", "捆绑调教"),
        ("8", "多P群交"), ("10", "羞辱强暴"), ("11", "无码高清"),
        ("14", "乱伦伦理"), ("15", "人妻诱惑"), ("17", "网黄精选"),
    ]

    def init(self, extend=""):
        self.profile = dict(self.profile)
        self.profile["providers"] = [
            ("readme", readme_provider(
                [
                    "https://gitlab.com/91JAV2/dz/-/raw/main/README.md",
                    "https://gitlab.com/91jav1/dz/-/raw/main/README.md",
                ],
                DEFAULT_HEADERS, {}, 15,
            ), 10),
            ("static", static_provider([
                "https://cabin.zbywlcc.com",
                "https://born.zbywlcc.com",
                "https://d1nqsse6ono4lc.cloudfront.net",
            ]), 99),
        ]
        super().init(extend)
        self._img_cache = {}

    def getName(self):
        return "91JAV"

    # ---------- 首页 ----------
    def homeContent(self, filter):
        r = self._request("/")
        if not r:
            return {"class": [], "list": []}

        # 自动抓主题分类（无需手工维护）
        classes = [
            {"type_id": "/new", "type_name": "最新更新"},
            {"type_id": "/theme/detail/3/update", "type_name": "中文字幕"},
            {"type_id": "/theme/detail/11/hot", "type_name": "无码高清"},
            {"type_id": "/heiliao", "type_name": "黑料吃瓜"},
            {"type_id": "/actress/hot", "type_name": "热门女优"},
        ]
        # 从首页额外发现主题链接（自动补齐）
        for tid, name in re.findall(
            r'<a href="/theme/detail/(\d+)/[a-z]*"[^>]*>.*?alt="([^"]*)"',
            r.text, re.S,
        ):
            entry = {"type_id": f"/theme/detail/{tid}/update",
                     "type_name": name.strip()}
            if entry not in classes:
                classes.append(entry)

        return {
            "class": classes,
            "list": _parse_91_list(r.text, self.host, self._pic),
        }

    def homeVideoContent(self):
        r = self._request("/new")
        return {"list": _parse_91_list(r.text, self.host, self._pic) if r else []}

    # ---------- 分类 ----------
    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        tid = str(tid)

        # theme/actress 特殊分页处理
        if tid.startswith("theme$"):
            theme_id = tid.split("$")[1]
            r = self._request(f"/theme/detail/{theme_id}/update/")
            items = _parse_91_list(r.text, self.host, self._pic) if r else []
            return {"page": pg, "pagecount": pg, "limit": len(items),
                    "total": len(items), "list": items}

        # 普通列表
        path = f"{tid}/" if pg == 1 else f"{tid}/{pg}/"
        r = self._request(path)
        if not r:
            return {"page": pg, "pagecount": pg, "limit": 0, "total": 0, "list": []}

        items = _parse_91_list(r.text, self.host, self._pic)
        if not items:
            items = _parse_91_heiliao_list(r.text, self.host, self._pic)

        # 页数粗判：页面出现 next 或数字分页
        has_next = bool(re.search(r'rel="next"|下一页', r.text))
        pagecount = pg + 1 if has_next else pg
        return {"page": pg, "pagecount": pagecount,
                "limit": len(items) or 24, "total": 0, "list": items}

    # ---------- 详情 ----------
    def detailContent(self, ids):
        out = []
        for vid in (ids if isinstance(ids, list) else [ids]):
            vid = str(vid)
            # theme$ / actress$ 这类合集，直接返回空，由分类页处理
            if vid.startswith(("theme$", "actress$")):
                continue
            r = self._request(vid)
            if not r:
                continue
            html = r.text

            # 尝试普通视频结构
            title = pic = desc = ""
            vm = re.search(r'<video[^>]*id="player"[^>]*>', html)
            if vm:
                tag = vm.group(0)
                tm = re.search(r'data-video_title="([^"]*)"', tag)
                pm = re.search(r'data-src="([^"]*)"', tag)
                title = tm.group(1) if tm else ""
                pic = pm.group(1) if pm else ""
            if not title:
                hm = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
                title = re.sub(r"<[^>]+>", "", hm.group(1)).strip() if hm else vid
            if not pic:
                pm = re.search(r'<img[^>]*?z-image-loader-url="([^"]*)"', html)
                pic = pm.group(1) if pm else ""

            # JSON-LD 里通常有描述
            jd = re.search(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',
                           html, re.S)
            if jd:
                m = re.search(r'"description"\s*:\s*"([^"]+)"', jd.group(1))
                if m:
                    desc = m.group(1)

            out.append({
                "vod_id": vid, "vod_name": title,
                "vod_pic": self._pic(pic),
                "vod_content": (desc or "")[:500],
                "vod_play_from": "91JAV",
                "vod_play_url": f"正片${vid}",  # 播放地址在 playerContent 里再解析
            })
        return {"list": out}

    # ---------- 搜索 ----------
    def searchContent(self, key, quick, pg="1"):
        r = self._request(f"/cn/search/{key}")
        if not r:
            return {"list": [], "page": int(pg)}
        return {"list": _parse_91_list(r.text, self.host, self._pic),
                "page": int(pg)}

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags):
        url = str(id or "")
        if url.endswith((".m3u8", ".mp4")) or ".m3u8?" in url:
            return {"parse": 0, "url": self._build_url(url), "header": self.headers}

        # 从详情页里再抓一次 m3u8
        r = self._request(url)
        if r:
            m = (re.search(r'var\s+hlsUrl\s*=\s*["\']([^"\']+)', r.text)
                 or re.search(r'<video[^>]+src=["\'](https?://[^"\']+\.m3u8[^"\']*)', r.text))
            if m:
                return {"parse": 0, "url": m.group(1).replace("&amp;", "&"),
                        "header": self.headers}
        return {"parse": 1, "url": self._build_url(url), "header": self.headers}

    # ---------- 图片代理 ----------
    def _pic(self, url):
        u = self._build_url(url) if url else ""
        if not u.startswith("http"):
            return u
        return self.proxy(u, "img")

    def localProxy(self, param):
        if not param or param.get("type") != "img":
            return [404, "text/plain", "", ""]
        try:
            u = d64(param.get("url", ""))
            if u in self._img_cache:
                return [200, "image/jpeg", self._img_cache[u], ""]
            r = requests.get(u, headers=self.headers, proxies=self.proxies,
                             timeout=20, verify=False)
            data = r.content or b""
            # 有些站图片是 AES 加密的
            dec = aes_decrypt(data)
            if dec and dec[:3] in (b"\xff\xd8\xff", b"GIF", b"\x89PNG"[:3]):
                data = dec
            self._img_cache[u] = data
            return [200, "image/jpeg", data, ""]
        except Exception:
            return [500, "text/plain", "", ""]


# =====================================================================
# 第 7 部分：离线自检（学习重点）
# =====================================================================
# 用 unittest.mock 模拟网络响应，不联网也能验证：
#   1. URL 拼接 / host 替换
#   2. HostManager 轮换（第一个挂 → 自动用第二个）
#   3. _request 失败切换
# =====================================================================

def _self_test():
    import unittest
    from unittest.mock import patch

    class TestReplaceHost(unittest.TestCase):
        def test_relative(self):
            self.assertEqual(
                UnifiedSpider._replace_host("/abc/def?x=1", "https://new.com"),
                "https://new.com/abc/def?x=1",
            )

        def test_absolute_replaces_netloc(self):
            self.assertEqual(
                UnifiedSpider._replace_host("https://old.com/a/b?k=v#frag", "https://new.com"),
                "https://new.com/a/b?k=v#frag",
            )

    class TestHostManager(unittest.TestCase):
        def test_rotation(self):
            """第一个域名探测失败，自动用第二个"""
            calls = []

            def fake_get(url, **_):
                calls.append(url)
                class R:
                    status_code = 200 if "ok.com" in url else 500
                    text = "<html>target</html>"
                return R()

            providers = [
                ("p1", static_provider(["https://bad.com"]), 10),
                ("p2", static_provider(["https://ok.com"]), 20),
            ]
            hm = HostManager(providers, headers={}, host_check=lambda h: "target" in h)
            with patch("unified_spider.requests.get", side_effect=fake_get):
                hm.refresh(force=True)
                self.assertEqual(hm.current, "https://ok.com")

        def test_switch_next_when_down(self):
            """当前域名挂了，switch_next 换下一个"""
            state = {"down": {"https://a.com"}}

            def fake_get(url, **_):
                class R:
                    status_code = 500 if any(d in url for d in state["down"]) else 200
                    text = "target"
                return R()

            providers = [
                ("p1", static_provider(["https://a.com", "https://b.com"]), 10),
            ]
            hm = HostManager(providers, headers={}, host_check=lambda h: "target" in h)
            with patch("unified_spider.requests.get", side_effect=fake_get):
                hm.refresh(force=True)
                self.assertEqual(hm.current, "https://a.com")
                hm.switch_next()
                self.assertEqual(hm.current, "https://b.com")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (TestReplaceHost, TestHostManager):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


def _live_probe(spider_cls):
    """联网探活：打印当前可用域名，不发太多请求"""
    print(f"\n===== 联网探测 {spider_cls.__name__} =====")
    s = spider_cls()
    s.init("")
    print(f"当前域名: {s.host or '(未找到)'}")
    if s.host:
        r = s._request("/")
        print(f"首页请求: {'OK' if r else 'FAIL'}，长度 = {len(r.text) if r else 0}")
    return s.host


if __name__ == "__main__":
    print("=" * 60)
    print("第一步：离线自检（不联网）")
    print("=" * 60)
    ok = _self_test()

    if ok:
        print("\n" + "=" * 60)
        print("第二步：联网探活（可选，Ctrl+C 可跳过）")
        print("=" * 60)
        try:
            _live_probe(Spider51)
            _live_probe(Spider91)
        except KeyboardInterrupt:
            print("跳过联网测试")
        except Exception as exc:
            print(f"联网测试异常（不影响核心逻辑）：{exc}")
