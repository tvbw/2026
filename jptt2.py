# -*- coding: utf-8 -*-
"""
禁片天堂 TVBox spider —— 按可用 xbpq 规则重写
对齐点：
1) 请求头完全照搬可用配置（Android 手机 UA + Origin/Referer），这是之前全空的最大嫌疑
2) 分类URL规则: /{cateId}?idx={pg}&sort={by}，含 /factory 发行商（原py被删除的分类）
3) 列表卡片: div.col.oneVideo, 标题 h5||h3, 图 img@src, 副标题 p
4) folder入口: 分类(tag)/女优(actor_list)/发行商(factory)/私藏连播(video_list) 一级页 + 私藏连播二级 .div_v_list_item(data-href)
5) 播放: <video>块内 <source> 的 src 属性(兼容 data-src / 转义\\/ / JSON内嵌url)
6) 搜索: /search?kw=..&idx=..&sort=2
7) 保留 extend 可配 host/cookie/proxy/plp，多镜像自动切换，调试信息 self.last_error
"""
import re
import sys
import json
import html
from urllib.parse import quote

import requests
from lxml import etree

sys.path.append('..')
from base.spider import Spider as BaseSpider


class Spider(BaseSpider):

    def getName(self):
        return "禁片天堂-xbpq对齐版"

    def init(self, extend):
        try:
            ext = json.loads(extend)
        except Exception:
            ext = {}
        if not isinstance(ext, dict):
            ext = {}
        self.proxy = ext.get('proxy', {}) or {}
        self.plp = ext.get('plp', '') or ''
        self.cookie = ext.get('cookie', '') or ''
        # 可在 extend 覆盖/追加镜像域名
        self.hosts = []
        h = (ext.get('host', '') or '').rstrip('/')
        if h:
            self.hosts.append(h)
        self.hosts += [
            'https://jptttvcity7.cc',
        ]
        self.host = self.hosts[0]
        self.debug = bool(ext.get('debug', False))
        self.last_error = ''
        # ==== 与可用 xbpq 配置完全一致的请求头 ====
        self.ua = ("Mozilla/5.0 (Linux; Android 15; 2407FRK8EC Build/AP3A.240617.008; wv) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
                   "Chrome/128.0.6613.127 Mobile Safari/537.36")
        self.headers = {
            "User-Agent": self.ua,
            "Origin": self.host,
            "Referer": self.host + "/",
        }
        if self.cookie:
            self.headers["Cookie"] = self.cookie

    # ---------------- 请求（带镜像切换与验证页识别） ----------------
    def fetch(self, url):
        last = None
        for host in self.hosts:
            try:
                real_url = url
                for old in self.hosts:
                    if old and old in url:
                        real_url = url.replace(old, host)
                        break
                headers = dict(self.headers)
                headers["Origin"] = host
                headers["Referer"] = host + "/"
                rsp = requests.get(real_url, headers=headers, proxies=self.proxy, timeout=20)
                text = rsp.text or ''
                challenge = ('cf-chl' in text) or ('Just a moment' in text) or ('challenge-platform' in text)
                if rsp.status_code == 200 and not challenge and '<' in text:
                    self.host = host
                    return rsp
                last = rsp
            except Exception as e:
                self.last_error = f'fetch {host} error: {e}'
                last = None
        return last

    def _clean(self, s):
        return re.sub(r"\s+", " ", html.unescape((s or '').strip()))

    def _abs(self, url):
        if not url:
            return ''
        if url.startswith('http'):
            return url
        if url.startswith('/'):
            return self.host + url
        return self.host + '/' + url

    def _clickable(self, name, href):
        name = self._clean(name)
        href = (href or '').strip()
        if not name or not href:
            return ''
        target = json.dumps({"id": href, "name": name}, ensure_ascii=False)
        return f"[a=cr:{target}/]{name}[/a]"

    # ================= 首页 =================
    def homeContent(self, filter):
        classes = [
            {"type_name": "最新发行", "type_id": "list"},
            {"type_name": "热门影片主题", "type_id": "tag"},
            {"type_name": "私藏连播", "type_id": "video_list"},
            {"type_name": "热门女优", "type_id": "actor_list"},
            {"type_name": "发行商", "type_id": "factory"},
        ]
        filters = {
            "list": [{"key": "by", "name": "排序", "value": [
                {"n": "最新发行", "v": "2"}, {"n": "最近更新", "v": "1"},
                {"n": "今日人气🔥", "v": "3"}, {"n": "本周人气", "v": "4"},
                {"n": "本月人气", "v": "5"}, {"n": "总人气", "v": "6"},
            ]}],
            "tag": [{"key": "by", "name": "排序", "value": [
                {"n": "热门搜寻", "v": "2"}, {"n": "最多影片", "v": "3"},
            ]}],
        }
        return {"class": classes, "filters": filters, "list": []}

    def homeVideoContent(self):
        return {"list": []}

    # ================= 列表解析（对齐 xbpq “数组/标题/图片/副标题/链接”） =================
    def _parse_videos(self, root):
        """普通视频卡片页: list / search / tag_list?tid= / tag_list?fid= / actor?id= """
        videos = []
        seen = set()
        for node in root.xpath('//div[contains(@class,"oneVideo")]'):
            try:
                title = ''
                for xp in ['.//h5/text()', './/h3/text()', './/a/@title', './/img/@alt']:
                    nodes = node.xpath(xp)
                    if nodes:
                        title = self._clean(nodes[0])
                        if title:
                            break
                img = ''
                for attr in ['data-src', 'src']:
                    nodes = node.xpath(f'.//img/@{attr}')
                    if nodes:
                        img = self._abs(nodes[0])
                        break
                remark = ''
                for p in node.xpath('.//p'):
                    t = self._clean(''.join(p.xpath('.//text()')))
                    if t:
                        remark = t
                        break
                href = ''
                nodes = node.xpath('.//div[contains(@class,"oneVideo-top")]/@data-href')
                if nodes:
                    href = nodes[0]
                if not href:
                    nodes = node.xpath('.//a/@href')
                    if nodes:
                        href = nodes[0]
                if not (title and href):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                is_folder = href.startswith(('/video_list_info', '/tag_list', '/actor?id=', '/tags/'))
                videos.append({
                    "vod_id": href,
                    "vod_name": title,
                    "vod_pic": f'{self.plp}{img}',
                    "vod_remarks": remark,
                    "vod_tag": "folder" if is_folder else "",
                })
            except Exception:
                continue
        return videos

    def _parse_folders(self, root):
        """一级 folder 页: 分类(tag) / 女优(actor_list) / 发行商(factory) / 私藏连播(video_list)
        xbpq规则: 同一数组 div.col.oneVideo; 标题 h5||h3; 图 img@src(发行商用占位图兜底); 副标题 p 或 .vdo_lst_mask"""
        items = []
        seen = set()
        for node in root.xpath('//div[contains(@class,"oneVideo")]'):
            try:
                title = ''
                for xp in ['.//h5/text()', './/h3/text()', './/a/@title']:
                    nodes = node.xpath(xp)
                    if nodes:
                        title = self._clean(nodes[0])
                        if title:
                            break
                img = ''
                for attr in ['data-src', 'src']:
                    nodes = node.xpath(f'.//img/@{attr}')
                    if nodes:
                        img = self._abs(nodes[0])
                        break
                if not img:
                    img = 'https://pic.616pic.com/ys_b_img/00/16/04/tSv1MBgqFi.jpg'  # xbpq 发行商占位图
                remark = ''
                mask = node.xpath('.//div[contains(@class,"vdo_lst_mask")]//text()')
                if mask:
                    raw = self._clean(' '.join([t for t in mask if t and t.strip()]))
                    m = re.search(r'(\d+)\s*部', raw)
                    if m:
                        remark = f"{m.group(1)}部"
                if not remark:
                    for p in node.xpath('.//p'):
                        t = self._clean(''.join(p.xpath('.//text()')))
                        if t:
                            remark = t
                            break
                href = ''
                nodes = node.xpath('.//div[contains(@class,"oneVideo-top")]/@data-href | .//a/@href')
                if nodes:
                    href = nodes[0]
                if not (title and href):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                items.append({
                    "vod_id": href,
                    "vod_name": title,
                    "vod_pic": f'{self.plp}{img}',
                    "vod_remarks": remark,
                    "vod_tag": "folder",
                })
            except Exception:
                continue
        return items

    def _parse_series_items(self, root):
        """私藏连播二级: .div_v_list_item, 标题 h3, 链接 data-href"""
        items = []
        seen = set()
        for node in root.xpath('//div[contains(@class,"div_v_list_item")]'):
            try:
                href_nodes = node.xpath('.//*[@data-href]/@data-href')
                href = href_nodes[0] if href_nodes else ''
                title = ''
                nodes = node.xpath('.//h3//text()')
                if nodes:
                    title = self._clean(''.join(nodes))
                if not title:
                    nodes = node.xpath('.//a/@title | .//img/@alt')
                    if nodes:
                        title = self._clean(nodes[0])
                img = ''
                for attr in ['data-src', 'src']:
                    nodes = node.xpath(f'.//img/@{attr}')
                    if nodes:
                        img = self._abs(nodes[0])
                        break
                remark = ''
                for p in node.xpath('.//p'):
                    t = self._clean(''.join(p.xpath('.//text()')))
                    if t:
                        remark = t
                        break
                if not (title and href):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                items.append({
                    "vod_id": href,
                    "vod_name": title,
                    "vod_pic": f'{self.plp}{img}',
                    "vod_remarks": remark,
                })
            except Exception:
                continue
        return items

    # ================= 分类页 =================
    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if not isinstance(extend, dict):
            extend = {}
        by = (extend.get('by') or extend.get('order') or '').strip()

        base = tid.lstrip('/')
        if base in ('list', 'tag'):
            # /list?idx={pg}&sort={by}  sort默认2；/tag?idx={pg}&sort={by}  sort默认2
            sort = by or '2'
            url = f"{self.host}/{base}?idx={pg}&sort={sort}"
            mode = 'videos'
        elif base == 'actor_list':
            url = f"{self.host}/actor_list?idx={pg}" + (f"&sort={by}" if by else '')
            mode = 'folders'
        elif base == 'factory':
            url = f"{self.host}/factory?idx={pg}" + (f"&sort={by}" if by else '')
            mode = 'folders'
        elif base == 'video_list':
            url = f"{self.host}/video_list?idx={pg}"
            mode = 'folders'
        elif tid.startswith('/video_list_info') or tid.startswith('video_list_info'):
            # 私藏连播二级，点击时 folder vod_id 可能已被追加了参数
            url = self._abs(tid)
            mode = 'series'
        elif tid.startswith('/list') or tid.startswith('list?'):
            url = self._abs(tid)
            mode = 'videos'
        else:
            # folder 二级链接: /tag_list?tid= /tag_list?fid= /actor?id= /tags/...
            # xbpq: 链接 + &idx={catePg}&sort={by}
            link = tid if tid.startswith('/') else '/' + tid
            sep = '&' if '?' in link else '?'
            url = f"{self.host}{link}{sep}idx={pg}" + (f"&sort={by or '2'}" if 'sort=' not in link else '')
            if '/tag_list' in link or '/actor?id=' in link:
                mode = 'videos'
            else:
                mode = 'videos'

        rsp = self.fetch(url)
        if rsp is None or rsp.status_code != 200:
            self.last_error = f'categoryContent HTTP失败: {url}'
            return {"list": [], "page": pg, "pagecount": 0, "limit": 0, "total": 0}
        root = etree.HTML(rsp.text)
        if root is None:
            self.last_error = f'categoryContent HTML解析失败: {url}'
            return {"list": [], "page": pg, "pagecount": 0, "limit": 0, "total": 0}

        if mode == 'folders':
            vodList = self._parse_folders(root)
        elif mode == 'series':
            vodList = self._parse_series_items(root)
        else:
            vodList = self._parse_videos(root)

        return {"list": vodList, "page": pg, "pagecount": 9999, "limit": 90, "total": 999999}

    # ================= 详情 =================
    def extractVideoUrl(self, html_text):
        try:
            if not html_text:
                return ''
            # 0) 播放器配置 JSON 内嵌 "url":"...m3u8"
            for m in re.finditer(r'"url"\s*:\s*"([^"]+?\.m3u8[^"]*)"', html_text):
                u = m.group(1).replace('\\/', '/').strip()
                if u:
                    return ('https:' + u) if u.startswith('//') else u
            # 1) 与 xbpq 一致: <video>块内 <source> 的 src 属性（兼容 data-src / 单双引号 / 转义）
            block = html_text
            mv = re.search(r'<video.*?</video>', html_text, re.S)
            if mv:
                block = mv.group(0)
            m = re.search(r'<source[^>]+?(?:data-src|src)=["\']([^"\']+)["\']', block)
            if not m:
                m = re.search(r'<source[^>]+?(?:data-src|src)=["\']([^"\']+)["\']', html_text)
            if not m:
                m = re.search(r'videoSourceUrl\s*=\s*["\']([^"\']+)["\']', html_text)
            if m:
                u = m.group(1).strip().replace('\\/', '/')
            else:
                m2 = re.search(r"(?:https?:)?//[^\"'\s\\]+?\.m3u8[^\"'\s\\]*", html_text)
                u = m2.group(0).strip().replace('\\/', '/') if m2 else ''
            if u and u.startswith('//'):
                u = 'https:' + u
            return u
        except Exception:
            return ''

    def detailContent(self, array):
        try:
            tid = array[0]
            url = tid if tid.startswith('http') else self._abs(tid)
            rsp = self.fetch(url)
            if rsp is None or rsp.status_code != 200:
                return {"list": []}
            root = etree.HTML(rsp.text)
            if root is None:
                return {"list": []}

            # 标题
            title = ''
            nodes = root.xpath('//h1//text()')
            if nodes:
                title = self._clean(''.join(nodes))
            if not title:
                nodes = root.xpath('//meta[@property="og:title"]/@content')
                if nodes:
                    title = self._clean(nodes[0])
            if not title:
                nodes = root.xpath('//title/text()')
                if nodes:
                    title = self._clean(nodes[0].split('｜')[0])

            # 海报: og:image → video poster → 首图
            pic = ''
            nodes = root.xpath('//meta[@property="og:image"]/@content')
            if nodes:
                pic = self._abs(nodes[0])
            if not pic:
                nodes = root.xpath('//video/@poster')
                if nodes:
                    pic = self._abs(nodes[0])
            if not pic:
                nodes = root.xpath('//img/@src')
                if nodes:
                    pic = self._abs(nodes[0])

            # xbpq: 影片类型 div[style="margin-bottom: 16px;"]
            type_text = ''
            nodes = root.xpath('//div[@style="margin-bottom: 16px;"]//text()')
            if nodes:
                type_text = self._clean(' '.join([t for t in nodes if t.strip()]))

            # xbpq: 年代 div.video-meta span
            year = ''
            nodes = root.xpath('//div[contains(@class,"video-meta")]//span//text()')
            if nodes:
                year = self._clean(' '.join([t for t in nodes if t.strip()]))

            # xbpq: 主演 div.video-meta a
            actors = []
            for a in root.xpath('//div[contains(@class,"video-meta")]//a[@href]'):
                name = self._clean(''.join(a.xpath('.//text()')))
                href = a.get('href') or ''
                if name:
                    actors.append(self._clickable(name, href) if href.startswith('/') else name)
            if actors:
                seen = set(); uniq = []
                for t in actors:
                    if t not in seen:
                        uniq.append(t); seen.add(t)
                vod_actor = ' '.join(uniq)
            else:
                vod_actor = ''

            # 简介: 首个有意义的 p（对齐 xbpq 简介 p:p->text）
            desc = ''
            for p in root.xpath('//p'):
                t = self._clean(''.join(p.xpath('.//text()')))
                if len(t) >= 10:
                    desc = t
                    break
            if not desc:
                nodes = root.xpath('//meta[@property="og:description"]/@content | //meta[@name="description"]/@content')
                if nodes:
                    desc = self._clean(nodes[0])
            if not desc:
                desc = title

            # 可点击标签（info-list 標籤）
            tags = []
            for a in root.xpath('//div[contains(@class,"info-list")]//li[contains(.,"標籤")]//a[@href]'):
                name = self._clean(''.join(a.xpath('.//text()')))
                href = a.get('href') or ''
                if name and href:
                    tags.append(self._clickable(name, href))
            tag_text = ' '.join(tags)

            # 厂商（info-list 廠商/發行商）
            pubs = []
            for a in root.xpath('//div[contains(@class,"info-list")]//li[(contains(.,"廠商") or contains(.,"發行商") or contains(.,"系列"))]//a[@href]'):
                name = self._clean(''.join(a.xpath('.//text()')))
                href = a.get('href') or ''
                if name and href and name not in ("更多發行商", "發行商一覽"):
                    pubs.append(self._clickable(name, href))
            vod_pub = ' '.join(dict.fromkeys(pubs))

            # 番号
            code = ''
            m = re.search(r'([A-Za-z]{2,}[ -]?\d{3,})', title or '')
            if m:
                code = m.group(1)

            play_url = self.extractVideoUrl(rsp.text)

            content_parts = []
            if type_text:
                content_parts.append(type_text)
            if tag_text:
                content_parts.append(tag_text)
            if desc:
                content_parts.append(desc)
            vod_content = ' '.join([p for p in content_parts if p]).strip() or (title or '')

            vod = {
                "vod_id": tid,
                "vod_name": title or '未知标题',
                "vod_pic": f'{self.plp}{pic}',
                "vod_content": vod_content,
                "vod_play_from": "注意身体",
                "vod_play_url": f"多看少打卡${play_url}",
                "vod_remarks": code,
                "vod_actor": vod_actor,
                "vod_director": vod_pub,
                "vod_pub": vod_pub,
                "vod_year": year,
            }
            return {"list": [vod]}
        except Exception as e:
            self.last_error = f'detailContent error: {e}'
            return {"list": []}

    # ================= 搜索 =================
    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg)
        except Exception:
            page = 1
        try:
            kw = quote(self._clean(key))
            url = f"{self.host}/search?kw={kw}&idx={page}&sort=2"
            rsp = self.fetch(url)
            if rsp is None or rsp.status_code != 200:
                return {"list": []}
            root = etree.HTML(rsp.text)
            if root is None:
                return {"list": []}
            return {"list": self._parse_videos(root)}
        except Exception:
            return {"list": []}

    # ================= 播放 =================
    def playerContent(self, flag, id, vipFlags):
        result = {}
        if flag == "注意身体":
            try:
                if id.startswith('http') and '.m3u8' in id:
                    result["parse"] = 0
                    result["playUrl"] = ''
                    result["url"] = f'{self.plp}{id}'
                else:
                    url = id if id.startswith('http') else self._abs(id)
                    rsp = self.fetch(url)
                    play_url = self.extractVideoUrl(rsp.text) if rsp is not None else ''
                    result["parse"] = 0
                    result["playUrl"] = ''
                    result["url"] = self.plp + play_url
            except Exception:
                result["parse"] = 0
                result["playUrl"] = ''
                result["url"] = ''
        result["header"] = {
            "User-Agent": self.ua,
            "Referer": self.host + "/",
            "Origin": self.host,
        }
        return result

    def isVideoFormat(self, url):
        return any(ext in (url or '') for ext in ['.m3u8', '.mp4'])

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return None
