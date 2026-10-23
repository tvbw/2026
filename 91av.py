#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
91通用最终版 v2.1（单文件 · 适配静态发布页）
=============================================================
发布页特征（已确认）：
  - 91jav18.cc / 91jav19.cc 返回明文 HTML
  - 线路链接直接写在 <a href="https://xxx"> 中
  - 没有 Base64 编码，没有 meta refresh / JS location
  - 线路域名每周可能变化，所以不能硬编码兜底

发现顺序：
  1) 请求 91jav18.cc → 提取 <a href> 线路
  2) 请求 91jav19.cc → 提取 <a href> 线路
  3) 合并去重，逐个探测
  4) 探测成功的即为当前 host，失败自动切下一个

运行：
  本地测试:  python 91av.py
  TVBox:     放入爬虫目录，配置名 "91通用最终版"
=============================================================
"""
import json
import re
import sys
import traceback
from base64 import b64decode, b64encode
from urllib.parse import urlparse, urlunparse

# ---- 依赖检查 ----
try:
    import requests
except ImportError:
    sys.stderr.write("\n[致命] 缺少 requests 库\n请先运行： pip install requests\n\n")
    raise

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
    from base.spider import Spider as _SpiderBase
    _TVBOX = True
except ImportError:
    class _SpiderBase(object):
        def getProxyUrl(self):
            return "http://127.0.0.1:9978/proxy"
        def log(self, msg):
            pass
    _TVBOX = False


# ============================================================
# 站点配置
# ============================================================
SITE_CONFIG = {
    "name": "91通用最终版",
    "play_from": "91通用最终版",
    "style": {"type": "rect", "ratio": 1.33},

    # ---- 发布页（入口，相对稳定）----
    "publish_urls": [
        "https://91jav18.cc",
        "https://91jav19.cc",
    ],

    # ---- 发布页解析方式 ----
    # 不再使用 js_base64；直接提取 HTML 中的 <a href>
    "publish_parse": "static_html",
    # 发布页中线路链接所在容器（可选，留空则全局扫描）
    "publish_link_selector": "#list-wrap a, .list a",
    # 需要排除的链接关键词（非线路）
    "publish_exclude": [
        "mailto:", "t.me", "x.com", "gitlab.com", "peach-av.com",
        "admire.snbbqdli.vip",  # APP 下载
    ],

    # ---- 目标站特征（判断某个域名是不是 91 正站）----
    "host_check_selector": "#index article a",
    # 没有 pyquery 时的字符串兜底
    "host_check_terms": ["bind_video_img", "/videos/"],

    # ---- 列表 ----
    "list_selector": "#index article a, #archive article a",
    "home_list_selector": "#index article a",
    "category_selectors": [
        ".category-list ul li", ".nav-menu li", ".menu li", "nav ul li",
    ],
    "default_classes": [
        {"type_name": "首页", "type_id": "/"},
        {"type_name": "最新", "type_id": "/latest/"},
        {"type_name": "热门", "type_id": "/hot/"},
    ],
    "folder_id_marker": "/mrdg",

    # ---- 详情 ----
    "title_selector": ".post-title",
    "tag_selector": ".tags .keywords a",
    "player_selector": ".dplayer",
    "player_config_attr": "data-config",
    "player_heading_selector": "h2, h3, h4",

    # ---- 合集 ----
    "folder_content_selector": ".post-content[itemprop='articleBody']",
    "folder_remove_selectors": [
        ".txt-apps", ".line", "blockquote", ".tags", ".content-tabs",
    ],
    "folder_img_attr": "data-xkrkllgl",

    # ---- 图片 ----
    "img_regex": r"loadBannerDirect\('([^']+)'",
    "aes_key": b"f5d965df75336270",
    "aes_iv": b"97b60394abc2fbe1",

    "headers": {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/134.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive",
    },
    "timeout": 15,
    "probe_timeout": 10,
}


# ============================================================
# 主类
# ============================================================
class Spider(_SpiderBase):
    cfg = SITE_CONFIG

    def __init__(self):
        self._host = ""
        self._proxies = {}
        self._headers = dict(self.cfg["headers"])
        self._candidates = []
        self._candidate_idx = -1
        self._ready = False

    def getName(self):
        return self.cfg["name"]

    def init(self, extend=""):
        try:
            self._proxies = json.loads(extend) if extend else {}
        except Exception:
            self._proxies = {}

        self._host = self._resolve_host()
        self._headers["Referer"] = self._host + "/"
        self._headers["Origin"] = self._host
        self._ready = True

        msg = f"[91] 最终使用域名: {self._host}"
        print(msg)
        try:
            self.log(msg)
        except Exception:
            pass

    # ============================================================
    # 域名发现（核心改动）
    # ============================================================
    def _resolve_host(self):
        all_links = []

        for p_url in self.cfg["publish_urls"]:
            print(f"\n[发布页] 请求: {p_url}")
            links = self._fetch_publish_links(p_url)
            print(f"[发布页] {p_url} -> 提取到 {len(links)} 个链接")
            for L in links:
                print(f"          · {L}")
            all_links.extend(links)

        # 去重保序
        seen = set()
        ordered = []
        for u in all_links:
            u = u.rstrip("/")
            if u.startswith("http") and u not in seen:
                seen.add(u)
                ordered.append(u)

        self._candidates = ordered
        print(f"\n[候选] 共 {len(ordered)} 个线路域名")

        if not ordered:
            print("[错误] 发布页没有提取到任何线路链接，请检查网络或发布页结构是否变化")
            return ""

        # 逐个探测
        for idx, url in enumerate(ordered):
            print(f"[探测] ({idx+1}/{len(ordered)}) {url} ...", end=" ")
            if self._probe(url):
                print("OK")
                self._candidate_idx = idx
                return url
            print("FAIL")

        print("[警告] 所有线路探测失败，返回第一个候选（后续请求时仍会自动轮换）")
        self._candidate_idx = 0
        return ordered[0]

    def _fetch_publish_links(self, p_url):
        """
        请求发布页，提取线路链接。
        适配你提供的静态 HTML 结构：
          <div class="list" id="list-wrap">
            <a href="https://broad.vfqju.cc">...</a>
            <a href="https://believe.vfqju.cc">...</a>
            ...
        不依赖 Base64 / meta refresh / JS 跳转。
        """
        try:
            r = requests.get(
                p_url, headers=self._headers, proxies=self._proxies,
                timeout=self.cfg["probe_timeout"], allow_redirects=True,
            )
            if r.status_code != 200:
                print(f"[发布页] HTTP {r.status_code}")
                return []
        except Exception as e:
            print(f"[发布页异常] {p_url}: {e}")
            return []

        html = r.text
        links = self._extract_links(html, p_url)
        if links:
            return links

        # 后备：如果静态解析失败，尝试 Base64（兼容旧格式）
        decoded = self._try_base64(html)
        if decoded != html:
            return self._extract_links(decoded, p_url)

        # 再后备：meta refresh / JS location（虽然你当前源码没有，但保留）
        jump = self._find_meta_refresh(html) or self._find_js_location(html)
        if jump:
            print(f"[发布页] 发现跳转 -> {jump}")
            return self._fetch_publish_links(jump)

        return []

    def _extract_links(self, html, base):
        """从 HTML 中提取线路链接"""
        links = []

        # 优先使用 pyquery 按容器选择器提取
        if _HAS_PQ and self.cfg["publish_link_selector"]:
            doc = pq(html)
            for a in doc(self.cfg["publish_link_selector"]).items():
                href = (a.attr("href") or "").strip()
                if href:
                    links.append(href)

        # 没有 pyquery 或容器选择器没抓到，全局扫描 <a href>
        if not links:
            for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', html or "", re.I):
                links.append(m.group(1))

        # 规范化 + 过滤
        out = []
        seen = set()
        for href in links:
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                p = urlparse(base)
                href = f"{p.scheme}://{p.netloc}{href}"
            if not href.startswith("http") or "." not in href:
                continue
            if any(ex in href for ex in self.cfg["publish_exclude"]):
                continue
            if href in seen:
                continue
            seen.add(href)
            out.append(href)
        return out

    def _try_base64(self, text):
        m = re.search(r"Base64\.decode\(['\"]([^'\"]+)['\"]\)", text)
        if m:
            try:
                return b64decode(m.group(1)).decode("utf-8", "ignore")
            except Exception:
                pass
        return text

    @staticmethod
    def _find_meta_refresh(html):
        m = re.search(
            r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+'
            r'content=["\'][^"\']*url=([^"\'>\s]+)',
            html or "", re.I,
        )
        return m.group(1).strip("'\"") if m else ""

    @staticmethod
    def _find_js_location(html):
        for pat in (
            r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
            r'document\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
            r'location\.replace\(\s*["\']([^"\']+)["\']',
            r'location\.assign\(\s*["\']([^"\']+)["\']',
        ):
            m = re.search(pat, html or "")
            if m:
                return m.group(1)
        return ""

    def _probe(self, url):
        """探测某个线路是否为目标站"""
        try:
            r = requests.get(
                url, headers=self._headers, proxies=self._proxies,
                timeout=self.cfg["probe_timeout"], allow_redirects=True,
            )
            if r.status_code != 200:
                return False

            # 优先 pyquery
            if _HAS_PQ:
                try:
                    return bool(pq(r.text)(self.cfg["host_check_selector"]))
                except Exception:
                    pass

            # 字符串兜底
            text = r.text or ""
            return any(t in text for t in self.cfg["host_check_terms"])
        except Exception:
            return False

    # ============================================================
    # 统一请求（失败自动轮换）
    # ============================================================
    @property
    def host(self):
        return self._host

    def _request(self, path, **kwargs):
        url = self._build_url(path)
        max_attempts = max(len(self._candidates), 1)
        attempted = set()

        for _ in range(max_attempts):
            if not self._host:
                break
            target = self._replace_host(url, self._host)
            if target in attempted:
                break
            attempted.add(target)
            try:
                r = requests.get(
                    target, headers=self._headers, proxies=self._proxies,
                    timeout=self.cfg["timeout"], **kwargs,
                )
                if r.status_code == 200:
                    return r
                if r.status_code in (403, 429, 502, 503, 504):
                    print(f"[失败] {target} -> HTTP {r.status_code}，切换线路")
                    if not self._next_host():
                        break
                    continue
                return r
            except Exception as e:
                print(f"[异常] {target}: {e}")
                if not self._next_host():
                    break
        return None

    def _next_host(self):
        n = len(self._candidates)
        if n <= 1:
            return None
        for offset in range(1, n + 1):
            i = (self._candidate_idx + offset) % n
            cand = self._candidates[i]
            if cand == self._host:
                continue
            if self._probe(cand):
                self._candidate_idx = i
                self._host = cand
                self._headers["Referer"] = cand + "/"
                self._headers["Origin"] = cand
                print(f"[切换] 新线路 -> {cand}")
                return cand
        return None

    def _build_url(self, p):
        p = (p or "").strip()
        if p.startswith("http"):
            return p
        if p.startswith("/"):
            return (self._host or "") + p
        return (self._host or "") + "/" + p

    @staticmethod
    def _replace_host(url, new_host):
        if not url.startswith("http"):
            return new_host.rstrip("/") + "/" + url.lstrip("/")
        old = urlparse(url)
        new = urlparse(new_host)
        return urlunparse(
            (new.scheme, new.netloc, old.path, old.params, old.query, old.fragment)
        )

    # ============================================================
    # 以下解析逻辑与 102 版一致（省略部分重复注释）
    # ============================================================
    def homeContent(self, filter):
        r = self._request("/")
        if not r:
            return {"class": [], "list": []}
        doc = pq(r.text)
        classes = []
        for sel in self.cfg["category_selectors"]:
            for item in doc(sel).items():
                a = item("a")
                href = (a.attr("href") or "").strip()
                name = (a.text() or "").strip()
                if href and href != "#" and name:
                    classes.append({"type_name": name, "type_id": href})
            if classes:
                break
        if not classes:
            classes = list(self.cfg["default_classes"])
        return {
            "class": classes,
            "list": self.getlist(doc(self.cfg["home_list_selector"])),
        }

    def homeVideoContent(self):
        r = self._request("/")
        if not r:
            return {"list": []}
        doc = pq(r.text)
        return {"list": self.getlist(doc(self.cfg["list_selector"]))}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            if "@folder" in tid:
                vids = self.getfod(tid.replace("@folder", ""))
                return {"list": vids, "page": pg, "pagecount": 1,
                        "limit": 90, "total": len(vids)}
            pg = int(pg)
            tid = tid.rstrip("/")
            path = f"{tid}/{pg}/" if pg > 1 else f"{tid}/"
            r = self._request(path)
            if not r:
                return {"list": [], "page": pg, "pagecount": pg,
                        "limit": 90, "total": 0}
            doc = pq(r.text)
            videos = self.getlist(doc("#archive article a, #index article a"), tid)

            total_pages, has_next = 1, False
            pn = doc("ul.page-navigator")
            if pn:
                mx = 0
                for a in pn("li a").items():
                    t = (a.text() or "").strip()
                    if t.isdigit():
                        mx = max(mx, int(t))
                total_pages = mx or 1
                if pn("li.next a").attr("href"):
                    has_next = True
            if total_pages <= 1:
                info = doc(".pagination .pages, .page-nav, .pagenavi").text() or ""
                if "共" in info and "页" in info:
                    try:
                        total_pages = int(info.split("共")[-1].split("页")[0])
                    except Exception:
                        pass
            if not has_next:
                nxt = doc("li.next a, a.next, a:contains('下一页')").attr("href")
                has_next = bool(nxt)
            pagecount = total_pages if total_pages > 1 else (pg + 1 if has_next else pg)
            return {"list": videos, "page": pg, "pagecount": pagecount,
                    "limit": 90, "total": pagecount * 90 if pagecount > 1 else len(videos)}
        except Exception as e:
            print(f"[categoryContent] {e}")
            return {"list": [], "page": pg, "pagecount": 1, "limit": 90, "total": 0}

    def detailContent(self, ids):
        raw_id = ids[0] if ids else ""
        r = self._request(raw_id)
        if not r:
            return {"list": [{
                "vod_play_from": self.cfg["play_from"],
                "vod_play_url": f"页面加载失败${raw_id}",
            }]}
        doc = pq(r.text)
        vod = {"vod_play_from": self.cfg["play_from"]}
        try:
            clist = []
            if doc(self.cfg["tag_selector"]):
                for k in doc(self.cfg["tag_selector"]).items():
                    t, h = k.text(), k.attr("href")
                    if t and h:
                        clist.append("[a=cr:" + json.dumps({"id": h, "name": t}) + "/]" + t + "[/a]")
            vod["vod_content"] = " ".join(clist) if clist else doc(self.cfg["title_selector"]).text()
        except Exception:
            vod["vod_content"] = doc(self.cfg["title_selector"]).text() or self.cfg["name"]
        try:
            plist = self._parse_players(doc)
            vod["vod_play_url"] = "#".join(plist) if plist else f"未找到视频源${self._build_url(raw_id)}"
        except Exception:
            vod["vod_play_url"] = f"视频解析失败${self._build_url(raw_id)}"
        return {"list": [vod]}

    def searchContent(self, key, quick, pg="1"):
        path = f"/search/{key}/{pg}/" if str(pg) != "1" else f"/search/{key}/"
        r = self._request(path)
        if not r:
            return {"list": [], "page": pg}
        return {"list": self.getlist(pq(r.text)(self.cfg["list_selector"])), "page": pg}

    def playerContent(self, flag, id, vipFlags):
        url, parse = id, 1
        if self.isVideoFormat(url):
            if ".m3u8" in url:
                url = self.proxy(url)
            parse = 0
        return {"parse": parse, "url": url, "header": self._headers}

    def _parse_players(self, doc):
        plist, used = [], set()
        sel, attr = self.cfg["player_selector"], self.cfg["player_config_attr"]
        if not doc(sel):
            return plist
        for idx, node in enumerate(doc(sel).items(), 1):
            raw = node.attr(attr)
            if not raw:
                continue
            try:
                cfg = json.loads(raw)
            except Exception:
                continue
            url = cfg.get("video", {}).get("url", "")
            if not url:
                continue
            name = ""
            try:
                parent = node.parents().eq(0)
                for _ in range(3):
                    if not parent:
                        break
                    h = parent.find(self.cfg["player_heading_selector"]).eq(0).text() or ""
                    if h.strip():
                        name = h.strip()
                        break
                    parent = parent.parents().eq(0)
            except Exception:
                pass
            name = name or f"视频{idx}"
            final, c = name, 2
            while final in used:
                final = f"{name} {c}"
                c += 1
            used.add(final)
            plist.append(f"{final}${url}")
        return plist

    def getlist(self, data, tid=""):
        videos = []
        is_folder = self.cfg["folder_id_marker"] in (tid or "")
        for k in data.items():
            href, name = k.attr("href"), k("h2").text()
            remark = k("span[itemprop='datePublished']").text() or k(".post-meta, .entry-meta, time").text()
            if not (href and name):
                continue
            videos.append({
                "vod_id": f"{href}{'@folder' if is_folder else ''}",
                "vod_name": name.replace("\n", " ").strip(),
                "vod_pic": self.getimg(k("script").text()),
                "vod_remarks": remark or "",
                "vod_tag": "folder" if is_folder else "",
                "style": self.cfg["style"],
            })
        return videos

    def getfod(self, folder_id):
        r = self._request(folder_id)
        if not r:
            return []
        doc = pq(r.text)
        body = doc(self.cfg["folder_content_selector"])
        for sel in self.cfg["folder_remove_selectors"]:
            body.remove(sel)
        p = body("p")
        out = []
        for i, h in enumerate(body("h2").items()):
            c = i * 2
            out.append({
                "vod_id": p.eq(c)("a").attr("href"),
                "vod_name": p.eq(c).text(),
                "vod_pic": f"{self.getProxyUrl()}&url={p.eq(c+1)('img').attr(self.cfg['folder_img_attr'])}&type=img",
                "vod_remarks": h.text(),
            })
        return out

    def getimg(self, text):
        m = re.search(self.cfg["img_regex"], text or "")
        return f"{self.getProxyUrl()}&url={m.group(1)}&type=img" if m else ""

    def isVideoFormat(self, url):
        return any(x in (url or "") for x in (".m3u8", ".mp4", ".ts"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def proxy(self, url, type_="m3u8"):
        if not url:
            return url
        try:
            return f"{self.getProxyUrl()}&url={self.e64(url)}&type={type_}"
        except Exception:
            return url

    def e64(self, text):
        try:
            return b64encode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def d64(self, text):
        try:
            return b64decode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def localProxy(self, param):
        if param.get("type") != "img":
            return [404, "text/plain", b""]
        try:
            res = requests.get(param["url"], headers=self._headers,
                               proxies=self._proxies, timeout=10)
            data = res.content
            if _HAS_CRYPTO:
                try:
                    data = unpad(AES.new(self.cfg["aes_key"], AES.MODE_CBC,
                                          self.cfg["aes_iv"]).decrypt(data), AES.block_size)
                except Exception:
                    pass
            return [200, res.headers.get("Content-Type", "image/jpeg"), data]
        except Exception:
            return [500, "text/plain", b""]


# ============================================================
# 入口：带详细日志的独立测试
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("91通用最终版 v2.1 · 静态发布页适配测试")
    print("=" * 60)
    print(f"TVBox: {'是' if _TVBOX else '否（独立运行）'}")
    print(f"pyquery: {'已安装' if _HAS_PQ else '未安装'}")
    print(f"Crypto: {'已安装' if _HAS_CRYPTO else '未安装'}")
    print()

    try:
        s = Spider()
        s.init("")
        print(f"\n最终线路: {s.host or '(空)'}")
        print()

        if s.host:
            print("[首页] 请求中 ...")
            r = s._request("/")
            if r:
                print(f"[首页] OK, 长度 = {len(r.text)}")
                home = s.homeContent(None)
                print(f"[首页] 分类数 = {len(home.get('class', []))}")
                print(f"[首页] 视频数 = {len(home.get('list', []))}")
                for it in home.get("list", [])[:5]:
                    print(f"  · {it.get('vod_name')}  ({it.get('vod_remarks')})")
            else:
                print("[首页] 请求失败")
        else:
            print("[警告] 没有可用线路，无法继续测试首页")
    except KeyboardInterrupt:
        print("\n用户中断")
    except Exception:
        print("\n[未捕获异常]")
        traceback.print_exc()
