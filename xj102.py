#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import re
import json
import base64
import urllib.request
import urllib.error
import urllib.parse
from urllib.parse import quote, urlparse, parse_qs
import http.cookiejar
import gzip
import zlib
import ssl
import random

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
        self.tgGroup = "https://t.me/tvshare23"
        self.brandActor = "🦋 TG群: @tvshare23"
        self.brandDirector = "🦋 蝴蝶影视"
        self._ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.img_key_589 = b"2019ysapp7527"

        # ==============================================================
        # 单区配置区：切 z1~z9 只改这里
        # ==============================================================
        self.zone_slug = "z1"
        self.site = {
            "name": "一区",
            "host": "https://618405.xyz",
            "api_host": "https://h5.xxoo475.org",   # ★新增：z1 API 域名
            "mod": "vod",                            # z4 改 art
            "default": "1",
            "subs": [
                    {"n": "全部视频", "v": "1"}, {"n": "香蕉精品", "v": "13"}, {"n": "制服诱惑", "v": "22"},
                    {"n": "国产视频", "v": "6"}, {"n": "清纯少女", "v": "8"}, {"n": "辣妹大奶", "v": "9"},
                    {"n": "女同专属", "v": "10"}, {"n": "素人出演", "v": "11"}, {"n": "角色扮演", "v": "12"},
                    {"n": "人妻熟女", "v": "20"}, {"n": "日韩剧情", "v": "23"}, {"n": "经典伦理", "v": "21"},
                    {"n": "成人动漫", "v": "7"}, {"n": "精品二区", "v": "14"}, {"n": "精品三区", "v": "40"}
            ]
        }

        # ==============================================================
        # 域名池（不要改顺序）
        # ==============================================================
        self.remote_pool_js = "https://webimgg.jiekrrj.cn/cf230705/image/2n8/108/18d/2pz/440fca8bd2f8b9b6342e412746428d85.jpg"
        self.zone_order = ["z1", "z2", "z3", "z4", "z5", "z6", "z7", "z8", "z9"]
        self.domain_pools = {zid: [] for zid in self.zone_order}

        # CDN 域名关键字（这些不是主站，不做相对路径转换）
        self._cdn_keywords = ("618799", "6180013", "6180023", "6182321",
                              "6182063", "6182275", "6182231")

        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx)
        )

    # ==================== 日志与域名工具 ====================
    def log(self, msg):
        print("[蝴蝶-%s] %s" % (self.zone_slug, msg))

    def _fmt_host(self, n):
        n = str(n).strip()
        if not n:
            return ""
        if n.startswith("http"):
            return n.rstrip("/")
        if n.startswith("618"):
            return "https://%s.xyz" % n
        return "https://618%s.xyz" % n

    def _is_main_site_url(self, url):
        """是否是主站域名的 URL（需要转相对路径）"""
        if not url or not re.match(r'^https?://618\d+\.xyz', url):
            return False
        if any(k in url for k in self._cdn_keywords):
            return False
        return True

    def _to_relative(self, url):
        """主站 URL 转相对路径，让 playerContent 用动态 host 重建"""
        if self._is_main_site_url(url):
            p = urlparse(url)
            return p.path + ("?" + p.query if p.query else "")
        return url

    # ==================== init / 域名池 ====================
    def init(self, extend=""):
        self.sync_remote_domain_pools()
        self.log("初始化完成 zone=%s host=%s" % (self.zone_slug, self.site["host"]))
        return True

    def getName(self):
        return "蝴蝶影视·%s" % self.site.get("name", "")

    def sync_remote_domain_pools(self):
        try:
            headers = {"User-Agent": self._ua, "Accept": "*/*"}
            req = urllib.request.Request(self.remote_pool_js, headers=headers)
            with self.opener.open(req, timeout=6) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
            m = re.search(r'const\s+zuArr\s*=\s*(\[\[[\s\S]*?\]\]);', text)
            if m:
                raw_arr_str = m.group(1).replace("'", '"')
                zu_list = json.loads(raw_arr_str)
                for idx, num_pool in enumerate(zu_list):
                    if idx < len(self.zone_order):
                        zid = self.zone_order[idx]
                        self.domain_pools[zid] = [self._fmt_host(n) for n in num_pool if n]
                self.log("域名池同步完成: " + str({k: len(v) for k, v in self.domain_pools.items()}))
            else:
                self.log("域名池同步失败：未匹配到 zuArr")
        except Exception as e:
            self.log("域名池同步异常: %s" % e)

    def switch_live_domain(self):
        slug = self.zone_slug
        pool = self.domain_pools.get(slug, [])
        if not pool:
            self.sync_remote_domain_pools()
            pool = self.domain_pools.get(slug, [])
        if pool:
            cur_host = self.site["host"]
            candidates = [h for h in pool if h != cur_host]
            if candidates:
                new_host = random.choice(candidates)
                self.site["host"] = new_host
                self.log("切换域名: %s -> %s" % (cur_host, new_host))
                return new_host
        return self.site["host"]

    # ==================== 基础 ====================
    def decrypt(self, text):
        if not text: return ""
        try: return "".join([chr(128 ^ ord(ch)) for ch in text])
        except Exception: return text

    def smart_decrypt(self, text):
        if not text: return ""
        if any(32 <= ord(c) < 128 for c in text): return text
        return self.decrypt(text)

    def isVideoFormat(self, url):
        low = (url or "").lower()
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".mkv", ".avi", ".ts", ".mpd", "index.png"))

    def manualVideoCheck(self): return False

    def _safe_quote_url(self, url_str):
        if not url_str: return ""
        parts = urlparse(url_str)
        path = quote(parts.path, safe="/:")
        query = quote(parts.query, safe="=&?:/")
        return urllib.parse.urlunparse((parts.scheme, parts.netloc, path, parts.params, query, parts.fragment))

    def _fetch(self, target_url, host="", custom_headers=None, raw_bytes=False):
        if not target_url:
            return {"code": 0, "text": "", "bytes": b"", "err": "", "final_url": ""}
        if target_url.startswith("//"):
            target_url = "https:" + target_url
        elif target_url.startswith("/") and host:
            target_url = host.rstrip("/") + target_url
        safe_url = self._safe_quote_url(target_url)
        headers = {
            "User-Agent": self._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }
        if host: headers["Referer"] = host.rstrip("/") + "/"
        if custom_headers: headers.update(custom_headers)
        last_err = ""
        for attempt in range(2):
            try:
                req = urllib.request.Request(safe_url, headers=headers)
                with self.opener.open(req, timeout=8) as resp:
                    code = resp.getcode()
                    final_url = resp.geturl()
                    data = resp.read()
                    enc = getattr(resp, "headers", {}).get("Content-Encoding", "")
                    if data.startswith(b"\x1f\x8b") or enc == "gzip":
                        data = gzip.decompress(data)
                    elif enc == "deflate":
                        try: data = zlib.decompress(data)
                        except Exception: data = zlib.decompress(data, -zlib.MAX_WBITS)
                    if raw_bytes:
                        return {"code": code, "text": "", "bytes": data, "err": "", "final_url": final_url}
                    try: text = data.decode("utf-8")
                    except Exception: text = data.decode("latin1", errors="ignore")
                    return {"code": code, "text": text, "bytes": data, "err": "", "final_url": final_url}
            except urllib.error.HTTPError as e:
                last_err = "HTTP %s" % e.code
                if e.code in (451, 403, 429) and attempt == 0: continue
                return {"code": e.code, "text": "", "bytes": b"", "err": str(e), "final_url": safe_url}
            except Exception as e:
                last_err = str(e)
                if attempt == 0: continue
                return {"code": -1, "text": "", "bytes": b"", "err": str(e), "final_url": safe_url}
        return {"code": -1, "text": "", "bytes": b"", "err": last_err, "final_url": safe_url}

    # ==================== 首页 ====================
    def homeContent(self, filter):
        classes = []
        for sub in self.site.get("subs", []):
            classes.append({"type_name": sub["n"], "type_id": str(sub["v"])})
        return {"class": classes}

    def homeVideoContent(self): return {"list": []}

    # ==================== m3u8 映射（z5/z8/z9） ====================
    def _map_m3u8_url(self, raw_url):
        if not raw_url: return ""
        m = re.search(r'/(bktappup/.+\.m3u8|v3/.+\.m3u8|cf\d+/.+\.m3u8)', raw_url)
        if m:
            sub_path = m.group(1)
            target = "https://6180013.xyz" if "bktappup" in sub_path else "https://6180023.xyz"
            return "%s/m3u8/%s" % (target, sub_path)
        m_fb = re.search(r'/(?:api/app/vid/h5/m3u8|m3u8)/([a-zA-Z0-9_\-/]+\.m3u8)', raw_url)
        if m_fb:
            sub_path = m_fb.group(1)
            target = "https://6180013.xyz" if "bktappup" in sub_path else "https://6180023.xyz"
            return "%s/m3u8/%s" % (target, sub_path)
        return raw_url

    # ==================== 列表解析（关键改动） ====================
    def parse_items(self, html_text, host, zone_slug=""):
        vod_list = []
        pattern = r'(<div[^>]*class=["\'][^"\']*xowe-thumb-bl[^"\']*["\'][^>]*>[\s\S]*?</div>\s*</div>|<a[^>]*class=["\'][^"\']*vodbox[^"\']*["\'][^>]*>[\s\S]*?</a>|<a[^>]*href=["\'][^"\']*(?:/html/|\.html\?)[^"\']*["\'][^>]*>[\s\S]*?</a>)'
        matches = re.findall(pattern, html_text, re.I)
        seen_urls = set()
        for raw_block in matches:
            try:
                href_m = re.search(r'href=["\']([^"\']+)["\']', raw_block, re.I)
                if not href_m: continue
                href = href_m.group(1).replace("&amp;", "&")
                if "/type/id/" in href: continue
                parsed = urlparse(href)
                params = parse_qs(parsed.query)
                v_url = ""
                for k in ["id", "v", "kd", "m"]:
                    if k in params and params[k]:
                        v_url = params[k][0].strip()
                        break
                if not v_url:
                    v_url = href if href.startswith("http") else (host + href)

                # 区域特殊处理（保留原逻辑）
                if zone_slug == "z1" and v_url.isdigit():
                    v_url = "z1_mk://" + v_url
                if zone_slug == "z4" and v_url.endswith(".m3u8"):
                    if not v_url.startswith("http"):
                        v_url = "https://618799.xyz/web" + ("/" if not v_url.startswith("/") else "") + v_url
                if zone_slug in ("z5", "z8", "z9"):
                    v_url = self._map_m3u8_url(v_url)

                # ★新增：主站域名 URL → 相对路径，播放时用动态 host 重建
                v_url = self._to_relative(v_url)

                if v_url in seen_urls: continue
                seen_urls.add(v_url)

                pic = ""
                pic_cover = re.search(r'data-cover=["\']([^"\']+)["\']', raw_block, re.I)
                if pic_cover: pic = pic_cover.group(1).strip()
                if not pic:
                    pic_m = re.search(r'data-original=["\']([^"\']+)["\']', raw_block, re.I)
                    if pic_m: pic = pic_m.group(1).strip()
                if not pic:
                    pic_src = re.search(r'src=["\']([^"\']+)["\']', raw_block, re.I)
                    if pic_src: pic = pic_src.group(1).strip()
                if not pic:
                    pic = params.get("b", [""])[0] or params.get("pic", [""])[0]
                proxy_pic = ""
                if pic:
                    if pic.startswith("//"): pic = "https:" + pic
                    elif pic.startswith("/"): pic = host + pic
                    proxy_pic = "proxy://do=py&type=img&url=%s&zone=%s&host=%s" % (
                        urllib.parse.quote(pic), zone_slug, urllib.parse.quote(host)
                    )

                title = ""
                km_match = re.search(r'<(?:p|span|div)[^>]*class=["\'][^"\']*km-script[^"\']*["\'][^>]*>([\s\S]*?)</(?:p|span|div)>', raw_block, re.I)
                if km_match: title = self.smart_decrypt(km_match.group(1).strip())
                if not title:
                    clean_inner = re.sub(r'<[^>]+>', '', raw_block).strip()
                    if clean_inner and not clean_inner.startswith("http"):
                        title = self.smart_decrypt(clean_inner)
                if not title:
                    m_path = re.search(r'/html/[a-zA-Z0-9]+/(.+?)\.html', parsed.path)
                    if m_path: title = self.smart_decrypt(m_path.group(1))
                if not title: title = "高清精彩正片"
                title = title.replace("ゐ", "").replace("ゑ", "").replace("ﾌ", " ").strip()

                pack_id = "%s@@%s@@%s" % (urllib.parse.quote(title), urllib.parse.quote(v_url), urllib.parse.quote(host))
                vod_list.append({
                    "vod_id": pack_id,
                    "vod_name": title,
                    "vod_pic": proxy_pic,
                    "vod_remarks": "蝴蝶影视",
                    "style": {"type": "rect", "ratio": 1.78}
                })
            except Exception:
                continue
        return vod_list

    # ==================== 分类 ====================
    def categoryContent(self, tid, pg, filter, extend):
        del filter
        extend = extend if isinstance(extend, dict) else {}
        zone_slug = self.zone_slug
        host = self.site["host"]
        mod = self.site.get("mod", "vod")
        default_sub = self.site["default"]
        cur_id = str(tid or extend.get("sub") or default_sub)
        page = int(pg) if pg else 1
        if page == 1:
            target_url = "%s/index.php/%s/type/id/%s.html" % (host, mod, cur_id)
        else:
            target_url = "%s/index.php/%s/type/id/%s/page/%s.html" % (host, mod, cur_id, page)
        res = self._fetch(target_url, host)
        html_text = res.get("text", "")
        if not html_text or "404" in html_text or res.get("code") != 200:
            old_host = host
            new_host = self.switch_live_domain()
            if new_host != old_host:
                host = new_host
                target_url = target_url.replace(old_host, host)
                res = self._fetch(target_url, host)
                html_text = res.get("text", "")
        vod_list = self.parse_items(html_text, host, zone_slug=zone_slug)
        if not vod_list and page == 1:
            target_url_fb = "%s/index.php/%s/type/id/%s/page/1.html" % (host, mod, cur_id)
            res_fb = self._fetch(target_url_fb, host)
            vod_list = self.parse_items(res_fb.get("text", ""), host, zone_slug=zone_slug)
        total_pages = 1
        m_page = re.search(r"totalPages='(\d+)'", html_text)
        if m_page:
            try: total_pages = int(m_page.group(1))
            except Exception: total_pages = 1
        return {
            "page": page,
            "pagecount": total_pages if total_pages > 1 else (999 if len(vod_list) >= 10 else 1),
            "limit": len(vod_list) if vod_list else 20,
            "total": total_pages * 20 if total_pages > 1 else 999,
            "list": vod_list
        }

    # ==================== 详情 ====================
    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) else str(ids)
        title = "高清正片"
        play_url = ""
        host = self.site["host"]  # ★用动态 host
        if "@@" in raw_id:
            parts = raw_id.split("@@")
            title = urllib.parse.unquote(parts[0])
            play_url = urllib.parse.unquote(parts[1])
            # 不强制用旧 host：play_url 已相对化，playerContent 会用动态 host 重建
        else:
            play_url = raw_id
        final_play_target = "%s@@%s" % (play_url, host)
        full_desc = (
            "【🔥 官方交流群: %s】\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "• 播放模式: 零嗅探秒播\n"
            "• 片名: %s\n"
            "• 提示: 视频来源于源站集群，支持拖拽倍速。"
        ) % (self.tgGroup, title)
        return {
            "list": [{
                "vod_id": raw_id,
                "vod_name": title,
                "vod_pic": "",
                "vod_actor": self.brandActor,
                "vod_director": self.brandDirector,
                "vod_remarks": "直出正片",
                "vod_content": full_desc,
                "vod_play_from": "官方直链",
                "vod_play_url": "正片$%s" % final_play_target
            }]
        }

    # ==================== 播放页提取 ====================
    def _extract_media_url(self, html_text):
        if not html_text:
            return ""
        patterns = [
            r'(?:url|src|file)\s*[:=]\s*["\']([^"\']+\.(?:m3u8|mp4|flv|mkv|ts|mpd)[^"\']*)["\']',
            r'(https?://[^\s<>"\']+\.(?:m3u8|mp4|flv|mkv|ts|mpd)[^\s<>"\']*)',
        ]
        for p in patterns:
            m = re.search(p, html_text, re.I)
            if m:
                url = m.group(1).replace("\\/", "/")
                if url.startswith("//"):
                    url = "https:" + url
                return url
        return ""

    # ==================== 播放（关键改动） ====================
    def playerContent(self, flag, id, vipFlags):
        raw_target = str(id).strip()
        play_url = raw_target
        origin_host = self.site["host"]
        if "@@" in raw_target:
            parts = raw_target.split("@@")
            play_url = parts[0]
            if len(parts) > 1 and parts[1]:
                origin_host = parts[1]

        # ★核心改动：相对路径用动态 host 重建；播放页主动请求提取 + 404 切域名重试
        if play_url.startswith("/") and not play_url.startswith("//"):
            full_url = self.site["host"].rstrip("/") + play_url
            is_media = bool(re.search(r'\.(m3u8|mp4|flv|mkv|ts|mpd)(\?|$)', play_url, re.I))
            if is_media:
                play_url = full_url
            else:
                res = self._fetch(full_url, self.site["host"])
                if res.get("code") != 200:
                    new_host = self.switch_live_domain()
                    if new_host != self.site["host"]:
                        full_url = new_host.rstrip("/") + play_url
                        res = self._fetch(full_url, new_host)
                if res.get("code") == 200:
                    media_url = self._extract_media_url(res.get("text", ""))
                    if media_url:
                        self.log("播放页提取到视频地址: %s" % media_url[:80])
                        play_url = media_url
                    else:
                        play_url = full_url
                else:
                    play_url = full_url

        # z1 特殊（API 域名改为可配）
        if play_url.startswith("z1_mk://"):
            mk_id = play_url.replace("z1_mk://", "").strip()
            api_host = self.site.get("api_host", "https://h5.xxoo475.org")
            api_url = api_host.rstrip("/") + "/api/v2/vod/reqplay/" + mk_id
            api_res = self._fetch(api_url, origin_host, custom_headers={
                "Accept": "application/json, text/plain, */*",
                "Connection": "keep-alive"
            })
            if api_res.get("text"):
                try:
                    data = json.loads(api_res["text"])
                    vod_url = data.get("data", {}).get("httpurl_preview" if data.get("retcode") == 3 else