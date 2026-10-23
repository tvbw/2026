#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
91通用最终版（单文件 · 可直接运行）
=============================================================
域名发现顺序：
  1) 发布页 https://91jav18.cc    (js_base64)
  2) 发布页 https://91jav19.cc    (js_base64)
  3) 兜底   https://basis.vfqju.cc/
  4) 兜底   https://adult.vfqju.cc/

使用方式：
  A) 本地测试：  python 91av.py
  B) TVBox：     放到爬虫目录，配置名 "91通用最终版"
=============================================================
"""
import json
import re
import sys
from base64 import b64decode, b64encode
from urllib.parse import urlparse, urlunparse

# ---- 依赖检查 ----
try:
    import requests
except ImportError:
    sys.stderr.write(
        "\n[致命] 缺少 requests 库\n"
        "请先运行：  pip install requests\n\n"
    )
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
    # 独立运行时的最小接口，保证代码可执行
    class _SpiderBase(object):
        def getProxyUrl(self):
            return "http://127.0.0.1:9978/proxy"
        def log(self, msg):
            pass
    _TVBOX = False


# ============================================================
# 站点配置（全部集中在这里，方便维护）
# ============================================================
SITE_CONFIG = {
    "name": "91通用最终版",
    "play_from": "91通用最终版",
    "style": {"type": "rect", "ratio": 1.33},

    # ---- 域名发现 ----
    "publish_urls": [
        "https://91jav18.cc",
        "https://91jav19.cc",
    ],
    "publish_decode": "js_base64",
    "host_check_selector": "#index article a",
    "fallback_hosts": [
        "https://basis.vfqju.cc/",
        "https://adult.vfqju.cc/",
    ],

    # ---- 列表 ----
    "list_selector": "#index article a, #archive article a",
    "home_list_selector": "#index article a",
    "category_selectors": [
        ".category-list ul li",
        ".nav-menu li",
        ".menu li",
        "nav ul li",
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

    # ---- 生命周期 ----
    def __init__(self):
        # TVBox 会直接调用 init()，所以 __init__ 只做最基本初始化
        self._host = ""
        self._proxies = {}
        self._headers = dict(self.cfg["headers"])
        self._candidates = []        # 候选域名（发现后填充）
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
    # 域名发现
    # ============================================================
    def _resolve_host(self):
        candidates = []

        # 1) 从两个发布页收集候选
        for p_url in self.cfg["publish_urls"]:
            got = self._collect_from_publish(p_url)
            print(f"[发布页] {p_url} -> 解析到 {len(got)} 个链接")
            candidates.extend(got)

        # 2) 兜底域名补在后面
        candidates.extend(h.rstrip("/") for h in self.cfg["fallback_hosts"])

        # 3) 去重保序
        seen = set()
        ordered = []
        for c in candidates:
            c = (c or "").rstrip("/")
            if c.startswith("http") and c not in seen:
                seen.add(c)
                ordered.append(c)

        self._candidates = ordered
        print(f"[候选] 共 {len(ordered)} 个候选域名")

        # 4) 逐个探测
        for idx, url in enumerate(ordered):
            print(f"[探测] ({idx+1}/{len(ordered)}) {url} ...", end=" ")
            if self._probe(url):
                print("OK")
                self._candidate_idx = idx
                return url
            print("FAIL")

        print("[警告] 所有候选都探测失败，使用第一个兜底域名")
        return self.cfg["fallback_hosts"][0].rstrip("/")

    def _collect_from_publish(self, p_url):
        """从单个发布页提取候选域名（含 meta/JS 跳转补丁）"""
        try:
            r = requests.get(
                p_url, headers=self._headers, proxies=self._proxies,
                timeout=self.cfg["probe_timeout"], allow_redirects=True,
            )
            if r.status_code != 200:
                return []
        except Exception as e:
            print(f"[发布页异常] {p_url}: {e}")
            return []

        html = self._decode_publish(r.text)
        links = self._extract_domain_links(html, p_url)
        if links:
            return links

        # 拿不到候选，尝试跳转
        jump = self._find_meta_refresh(r.text) or self._find_js_location(r.text)
        if not jump:
            return []

        if jump.startswith("//"):
            jump = "https:" + jump
        elif jump.startswith("/"):
            p = urlparse(p_url)
            jump = f"{p.scheme}://{p.netloc}{jump}"
        if not jump.startswith("http"):
            return []

        print(f"[跳转] 发现跳转 -> {jump}")
        try:
            r2 = requests.get(jump, headers=self._headers, proxies=self._proxies,
                              timeout=self.cfg["probe_timeout"], allow_redirects=True)
            if r2.status_code == 200:
                return self._extract_domain_links(
                    self._decode_publish(r2.text), jump)
        except Exception:
            pass
        return []

    def _probe(self, url):
        try:
            r = requests.get(url, headers=self._headers, proxies=self._proxies,
                             timeout=self.cfg["probe_timeout"], allow_redirects=True)
            if r.status_code != 200:
                return False
            sel = self.cfg["host_check_selector"]
            if _HAS_PQ:
                return bool(pq(r.text)(sel))
            # 没有 pyquery 时退化为字符串检查
            return ("index" in r.text and "article" in r.text)
        except Exception:
            return False

    def _decode_publish(self, text):
        mode = self.cfg["publish_decode"]
        if mode == "js_base64":
            m = re.search(r"Base64\.decode\(['\"]([^'\"]+)['\"]\)", text)
            if m:
                try:
                    return b64decode(m.group(1)).decode("utf-8", "ignore")
                except Exception:
                    pass
        elif mode == "js_atob":
            m = re.search(r"atob\(['\"]([^'\"]+)['\"]\)", text)
            if m:
                try:
                    return b64decode(m.group(1)).decode("utf-8", "ignore")
                except Exception:
                    pass
        return text

    @staticmethod
    def _extract_domain_links(html, base):
        out, seen = [], set()
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', html or ""):
            href = m.group(1)
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                p = urlparse(base)
                href = f"{p.scheme}://{p.netloc}{href}"
            if not href.startswith("http") or "." not in href:
                continue
            if any(x in href for x in ("javascript:", "mailto:", "#")):
                continue
            if href in seen:
                continue
            seen.add(href)
            out.append(href)
        return out

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

    # ============================================================
    # 统一请求（失败自动轮换）
    # ============================================================
    @property
    def host(self):
        return self._host

    def _request(self, path, **kwargs):
        url = self._build_url(path)
        # 允许尝试所有候选，每个 1 次
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
                    print(f"[失败] {target} -> HTTP {r.status_code}，切换域名")
                    if not self._next_host():
                        break
                    continue
                return r  # 404 之类非域名问题，直接返回
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
                print(f"[切换] 新域名 -> {cand}")
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
    # 首页 / 分类 / 详情 / 搜索 / 播放（51 主题原样搬过来）
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
            videos = self.getlist(
                doc("#archive article a, #index article a"), tid
            )

            # 页数判定（同 102）
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
                nxt = doc(
                    "ul.page-navigator li.next a, "
                    ".pagination a.next, .pagenavi a.next, "
                    "li.next a, a.next, a:contains('下一页')"
                ).attr("href")
                has_next = bool(nxt)

            pagecount = total_pages if total_pages > 1 else (
                pg + 1 if has_next else pg
            )
            total_count = pagecount * 90 if pagecount > 1 else len(videos)

            return {"list": videos, "page": pg, "pagecount": pagecount,
                    "limit": 90, "total": total_count}
        except Exception as e:
            print(f"[categoryContent] {e}")
            return {"list": [], "page": pg, "pagecount": 1,
                    "limit": 90, "total": 0}

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
                        clist.append(
                            "[a=cr:" + json.dumps({"id": h, "name": t}) + "/]"
                            + t + "[/a]"
                        )
            vod["vod_content"] = (
                " ".join(clist) if clist
                else doc(self.cfg["title_selector"]).text()
            )
        except Exception:
            vod["vod_content"] = doc(self.cfg["title_selector"]).text() or self.cfg["name"]

        try:
            plist = self._parse_players(doc)
            vod["vod_play_url"] = (
                "#".join(plist) if plist else f"未找到视频源${self._build_url(raw_id)}"
            )
        except Exception:
            vod["vod_play_url"] = f"视频解析失败${self._build_url(raw_id)}"

        return {"list": [vod]}

    def searchContent(self, key, quick, pg="1"):
        if str(pg) != "1":
            path = f"/search/{key}/{pg}/"
        else:
            path = f"/search/{key}/"
        r = self._request(path)
        if not r:
            return {"list": [], "page": pg}
        doc = pq(r.text)
        return {"list": self.getlist(doc(self.cfg["list_selector"])), "page": pg}

    def playerContent(self, flag, id, vipFlags):
        url = id
        parse = 1
        if self.isVideoFormat(url):
            if ".m3u8" in url:
                url = self.proxy(url)
            parse = 0
        return {"parse": parse, "url": url, "header": self._headers}

    # ============================================================
    # 内部解析
    # ============================================================
    def _parse_players(self, doc):
        plist, used = [], set()
        sel = self.cfg["player_selector"]
        attr = self.cfg["player_config_attr"]
        if not doc(sel):
            return plist

        for idx, node in enumerate(doc(sel).items(), start=1):
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
                    h = parent.find(
                        self.cfg["player_heading_selector"]).eq(0).text() or ""
                    h = h.strip()
                    if h:
                        name = h
                        break
                    parent = parent.parents().eq(0)
            except Exception:
                name = ""
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
            href = k.attr("href")
            name = k("h2").text()
            remark = (
                k("span[itemprop='datePublished']").text()
                or k(".post-meta, .entry-meta, time").text()
            )
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
                "vod_pic": (
                    f"{self.getProxyUrl()}&url="
                    f"{p.eq(c+1)('img').attr(self.cfg['folder_img_attr'])}&type=img"
                ),
                "vod_remarks": h.text(),
            })
        return out

    def getimg(self, text):
        m = re.search(self.cfg["img_regex"], text or "")
        if m:
            return f"{self.getProxyUrl()}&url={m.group(1)}&type=img"
        return ""

    def isVideoFormat(self, url):
        return any(x in (url or "") for x in (".m3u8", ".mp4", ".ts"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ---- 本地代理（图片/视频） ----
    def proxy(self, url, type_="m3u8"):
        if not url:
            return url
        try:
            base = self.getProxyUrl()
        except Exception:
            return url
        return f"{base}&url={self.e64(url)}&type={type_}"

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
        t = param.get("type")
        if t == "img":
            try:
                res = requests.get(param["url"], headers=self._headers,
                                   proxies=self._proxies, timeout=10)
                data = res.content
                if _HAS_CRYPTO:
                    try:
                        data = unpad(
                            AES.new(self.cfg["aes_key"], AES.MODE_CBC,
                                    self.cfg["aes_iv"]).decrypt(data),
                            AES.block_size,
                        )
                    except Exception:
                        pass
                return [200, res.headers.get("Content-Type", "image/jpeg"), data]
            except Exception:
                return [500, "text/plain", b""]
        return [404, "text/plain", b""]


# ============================================================
# 离线自检（不依赖文件名，随便叫什么都能跑）
# ============================================================
def _self_test():
    import unittest
    from unittest import mock

    class TestReplaceHost(unittest.TestCase):
        def test_relative_path(self):
            self.assertEqual(
                Spider._replace_host("/abc/x?y=1", "https://n.com"),
                "https://n.com/abc/x?y=1",
            )

        def test_absolute_url(self):
            self.assertEqual(
                Spider._replace_host("https://old.com/p/a?k=v#f", "https://new.com"),
                "https://new.com/p/a?k=v#f",
            )

    class TestHostSwitch(unittest.TestCase):
        def test_switch_on_failure(self):
            """当前域名 500，_next_host 应切到下一个可用域名"""

            def fake_get(url, **_):
                ok = "good.com" in url
                class R:
                    status_code = 200 if ok else 500
                    text = "<div id='index'><article><a href='/x'>t</a></article></div>"
                return R()

            s = Spider()
            s._host = "https://bad.com"
            s._candidates = ["https://bad.com", "https://good.com"]
            s._candidate_idx = 0
            s._headers = dict(SITE_CONFIG["headers"])

            with mock.patch.object(requests, "get", side_effect=fake_get):
                new = s._next_host()
                self.assertEqual(new, "https://good.com")
                self.assertEqual(s.host, "https://good.com")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (TestReplaceHost, TestHostSwitch):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("91通用最终版 · 单文件测试")
    print("=" * 60)
    print(f"TVBox 环境: {'是' if _TVBOX else '否（独立运行）'}")
    print(f"pyquery  : {'已安装' if _HAS_PQ else '未安装（强烈建议 pip install pyquery）'}")
    print(f"Crypto   : {'已安装' if _HAS_CRYPTO else '未安装（图片解密可能失败）'}")
    print()

    # ---- 第 1 步：离线自检 ----
    print("-" * 60)
    print("第 1 步：离线自检（不联网）")
    print("-" * 60)
    ok = _self_test()
    print()
    print(f"离线自检结果: {'全部通过 ✓' if ok else '有失败 ✗'}")
    print()

    # ---- 第 2 步：联网测试 ----
    print("-" * 60)
    print("第 2 步：联网测试（Ctrl+C 可跳过）")
    print("-" * 60)
    try:
        s = Spider()
        s.init("")
        print(f"最终域名: {s.host}")
        print()

        print("[首页] 请求中 ...")
        r = s._request("/")
        if r:
            print(f"[首页] OK, 长度 = {len(r.text)}")
            home = s.homeContent(None)
            print(f"[首页] 分类数 = {len(home.get('class', []))}")
            print(f"[首页] 视频数 = {len(home.get('list', []))}")
            for it in home.get("list", [])[:3]:
                print(f"  · {it.get('vod_name')}  ({it.get('vod_remarks')})")
        else:
            print("[首页] 请求失败，域名可能都不通")
    except KeyboardInterrupt:
        print("用户中断")
    except Exception as e:
        print(f"[联网测试异常] {e}")
        import traceback
        traceback.print_exc()
