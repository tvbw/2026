# -*- coding: utf-8 -*-
"""
91大赛 · 多域名自愈版（图片修复版 v2）
================================
- 域名自愈：并发探测 + TTL缓存 + 302跟随 + 详细日志 + 兜底
- 图片链路：urlsafe b64 + 原URL优先/CDN兜底 + 明图直通 + 解密失败返回原内容
- CDN 域名：从首页 HTML 动态提取，站点换图床无需改代码
- 业务保留：正则列表 + 13策略提取 + 剧集聚合 + AES解密 + CDN重写
"""
import sys
import json
import re
import time
import base64
import logging
import random
from urllib.parse import quote, urljoin, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

sys.path.append("..")
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        def getCache(self, k):    return None
        def setCache(self, k, v): pass
        def getProxyUrl(self):    return ""

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

LOG = logging.getLogger(__name__)


# ==================== 分类 / 标签常量 ====================
MANUAL_CLASSES = [
    ('/category/jrds/',  '今日大赛',    'iconfont icon-jrds'),
    ('/category/rsds/',  '热搜大赛',    'iconfont icon-rsds'),
    ('/category/mrds/',  '每日大赛',    'iconfont icon-mrds'),
    ('/category/aidj/',  'AI短剧',     'iconfont icon-aidj'),
    ('/category/nsds/',  '女神大赛',    'iconfont icon-nsds'),
    ('/category/llds/',  '乱伦大赛',    'iconfont icon-llds'),
    ('/category/xyds/',  '学院大赛',    'iconfont icon-xyds'),
    ('/category/whds/',  '网红大赛',    'iconfont icon-whds'),
    ('/category/lyds/',  '撸友看片',    'iconfont icon-lyds'),
    ('/category/sjbzq/', '优选投放区',  'iconfont icon-sjbzq'),
    ('/category/qwds/',  '奇闻大赛',    'iconfont icon-qwds'),
    ('/category/mxds/',  '明星吃瓜',    'iconfont icon-mxds'),
    ('/category/ntds/',  '女同大赛',    'iconfont icon-ntds'),
    ('/category/wmds/',  '污漫大赛',    'iconfont icon-wmds'),
]

HOT_TAGS = [
    ('/tag/91大赛/', '91大赛', '🔥'),
    ('/tag/吃瓜/', '吃瓜', '🍉'),
    ('/tag/反差婊/', '反差婊', '💋'),
    ('/tag/高颜值/', '高颜值', '✨'),
    ('/tag/美乳/', '美乳', '🍒'),
    ('/tag/黑丝/', '黑丝', '🖤'),
]

EPISODE_PATTERN      = re.compile(r'^(.*?)(第\d+集)\s*(.*)$')
SERIES_CLEAN_PATTERN = re.compile(r'^(.*?)(第\d+集|\d+集|完整版|无码版|爆燃来袭|重磅流出|高能开场|重磅来袭|已完结).*')


# ==================== 配置层 ====================
class SiteConfig:
    # ---- 三级域名列表 ----
    SEED_HOSTS = [
        "https://alone.poampwcv.cc/",
        "https://break.poampwcv.cc/",
        "https://any.zenolyqt.cc/",
    ]
    FALLBACK_HOST  = None
    HOST_CACHE_KEY = "91ds_host"
    HOST_CACHE_TTL = 6 * 3600

    PROBE_TIMEOUT        = 8
    PROBE_MIN_HTML       = 3000
    PROBE_MIN_ARTICLE    = 3

    SITE_KEYWORDS    = ["91大赛"]
    SITE_MARKERS     = ["Xc_home_article", "Xc_archive", "/archives/"]

    # ---- 图片配置（CDN_XHOST 会被 init() 动态覆盖，这里是兜底默认值）----
    CDN_XHOST   = "https://pic.hdhwqx.cn"   # 原 pic.xustgq.cn 已挂，更新为当前域名
    IMG_AES_KEY = "f5d965df75336270"
    IMG_AES_IV  = "97b60394abc2fbe1"

    # ---- 通用 Headers ----
    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }


