# -*- coding: utf-8 -*-
"""
91热爆 · 多域名自愈版
================================
架构参考每日模板：并发探测 + TTL缓存 + 详细日志 + 兜底
站点特点：API 驱动（列表/详情/搜索全走 api.vuecloudrb.com）
自愈逻辑：
    每对 {site, api} 作为一个种子
    探测时以 API 健康检查为准（site 仅作 Referer 参考）
    缓存 6 小时；全部失败返回第一对
换站只需改 SiteConfig.SEED_HOSTS。
"""
import json
import sys
import time
import logging
from urllib.parse import quote

import requests

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        def getCache(self, k):    return None
        def setCache(self, k, v): pass
        def getProxyUrl(self):    return ""

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

LOG = logging.getLogger(__name__)


# ==================================================================
# ① 配置层（换站只改 SEED_HOSTS）
# ==================================================================
class SiteConfig:
    # 每对 {site, api} 是一个"站点身份"；换域名时加新对或替换现有对
    SEED_HOSTS = [
        {
            "site": "https://rb.jnyk08.icu",
            "api":  "https://api.vuecloudrb.com",
        },
        # 备用（示例，真实备用域名请自行补充）：
        # {"site": "https://rb.xxx.icu", "api": "https://api.yyy.com"},
    ]

    HOST_CACHE_KEY = "91rebao_host"     # 必须唯一
    HOST_CACHE_TTL = 6 * 3600
    PROBE_TIMEOUT  = 8

    # 探测时调用的健康检查接口
    PROBE_API_PATH   = "/videos/classification"
    PROBE_API_PARAMS = {"page": 1, "size": 1, "categories": 0, "sort": "post_date"}

    USER_AGENT = "Mozilla/5.0"


# ==================================================================
# ② API 域名解析器（返回 (site, api) 成对结果）
# ==================================================================
class ApiDomainResolver:
    def __init__(self, cfg, cache_get=None, cache_set=None):
        self.cfg = cfg
        self.cache_get = cache_get
        self.cache_set = cache_set

    # ---------- 健康检查：只验 API，不管 site ----------
    def _api_ok(self, api_base):
        if not api_base or not api_base.startswith("http"):
            return False
        try:
            r = requests.get(
                api_base.rstrip("/") + self.cfg.PROBE_API_PATH,
                headers={"User-Agent": self.cfg.USER_AGENT},
                params=self.cfg.PROBE_API_PARAMS,
                timeout=self.cfg.PROBE_TIMEOUT,
                verify=False,
            )
            if r.status_code != 200:
                return False
            try:
                j = r.json()
            except Exception:
                return False
            if not isinstance(j, dict):
                return False
            # 只要返回结构里有 content 就算 API 健康
            return "content" in j
        except Exception as e:
            LOG.debug("API 探测异常 %s: %s", api_base, e)
            return False

    # ---------- 缓存 ----------
    def _read_cache(self):
        if not self.cache_get:
            return None
        try:
            raw = self.cache_get(self.cfg.HOST_CACHE_KEY)
        except Exception:
            return None
        if not raw:
            return None
        try:
            if isinstance(raw, str):
                raw = json.loads(raw)
            if isinstance(raw, dict) and raw.get("api"):
                return raw
        except Exception:
            pass
        return None

    def _cache_fresh(self, c):
        ttl = int(getattr(self.cfg, "HOST_CACHE_TTL", 0) or 0)
        if ttl <= 0:
            return True
        return (time.time() - int(c.get("ts") or 0)) < ttl

    def _write_cache(self, site, api):
        if not self.cache_set:
            return
        try:
            self.cache_set(
                self.cfg.HOST_CACHE_KEY,
                json.dumps({
                    "site": site,
                    "api":  api,
                    "ts":   int(time.time()),
                }, ensure_ascii=False),
            )
        except Exception:
            pass

    # ---------- 主流程 ----------
    def resolve(self):
        cfg = self.cfg
        cached = self._read_cache()

        # 1) 缓存优先（用 API 判断）
        if cached and self._cache_fresh(cached):
            if self._api_ok(cached.get("api")):
                print(f"缓存有效: site={cached.get('site')}, api={cached.get('api')}")
                return cached.get("site", ""), cached.get("api", "")
            print(f"缓存失效: api={cached.get('api')}")

        # 2) 遍历种子对
        if not cfg.SEED_HOSTS:
            print("【错误】SEED_HOSTS 未配置")
            return "", ""

        for pair in cfg.SEED_HOSTS:
            site = (pair.get("site") or "").rstrip("/")
            api  = (pair.get("api")  or "").rstrip("/")
            if not api:
                continue
            if self._api_ok(api):
                self._write_cache(site, api)
                print(f"探测成功: site={site}, api={api}")
                return site, api
            else:
                print(f"探测失败: api={api}")

        # 3) 全部失败：优先用过期缓存，其次兜底第一个种子
        if cached:
            print(f"【警告】使用过期缓存: site={cached.get('site')}, api={cached.get('api')}")
            return cached.get("site", ""), cached.get("api", "")

        fallback = cfg.SEED_HOSTS[0]
        site = (fallback.get("site") or "").rstrip("/")
        api  = (fallback.get("api")  or "").rstrip("/")
        print(f"【警告】所有种子探测失败，回退到: site={site}, api={api}")
        return site, api


