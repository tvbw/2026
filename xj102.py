#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
import re
import json
import base64
import html as html_lib
import urllib.request
import urllib.parse
from urllib.parse import quote, unquote, parse_qs, urlparse, urljoin
import http.cookiejar
import gzip
import zlib
import ssl
import hashlib
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
        super().__init__()
        # ==============================================================
        # ★★★【单区配置块｜切换z1~z9仅修改此处，业务代码禁止改动】
        # zone_slug: z1/z2/z3/z4/z5/z6/z7/z8/z9
        # init_cfg["mod"]: z4填 "art"，其余全部填 "vod"
        # api_host: z1=https://h5.xxoo475.org ; z2‑z9=https://h5.xxoo168.org
        # subs: 直接粘贴对应区分类列表
        # ==============================================================
        self.zone_slug = "z2"
        self.init_cfg = {
            "host": "https://618302.xyz",
            "api_host": "https://h5.xxoo475.org",
            "mod": "vod",
            "subs": [
                    {"n": "全部", "v": "1"}, {"n": "推荐", "v": "6"},{"n": "无码", "v": "56"},
                    {"n": "动漫", "v": "9"},{"n": "热门", "v": "5"}, {"n": "黑料", "v": "31"}, 
                    {"n": "欧美", "v": "8"}, {"n": "传媒", "v": "10"}, {"n": "网黄", "v": "55"},
                    {"n": "JK", "v": "57"}, {"n": "国产", "v": "54"}, {"n": "字幕", "v": "7"}
            ]
        }
        # --------------------------域名池【禁止修改】--------------------------
        self.remote_pool_js = "https://webimgg.jiekrrj.cn/cf230705/image/2n8/108/18d/2pz/440fca8bd2f8b9b6342e412746428d85.jpg"
        self.zone_order = ["z1", "z2", "z3", "z4", "z5", "z6", "z7", "z8", "z9"]
        self.domain_pools = {zid: [] for zid in self.zone_order}
        # ---------------------------------------------------------------------
        self.host = self.init_cfg["host"]
        self.api_host = self.init_cfg["api_host"]
        self.mod = self.init_cfg["mod"]
        self.special_categories = ['13', '14', '33', '53', '32', '52', '9', '40', '44']

        self._ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx)
        )

    def getName(self):
        return f"蝴蝶融合版·{self.zone_slug}"

    def init(self, extend=""):
        self.sync_remote_domain_pools()
        self.log(f"初始化完成 zone={self.zone_slug} host={self.host} mod={self.mod}")
        return True

    def log(self, msg):
        print(f"[FUSION-{self.zone_slug}] {msg}")

    def sync_remote_domain_pools(self):
        """同步远端域名池，从伪装jpg解析zuArr数组"""
        try:
            headers = {"User‑Agent": self._ua, "Accept": "*/*"}
            req = urllib.request.Request(self.remote_pool_js, headers=headers)
            with self.opener.open(req, timeout=6) as resp:
                text = resp.read().decode("utf‑8", errors="ignore")
                m = re.search(r'const\s+zuArr\s*=\s*(\[\[[\s\S]*?\]\]);', text)
                if m:
                    raw_arr_str = m.group(1).replace("'", '"')
                    zu_list = json.loads(raw_arr_str)
                    for idx, num_pool in enumerate(zu_list):
                        if idx < len(self.zone_order):
                            zid = self.zone_order[idx]
                            self.domain_pools[zid] = ["https://618%s.xyz" % n for n in num_pool if n]
        except Exception as e:
            self.log(f"域名池同步异常:{str(e)}")

    def switch_live_domain(self):
        """访问404自动切换该区可用域名，更新self.host"""
        slug = self.zone_slug
        pool = self.domain_pools.get(slug, [])
        if not pool:
            self.sync_remote_domain_pools()
            pool = self.domain_pools.get(slug, [])
        if pool:
            cur_host = self.host
            candidates = [h for h in pool if h != cur_host]
            if candidates:
                new_host = random.choice(candidates)
                self.host = new_host
                self.log(f"自动切换域名 → {new_host}")
                return new_host
        return self.host

    def _safe_quote_url(self, url_str):
        if not url_str: return ""
        parts = urlparse(url_str)
        path = quote(parts.path, safe="/:")
        query = quote(parts.query, safe="=&?:/")
        return urllib.parse.urlunparse((parts.scheme, parts.netloc, path, parts.params, query, parts.fragment))

    def _fetch(self, target_url, host="", custom_headers=None, raw_bytes=False):
        """urllib底层网络请求，gzip/deflate解压、重试、忽略ssl"""
        if not target_url:
            return {"code": 0, "text": "", "bytes": b"", "err": "", "final_url": ""}
        if target_url.startswith("//"):
            target_url = "https:" + target_url
        elif target_url.startswith("/") and host:
            target_url = host + target_url
        safe_url = self._safe_quote_url(target_url)
        headers = {
            "User‑Agent": self._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept‑Language": "zh‑CN,zh;q=0.9,en;q=0.8",
            "Accept‑Encoding": "gzip, deflate",
            "Connection": "keep‑alive"
        }
        if host: headers["Referer"] = host + "/"
        if custom_headers: headers.update(custom_headers)
        last_err = ""
        for attempt in range(2):
            try:
                req = urllib.request.Request(safe_url, headers=headers)
                with self.opener.open(req, timeout=8) as resp:
                    code = resp.getcode()
                    final_url = resp.geturl()
                    data = resp.read()
                    enc = resp.headers.get("Content‑Encoding", "")
                    if data.startswith(b"\x1f\x8b") or enc == "gzip":
                        data = gzip.decompress(data)
                    elif enc == "deflate":
                        try: data = zlib.decompress(data)
                        except Exception: data = zlib.decompress(data, -zlib.MAX_WBITS)
                    if raw_bytes:
                        return {"code": code, "text": "", "bytes": data, "err": "", "final_url": final_url}
                    try: text = data.decode("utf‑8")
                    except Exception: text = data.decode("latin‑1", errors="ignore")
                    return {"code": code, "text": text, "bytes": data, "err": "", "final_url": final_url}
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}"
                if e.code in (451,403,429) and attempt == 0: continue
                return {"code": e.code, "text": "", "bytes": b"", "err": str(e), "final_url": safe_url}
            except Exception as e:
                last_err = str(e)
                if attempt == 0: continue
                return {"code": -1, "text": "", "bytes": b"", "err": str(e), "final_url": safe_url}
        return {"code": -1, "text": "", "bytes": b"", "err": last_err, "final_url": safe_url}

    def regStr(self, pattern, html, index=1):
        m = re.search(pattern, html, re.I | re.S)
        if m and len(m.groups()) >= index:
            return m.group(index).strip()
        return ""

    def _decrypt_title(self, encrypted_text):
        """XOR 128 解密标题，源自xj101"""
        try:
            decrypted_chars = []
            for char in encrypted_text:
                decrypted_code = ord(char) ^ 128
                decrypted_chars.append(chr(decrypted_code))
            decrypted_text = "".join(decrypted_chars)
            decrypted_text = decrypted_text.replace("&nbsp;", " ")
            return decrypted_text
        except Exception:
            return encrypted_text

    def _extract_vodbox_list(self, html):
        """正则提取全部 class=vodbox 的a块，替代xpath //a[@class="vodbox"]"""
        pattern = re.compile(r'<a[^>]+class=["\'][^"\']*vodbox[^"\']*["\'][^>]*>([\s\S]*?)</a>', re.I | re.S)
        return pattern.findall(html)

    def _extract_video_item(self, block_html, host, category_id=None):
        """解析单个vodbox块，生成vod对象；保留special_ dcdc直链逻辑"""
        href = self.regStr(r'href=["\']([^"\']+)["\']', block_html)
        if not href:
            return None
        if href.startswith("/"):
            href = host + href
        is_special_link = "/html/dcdc/" in href

        # 提取图片
        pic = self.regStr(r'data‑original=["\']([^"\']+)["\']', block_html)
        if not pic:
            pic = self.regStr(r'src=["\']([^"\']+)["\']', block_html)
        if pic:
            if pic.startswith("//"):
                pic = "https:" + pic
            elif pic.startswith("/"):
                pic = host + pic

        # 提取加密标题
        enc_title = self.regStr(r'<p[^>]+class=["\'][^"\']*km‑script[^"\']*["\']*>([\s\S]*?)</p>', block_html)
        if not enc_title:
            enc_title = self.regStr(r'<p>([\s\S]*?)</p>', block_html)
        title = self._decrypt_title(enc_title).strip() if enc_title else "未知影片"

        if is_special_link:
            parsed_url = urlparse(href)
            qs = parse_qs(parsed_url.query)
            video_url = qs.get("v", [""])[0]
            pic_url = qs.get("b", [""])[0]
            if not pic: pic = pic_url
            if video_url:
                m_vid = re.search(r'/([a‑f0‑9‑]+)/video\.m3u8', video_url)
                if m_vid:
                    video_id = m_vid.group(1)
                else:
                    video_id = hashlib.md5(video_url.encode()).hexdigest()[:8]
            else:
                video_id = str(hash(href) % 1000000)
            encoded_link = urllib.parse.quote(href)
            vod_id = f"special_{category_id}_{video_id}_{encoded_link}"
            return {
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": "",
                "vod_year": ""
            }
        else:
            vod_id_raw = self.regStr(r'm=(\d+)', href)
            if not vod_id_raw:
                vod_id_raw = str(hash(href) % 1000000)
            if category_id:
                final_vod_id = f"{host}_{category_id}_{vod_id_raw}"
            else:
                final_vod_id = f"{host}_{vod_id_raw}"
            return {
                "vod_id": final_vod_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": "",
                "vod_year": ""
            }

    def homeContent(self, filter):
        result = {}
        classes = []
        for sub in self.init_cfg["subs"]:
            tid_str = f"{self.host}_{sub['v']}"
            classes.append({"type_id": tid_str, "type_name": sub["n"]})
        result["class"] = classes
        result["list"] = []
        return result

    def homeVideoContent(self):
        classes = []
        for sub in self.init_cfg["subs"]:
            tid_str = f"{self.host}_{sub['v']}"
            classes.append({"type_id": tid_str, "type_name": sub["n"]})
        return {"class": classes}

    def categoryContent(self, tid, pg, filter, extend):
        """分类：tid格式 host_typeid；mod自动区分vod/art；404自动切换域名重试"""
        try:
            domain, type_id = tid.split("_")
            page = int(pg) if str(pg).isdigit() else 1
            base_path = f"/index.php/{self.mod}/type/id/{type_id}"
            if page == 1:
                url = f"https://{domain}{base_path}.html"
            else:
                url = f"https://{domain}{base_path}/page/{page}.html"
            self.log(f"请求分类url={url}")
            rsp = self._fetch(url, host=domain)
            code = rsp["code"]
            html_text = rsp["text"]
            # 404/403触发域名切换重试一次
            if code in [404,403,451]:
                old_d = domain
                new_d = self.switch_live_domain()
                url = url.replace(old_d, new_d)
                rsp = self._fetch(url, host=new_d)
                html_text = rsp["text"]
                domain = new_d
            blocks = self._extract_vodbox_list(html_text)
            self.log(f"解析到vodbox块数量:{len(blocks)}")
            vod_list = []
            for blk in blocks:
                item = self._extract_video_item(blk, domain, category_id=type_id)
                if item:
                    vod_list.append(item)
            # 解析总页数
            pagecount = 50
            m_page = re.search(r'totalPages\s*=\s*[\'\"](\d+)[\'\"]', html_text)
            if m_page:
                pagecount = int(m_page.group(1))
            elif re.search(r'尾页|最后一页', html_text):
                m_p = re.search(r'/page/(\d+)\.html', html_text, re.S)
                if m_p:
                    pagecount = int(m_p.group(1))
            total = pagecount * 20
            return {
                "page": page,
                "pagecount": pagecount,
                "limit": len(vod_list),
                "total": total,
                "list": vod_list
            }
        except Exception as e:
            self.log(f"categoryContent异常:{str(e)}")
            return {"list": []}

    def searchContent(self, key, quick, pg="1"):
        """搜索功能"""
        try:
            page = int(pg) if str(pg).isdigit() else 1
            q = urllib.parse.quote(key)
            url = f"{self.host}/index.php/{self.mod}/type/id/1/wd/{q}/page/{page}.html"
            rsp = self._fetch(url, host=self.host)
            html_text = rsp["text"]
            blocks = self._extract_vodbox_list(html_text)
            vod_list = []
            for blk in blocks:
                item = self._extract_video_item(blk, self.host)
                if item:
                    vod_list.append(item)
            pagecount = 5
            m_page = re.search(r'totalPages\s*=\s*[\'\"](\d+)[\'\"]', html_text)
            if m_page:
                pagecount = int(m_page.group(1))
            total = pagecount * 20
            return {
                "page": page,
                "pagecount": pagecount,
                "limit": len(vod_list),
                "total": total,
                "list": vod_list
            }
        except Exception as e:
            self.log(f"searchContent异常:{str(e)}")
            return {"list": []}

    def detailContent(self, ids):
        try:
            vid = ids[0] if isinstance(ids, (list,tuple)) else str(ids)
            if vid.startswith("special_"):
                parts = vid.split("_")
                if len(parts)>=4:
                    encoded_url = "_".join(parts[3:])
                    play_url = urllib.parse.unquote(encoded_url)
                    parsed_url = urlparse(play_url)
                    qs = parse_qs(parsed_url.query)
                    video_url = qs.get("v",[""])[0]
                    pic_url = qs.get("b",[""])[0]
                    enc_title = parsed_url.path.split("/")[-1].replace(".html","")
                    title = self._decrypt_title(enc_title)
                    return {
                        "list":[{
                            "vod_id":vid,
                            "vod_name":title,
                            "vod_pic":pic_url,
                            "vod_remarks":"",
                            "vod_year":"",
                            "vod_area":"",
                            "vod_actor":"",
                            "vod_director":"",
                            "vod_content":"",
                            "vod_play_from":"直接播放",
                            "vod_play_url":f"第1集${play_url}"
                        }]
                    }
            # 普通id: host_categoryid_vid
            parts = vid.split("_")
            if len(parts)>=3:
                domain, cid, vid_num = parts
            else:
                domain, vid_num = parts[0], parts[1]
            detail_url = f"https://{domain}/index.php/{self.mod}/detail/id/{vid_num}.html"
            rsp = self._fetch(detail_url, host=domain)
            html = rsp["text"]
            title = self.regStr(r'<h1[^>]*>([\s\S]*?)</h1>', html).strip() or "影片"
            pic = self.regStr(r'data‑original=["\']([^"\']+)["\']', html) or self.regStr(r'src=["\']([^"\']+\.(jpg|png|jpeg))["\']', html)
            if pic and pic.startswith("/"): pic = domain + pic
            desc = self.regStr(r'<div[^>]+class=["\']yp_context["\'][^>]*>([\s\S]*?)</div>', html)
            play_links = re.findall(r'href=["\']([^"\']+(ar\.html|kkyd\.html|dcdc/[^"\']*))["\']', html)
            play_from = ["默认播放源"]
            play_urls = []
            eps = []
            for link_tup in play_links:
                link = link_tup[0]
                full_link = urljoin(domain, link)
                eps.append(f"第1集${full_link}")
            if eps:
                play_urls.append("#".join(eps))
            if not play_urls:
                play_urls.append(f"第1集${vid}")
            return {
                "list":[{
                    "vod_id":vid,
                    "vod_name":title,
                    "vod_pic":pic,
                    "vod_year":"",
                    "vod_area":"",
                    "vod_actor":"",
                    "vod_director":"",
                    "vod_content":desc,
                    "vod_play_from":"$$$".join(play_from),
                    "vod_play_url":"$$$".join(play_urls)
                }]
            }
        except Exception as e:
            self.log(f"detailContent异常:{str(e)}")
            return {"list":[]}

    def _get_video_by_api(self, video_id, refer_host):
        """API请求获取播放地址，来自xj101逻辑"""
        try:
            api_url = f"{self.api_host}/api/v2/vod/reqplay/{video_id}"
            headers = {
                "Referer": refer_host + "/",
                "Origin": refer_host,
                "X‑Requested‑With": "XMLHttpRequest"
            }
            rsp = self._fetch(api_url, custom_headers=headers)
            if rsp["code"] != 200:
                return None
            data = json.loads(rsp["text"])
            if data.get("retcode") ==3:
                video_url = data.get("data",{}).get("httpurl_preview","")
            else:
                video_url = data.get("data",{}).get("httpurl","")
            if video_url:
                return video_url.replace("?300","").strip()
            return None
        except Exception as e:
            self.log(f"api获取播放失败:{e}")
            return None

    def _extract_direct_video_url(self, html):
        patterns = [
            r'v=([^&]+\.(?:m3u8|mp4))',
            r'"url"\s*:\s*["\']([^"\']+\.(?:mp4|m3u8))["\']',
            r'src\s*=\s*["\']([^"\']+\.(?:mp4|m3u8))["\']',
            r'https?://[^\s<>"\']+\.(?:m3u8|mp4)'
        ]
        for pat in patterns:
            res = re.findall(pat, html, re.I)
            for u in res:
                if isinstance(u,tuple): u=u[0]
                u = urllib.parse.unquote(u.replace('\\',''))
                if u.startswith("//"): u="https:"+u
                if u.startswith("http"):
                    return u
        return None

    def playerContent(self, flag, id, vipFlags):
        try:
            self.log(f"playerContent id={id}")
            if id.startswith("special_"):
                parts = id.split("_")
                encoded_url = "_".join(parts[3:])
                play_url = urllib.parse.unquote(encoded_url)
                qs = parse_qs(urlparse(play_url).query)
                video_url = qs.get("v",[""])[0]
                if video_url:
                    if video_url.startswith("//"): video_url="https:"+video_url
                    return {"parse":0,"playUrl":"","url":video_url}
                else:
                    return {"parse":1,"playUrl":"","url":play_url}
            # 普通id host_cid_vid
            parts = id.split("_")
            if len(parts)>=3:
                domain, cid, vid_num = parts
            else:
                domain, vid_num = parts[0], parts[1]
            if cid in self.special_categories:
                play_page_url = f"https://{domain}/index.php/{self.mod}/play/id/{vid_num}.html"
                rsp = self._fetch(play_page_url, host=domain)
                html = rsp["text"]
                video_url = self._extract_direct_video_url(html)
                if video_url:
                    return {"parse":0,"playUrl":"","url":video_url}
                # 提取失败回退api
                api_url = self._get_video_by_api(vid_num, domain)
                if api_url:
                    return {"parse":0,"playUrl":"","url":api_url}
                return {"parse":1,"playUrl":"","url":play_page_url}
            else:
                api_url = self._get_video_by_api(vid_num, domain)
                if api_url:
                    return {"parse":0,"playUrl":"","url":api_url}
                fallback = f"https://{domain}/html/kkyd.html?m={vid_num}"
                return {"parse":1,"playUrl":"","url":fallback}
        except Exception as e:
            self.log(f"playerContent异常:{str(e)}")
            return {"parse":1,"playUrl":"","url":""}

    def isVideoFormat(self, url):
        low = (url or "").lower()
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".mkv", ".avi", ".ts", ".mpd"))

    def manualVideoCheck(self):
        return False

    def localProxy(self, params):
        """本模板不做图片代理，交由壳全局图片代理处理"""
        return [404, "text/plain", "NotImplemented"]

    def action(self, action):
        return {"msg":"运行正常"}

    def liveContent(self):
        return ""

    def destroy(self):
        pass
