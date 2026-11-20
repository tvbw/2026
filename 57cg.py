#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
57吃瓜 · 直达域名自愈版（urllib 版 V5）
=========================================
相比 V4.1 的改动
- 【新增】HOSTS_CG / HOSTS_SITE 集中配置，4 个直达域名并发探测
- 【新增】域名探测结果缓存 6 小时（getCache / setCache）
- 【新增】_probe_one 内容校验：必含 /events/ 或 /thread/，排除 CloudFlare 页
- 【修复】siteUrl 单点：57duanju.org 挂掉时降级到 cgUrl（搜索/全部分类至少不会空）
- 【修复】detailContent 双域名兜底避免 siteUrl==cgUrl 时重复请求
- 【增强】extend={"host": "..."} 手动指定跳过探测
- 【保留】homeContent 11 分类 / _parse_card_list / categoryContent slug 路由 /
        detailContent 的 5 层视频解析 / playerContent / localProxy 全部原样
=========================================================================
说明
- 无发布页/导航页锚点，所以域名挂了只能手动改 HOSTS_CG
- 如需增加域名，往 HOSTS_CG 里加即可，代码会自动探测
=========================================================================
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
    # ================== 站点配置（换站只改这一段）==================
    SITE_NAME    = "57吃瓜"
    PLAY_FROM    = "57吃瓜在线"

    # ---- 直达域名（无发布页，挂了就手动加）----
    HOSTS_CG = [
        "https://57cg4.com",
        "https://57cg1.com",
        "https://57cg2.com",
        "https://57cg3.com",
    ]
    HOSTS_SITE = [
        "https://57cg1.com",
    ]

    # ---- 探测参数 ----
    FAST_TIMEOUT  = 6
    PROBE_MIN_HTML = 1000

    # ---- 内容校验 ----
    BLOCKED_MARKERS = (
        'just a moment', 'cf-browser-verification', 'cf-challenge',
        'checking your browser', '__cf_chl_', 'ddos-guard',
        'cf-ray', 'cloudflare-nginx', 'enable javascript and cookies',
    )
    VALID_MARKERS = ("/events/", "events/", "/thread/", "/t/", "events")

    # ---- 缓存 ----
    HOST_CACHE_KEY = "cg57_host_v1"
    HOST_CACHE_TTL = 6 * 3600

    def __init__(self):
        super(Spider, self).__init__()
        # 默认值（init 探测后会被覆盖）
        self.cgUrl      = self.HOSTS_CG[0]
        self.siteUrl    = self.HOSTS_SITE[0]
        self.imgReferer = self.HOSTS_CG[0] + "/"

        self.tgGroup      = "https://t.me/tvshare23"
        self.brandActor   = "🦋 TG群: @tvshare23"
        self.brandDirector = "🦋 蝴蝶影视"

        self._ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0.0.0 Safari/537.36")
        self.options = {}

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
        if isinstance(extend, dict):
            self.options = extend
        elif extend:
            try:
                self.options = json.loads(extend)
            except Exception:
                self.options = {}

        # extend={"host":"..."} 或 extend="https://..."
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

    # ================== 首页 ==================
    def homeContent(self, filter):
        # 彻底规避 hot / video / root 等底层保留关键字
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
            sort_filter = [
                {
                    "key": "sort",
                    "name": "排序",
                    "value": [
                        {"n": "最新发布", "v": ""},
                        {"n": "全站最热", "v": "hot"},
                        {"n": "飙升热榜", "v": "trending"}
                    ]
                }
            ]
            filters_dict = {}
            for item in classes:
                filters_dict[item["type_id"]] = sort_filter
            result["filters"] = filters_dict

        return result

    def homeVideoContent(self):
        res = self.categoryContent("cat_aichengduanju", 1, False, {})
        return {"list": res.get("list", [])[:12]}

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

        return {
            "page": page,
            "pagecount": page + 1 if len(vod_list) >= 10 else page,
            "limit": len(vod_list),
            "total": 9999,
            "list": vod_list
        }

    # ================== 详情 ==================
    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) else str(ids)
        event_id = raw_id.strip("/")

        target_url = "%s/events/%s/" % (self.cgUrl, event_id)
        res = self._fetch(target_url)
        detail_html = res.get("text", "")

        # 避免 siteUrl==cgUrl（降级场景）时重复请求
        if (not detail_html or len(detail_html) < 500) and self.siteUrl != self.cgUrl:
            target_url = "%s/events/%s/" % (self.siteUrl, event_id)
            res = self._fetch(target_url)
            detail_html = res.get("text", "")

        title = "AI短剧/热点 %s" % event_id
        cover = ""
        desc = "暂无详细介绍"

        m_title = re.search(r'<h1[^>]*>([\s\S]*?)</h1>', detail_html)
        if m_title:
            title = re.sub(r'<[^>]+>', '', m_title.group(1)).strip()

        m_desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', detail_html)
        if m_desc:
            desc = m_desc.group(1).strip()

        episodes = []

        # 1. <video> 标签（优先 data-hls-src）
        v_blocks = re.findall(r'<video([^>]+)>', detail_html)
        for idx, attr in enumerate(v_blocks):
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

        full_desc = (
            "【🔥 官方交流群: %s】\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "本贴为您解析到【%d】个现场视频片段，点击下方片段即可起播！\n\n%s"
        ) % (self.tgGroup, len(episodes), desc)

        play_url = "#".join(episodes) if episodes else ("无可用视频流$http://127.0.0.1")

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

    # ================== 播放 / 代理 ==================
    def playerContent(self, flag, id, vipFlags):
        raw_url = str(id).strip()
        headers = {
            "User-Agent": self._ua,
            "Referer": self.imgReferer,
            "Origin": self.imgReferer.rstrip("/")
        }
        return {
            "parse": 0,
            "playUrl": "",
            "url": raw_url,
            "header": headers
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