# ==================================================================
# ③ 主爬虫（保留原 91热爆 全部业务逻辑，仅替换域名初始化）
# ==================================================================
class Spider(BaseSpider):
    CONFIG = SiteConfig

    def __init__(self):
        # 兼容不同框架的构造函数签名
        try:
            super().__init__()
        except Exception:
            pass
        self.site = ""
        self.api = ""
        self.headers = {"User-Agent": self.CONFIG.USER_AGENT}

    # ---- 生命周期 ----
    def getName(self):
        return "91热爆·多域自愈版"

    def init(self, extend=""):
        resolver = ApiDomainResolver(
            self.CONFIG,
            cache_get=getattr(self, "getCache", None),
            cache_set=getattr(self, "setCache", None),
        )
        self.site, self.api = resolver.resolve()
        self.headers = {
            "User-Agent": self.CONFIG.USER_AGENT,
            "Referer":    (self.site or "") + "/",
            "Origin":     self.site or "",
        }
        print(f"使用站点: site={self.site}, api={self.api}")

    def isVideoFormat(self, url):
        return True

    def manualVideoCheck(self):
        return False

    def destroy(self):
        return None

    # ---- 内部请求 ----
    def _ok(self):
        if not self.api:
            self.init("")

    def _api_get(self, path, params=None):
        self._ok()
        try:
            r = requests.get(
                self.api + path,
                headers=self.headers,
                params=params or {},
                timeout=10,
                verify=False,
            )
            return r.json()
        except Exception as e:
            LOG.debug("API 请求异常 %s: %s", path, e)
            return {}

    # ---- 数据格式化 ----
    def _time(self, s):
        try:
            s = int(s or 0)
            h, m, sec = s // 3600, s % 3600 // 60, s % 60
            return "%02d:%02d:%02d" % (h, m, sec) if h else "%02d:%02d" % (m, sec)
        except Exception:
            return ""

    def _pic(self, i):
        return i.get("video_img") or i.get("screenshot1") or ""

    def _items(self, data):
        if isinstance(data, dict):
            data = (data.get("data")
                    or data.get("list_new", {}).get("data")
                    or data.get("list_hot", {}).get("data")
                    or [])
        return [{
            "vod_id":      str(i.get("video_id") or i.get("id") or ""),
            "vod_name":    i.get("title") or i.get("name") or "",
            "vod_pic":     self._pic(i),
            "vod_remarks": self._time(i.get("duration", 0)),
        } for i in (data or []) if (i.get("video_id") or i.get("id"))]

    # ---- 首页 ----
    def homeContent(self, filter):
        cls = [
            {"type_id": "all", "type_name": "推荐"},
            {"type_id": "new", "type_name": "最新"},
            {"type_id": "hot", "type_name": "热门"},
        ]
        try:
            c = self._api_get("/videos/classification", {
                "page": 1, "size": 50, "categories": 0, "sort": "post_date",
            }).get("content", [])
            cls += [{"type_id": str(i.get("category_id")),
                     "type_name": i.get("title", "")}
                    for i in c if i.get("category_id")]
        except Exception:
            pass

        data = self._api_get("/videos/index_byall", {
            "page": 1, "size": 24, "categories": 0, "sort": "post_date",
        }).get("content", {})

        return {
            "class": cls,
            "list":  self._items(data.get("list_new", {})),
        }

    def homeVideoContent(self):
        data = self._api_get("/videos/index_byall", {
            "page": 1, "size": 24, "categories": 0, "sort": "post_date",
        }).get("content", {})
        return {"list": self._items(data.get("list_new", {}))}

    # ---- 分类 ----
    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        if tid == "all":
            data = self._api_get("/videos/index", {"page": pg, "size": 24}).get("content", {})
        elif tid == "new":
            data = self._api_get("/videos/index_byall", {
                "page": pg, "size": 24, "categories": 0, "sort": "post_date",
            }).get("content", {}).get("list_new", {})
        elif tid == "hot":
            data = self._api_get("/videos/index_byall", {
                "page": pg, "size": 24, "categories": 0, "sort": "video_viewed",
            }).get("content", {}).get("list_hot", {})
        elif str(tid).startswith("tag_"):
            data = self._api_get("/videos/list_bytags", {
                "page": pg, "size": 24, "categories": 0,
                "sort": "post_date", "tags": str(tid)[4:],
            }).get("content", {})
        else:
            data = self._api_get("/videos/index", {
                "page": pg, "size": 24, "categories": tid, "sort": "post_date",
            }).get("content", {})

        return {
            "list":      self._items(data),
            "page":      pg,
            "pagecount": data.get("last_page", pg) if isinstance(data, dict) else pg,
            "limit":     24,
            "total":     data.get("total", 0) if isinstance(data, dict) else 0,
        }

    # ---- 详情 ----
    def detailContent(self, ids):
        vid = str(ids[0])
        c = self._api_get("/videos/detail", {"id": vid}).get("content", {})
        name = c.get("title") or vid
        pic  = c.get("video_img") or ""
        tags = ",".join([i.get("tag", "") for i in c.get("tags", []) if isinstance(i, dict)])
        cats = ",".join([i.get("title", "") for i in c.get("categories", []) if isinstance(i, dict)])

        return {"list": [{
            "vod_id":        vid,
            "vod_name":      name,
            "vod_pic":       pic,
            "type_name":     cats,
            "vod_year":      c.get("post_date", ""),
            "vod_area":      "",
            "vod_remarks":   self._time(c.get("duration", 0)),
            "vod_actor":     tags,
            "vod_director":  "",
            "vod_content":   name,
            "vod_play_from": "直连",
            "vod_play_url":  name + "$" + vid,
        }]}

    # ---- 搜索 ----
    def searchContent(self, key, quick, pg="1"):
        data = self._api_get("/videos/search", {
            "keyword": key, "page": int(pg or 1), "limit": 20,
        }).get("content", {})
        return {
            "list":      self._items(data),
            "page":      int(pg or 1),
            "pagecount": data.get("last_page", 1) if isinstance(data, dict) else 1,
            "limit":     20,
            "total":     data.get("total", 0) if isinstance(data, dict) else 0,
        }

    def searchContentPage(self, key, quick, pg):
        return self.searchContent(key, quick, pg)

    # ---- 播放 ----
    def playerContent(self, flag, id, vipFlags):
        vid = str(id).strip()
        if vid.isdigit():
            base = str((int(vid) // 1000) * 1000)
        else:
            base = vid[:-3] + "000" if len(vid) > 3 else vid

        url = ("https://delivery.douyinpaly.com/hls/contents/videos/"
               "%s/%s/%s.mp4/index.m3u8" % (base, vid, vid))

        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": {
                "User-Agent": self.CONFIG.USER_AGENT,
                "Referer":    (self.site or "") + "/",
                "Origin":     self.site or "",
            },
        }

    def localProxy(self, param):
        # 播放地址是 CDN 直链，不需要额外代理
        return None
