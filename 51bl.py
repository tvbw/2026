# ============================================================
# 102 版本 + 跳转识别最小补丁
# 改动仅在 extract_domains_from_publish_page 增加 fallback 分支
# 新增 _find_meta_refresh / _find_js_location / _fetch_and_extract
# 其余所有方法保持 102 原样
# ============================================================
import json
import random
import re
import sys
import threading
import time
from base64 import b64decode, b64encode
from urllib.parse import urlparse
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from pyquery import PyQuery as pq
sys.path.append('..')
from base.spider import Spider

SITE_CONFIG = {
    "name": "51通用最终版",
    "play_from": "51通用最终版",
    "style": {"type": "rect", "ratio": 1.33},
    # ===== 保持 102 原配置（已验证可用） =====
    "publish_url": "https://51bla20.com/",
    
    # 发布页编码方式: js_base64 / js_atob / plain / redirect
    "publish_decode": "js_base64",
    # 判断“这个域名是不是目标站”的特征选择器
    "host_check_selector": "#index article a",
    
    # 发布页解析失败时的兜底域名
    "fallback_hosts": [
        "https://blind.luwhogpx.cc/",
        "https://and.luwhogpx.cc/",
        "https://but.luwhogpx.cc/",
     # "https://able.htinjysz.cc/",
    ],

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

    "title_selector": ".post-title",
    "tag_selector": ".tags .keywords a",
    "player_selector": ".dplayer",
    "player_config_attr": "data-config",
    "player_heading_selector": "h2, h3, h4",

    "folder_content_selector": ".post-content[itemprop='articleBody']",
    "folder_remove_selectors": [".txt-apps", ".line", "blockquote", ".tags", ".content-tabs"],
    "folder_img_attr": "data-xkrkllgl",

    "img_regex": r"loadBannerDirect\('([^']+)'",
    "aes_key": b"f5d965df75336270",
    "aes_iv": b"97b60394abc2fbe1",

    "search_url_tpl": "{host}/search/{key}/",
    "search_url_tpl_paged": "{host}/search/{key}/{pg}/",

    "headers": {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/134.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,image/apng,*/*;q=0.8,"
                  "application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    },

    "timeout": 15,
    "probe_timeout": 10,
}
# ============================================================


class Spider(Spider):

    cfg = SITE_CONFIG

    # ================= 生命周期 =================
    def init(self, extend=""):
        try:
            self.proxies = json.loads(extend)
        except Exception:
            self.proxies = {}

        self.cfg = SITE_CONFIG
        self.headers = dict(self.cfg["headers"])

        self.host = self.get_working_host()
        self.headers.update({
            "Origin": self.host,
            "Referer": f"{self.host}/",
        })
        self.log(f"使用站点: {self.host}")
        print(f"使用站点: {self.host}")

    def getName(self):
        return SITE_CONFIG.get("name", "51爆料")

    def isVideoFormat(self, url):
        return any(ext in (url or "") for ext in [".m3u8", ".mp4", ".ts"])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ================= 首页（102 原样） =================
    def homeContent(self, filter):
        try:
            r = requests.get(self.host, headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["timeout"])
            if r.status_code != 200:
                return {"class": [], "list": []}

            doc = self.getpq(r.text)
            classes = []
            for selector in self.cfg["category_selectors"]:
                for item in doc(selector).items():
                    a = item("a")
                    href = (a.attr("href") or "").strip()
                    name = (a.text() or "").strip()
                    if not href or href == "#" or not name:
                        continue
                    classes.append({"type_name": name, "type_id": href})
                if classes:
                    break
            if not classes:
                classes = list(self.cfg["default_classes"])

            return {
                "class": classes,
                "list": self.getlist(doc(self.cfg["home_list_selector"])),
            }
        except Exception as e:
            print(f"homeContent error: {e}")
            return {"class": [], "list": []}

    def homeVideoContent(self):
        try:
            r = requests.get(self.host, headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["timeout"])
            if r.status_code != 200:
                return {"list": []}
            doc = self.getpq(r.text)
            return {"list": self.getlist(doc(self.cfg["list_selector"]))}
        except Exception as e:
            print(f"homeVideoContent error: {e}")
            return {"list": []}

    # ================= 分类（102 原样，翻页逻辑不动） =================
    def categoryContent(self, tid, pg, filter, extend):
        try:
            if '@folder' in tid:
                id = tid.replace('@folder', '')
                videos = self.getfod(id)
                return {'list': videos, 'page': pg, 'pagecount': 1, 'limit': 90, 'total': len(videos)}

            pg = int(pg)
            tid = tid.rstrip('/')                       # ← 就加这一行
            url = f"{self.host}{tid}/{pg}/" if pg > 1 else f"{self.host}{tid}/"

            rsp = requests.get(url, headers=self.headers, proxies=self.proxies, timeout=15)
            if rsp.status_code != 200:
                return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 90, 'total': 0}

            doc = self.getpq(rsp.text)
            videos = self.getlist(doc('#archive article a, #index article a'), tid)

            # 总页数 & 下一页
            total_pages = 1
            page_info = doc('.pagination .pages, .page-nav, .pagenavi').text()
            if '共' in page_info and '页' in page_info:
                total_pages = int(page_info.split('共')[-1].split('页')[0])
            next_url = doc('a.next, .pagination a.next, .pagenavi .next, a:contains("下一页")').attr('href')
            has_next = bool(next_url)

            return {
                'list': videos,
                'page': pg,
                'pagecount': total_pages if total_pages > 1 else 99999 if has_next else pg,
                'limit': 90,
                'total': 999999 if has_next else len(videos)
            }
        except Exception as e:
            print(f"categoryContent error: {e}")
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 90, 'total': 0}

    # ================= 详情（102 原样） =================
    def detailContent(self, ids):
        try:
            raw_id = ids[0] if ids else ""
            url = raw_id if raw_id.startswith("http") else f"{self.host}{raw_id}"

            r = requests.get(url, headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["timeout"])
            if r.status_code != 200:
                return {"list": [{
                    "vod_play_from": self.cfg["play_from"],
                    "vod_play_url": f"页面加载失败${url}",
                }]}

            doc = self.getpq(r.text)
            vod = {"vod_play_from": self.cfg["play_from"]}

            try:
                clist = []
                tag_sel = self.cfg["tag_selector"]
                if tag_sel and doc(tag_sel):
                    for k in doc(tag_sel).items():
                        title = k.text()
                        href = k.attr("href")
                        if title and href:
                            clist.append(
                                "[a=cr:" + json.dumps({"id": href, "name": title}) + "/]"
                                + title + "[/a]"
                            )
                vod["vod_content"] = (
                    " ".join(clist) if clist
                    else doc(self.cfg["title_selector"]).text()
                )
            except Exception:
                vod["vod_content"] = doc(self.cfg["title_selector"]).text() or self.cfg["name"]

            try:
                plist = self._parse_players(doc)
                if plist:
                    vod["vod_play_url"] = "#".join(plist)
                else:
                    vod["vod_play_url"] = f"未找到视频源${url}"
            except Exception:
                vod["vod_play_url"] = f"视频解析失败${url}"

            return {"list": [vod]}
        except Exception as e:
            print(f"detailContent error: {e}")
            return {"list": [{
                "vod_play_from": self.cfg["play_from"],
                "vod_play_url": f"详情页加载失败${ids[0] if ids else ''}",
            }]}

    # ================= 搜索（102 原样） =================
    def searchContent(self, key, quick, pg="1"):
        try:
            if str(pg) != "1":
                url = self.cfg["search_url_tpl_paged"].format(host=self.host, key=key, pg=pg)
            else:
                url = self.cfg["search_url_tpl"].format(host=self.host, key=key)

            r = requests.get(url, headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["timeout"])
            if r.status_code != 200:
                return {"list": [], "page": pg}

            doc = self.getpq(r.text)
            videos = self.getlist(doc(self.cfg["list_selector"]))
            return {"list": videos, "page": pg}
        except Exception as e:
            print(f"searchContent error: {e}")
            return {"list": [], "page": pg}

    # ================= 播放（102 原样） =================
    def playerContent(self, flag, id, vipFlags):
        url = id
        p = 1
        if self.isVideoFormat(url):
            if ".m3u8" in url:
                url = self.proxy(url)
            p = 0
        self.log(f"播放请求: parse={p}, url={url}")
        print(f"播放请求: parse={p}, url={url}")
        return {"parse": p, "url": url, "header": self.headers}

    def localProxy(self, param):
        t = param.get("type")
        if t == "img":
            res = requests.get(param["url"], headers=self.headers,
                               proxies=self.proxies, timeout=10)
            return [200, res.headers.get("Content-Type"), self.aesimg(res.content)]
        if t == "m3u8":
            return self.m3Proxy(param["url"])
        return self.tsProxy(param["url"])

    def proxy(self, data, type="m3u8"):
        if data and len(self.proxies):
            return f"{self.getProxyUrl()}&url={self.e64(data)}&type={type}"
        return data

    def m3Proxy(self, url):
        url = self.d64(url)
        ydata = requests.get(url, headers=self.headers,
                             proxies=self.proxies, allow_redirects=False)
        data = ydata.content.decode("utf-8")
        if ydata.headers.get("Location"):
            url = ydata.headers["Location"]
            data = requests.get(url, headers=self.headers,
                                proxies=self.proxies).content.decode("utf-8")

        lines = data.strip().split("\n")
        last_r = url[:url.rfind("/")]
        parsed = urlparse(url)
        durl = parsed.scheme + "://" + parsed.netloc
        iskey = True

        for index, string in enumerate(lines):
            if iskey and "URI" in string:
                pattern = r'URI="([^"]*)"'
                m = re.search(pattern, string)
                if m:
                    lines[index] = re.sub(
                        pattern,
                        f'URI="{self.proxy(m.group(1), "mkey")}"',
                        string,
                    )
                    iskey = False
                    continue
            if "#EXT" not in string:
                if "http" not in string:
                    domain = last_r if string.count("/") < 2 else durl
                    string = domain + ("" if string.startswith("/") else "/") + string
                lines[index] = self.proxy(string, string.split(".")[-1].split("?")[0])

        return [200, "application/vnd.apple.mpegur", "\n".join(lines)]

    def tsProxy(self, url):
        url = self.d64(url)
        data = requests.get(url, headers=self.headers,
                            proxies=self.proxies, stream=True)
        return [200, data.headers["Content-Type"], data.content]

    # ================= Base64（102 原样） =================
    def e64(self, text):
        try:
            return b64encode(text.encode("utf-8")).decode("utf-8")
        except Exception as e:
            print(f"Base64编码错误: {e}")
            return ""

    def d64(self, text):
        try:
            return b64decode(text.encode("utf-8")).decode("utf-8")
        except Exception as e:
            print(f"Base64解码错误: {e}")
            return ""

    # ================= 发布页 / 动态域名（102 原样 + 跳转 fallback） =================
    def get_working_host(self):
        for url in self.extract_domains_from_publish_page():
            try:
                r = requests.get(url, headers=self.headers,
                                 proxies=self.proxies, timeout=self.cfg["probe_timeout"])
                if r.status_code == 200 and self.getpq(r.text)(self.cfg["host_check_selector"]):
                    self.log(f"动态解析到可用站点: {url}")
                    print(f"动态解析到可用站点: {url}")
                    return url
            except Exception:
                continue

        for url in self.cfg["fallback_hosts"]:
            try:
                r = requests.get(url, headers=self.headers,
                                 proxies=self.proxies, timeout=self.cfg["probe_timeout"])
                if r.status_code == 200 and self.getpq(r.text)(self.cfg["host_check_selector"]):
                    self.log(f"回退选用可用站点: {url}")
                    print(f"回退选用可用站点: {url}")
                    return url
            except Exception:
                continue

        fallback = self.cfg["fallback_hosts"][0]
        self.log(f"未检测到可用站点，回退: {fallback}")
        print(f"未检测到可用站点，回退: {fallback}")
        return fallback

    def extract_domains_from_publish_page(self):
        """102 原逻辑 + 拿不到候选时尝试 meta refresh / JS location 跳转"""
        try:
            r = requests.get(self.cfg["publish_url"], headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["probe_timeout"],
                             allow_redirects=True)
            if r.status_code != 200:
                self.log(f"发布页请求失败: HTTP {r.status_code}")
                return []

            html = self._decode_publish(r.text, self.cfg["publish_decode"])
            doc = self.getpq(html)
            domains = self._pick_domains(doc, self.cfg["publish_url"])

            # ===== 新增：102 原逻辑拿不到候选时，尝试跳转识别 =====
            if not domains:
                target = self._find_meta_refresh(r.text)
                if target:
                    self.log(f"发现 meta refresh 跳转: {target}")
                    print(f"发现 meta refresh 跳转: {target}")
                    domains = self._fetch_and_extract(target, self.cfg["publish_url"])

            if not domains:
                target = self._find_js_location(r.text)
                if target:
                    self.log(f"发现 JS location 跳转: {target}")
                    print(f"发现 JS location 跳转: {target}")
                    domains = self._fetch_and_extract(target, self.cfg["publish_url"])
            # ====================================================

            self.log(f"发布页解析到 {len(domains)} 个候选域名")
            print(f"发布页解析到 {len(domains)} 个候选域名")
            return domains
        except Exception as e:
            self.log(f"解析发布页失败: {e}")
            print(f"解析发布页失败: {e}")
            return []

    # ============ 新增：三个跳转辅助方法 ============
    def _find_meta_refresh(self, html):
        m = re.search(
            r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+'
            r'content=["\'][^"\']*url=([^"\'>\s]+)',
            html or "", re.I,
        )
        return m.group(1).strip("'\"") if m else ""

    def _find_js_location(self, html):
        if not html:
            return ""
        patterns = [
            r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
            r'document\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
            r'location\.replace\(\s*["\']([^"\']+)["\']',
            r'location\.assign\(\s*["\']([^"\']+)["\']',
        ]
        for p in patterns:
            m = re.search(p, html)
            if m:
                return m.group(1)
        return ""

    def _fetch_and_extract(self, target_url, base):
        try:
            if target_url.startswith("//"):
                target_url = "https:" + target_url
            elif target_url.startswith("/"):
                target_url = base.rstrip("/") + target_url
            elif not target_url.startswith("http"):
                return []

            self.log(f"请求跳转目标: {target_url}")
            print(f"请求跳转目标: {target_url}")

            r = requests.get(target_url, headers=self.headers,
                             proxies=self.proxies,
                             timeout=self.cfg["probe_timeout"],
                             allow_redirects=True)
            if r.status_code != 200:
                return []

            html = self._decode_publish(r.text, self.cfg["publish_decode"])
            doc = self.getpq(html)
            return self._pick_domains(doc, target_url)
        except Exception as e:
            self.log(f"请求跳转目标失败: {e}")
            print(f"请求跳转目标失败: {e}")
            return []
    # =================================================

    def _decode_publish(self, text, mode):
        if mode == "js_base64":
            m = re.search(r"Base64\.decode\(['\"]([^'\"]+)['\"]\)", text)
            if m:
                try:
                    return b64decode(m.group(1)).decode("utf-8", "ignore")
                except Exception:
                    return text
            return text
        if mode == "js_atob":
            m = re.search(r"atob\(['\"]([^'\"]+)['\"]\)", text)
            if m:
                try:
                    return b64decode(m.group(1)).decode("utf-8", "ignore")
                except Exception:
                    return text
            return text
        if mode == "plain":
            return text
        if mode == "redirect":
            return ""
        return text

    def _pick_domains(self, doc, base):
        seen, out = set(), []
        for a in doc("a").items():
            href = (a.attr("href") or "").strip()
            if not href:
                continue
            if href.startswith("//"):
                href = "https:" + href
            if href.startswith("/") and base:
                href = base.rstrip("/") + href
            if not href.startswith("http") or "." not in href:
                continue
            if any(x in href for x in ["javascript:", "mailto:", "#"]):
                continue
            if href not in seen:
                seen.add(href)
                out.append(href)
        return out

    # ================= 播放器解析（102 原样） =================
    def _parse_players(self, doc):
        plist = []
        used_names = set()
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
            video_url = cfg.get("video", {}).get("url", "")
            if not video_url:
                continue

            ep_name = ""
            try:
                parent = node.parents().eq(0)
                for _ in range(3):
                    if not parent:
                        break
                    h = parent.find(self.cfg["player_heading_selector"]).eq(0).text() or ""
                    h = h.strip()
                    if h:
                        ep_name = h
                        break
                    parent = parent.parents().eq(0)
            except Exception:
                ep_name = ""

            base_name = ep_name or f"视频{idx}"
            name = base_name
            c = 2
            while name in used_names:
                name = f"{base_name} {c}"
                c += 1
            used_names.add(name)

            self.log(f"解析到视频: {name} -> {video_url}")
            print(f"解析到视频: {name} -> {video_url}")
            plist.append(f"{name}${video_url}")
        return plist

    # ================= 列表（102 原样） =================
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
            if href and name:
                videos.append({
                    "vod_id": f"{href}{'@folder' if is_folder else ''}",
                    "vod_name": name.replace("\n", " "),
                    "vod_pic": self.getimg(k("script").text()),
                    "vod_remarks": remark or "",
                    "vod_tag": "folder" if is_folder else "",
                    "style": self.cfg["style"],
                })
        return videos

    # ================= 合集（102 原样） =================
    def getfod(self, folder_id):
        url = f"{self.host}{folder_id}"
        r = requests.get(url, headers=self.headers,
                         proxies=self.proxies, timeout=self.cfg["timeout"])
        doc = self.getpq(r.text)
        vdata = doc(self.cfg["folder_content_selector"])

        for sel in self.cfg["folder_remove_selectors"]:
            vdata.remove(sel)

        p = vdata("p")
        img_attr = self.cfg["folder_img_attr"]
        videos = []
        for i, x in enumerate(vdata("h2").items()):
            c = i * 2
            videos.append({
                "vod_id": p.eq(c)("a").attr("href"),
                "vod_name": p.eq(c).text(),
                "vod_pic": f"{self.getProxyUrl()}&url={p.eq(c + 1)('img').attr(img_attr)}&type=img",
                "vod_remarks": x.text(),
            })
        return videos

    # ================= 图片（102 原样） =================
    def getimg(self, text):
        m = re.search(self.cfg["img_regex"], text or "")
        if m:
            return f"{self.getProxyUrl()}&url={m.group(1)}&type=img"
        return ""

    def aesimg(self, word):
        cipher = AES.new(self.cfg["aes_key"], AES.MODE_CBC, self.cfg["aes_iv"])
        return unpad(cipher.decrypt(word), AES.block_size)

    # ================= PyQuery（102 原样） =================
    def getpq(self, data):
        try:
            return pq(data)
        except Exception as e:
            print(f"{e}")
            return pq(data.encode("utf-8"))


# ==============  万能一键加速（2026-10五星无探测双 CDN 版）  ==============
_PIC_CDN_POOL = ('lib.baomitu.com', 'open.oppomobile.com')

def _cover_fallback(self, pic_url):
    import urllib.parse
    raw = pic_url or ''
    parent_impl = getattr(super(Spider, self), '_cover_fallback', None)
    if callable(parent_impl):
        try:
            raw = parent_impl(pic_url) or raw
        except Exception:
            pass
    if not raw:
        return ''
    url = raw
    for cdn in _PIC_CDN_POOL:
        if cdn in raw:
            url = raw.replace(cdn, _PIC_CDN_POOL[0])
            break
    proxy_base = getattr(self, 'proxy_base', None)
    if proxy_base:
        url = f'{proxy_base}{urllib.parse.quote(url)}'
    return url

Spider._cover_fallback = _cover_fallback
# 注册爬虫
if __name__ == '__main__':
    from base.spider import Spider as BaseSpider
    BaseSpider.register(Spider)