# ==================== 域名解析器 ====================
class DomainResolver:
    def __init__(self, cfg, fetcher, cache_get=None, cache_set=None):
        self.cfg, self.fetch = cfg, fetcher
        self.cache_get, self.cache_set = cache_get, cache_set

    def _site_ok(self, html):
        if not html or len(html) < self.cfg.PROBE_MIN_HTML:
            return False
        if self.cfg.SITE_KEYWORDS:
            if any(kw in html for kw in self.cfg.SITE_KEYWORDS):
                return True
        return any(m in html for m in self.cfg.SITE_MARKERS)

    def _safe_fetch(self, url, timeout):
        try:
            return self.fetch(url, timeout=timeout)
        except Exception:
            return None

    def _read_cache(self):
        if not self.cache_get:
            return None
        try:
            raw = self.cache_get(self.cfg.HOST_CACHE_KEY)
        except Exception:
            return None
        if not raw:
            return None
        if isinstance(raw, str) and raw.startswith("http"):
            return {"host": raw.rstrip("/"), "ts": 0}
        try:
            if isinstance(raw, str):
                raw = json.loads(raw)
            if isinstance(raw, dict) and raw.get("host"):
                return raw
        except Exception:
            pass
        return None

    def _cache_fresh(self, c):
        ttl = int(getattr(self.cfg, "HOST_CACHE_TTL", 0) or 0)
        if ttl <= 0:
            return True
        return (time.time() - int(c.get("ts") or 0)) < ttl

    def _write_cache(self, host):
        if not self.cache_set:
            return
        try:
            self.cache_set(self.cfg.HOST_CACHE_KEY,
                           json.dumps({"host": host, "ts": int(time.time())}))
        except Exception:
            pass

    def _clear_cache(self):
        if not self.cache_set:
            return
        try:
            if hasattr(self, "cache_del") and self.cache_del:
                self.cache_del(self.cfg.HOST_CACHE_KEY)
        except Exception:
            pass

    def resolve(self):
        cached = self._read_cache()

        if cached and self._cache_fresh(cached):
            r = self._safe_fetch(cached["host"] + "/", self.cfg.PROBE_TIMEOUT)
            if r is not None and r.status_code == 200 and self._site_ok(r.text):
                final = (r.url or cached["host"]).rstrip("/")
                print(f"缓存有效: {cached['host']} → {final}")
                if final != cached["host"]:
                    self._write_cache(final)
                return final
            print(f"缓存失效: {cached['host']}")

        urls = list(self.cfg.SEED_HOSTS)
        if cached:
            urls.insert(0, cached["host"] + "/")
        if not urls:
            return ""

        with ThreadPoolExecutor(max_workers=min(6, len(urls))) as ex:
            futs = {ex.submit(self._safe_fetch, u, self.cfg.PROBE_TIMEOUT): u for u in urls}
            try:
                for f in as_completed(futs, timeout=self.cfg.PROBE_TIMEOUT + 8):
                    u = futs[f]
                    try:
                        r = f.result()
                    except Exception as e:
                        print(f"探测异常 {u}: {e}")
                        continue
                    if r is None:
                        print(f"探测无响应: {u}")
                        continue
                    if r.status_code != 200:
                        print(f"探测 HTTP {r.status_code}: {u}")
                        continue
                    if not self._site_ok(r.text):
                        kws = self.cfg.SITE_KEYWORDS or '结构判断'
                        print(f"探测内容不匹配: {u} (len={len(r.text or '')}, 关键词={kws})")
                        continue
                    final = (r.url or u).rstrip("/")
                    self._write_cache(final)
                    if final.rstrip("/") != u.rstrip("/"):
                        print(f"探测成功（含跳转）: {u} → {final}")
                    else:
                        print(f"探测成功: {final}")
                    return final
            except Exception as e:
                LOG.debug("并发探测异常: %s", e)

        if cached:
            print(f"使用过期缓存: {cached['host']}")
            return cached["host"]

        if self.cfg.SEED_HOSTS:
            fallback = self.cfg.SEED_HOSTS[0].rstrip("/")
            print(f"【警告】所有域名探测失败，回退到种子域名: {fallback}")
            return fallback

        return ""


