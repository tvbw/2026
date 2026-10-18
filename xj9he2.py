# -*- coding: utf-8 -*-
"""
BaseSpider：把工具模块串成完整生命周期。
子类只要覆盖 ZONE_SLUG，就完成"换区"。

约定接口（与框架一致）：
  init / getName / homeContent / homeVideoContent / categoryContent /
  detailContent / playerContent / localProxy / searchContent /
  action / liveContent / destroy / isVideoFormat / manualVideoCheck
"""

import re
import random
import urllib.parse

from . import config, net, parser, proxy, player

try:
    from base.spider import Spider as _FrameworkSpider
except ImportError:
    class _FrameworkSpider(object):
        def getCache(self, key): return None
        def setCache(self, key, value): return "fail"
        def delCache(self, key): return "fail"


class BaseSpider(_FrameworkSpider):
    # 子类唯一需要覆盖的类属性
    ZONE_SLUG = "z1"

    def __init__(self):
        super().__init__()
        self.zone_slug = self.ZONE_SLUG
        self.site = dict(config.SITES[self.zone_slug])  # 拷贝，换域名不影响全局
        self.opener = config.build_opener()

    # ---------- 生命周期 ----------
    def init(self, extend=""):
        config.sync_domain_pools(self.opener)
        return True

    def getName(self):
        return "蝴蝶影视·%s" % self.site.get("name", "")

    def homeContent(self, filter):
        return {
            "class": [
                {"type_name": s["n"], "type_id": str(s["v"])}
                for s in self.site.get("subs", [])
            ]
        }

    def homeVideoContent(self):
        return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        extend = extend if isinstance(extend, dict) else {}
        host = self.site["host"]
        mod = self.site.get("mod", "vod")
        default_sub = self.site["default"]

        cur_id = str(tid or extend.get("sub") or default_sub)
        page = int(pg) if pg else 1

        if page == 1:
            target_url = "%s/index.php/%s/type/id/%s.html" % (host, mod, cur_id)
        else:
            target_url = "%s/index.php/%s/type/id/%s/page/%s.html" % (host, mod, cur_id, page)

        res = net.fetch(self.opener, target_url, host)
        html_text = res.get("text", "")

        if not html_text or "404" in html_text or res.get("code") != 200:
            old_host = host
            new_host = self._switch_live_domain()
            if new_host != old_host:
                host = new_host
                target_url = target_url.replace(old_host, host)
                res = net.fetch(self.opener, target_url, host)
                html_text = res.get("text", "")

        vod_list = parser.parse_items(html_text, host, zone_slug=self.zone_slug)
        if not vod_list and page == 1:
            fb_url = "%s/index.php/%s/type/id/%s/page/1.html" % (host, mod, cur_id)
            fb_res = net.fetch(self.opener, fb_url, host)
            vod_list = parser.parse_items(fb_res.get("text", ""), host, zone_slug=self.zone_slug)

        total_pages = 1
        m_page = re.search(r"totalPages='(\d+)'", html_text)
        if m_page:
            try:
                total_pages = int(m_page.group(1))
            except Exception:
                total_pages = 1

        return {
            "page": page,
            "pagecount": total_pages if total_pages > 1 else (999 if len(vod_list) >= 10 else 1),
            "limit": len(vod_list) if vod_list else 20,
            "total": total_pages * 20 if total_pages > 1 else 999,
            "list": vod_list,
        }

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) else str(ids)
        title = "高清正片"
        play_url = ""
        host = self.site["host"]

        if "@@" in raw_id:
            parts = raw_id.split("@@")
            title = urllib.parse.unquote(parts[0])
            play_url = urllib.parse.unquote(parts[1])
            if len(parts) > 2:
                host = urllib.parse.unquote(parts[2])
        else:
            play_url = raw_id

        desc = (
            "【🔥 官方交流群: %s】\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "• 播放模式: 零嗅探秒播\n"
            "• 片名: %s\n"
            "• 提示: 视频来源于源站集群，支持拖拽倍速。"
        ) % (config.TG_GROUP, title)

        return {
            "list": [{
                "vod_id": raw_id,
                "vod_name": title,
                "vod_pic": "",
                "vod_actor": config.BRAND_ACTOR,
                "vod_director": config.BRAND_DIRECTOR,
                "vod_remarks": "直出正片",
                "vod_content": desc,
                "vod_play_from": "官方直链",
                "vod_play_url": "正片$%s@@%s" % (play_url, host),
            }]
        }

    def playerContent(self, flag, id, vipFlags):
        return player.handle(flag, id, self.site["host"], self.opener)

    def localProxy(self, params):
        return proxy.handle(params, self.opener, self.site["host"])

    def searchContent(self, key, quick, pg="1"):
        return {"page": 1, "pagecount": 1, "limit": 0, "total": 0, "list": []}

    def action(self, action):
        return {"msg": "运行正常"}

    def liveContent(self):
        return ""

    def destroy(self):
        pass

    def isVideoFormat(self, url):
        low = (url or "").lower()
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".mkv", ".avi", ".ts", ".mpd", "index.png"))

    def manualVideoCheck(self):
        return False

    # ---------- 内部 ----------
    def _switch_live_domain(self):
        """当前 host 失效时，从该区的域名池里随机换一个"""
        pool = config.get_domain_pool(self.zone_slug)
        if not pool:
            config.sync_domain_pools(self.opener, force=True)
            pool = config.get_domain_pool(self.zone_slug)
        if pool:
            cur_host = self.site["host"]
            candidates = [h for h in pool if h != cur_host]
            if candidates:
                new_host = random.choice(candidates)
                self.site["host"] = new_host
                return new_host
        return self.site["host"]
