#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
57吃瓜 · 直达域名自愈 + 播放相关推荐（urllib 版 V6）
=====================================================
V6 相比 V5 新增
- 【新增】播放页面「相关推荐」：当前页其他视频以 nid:base64url(event_id) 伪集
        追加到播放列表末尾，点开即切到对应视频
- 【新增】_cache_items / _items_of / _encode_nid / _decode_nid
- 【新增】_extract_episodes 从 detailContent 抽出，供 _fetch_real_stream 复用
- 【新增】_fetch_real_stream LRU 缓存，来回点推荐不重复请求
- 【新增】detailContent 兼容 nid: 前缀入口
- 其余（域名自愈 / 内容校验 / 11 分类 / slug 路由 / 5 层视频解析）与 V5 一致
=====================================================
"""

import sys
import os
import re
import json
import time
import base64
import gzip
import zlib
import ssl
import http.cookiejar
import urllib.request
import urllib.parse
from urllib.parse import urlparse, quote, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        def getCache(self, key): return None
        def setCache(self, key, value): return "fail"
        def delCache(self, key): return "fail"


class Spider(SpiderBase):
    # ================== 站点配置 ==================
    SITE_NAME    = "57吃瓜"
    PLAY_FROM    = "57吃瓜在线"

    HOSTS_CG = [
        "https://57cg4.com",
        "https://57cg1.com",
        "https://57cg2.com",
        "https://57cg3.com",
    ]
    HOSTS_SITE = [
        "https://57cg1.com",
    ]

    FAST_TIMEOUT   = 6
    PROBE_MIN_HTML = 1000

    BLOCKED_MARKERS = (
        'just a moment', 'cf-browser-verification', 'cf-challenge',
        'checking your browser', '__cf_chl_', 'ddos-guard',
        'cf-ray', 'cloudflare-nginx', 'enable javascript and cookies',
    )
    VALID_MARKERS = ("/events/", "events/", "/thread/", "/t/", "events")

    HOST_CACHE_KEY = "cg57_host_v1"
    HOST_CACHE_TTL = 6 * 3600

    def __init__(self):
        super(Spider, self).__init__()
        self.cgUrl      = self.HOSTS_CG[0]
        self.siteUrl    = self.HOSTS_SITE[0]
        self.imgReferer = self.HOSTS_CG[0] + "/"

        self.tgGroup       = "https://t.me/tvshare23"
        self.brandActor    = "🦋 23"
        self.brandDirector = "🦋 影视"

        self._ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0.0.0 Safari/537.36")
        self.options = {}

        # ---- 播放相关推荐缓存 ----
        self._page_cache   = {}   # key → [vod items]
        self._page_index   = {}   # vid → key
        self._page_keys    = []   # LRU keys
        self._detail_cache = {}   # vid → 第一条真实地址

        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx)
        )

    # ================== 生命周期 ==================
    def init(self, extend=""):
        # 清空缓存
        self._page_cache   = {}
        self._page_index   = {}
        self._page_keys    = []
        self._detail_cache = {}

        if isinstance(extend, dict):
            self.options = extend
        elif extend:
            try:
                self.options = json.loads(extend)
            except Exception:
                self.options = {}

        manual = ""
        if isinstance(self.options, dict):
            manual = self.options.get("host", "") or ""
        if not manual and isinstance(extend, str) and extend.strip().startswith("http"):
            manual = extend.strip()

        if manual:
            manual = manual.strip().rstrip("/")
            if not manual.startswith("http"):
                manual = "https://" + manual
            print(f"【extend 指定】使用域名: {manual}")
            self.cgUrl = manual
            self.siteUrl = manual
            self.imgReferer = manual + "/"
        else:
            self._resolve_hosts()

        print(f"使用站点: CG={self.cgUrl} SITE={self.siteUrl}")
        return True

    def getName(self):
        return self.SITE_NAME

    def isVideoFormat(self, url):
        low = (url or "").lower()
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".mkv", ".ts"))

    def manualVideoCheck(self):
        return False

    # ================== 域名探测 ==================
    def _resolve_hosts(self):
        cached = self._read_host_cache()
        if cached:
            cg = cached.get("cg", "")
            site = cached.get("site", "")
            if cg and self._verify_host(cg):
                self.cgUrl = cg.rstrip("/")
                if site and site.rstrip("/") != self.cgUrl and self._verify_host(site):
                    self.siteUrl = site.rstrip("/")
                else:
                    self.siteUrl = self.cgUrl
                self.imgReferer = self.cgUrl + "/"
                print(f"缓存有效: CG={self.cgUrl} SITE={self.siteUrl}")
                return
            print("缓存失效，重新探测")

        print(f"--- 探测 CG 域名 {len(self.HOSTS_CG)} 个 ---")
        cg = self._probe_hosts(self.HOSTS_CG)
        if cg:
            self.cgUrl = cg.rstrip("/")

        print(f"--- 探测 SITE 域名 {len(self.HOSTS_SITE)} 个 ---")
        site = self._probe_hosts(self.HOSTS_SITE)
        if site:
            self.siteUrl = site.rstrip("/")
        else:
            print("【警告】SITE 域名全部失败，降级到 CG")
            self.siteUrl = self.cgUrl

        self.imgReferer = self.cgUrl + "/"
        self._write_host_cache({"cg": self.cgUrl, "site": self.siteUrl})

    def _probe_hosts(self, urls):
        urls = [u.rstrip("/") for u in urls if u]
        if not urls:
            return ""
        results = {}
        try:
            with ThreadPoolExecutor(max_workers=min(6, len(urls))) as ex:
                futs = {ex.submit(self._probe_one, u): u for u in urls}
                try:
                    for f in as_completed(futs, timeout=self.FAST_TIMEOUT + 5):
                        u = futs[f]
                        try:
                            ok, final = f.result()
                            results[u] = final if ok else ""
                        except Exception:
                            results[u] = ""
                except Exception:
                    pass
        except Exception:
            pass

        for u in urls:
            if results.get(u):
                return results[u]
        return ""

    def _probe_one(self, url):
        try:
            base = url.rstrip("/") + "/"
            req = urllib.request.Request(base, headers={
                "User-Agent": self._ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Accept-Encoding": "gzip, deflate",
            })
            with self.opener.open(req, timeout=self.FAST_TIMEOUT) as resp:
                if resp.getcode() != 200:
                    print(f"  [探测失败] {url} HTTP={resp.getcode()}")
                    return False, ""
                raw = resp.read()
                enc = getattr(resp, "headers", {}).get("Content-Encoding", "")
                if raw.startswith(b"\x1f\x8b") or enc == "gzip":
                    try: raw = gzip.decompress(raw)
                    except Exception: pass
                elif enc == "deflate":
                    try: raw = zlib.decompress(raw)
                    except Exception:
                        try: raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                        except Exception: pass
                text = raw.decode("utf-8", errors="ignore")
                if not self._is_site_ok(text):
                    print(f"  [探测不匹配] {url} 长度={len(text)}")
                    return False, ""
                final_url = resp.geturl() or base
                final_host = self._final_host_url(final_url) or url.rstrip("/")
                print(f"  [探测成功] {url} → {final_host}")
                return True, final_host
        except Exception as e:
            print(f"  [探测异常] {url} {e}")
            return False, ""

    def _is_site_ok(self, html):
        if not html or len(html) < self.PROBE_MIN_HTML:
            return False
        low = html.lower()
        if any(m in low for m in self.BLOCKED_MARKERS):
            return False
        return any(m in html for m in self.VALID_MARKERS)

    @staticmethod
    def _final_host_url(url):
        if not url:
            return ""
        try:
            p = urlparse(url)
            if p.scheme in ("http", "https") and p.netloc:
                return "%s://%s" % (p.scheme, p.netloc.lower())
        except Exception:
            pass
        return ""

    def _verify_host(self, url):
        ok, _final = self._probe_one(url)
        return ok

    # ================== 缓存 ==================
    def _read_host_cache(self):
        try:
            raw = self.getCache(self.HOST_CACHE_KEY)
        except Exception:
            return None
        if not raw:
            return None
        try:
            if isinstance(raw, str):
                raw = json.loads(raw)
            if not isinstance(raw, dict):
                return None
            ts = int(raw.get("ts") or 0)
            if time.time() - ts >= self.HOST_CACHE_TTL:
                return None
            return raw
        except Exception:
            return None

    def _write_host_cache(self, data):
        try:
            data["ts"] = int(time.time())
            self.setCache(self.HOST_CACHE_KEY,
                          json.dumps(data, ensure_ascii=False))
        except Exception:
            pass

    # ================== 网络请求 ==================
    def _fetch(self, target_url, referer=""):
        if not target_url:
            return {"code": 0, "text": "", "bytes": b"", "err": "", "final_url": ""}
        if target_url.startswith("//"):
            target_url = "https:" + target_url
        elif target_url.startswith("/"):
            target_url = (self.siteUrl or self.HOSTS_SITE[0]) + target_url

        headers = {
            "User-Agent": self._ua,
            "Referer": referer if referer else self.imgReferer,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }

        for attempt in range(2):
            try:
                req = urllib.request.Request(target_url, headers=headers)
                with self.opener.open(req, timeout=12) as resp:
                    code = resp.getcode()
                    final_url = resp.geturl()
                    raw = resp.read()
                    enc = getattr(resp, "headers", {}).get("Content-Encoding", "")
                    if raw.startswith(b"\x1f\x8b") or enc == "gzip":
                        raw = gzip.decompress(raw)
                    elif enc == "deflate":
                        try:
                            raw = zlib.decompress(raw)
                        except Exception:
                            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                    try:
                        text = raw.decode("utf-8")
                    except Exception:
                        text = raw.decode("latin1", errors="ignore")
                    return {"code": code, "text": text, "bytes": raw,
                            "err": "", "final_url": final_url}
            except Exception as e:
                if attempt == 0:
                    continue
                return {"code": -1, "text": "", "bytes": b"",
                        "err": str(e), "final_url": target_url}

        return {"code": -1, "text": "", "bytes": b"",
                "err": "timeout", "final_url": target_url}

    # ================== 图片 ==================
    def _wrap_pic(self, pic_url):
        if not pic_url:
            return ""
        if pic_url.startswith("//"):
            pic_url = "https:" + pic_url
        elif pic_url.startswith("/"):
            pic_url = (self.siteUrl or self.HOSTS_SITE[0]) + pic_url
        if "s.chigua.media" in pic_url and "@" not in pic_url:
            return "%s@Referer=%s@User-Agent=%s" % (
                pic_url, self.imgReferer, quote(self._ua))
        return pic_url

    # ================== 播放相关推荐：基础工具 ==================
    @staticmethod
    def _clean_name(s):
        return str(s or "").replace("$", " ").replace("#", " ").strip()

    @staticmethod
    def _encode_nid(vid):
        try:
            return base64.urlsafe_b64encode(
                str(vid).encode("utf-8")).decode("ascii").rstrip("=")
        except Exception:
            return ""

    @staticmethod
    def _decode_nid(s):
        s = str(s or "")
        if s.startswith("nid:"):
            s = s[4:]
        if not s:
            return ""
        pad = "=" * (-len(s) % 4)
        try:
            return base64.urlsafe_b64decode(s + pad).decode("utf-8", "ignore")
        except Exception:
            return ""

    def _cache_items(self, key, items):
        out = [x for x in (items or []) if isinstance(x, dict) and x.get("vod_id")]
        if not out:
            return
        self._page_cache[key] = out
        if key in self._page_keys:
            self._page_keys.remove(key)
        self._page_keys.append(key)
        for it in out:
            self._page_index[str(it["vod_id"])] = key
        while len(self._page_keys) > 30:
            self._page_cache.pop(self._page_keys.pop(0), None)

    def _items_of(self, vid):
        key = self._page_index.get(str(vid))
        if key is None or key not in self._page_cache:
            return []
        return list(self._page_cache.get(key, []))

    # ================== 首页 ==================
    def homeContent(self, filter):
        classes = [
            {"type_name": "成人AI短剧", "type_id": "cat_aichengduanju"},
            {"type_name": "热门精选",   "type_id": "cat_hot"},
            {"type_name": "今日吃瓜",   "type_id": "cat_jrcg"},
            {"type_name": "每日大赛",   "type_id": "cat_mrds"},
            {"type_name": "网红黑料",   "type_id": "cat_wanghong"},
            {"type_name": "网黄合集",   "type_id": "cat_video"},
            {"type_name": "出轨劈腿",   "type_id": "cat_cheating"},
            {"type_name": "直播擦边",   "type_id": "cat_live"},
            {"type_name": "社会事件",   "type_id": "cat_society"},
            {"type_name": "明星八卦",   "type_id": "cat_star"},
            {"type_name": "全部短剧",   "type_id": "cat_all"}
        ]
        result = {"class": classes}
        if filter:
            sort_filter = [{
                "key": "sort",
                "name": "排序",
                "value": [
                    {"n": "最新发布", "v": ""},
                    {"n": "全站最热", "v": "hot"},
                    {"n": "飙升热榜", "v": "trending"}
                ]
            }]
            filters_dict = {}
            for item in classes:
                filters_dict[item["type_id"]] = sort_filter
            result["filters"] = filters_dict
        return result

    def homeVideoContent(self):
        res = self.categoryContent("cat_aichengduanju", 1, False, {})
        lst = res.get("list", [])[:12]
        if lst:
            self._cache_items(("homev",), lst)     # 首页 12 条作为相关推荐
        return {"list": lst}

    # ================== 列表 ==================
    def _parse_card_list(self, html_text):
        vod_list = []
        seen_ids = set()

        pattern_events = r'<a[^>]+href=["\'](?:https?://[^/]+)?/events/(\d+)/?["\'][^>]*>([\s\S]*?)</a>'
        matches = re.findall(pattern_events, html_text)

        if not matches:
            pattern_all = r'<a[^>]+href=["\'](?:https?://[^/]+)?/(?:events/)?(\d+)/?["\'][^>]*>([\s\S]*?)</a>'
            matches = re.findall(pattern_all, html_text)

        for event_id, inner in matches:
            if event_id in seen_ids or len(event_id) < 2:
                continue
            seen_ids.add(event_id)

            m_t = re.search(r'<h[23][^>]*>([\s\S]*?)</h[23]>', inner)
            if m_t:
                name = re.sub(r'<[^>]+>', '', m_t.group(1)).strip()
            else:
                raw_txt = re.sub(r'<[^>]+>', ' ', inner).strip()
                name = raw_txt[:40] if raw_txt else ("短剧/热点 %s" % event_id)

            pic = ""
            img_matches = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', inner)
            for src_cand in img_matches:
                if not src_cand.endswith(".svg") and "logo" not in src_cand:
                    pic = src_cand.strip()
                    break

            vod_list.append({
                "vod_id": event_id,
                "vod_name": name,
                "vod_pic": self._wrap_pic(pic),
                "vod_remarks": "蝴蝶影视",
                "style": {"type": "rect", "ratio": 1.78}
            })

        return vod_list

    def categoryContent(self, tid, pg, filter, extend):
        del filter
        page = int(pg) if pg else 1
        raw_slug = str(tid).strip("/")
        slug = raw_slug.replace("cat_", "")
        sort_val = extend.get("sort") if isinstance(extend, dict) else ""

        if slug == "all":
            base = self.siteUrl
            target_url = ("%s/page/%d/" % (base, page)) if page > 1 else ("%s/" % base)
        elif slug in ("aichengduanju", "hot"):
            base = self.siteUrl
            target_url = ("%s/%s/%d/" % (base, slug, page)) if page > 1 else ("%s/%s/" % (base, slug))
        else:
            base = self.cgUrl
            target_url = ("%s/%s/%d/" % (base, slug, page)) if page > 1 else ("%s/%s/" % (base, slug))

        if sort_val:
            target_url += ("&sort=%s" if "?" in target_url else "?sort=%s") % sort_val

        res = self._fetch(target_url)
        html_text = res.get("text", "")
        vod_list = self._parse_card_list(html_text)

        # 缓存本页作为相关推荐来源
        if vod_list:
            self._cache_items(
                ("cate", str(tid), str(page), str(sort_val or "")), vod_list)

        return {
            "page": page,
            "pagecount": page + 1 if len(vod_list) >= 10 else page,
            "limit": len(vod_list),
            "total": 9999,
            "list": vod_list
        }

    # ================== 详情（含相关推荐聚合）==================
    def _extract_episodes(self, detail_html):
        """从详情 HTML 提取 (episodes, cover, title, desc)，供 detailContent / _fetch_real_stream 复用"""
        title, desc, cover = "", "", ""
        episodes = []

        m_title = re.search(r'<h1[^>]*>([\s\S]*?)</h1>', detail_html)
        if m_title:
            title = re.sub(r'<[^>]+>', '', m_title.group(1)).strip()

        m_desc = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
            detail_html)
        if m_desc:
            desc = m_desc.group(1).strip()

        # 1. <video> 标签
        v_blocks = re.findall(r'<video([^>]+)>', detail_html)
        for attr in v_blocks:
            m_hls = re.search(r'data-hls-src=["\']([^"\']+)["\']', attr)
            m_src = re.search(r'src=["\']([^"\']+)["\']', attr)
            stream_url = (m_hls.group(1).strip() if m_hls
                          else (m_src.group(1).strip() if m_src else ""))
            if not cover:
                m_post = re.search(r'poster=["\']([^"\']+)["\']', attr)
                if m_post:
                    cover = m_post.group(1).strip()
            if stream_url:
                episodes.append("片段 %02d$%s" % (len(episodes) + 1, stream_url))

        # 2. JSON-LD VideoObject
        if not episodes:
            m_schema = re.findall(
                r'<script\s+type=["\']application/ld\+json["\']>([\s\S]*?)</script>',
                detail_html)
            for s in m_schema:
                if '"VideoObject"' in s:
                    try:
                        data = json.loads(s)
                        v_list = data.get("video", [])
                        if isinstance(v_list, dict):
                            v_list = [v_list]
                        for v_item in v_list:
                            c_url = v_item.get("contentUrl", "")
                            if c_url:
                                episodes.append("第 %02d 集$%s" % (len(episodes) + 1, c_url))
                                if not cover:
                                    cover = v_item.get("thumbnailUrl", "")
                    except Exception:
                        pass

        # 3. 正则兜底
        if not episodes:
            all_media = re.findall(
                r'["\'](https?://[^"\'\s]+\.(?:m3u8|mp4)[^"\'\s]*)["\']',
                detail_html)
            seen_streams = set()
            for m_url in all_media:
                if m_url in seen_streams:
                    continue
                seen_streams.add(m_url)
                episodes.append("播放 %02d$%s" % (len(episodes) + 1, m_url))

        if not cover:
            m_pic = re.search(
                r'<meta property=["\']og:image["\'] content=["\']([^"\']+)["\']',
                detail_html)
            if m_pic:
                cover = m_pic.group(1).strip()

        return episodes, cover, title, desc

    def _build_playlist_with_related(self, vid, own_episodes, related):
        """当前视频保留真实片段；当前页其他视频以 nid: 伪集追加"""
        parts, used = [], set()

        for ep in (own_episodes or []):
            name = self._clean_name(ep.split("$", 1)[0] if "$" in ep else ep)
            if not name or name in used:
                continue
            used.add(name)
            parts.append(ep)

        # 当前视频一个片段都没解析到：用 nid 占位，playerContent 会自己抓
        if not parts:
            cur_name = "正片"
            for it in related:
                if str(it.get("vod_id")) == str(vid):
                    cur_name = self._clean_name(it.get("vod_name") or "") or "正片"
                    break
            parts.append("%s$nid:%s" % (cur_name, self._encode_nid(vid)))
            used.add(cur_name)

        for it in related:
            iid = str(it.get("vod_id") or "")
            if not iid or iid == str(vid):
                continue
            name = self._clean_name(it.get("vod_name") or iid) or iid
            if not name or name in used:
                continue
            used.add(name)
            parts.append("%s$nid:%s" % (name, self._encode_nid(iid)))

        return "#".join(parts)

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) else str(ids)
        event_id = raw_id.strip("/")

        # 允许 nid: 前缀（从推荐再点进详情）
        if event_id.startswith("nid:"):
            decoded = self._decode_nid(event_id)
            if decoded:
                event_id = decoded

        target_url = "%s/events/%s/" % (self.cgUrl, event_id)
        res = self._fetch(target_url)
        detail_html = res.get("text", "")

        if (not detail_html or len(detail_html) < 500) and self.siteUrl != self.cgUrl:
            target_url = "%s/events/%s/" % (self.siteUrl, event_id)
            res = self._fetch(target_url)
            detail_html = res.get("text", "")

        episodes, cover, title, desc = self._extract_episodes(detail_html)

        if not title:
            title = "AI短剧/热点 %s" % event_id
        if not desc:
            desc = "暂无详细介绍"

        # ---- 拼接相关推荐 ----
        related = self._items_of(event_id)
        if related:
            play_url = self._build_playlist_with_related(event_id, episodes, related)
        else:
            play_url = "#".join(episodes) if episodes else ("无可用视频流$http://127.0.0.1")

        full_desc = (
            "【🔥 官方交流群: %s】\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "本贴为您解析到【%d】个现场视频片段"
            "（含 %d 个相关推荐），点击片段即可起播！\n\n%s"
        ) % (self.tgGroup, len(episodes),
             max(0, len(related) - 1) if related else 0, desc)

        return {
            "list": [{
                "vod_id": event_id,
                "vod_name": title,
                "vod_pic": self._wrap_pic(cover),
                "vod_actor": self.brandActor,
                "vod_director": self.brandDirector,
                "vod_remarks": ("共 %d 个片段" % len(episodes)) if len(episodes) > 1 else "蝴蝶影视",
                "vod_content": full_desc,
                "vod_play_from": self.PLAY_FROM,
                "vod_play_url": play_url
            }]
        }

    # ================== 推荐跳转：拿真实视频地址 ==================
    def _fetch_real_stream(self, vid):
        """从详情页拿第一条真实视频地址（带 LRU 缓存）"""
        key = str(vid)
        if key in self._detail_cache:
            return self._detail_cache[key]

        real = ""
        try:
            target = "%s/events/%s/" % (self.cgUrl, key)
            res = self._fetch(target)
            html_text = res.get("text", "")
            if (not html_text or len(html_text) < 500) and self.siteUrl != self.cgUrl:
                target = "%s/events/%s/" % (self.siteUrl, key)
                res = self._fetch(target)
                html_text = res.get("text", "")
            if html_text:
                episodes, _c, _t, _d = self._extract_episodes(html_text)
                if episodes:
                    first = episodes[0]
                    real = first.split("$", 1)[1] if "$" in first else first
        except Exception:
            pass

        self._detail_cache[key] = real
        while len(self._detail_cache) > 60:
            k = next(iter(self._detail_cache))
            self._detail_cache.pop(k, None)
        return real

    # ================== 播放 / 代理 ==================
    def _player_headers(self):
        return {
            "User-Agent": self._ua,
            "Referer": self.imgReferer,
            "Origin": self.imgReferer.rstrip("/")
        }

    def playerContent(self, flag, id, vipFlags):
        s = str(id or "")

        # nid: 伪集 → 还原到真实 event_id，抓第一条真实播放地址
        if s.startswith("nid:"):
            vid = self._decode_nid(s)
            if not vid:
                return {"parse": 0, "playUrl": "", "url": "",
                        "header": self._player_headers()}
            real = self._fetch_real_stream(vid)
            s = real or vid

        return {
            "parse": 0,
            "playUrl": "",
            "url": s,
            "header": self._player_headers()
        }

    def searchContent(self, key, quick, pg="1"):
        del quick
        page = int(pg) if pg else 1
        search_url = "%s/search/?q=%s" % (self.siteUrl, quote(key))
        if page > 1:
            search_url += "&page=%d" % page

        res = self._fetch(search_url)
        html_text = res.get("text", "")
        vod_list = self._parse_card_list(html_text)

        if vod_list:
            self._cache_items(("search", str(key), str(page)), vod_list)

        return {
            "page": page,
            "pagecount": page + 1 if len(vod_list) >= 10 else page,
            "limit": len(vod_list),
            "total": 9999,
            "list": vod_list
        }

    def action(self, action):
        return {"msg": "ok"}

    def liveContent(self):
        return ""

    def localProxy(self, params):
        url = params.get("url", "")
        if not url:
            return [404, "text/plain; charset=utf-8", "Missing url parameter"]
        res = self._fetch(url, referer=self.imgReferer)
        return [res.get("code", 200), "image/jpeg", res.get("bytes", b"")]

    def destroy(self):
        self.options = {}
        self._page_cache   = {}
        self._page_index   = {}
        self._page_keys    = []
        self._detail_cache = {}