# ==================== 主爬虫 ====================
class Spider(BaseSpider):
    CONFIG = SiteConfig

    def __init__(self, *a, **kw):
        try:
            super().__init__(*a, **kw)
        except Exception:
            pass
        self.host = ""
        self.proxies = {}
        self.headers = dict(self.CONFIG.HEADERS)

    def getName(self):
        return "91大赛·多域自愈版"

    def init(self, extend=""):
        try:
            self.proxies = json.loads(extend) if extend else {}
            if not isinstance(self.proxies, dict):
                self.proxies = {}
        except Exception:
            self.proxies = {}
        self.headers = dict(self.CONFIG.HEADERS)

        resolver = DomainResolver(
            self.CONFIG, self._get,
            cache_get=getattr(self, "getCache", None),
            cache_set=getattr(self, "setCache", None),
        )
        try:
            resolver.cache_del = getattr(self, "delCache", None)
        except Exception:
            pass

        self.host = resolver.resolve()
        if self.host:
            self.headers.update({"Origin": self.host, "Referer": self.host + "/"})
            # ★ 从首页 HTML 动态提取图片 CDN 域名（站点换图床时自动适配）
            self._detect_cdn_host()
        print(f"使用站点: {self.host}")

    def _detect_cdn_host(self):
        """从首页 HTML 里提取图片域名，作为 CDN_XHOST 的兜底来源。
        优先 data-src / loadThumb 的绝对地址；失败则保留默认值。"""
        try:
            html = self._get_html(self.host)
            if not html:
                return
            candidates = []
            # 1) data-src="https://xxx/path/..."
            for m in re.finditer(r'data-src="(https?://([^/"]+)/[^"]+)"', html):
                candidates.append(m.group(2))
            # 2) loadThumb("https:\/\/xxx\/path...")
            for m in re.finditer(r'loadThumb\(\s*"(https?:[^"]+)"', html):
                v = m.group(1).replace('\\/', '/')
                mm = re.match(r'https?://([^/]+)/', v)
                if mm:
                    candidates.append(mm.group(1))
            # 3) <img src="https://xxx/..."> 且非 data:
            for m in re.finditer(r'<img[^>]+src="(https?://([^/"]+)/[^"]+)"', html):
                candidates.append(m.group(2))

            if not candidates:
                return
            # 取出现次数最多的域名
            from collections import Counter
            host = Counter(candidates).most_common(1)[0][0]
            if host:
                self.CONFIG.CDN_XHOST = "https://" + host
                print(f"动态 CDN 域名: {self.CONFIG.CDN_XHOST}")
        except Exception as e:
            print(f"提取 CDN 失败: {e}")

    def isVideoFormat(self, url):
        return True

    def manualVideoCheck(self):
        return False

    def destroy(self):
        return None

    # ==================== 通用请求 ====================
    def _get(self, url, timeout=None, **kw):
        try:
            time.sleep(random.uniform(0.2, 0.5))
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=timeout or 15, verify=False,
                             allow_redirects=True, **kw)
            if r.status_code == 200:
                try:
                    r.encoding = 'utf-8'
                except Exception:
                    pass
            return r
        except Exception as e:
            LOG.debug("GET 异常 %s: %s", url, e)
            return None

    def _get_html(self, url, timeout=15):
        r = self._get(url, timeout=timeout)
        if r is None or r.status_code != 200:
            return None
        text = r.text or ""
        if len(text) < 500:
            print(f"内容过短：{url} 长度 {len(text)}")
            return None
        return text

    def _abs(self, href):
        if not href:
            return ""
        if href.startswith("http"):
            return href
        if href.startswith("//"):
            return "https:" + href
        if not self.host:
            return href
        return urljoin(self.host + "/", href.lstrip("/"))

    # ==================== 首页 ====================
    def homeVideoContent(self):
        html = self._get_html(self.host)
        videos = self._parse_list_html(html) if html else []
        return {'list': videos}

    def homeContent(self, filter=False):
        result = {'class': []}
        html = self._get_html(self.host)
        dynamic = self._fetch_dynamic_classes(html) if html else []
        seen = set()

        for tid, name in dynamic:
            if tid not in seen:
                seen.add(tid)
                result['class'].append({
                    'type_id':   tid,
                    'type_name': name,
                    'type_icon': self._get_class_icon(name),
                    'subclass':  [{'type_id': t[0], 'type_name': f"{t[2]} {t[1]}"}
                                  for t in HOT_TAGS]
                })
        for tid, name, icon in MANUAL_CLASSES:
            if tid not in seen:
                seen.add(tid)
                result['class'].append({
                    'type_id':   tid,
                    'type_name': name,
                    'type_icon': icon,
                    'subclass':  [{'type_id': t[0], 'type_name': f"{t[2]} {t[1]}"}
                                  for t in HOT_TAGS]
                })
        return result

    def _get_class_icon(self, name):
        mapping = {c[1]: c[2] for c in MANUAL_CLASSES}
        return mapping.get(name, 'iconfont icon-default')

    def _fetch_dynamic_classes(self, html):
        if not html:
            return []
        classes = []
        for href, name in re.findall(
            r'<a class="item[^"]*" href="(/category/[^"]+)"[^>]*>(.*?)</a>',
            html, re.S,
        ):
            name = re.sub(r'<[^>]+>', '', name).strip()
            if name and href not in [c[0] for c in classes]:
                classes.append((href, name))
        for href, name in re.findall(
            r'<li><a class="link[^"]*" href="(/category/[^"]+)"[^>]*>(.*?)</a>',
            html, re.S,
        ):
            name = re.sub(r'<[^>]+>', '', name).strip()
            if name and href not in [c[0] for c in classes]:
                classes.append((href, name))
        return classes

    # ==================== 分类列表 ====================
    def categoryContent(self, cid, pg='1', filter=False, ext=None):
        pg = pg if pg and str(pg).isdigit() and int(pg) > 0 else '1'
        base_url = urljoin(self.host + "/", str(cid).lstrip("/"))
        urls = [base_url] if pg == '1' else [
            base_url.rstrip('/') + '/' + str(pg) + '/',
            base_url.rstrip('/') + '/page/' + str(pg) + '/',
            base_url + ('&' if '?' in base_url else '?') + 'page=' + str(pg),
        ]
        html = None
        for url in urls:
            html = self._get_html(url)
            if html:
                break
        videos = self._parse_list_html(html) if html else []
        return {
            'list': videos, 'page': int(pg), 'pagecount': 9999,
            'limit': 90, 'total': len(videos),
        }

    # ==================== 列表解析 ====================
    def _parse_list_html(self, html):
        if not html:
            return []
        videos = []
        try:
            items = re.findall(
                r'<li class="(?:Xc_home_article-si|Xc_archive-si)[^"]*"[^>]*>(.*?)</li>',
                html, re.S,
            )
            if not items:
                items = re.findall(
                    r'<(?:article|div)\s[^>]*class="[^"]*(?:post|article|card)[^"]*"[^>]*>'
                    r'(.*?)</(?:article|div)>',
                    html, re.S,
                )
            if not items:
                for block, href in re.findall(r'(<a\s[^>]*href="([^"]*)"[^>]*>.*?</a>)', html, re.S):
                    title = re.search(r'title="([^"]*)"', block) or re.search(r'alt="([^"]*)"', block)
                    title = title.group(1) if title else ''
                    if not title:
                        continue
                    pic = self._extract_list_image(block) or ''
                    vid = re.search(r'/archives/(\d+)/', href)
                    vid = vid.group(1) if vid else href
                    remarks = re.search(r'<time[^>]*>(.*?)</time>', block, re.S)
                    remarks = re.sub(r'<[^>]+>', '', remarks.group(1)).strip() if remarks else ''
                    videos.append({
                        "vod_id": vid, "vod_name": title,
                        "vod_pic": pic, "vod_remarks": remarks,
                    })
                return videos

            for item in items:
                a_match = re.search(r'<a\s[^>]*href="([^"]+)"[^>]*title="([^"]*)"', item)
                if not a_match:
                    a_match = re.search(r'<a\s[^>]*href="([^"]+)"[^>]*>.*?<img[^>]*alt="([^"]*)"', item)
                if not a_match:
                    a_match = re.search(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', item, re.S)
                    if a_match:
                        title_text = re.sub(r'<[^>]+>', '', a_match.group(2)).strip()
                        a_match = (a_match.group(1), title_text) if title_text else None
                if not a_match:
                    continue

                if isinstance(a_match, tuple):
                    href, title = a_match
                else:
                    href = a_match.group(1)
                    title = a_match.group(2).strip() if a_match.lastindex and a_match.lastindex >= 2 else ''
                    if not title:
                        t = re.search(r'<img[^>]*alt="([^"]*)"', item)
                        title = t.group(1).strip() if t else ''

                pic = self._extract_list_image(item) or ''
                vid = re.search(r'/archives/(\d+)/', href)
                vid = vid.group(1) if vid else href
                remarks = (re.search(r'<div class="last">(.*?)</div>', item, re.S)
                           or re.search(r'<time[^>]*>(.*?)</time>', item, re.S))
                remarks = re.sub(r'<[^>]+>', '', remarks.group(1)).strip() if remarks else ''
                videos.append({
                    "vod_id": vid, "vod_name": title,
                    "vod_pic": pic, "vod_remarks": remarks,
                })
        except Exception as e:
            print(f"列表解析出错: {e}")
        return videos

    # ==================== 图片提取：多属性兜底 ====================
    def _extract_list_image(self, block):
        """多属性兜底：data-xkrkllgl → data-src/data-* → src"""
        xk = re.search(r'data-xkrkllgl="([^"]+)"', block)
        if xk and xk.group(1).strip():
            return self._cover_url(xk.group(1).strip())

        for attr in ('data-src', 'data-original', 'data-lazy', 'data-img', 'data-url'):
            m = re.search(rf'{attr}="([^"]+)"', block)
            if m:
                val = m.group(1).strip()
                if val and 'zw.png' not in val and 'lazyload' not in val:
                    return self._cover_url(val)

        src = re.search(r'<img[^>]*src="([^"]+)"', block)
        if src:
            val = src.group(1).strip()
            if val and 'zw.png' not in val and 'lazyload' not in val and not val.startswith('data:'):
                return self._cover_url(val)
        return ''

    def _fix_image_url(self, pic_url):
        if not pic_url:
            return ''
        if pic_url.startswith('data:'):
            return pic_url
        if pic_url.startswith('//'):
            return 'https:' + pic_url
        return urljoin(self.host + "/", pic_url)

    def _cdn_image_url(self, pic_url):
        """把原图 URL 的 host 换成 CDN_XHOST（仅当路径命中图片目录时）。"""
        if not pic_url:
            return pic_url
        if re.search(r'/(?:new|xiao|upload|uploads)/', pic_url):
            return self.CONFIG.CDN_XHOST + re.sub(r'^https?://[^/]+', '', pic_url)
        return pic_url

    def _cover_url(self, raw_url):
        if not raw_url:
            return ''
        raw_url = self._fix_image_url(raw_url)
        if re.search(r'/(?:new|xiao|upload|uploads)/', raw_url):
            return self._proxy_image_url(raw_url)
        return raw_url

    # ==================== 图片代理URL：urlsafe b64（不预转CDN） ====================
    def _proxy_image_url(self, raw_url):
        if not raw_url:
            return ''
        try:
            # ★ 不再预先转 CDN，把原始 URL 交给代理做多路兜底
            proxy_base = self.getProxyUrl() if hasattr(self, 'getProxyUrl') else ''
            if not proxy_base:
                return raw_url
            sep = '&' if '?' in proxy_base else '?'
            b64 = base64.urlsafe_b64encode(raw_url.encode('utf-8')).decode('utf-8').rstrip('=')
            return f"{proxy_base}{sep}type=image&url={b64}"
        except Exception as e:
            print(f"[img] URL构造失败: {e}")
            return raw_url

    # ==================== 详情页 ====================
    def _norm_ids(self, ids):
        if ids is None:
            return ""
        if isinstance(ids, (list, tuple)):
            return str(ids[0]) if ids else ""
        if isinstance(ids, bytes):
            return ids.decode("utf-8", errors="ignore")
        return str(ids).strip()

    def detailContent(self, ids):
        did = self._norm_ids(ids)
        if not did:
            return {'list': []}

        if did.isdigit():
            detail_url = self.host + '/archives/' + did + '/'
            vid = did
        elif did.startswith('/archives/'):
            detail_url = self.host + did
            m = re.search(r'/archives/(\d+)/', did)
            vid = m.group(1) if m else did
        else:
            detail_url = self.host + did
            vid = did

        result = {'list': []}
        html = self._get_html(detail_url, timeout=20)
        if not html:
            return result

        try:
            title = ''
            for p in [
                r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h1>',
                r'<meta[^>]*property="og:title"[^>]*content="([^"]*)"',
                r'<title>(.*?)</title>',
            ]:
                m = re.search(p, html, re.S)
                if m:
                    title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                    break

            purl, pic = self._extract_video_info_from_config(html)
            if not purl:
                purl = self._extract_video_13_strategies(html)

            if not pic:
                pic_m = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]*)"', html)
                if pic_m:
                    pic = self._cover_url(pic_m.group(1))
            if not pic:
                img_m = re.search(r'<img[^>]*data-xkrkllgl="([^"]+)"', html)
                if img_m:
                    pic = self._cover_url(img_m.group(1))

            ep_info = EPISODE_PATTERN.search(title) if title else None
            if ep_info and purl:
                series_name = ep_info.group(1).strip()
                series_name = SERIES_CLEAN_PATTERN.sub(r'\1', series_name).strip() or series_name
                series_videos = self._search_series(series_name, vid)
                if series_videos and len(series_videos) > 1:
                    series_videos.sort(key=lambda x: x.get('episode_num', 0))
                    play_list = [
                        f"{v['episode_name']}${v['vod_play_url']}"
                        for v in series_videos if v.get('vod_play_url')
                    ]
                    result['list'].append({
                        "vod_id":        vid,
                        "vod_name":      title,
                        "vod_pic":       pic,
                        "vod_remarks":   f"共{len(series_videos)}集",
                        "vod_play_from": "剧集连播",
                        "vod_play_url":  "#".join(play_list),
                    })
                else:
                    result['list'].append(self._single_video(vid, title, pic, purl))
            else:
                result['list'].append(self._single_video(vid, title, pic, purl))
        except Exception as e:
            print(f"详情解析出错: {e}")
        return result

    def _single_video(self, vid, title, pic, purl):
        return {
            "vod_id": vid, "vod_name": title, "vod_pic": pic,
            "vod_play_from": "直链播放", "vod_play_url": purl,
        }

    def _extract_video_info_from_config(self, html):
        purl, pic = '', ''
        for pattern in [
            r'data-config="([^"]*)"',
            r'data-config=\s*"([^"]*?)"',
            r"data-config='([^']*)'",
        ]:
            match = re.search(pattern, html, re.S)
            if match:
                try:
                    config_str = match.group(1).replace('&quot;', '"').replace('\\/', '/')
                    config = json.loads(config_str)
                    video = config.get('video', {})
                    purl = video.get('url', '')
                    pic  = video.get('pic', '')
                    if purl:
                        break
                except Exception:
                    continue
        if pic:
            pic = self._cover_url(pic)
        return purl, pic

    def _extract_video_13_strategies(self, html):
        url, _ = self._extract_video_info_from_config(html)
        if url:
            return url
        patterns = [
            r'new\s+DPlayer\s*\(\s*\{[^}]*url\s*:\s*["\']([^"\']+)',
            r'"","url":"(.*?)"',
            r'<video[^>]+src="([^"]+)"',
            r'<source[^>]+src="([^"]+)"',
            r'<iframe[^>]+src="([^"]+)"',
            r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',
            r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)',
            r'data-url="([^"]+)"',
            r'data-src="([^"]+\.(?:m3u8|mp4))"',
        ]
        for p in patterns:
            m = re.search(p, html)
            if m:
                val = m.group(1)
                if p == r'"","url":"(.*?)"':
                    val = val.replace("\\", "")
                return val
        m = re.search(r'var player_[^=]+=\s*({.*?})', html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                if data.get('url'):
                    return data['url']
            except Exception:
                pass
        m = re.search(r'playerConfig\s*=\s*({.*?})', html, re.S)
        if m:
            try:
                conf = json.loads(m.group(1))
                url = conf.get('url') or conf.get('video', {}).get('url')
                if url:
                    return url
            except Exception:
                pass
        m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                for item in data.get('@graph', [data]):
                    if item.get('@type') == 'VideoObject':
                        url = item.get('contentUrl') or item.get('embedUrl')
                        if url:
                            return url
            except Exception:
                pass
        all_media = re.findall(r'(https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*)', html)
        return all_media[0] if all_media else ""

    def _search_series(self, name, exclude_vid):
        series = []
        try:
            html = self._get_html(self.host + '/?s=' + quote(name))
            if not html:
                return series
            videos = self._parse_list_html(html)
            for v in videos:
                if str(v['vod_id']) == str(exclude_vid):
                    continue
                ep = EPISODE_PATTERN.search(v['vod_name'])
                if not ep:
                    continue
                v_series = ep.group(1).strip()
                v_series = SERIES_CLEAN_PATTERN.sub(r'\1', v_series).strip()
                if name in v_series or v_series in name or name in v['vod_name']:
                    ep_num_m = re.search(r'第(\d+)集', v['vod_name'])
                    ep_num = int(ep_num_m.group(1)) if ep_num_m else 0
                    d_url = (self.host + '/archives/' + str(v['vod_id']) + '/'
                             if str(v['vod_id']).isdigit()
                             else self.host + str(v['vod_id']))
                    dhtml = self._get_html(d_url)
                    if dhtml:
                        purl, _ = self._extract_video_info_from_config(dhtml)
                        purl = purl or self._extract_video_13_strategies(dhtml)
                        if purl:
                            series.append({
                                'vod_id': v['vod_id'], 'vod_name': v['vod_name'],
                                'episode_name': ep.group(2), 'episode_num': ep_num,
                                'vod_play_url': purl,
                            })
            self_url = (self.host + '/archives/' + str(exclude_vid) + '/'
                        if str(exclude_vid).isdigit()
                        else self.host + str(exclude_vid))
            dhtml = self._get_html(self_url)
            if dhtml:
                title_m = re.search(r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h1>', dhtml, re.S)
                title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ''
                purl, _ = self._extract_video_info_from_config(dhtml)
                purl = purl or self._extract_video_13_strategies(dhtml)
                if purl and title:
                    ep_m = EPISODE_PATTERN.search(title)
                    ep_num_m = re.search(r'第(\d+)集', title)
                    ep_num = int(ep_num_m.group(1)) if ep_num_m else 0
                    series.append({
                        'vod_id': exclude_vid, 'vod_name': title,
                        'episode_name': ep_m.group(2) if ep_m else f"第{ep_num}集",
                        'episode_num': ep_num, 'vod_play_url': purl,
                    })
        except Exception as e:
            print(f"系列聚合出错: {e}")
        return series

    # ==================== 搜索 ====================
    def searchContent(self, key, quick, pg="1"):
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick, page="1"):
        page = str(page or "1")
        url = self.host + '/?s=' + quote(key)
        if page != '1':
            url = self.host + '/page/' + str(page) + '/?s=' + quote(key)
        html = self._get_html(url)
        videos = self._parse_list_html(html) if html else []
        return {
            'list': videos, 'page': int(page), 'pagecount': 9999,
            'limit': 90, 'total': len(videos),
        }

    # ==================== 播放 ====================
    def playerContent(self, flag, id, vipFlags=None):
        play_url = str(id).strip()
        if not play_url:
            return {"parse": 0, "playUrl": "", "url": "", "header": {}}
        video_url = play_url if play_url.startswith('http') else urljoin(self.host + "/", play_url)
        return {
            "parse": 0,
            "playUrl": "",
            "url": video_url,
            "header": json.dumps({
                "User-Agent": self.CONFIG.HEADERS["User-Agent"],
                "Referer":    self.host + '/',
                "Origin":     self.host,
            }, ensure_ascii=False),
        }

    # ==================== 本地代理 ====================
    def localProxy(self, param):
        try:
            if not isinstance(param, dict):
                return [400, "text/plain", b"invalid param"]
            ptype = param.get('type', '')
            if ptype in ('image', 'img'):
                return self._proxy_image(param)
            if ptype == 'm3u8':
                return self._proxy_m3u8(param)
            return [404, "text/plain", b"unsupported type"]
        except Exception as e:
            return [500, "text/plain", ("localProxy error: %s" % type(e).__name__).encode("utf-8")]

    # ---------- 图片代理：原URL优先 + CDN兜底 + 多级兜底 ----------
    def _proxy_image(self, params):
        url = params.get('url', '')
        if not url:
            return [404, "text/plain", b"no url"]

        # 1) 解码 URL（urlsafe / 标准 b64 / 明文）
        if not url.startswith('http'):
            decoded = self._decode_url_param(url)
            if decoded:
                url = decoded
        # 1b) 兜底：参数可能被 URL 编码过（如 https%3A%2F%2F...）
        if not url.startswith('http'):
            try:
                url = unquote(url)
            except Exception:
                pass
        if not url.startswith('http'):
            print(f"[img] url 无效: {str(url)[:80]}")
            return [404, "text/plain", b"invalid url"]

        # 2) 构造尝试列表：原 URL 优先 → CDN 兜底
        try_urls = [('raw', url)]
        cdn = self._cdn_image_url(url)
        if cdn and cdn != url:
            try_urls.append(('cdn', cdn))

        # 3) 逐个尝试
        for tag, try_url in try_urls:
            try:
                r = requests.get(
                    try_url,
                    headers={
                        'Referer': self.host + '/',
                        'User-Agent': self.CONFIG.HEADERS["User-Agent"],
                    },
                    timeout=15, proxies=self.proxies, verify=False,
                )
                if r.status_code != 200:
                    print(f"[img] {tag} HTTP {r.status_code}: {try_url}")
                    continue

                raw = r.content or b""
                if not raw:
                    print(f"[img] {tag} 内容为空: {try_url}")
                    continue

                # 3a) 明图直通
                if self._image_magic_ok(raw):
                    print(f"[img] {tag} 明图直通 ({len(raw)}B): {try_url}")
                    return [200, self._detect_image_type(raw), raw]

                # 3b) AES 解密
                decrypted = self._aes_decrypt_image(raw)
                if decrypted:
                    print(f"[img] {tag} 解密成功 ({len(decrypted)}B): {try_url}")
                    return [200, self._detect_image_type(decrypted), decrypted]

                # 3c) 解密失败 → 返回原内容兜底
                print(f"[img] {tag} 解密失败，兜底返回原内容 "
                      f"({len(raw)}B, head={raw[:8].hex()}): {try_url}")
                return [200, "image/jpeg", raw]

            except Exception as e:
                print(f"[img] {tag} 请求异常 {type(e).__name__}: {try_url}")
                continue

        print(f"[img] 全链路失败: {url}")
        return [500, "text/plain", b"image failed"]

    # ---------- URL参数解码 ----------
    def _decode_url_param(self, s):
        if not s:
            return ''
        try:
            pad = '=' * ((4 - len(s) % 4) % 4)
            decoded = base64.urlsafe_b64decode(s + pad).decode('utf-8')
            if decoded.startswith('http'):
                return decoded
        except Exception:
            pass
        try:
            pad = '=' * ((4 - len(s) % 4) % 4)
            decoded = base64.b64decode(s + pad).decode('utf-8')
            if decoded.startswith('http'):
                return decoded
        except Exception:
            pass
        return s if s.startswith('http') else ''

    # ---------- 图片类型检测 ----------
    def _detect_image_type(self, data):
        if not data:
            return "image/jpeg"
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        if data[:6] in (b'GIF89a', b'GIF87a'):
            return "image/gif"
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return "image/webp"
        if data[:2] == b'\xff\xd8':
            return "image/jpeg"
        return "image/jpeg"

    # ---------- AES 图片解密 ----------
    def _image_magic_ok(self, data):
        if not data:
            return False
        return (data[:2] == b'\xff\xd8'
                or data[:8] == b'\x89PNG\r\n\x1a\n'
                or data[:6] in (b'GIF89a', b'GIF87a')
                or (data[:4] == b'RIFF' and data[8:12] == b'WEBP'))

    def _aes_decrypt_image(self, data):
        if not data or len(data) < 16:
            return None
        key  = self.CONFIG.IMG_AES_KEY.encode('utf-8')
        iv   = self.CONFIG.IMG_AES_IV.encode('utf-8')
        key2 = (self.CONFIG.IMG_AES_KEY[8:] + self.CONFIG.IMG_AES_KEY[:8]).encode('utf-8')
        iv2  = (self.CONFIG.IMG_AES_IV[8:] + self.CONFIG.IMG_AES_IV[:8]).encode('utf-8')
        try:
            for k, v in [(key, iv), (key2, iv2)]:
                try:
                    dec = unpad(AES.new(k, AES.MODE_CBC, v).decrypt(data), 16)
                    if self._image_magic_ok(dec):
                        return dec
                except Exception:
                    pass
            for k, _ in [(key, iv), (key2, iv2)]:
                try:
                    dec = unpad(AES.new(k, AES.MODE_ECB).decrypt(data), 16)
                    if self._image_magic_ok(dec):
                        return dec
                except Exception:
                    pass
        except Exception:
            pass
        return None

    # ---------- m3u8 代理 ----------
    def _proxy_m3u8(self, params):
        url = params.get('url', '')
        referer = params.get('referer', self.host + '/')
        if not url:
            return [404, "text/plain", b"no url"]
        try:
            r = requests.get(url, headers={'Referer': referer, 'Origin': self.host},
                             timeout=10, proxies=self.proxies, verify=False)
            if r.status_code != 200:
                return [404, "text/plain", b"download failed"]
            r.encoding = 'utf-8'
            text = r.text
        except Exception:
            return [404, "text/plain", b"download failed"]
        cleaned = self._clean_m3u8(text, url, referer)
        return [200, "application/vnd.apple.mpegurl", cleaned.encode("utf-8")]

    def _clean_m3u8(self, m3u8_text, m3u8_url='', referer=''):
        if not m3u8_text or "#EXTM3U" not in m3u8_text:
            return m3u8_text or "#EXTM3U\n"
        try:
            base = m3u8_url.rsplit('/', 1)[0] if m3u8_url else ''
            out = []
            for line in m3u8_text.replace("\r", "").split("\n"):
                s = line.strip()
                if not s:
                    continue
                if s.startswith("#"):
                    out.append(s)
                    continue
                if not s.startswith("http"):
                    s = base + "/" + s.lstrip("/") if base else s
                out.append(s)
            return "\n".join(out) + "\n"
        except Exception:
            return m3u8_text


# 注册
try:
    BaseSpider.register(Spider())
except Exception:
    pass
