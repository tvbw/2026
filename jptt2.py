# -*- coding: utf-8 -*-
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
    """
    禁片天堂适配（修复增强版）
    修复点：
    1) 支持多镜像域名自动切换 + extend 可配置 host/cookie，应对域名轮换与 Cloudflare
    2) 详情海报增加 og:image / 首图 多级兜底（video 标签为 JS 插入时不再取不到海报）
    3) 播放地址解析增强：兼容 https:\\/\\/ 转义、JSON 内嵌 "url":"...m3u8" 等格式
    4) /list 排序筛选 extend['order'] 真正生效
    5) 解析失败时保留调试信息（self.last_error），便于定位
    """

    def getName(self):
        return "禁片天堂适配-修复版"

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
        # 可通过 extend 覆盖主域名；默认内置一组镜像，逐个尝试
        self.hosts = []
        h = ext.get('host', '') or ''
        if h:
            self.hosts.append(h.rstrip('/'))
        self.hosts += [
            'https://jptttvcity7.cc',
        ]
        self.host = self.hosts[0]
        self.debug = bool(ext.get('debug', False))
        self.last_error = ''
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Referer": self.host + "/",
            "Origin": self.host,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9"
        }
        if self.cookie:
            self.headers["Cookie"] = self.cookie

    def fetch(self, url):
        """带镜像切换的请求：状态码非 200 / 被 Cloudflare 挑战时尝试下一个域名。"""
        last = None
        for host in self.hosts:
            try:
                real_url = url
                for old in self.hosts:
                    if old in url:
                        real_url = url.replace(old, host)
                        break
                headers = dict(self.headers)
                headers["Referer"] = host + "/"
                headers["Origin"] = host
                rsp = requests.get(real_url, headers=headers, proxies=self.proxy, timeout=20)
                ct = rsp.headers.get('Content-Type', '')
                text = rsp.text or ''
                # Cloudflare 挑战页 / JS 验证页特征：没有业务 HTML 容器
                looks_challenge = ('cf-chl' in text) or ('Just a moment' in text) or ('challenge-platform' in text)
                if rsp.status_code == 200 and not looks_challenge and ('<' in text):
                    self.host = host
                    return rsp
                last = rsp
            except Exception as e:
                self.last_error = f'fetch error {host}: {e}'
                last = None
                continue
        if last is not None:
            return last
        return None

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

    def homeContent(self, filter):
        classes = [
            {"type_name": "最新发行", "type_id": "/list?sort=2"},
            {"type_name": "热门影片主题", "type_id": "/tag?idx=1&sort=2"},
            {"type_name": "私藏连播", "type_id": "/video_list?idx=1"},
            {"type_name": "热门女优", "type_id": "/actor_list"}
        ]
        filters = {
            "/list?sort=2": [{"key": "order", "name": "排序", "value": [
                {"n": "最新发行", "v": "2"}, {"n": "今日热门", "v": "3"}, {"n": "本周热门", "v": "4"}, {"n": "本月热门", "v": "5"}
            ]}],
            "/tag?idx=1&sort=2": [{"key": "order", "name": "排序", "value": [
                {"n": "热门搜寻", "v": "2"}, {"n": "最多影片", "v": "3"}
            ]}],
            "/video_list?idx=1": [{"key": "order", "name": "排序", "value": [
                {"n": "最新发行", "v": "2"}
            ]}],
            "/actor_list": []
        }
        return {"class": classes, "filters": filters, "list": []}

    def homeVideoContent(self):
        return {"list": []}

    def _parse_cards(self, root):
        from urllib.parse import urlparse
        videos = []
        seen = set()
        for node in root.xpath('//div[contains(@class,"oneVideo")] | //article | //li[contains(@class, "section-content__item")]'):
            try:
                name = ''
                name_elements = node.xpath('.//h3/text()')
                if name_elements:
                    name = self._clean(name_elements[0])
                if not name:
                    a_title = node.xpath('.//a/@title')
                    if a_title:
                        name = self._clean(a_title[0])
                if not name:
                    a_text = node.xpath('.//a/text()')
                    if a_text:
                        name = self._clean(''.join([t for t in a_text if self._clean(t)]))
                if not name:
                    alt = node.xpath('.//img/@alt')
                    if alt:
                        name = self._clean(alt[0])
                img = ''
                for attr in ['data-src', 'data-original', 'src']:
                    img_elements = node.xpath(f'.//img/@{attr}')
                    if img_elements:
                        img = self._abs(img_elements[0])
                        break
                desc = ''
                dur = node.xpath('.//p[contains(@class,"p_duration")]/text()')
                if dur:
                    desc = self._clean(dur[0])
                else:
                    mask_texts = node.xpath('.//div[contains(@class,"vdo_lst_mask")]//text()')
                    if mask_texts:
                        raw = self._clean(' '.join([t for t in mask_texts if t and t.strip()]))
                        mcnt = re.search(r'(\d+)\s*部', raw)
                        if mcnt:
                            desc = f"{mcnt.group(1)}部"
                if not desc:
                    eye = node.xpath('.//i[contains(@class,"fa-eye")]/following-sibling::span/text()')
                    date = node.xpath('.//time/text()')
                    d_eye = self._clean(eye[0]) if eye else ''
                    d_date = self._clean(date[0]) if date else ''
                    if d_eye:
                        desc += f"👁 {d_eye} "
                    if d_date:
                        desc += f"📅 {d_date}"
                    desc = desc.strip()
                if not dur and node.xpath('ancestor-or-self::div[contains(@class,"type-item")]'):
                    pass
                unc_in_node = node.xpath('.//a[contains(text(),"無碼") or contains(text(),"無修正")] | .//*[contains(text(),"無碼") or contains(text(),"無修正")]')
                if dur and unc_in_node:
                    desc = (desc + ' ' + '无码').strip()
                link = ''
                data_href = node.xpath('.//div[contains(@class,"oneVideo-top")]/@data-href')
                if data_href:
                    link = data_href[0]
                else:
                    link_elements = node.xpath('.//div[contains(@class,"oneVideo-top")]//a/@href | .//a/@href')
                    if link_elements:
                        link = link_elements[0]
                if not (name and img and link):
                    continue
                norm = link
                try:
                    if link.startswith('http'):
                        p = urlparse(link)
                        norm = p.path
                        if p.query:
                            norm_q = []
                            for kv in p.query.split('&'):
                                if kv.startswith(('list=', 'kw=', 'fid=', 'tid=')):
                                    norm_q.append(kv)
                            if norm_q:
                                norm += '?' + '&'.join(sorted(norm_q))
                except Exception:
                    pass
                if norm in seen:
                    continue
                seen.add(norm)
                is_folder = (
                    str(link).startswith('/video_list_info') or
                    str(link).startswith('/tag_list') or
                    str(link).startswith('/actor?id=') or
                    str(link).startswith('/tags/')
                )
                videos.append({
                    "vod_name": name,
                    "vod_pic": f'{self.plp}{img}',
                    "vod_remarks": desc,
                    "vod_id": link,
                    "vod_tag": ("folder" if is_folder else "")
                })
            except Exception:
                continue
        return videos

    def _sort_by_date(self, items):
        def parse_date(s):
            if not s:
                return ''
            m = re.search(r'(\d{4}-\d{2}-\d{2})', s)
            return m.group(1) if m else ''
        try:
            return sorted(items, key=lambda x: parse_date(x.get('vod_remarks', '')), reverse=True)
        except Exception:
            return items

    # ------------------ 分类页 ------------------
    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if extend is None:
            extend = {}

        url = ''
        if tid.startswith('/list'):
            sort = extend.get('order', '2') or '2'   # 修复：排序筛选真正生效
            if pg == 1:
                url = f"{self.host}/list?sort={sort}"
            else:
                url = f"{self.host}/list?idx={pg}&sort={sort}"
        elif tid.startswith('/tag_list?tid='):
            m = re.search(r'tag_list\?tid=(\d+)', tid)
            t = m.group(1) if m else ''
            url = f"{self.host}/tag_list?tid={t}&idx={pg}"
        elif tid.startswith('/tag?'):
            sort = extend.get('order', '2') or '2'
            url = f"{self.host}/tag?idx={pg}&sort={sort}"
        elif tid.startswith('/video_list_info'):
            url = f"{self.host}{tid}"
        elif tid.startswith('/video_list'):
            m = re.search(r'idx=(\d+)', tid)
            idx = m.group(1) if m else str(pg)
            if str(idx) == '1' or pg == 1:
                url = f"{self.host}/video_list"
            else:
                url = f"{self.host}/video_list?idx={idx}"
        elif tid.startswith('/actor_list'):
            url = f"{self.host}/actor_list" + (f"?idx={pg}" if pg > 1 else '')
        elif tid.startswith('/actor?id='):
            url = f"{self.host}{tid}" + (f"&idx={pg}" if pg > 1 else '')
        elif tid.startswith('/tag_list?fid='):
            m = re.search(r'tag_list\?fid=(\d+)', tid)
            fid = m.group(1) if m else ''
            url = f"{self.host}/tag_list?fid={fid}" if pg == 1 else f"{self.host}/tag_list?fid={fid}&idx={pg}"
        elif tid.startswith('factory_click_'):
            base = tid.replace('factory_click_', '')
            m = re.search(r'tag_list\?fid=(\d+)', base)
            fid = m.group(1) if m else ''
            url = f"{self.host}/tag_list?fid={fid}" if pg == 1 else f"{self.host}/tag_list?fid={fid}&idx={pg}"
            rsp = self.fetch(url)
            if rsp is None or rsp.status_code != 200:
                return {"list": [], "page": pg, "pagecount": 0, "limit": 0, "total": 0}
            root = etree.HTML(rsp.text)
            vodList = self._sort_by_date(self._parse_cards(root))
            return {"list": vodList, "page": pg, "pagecount": 9999, "limit": 90, "total": 999999}
        else:
            url = self._abs(tid)
            if pg > 1:
                sep = '&' if '?' in url else '?'
                url = f"{url}{sep}page={pg}"

        rsp = self.fetch(url)
        if rsp is None or rsp.status_code != 200:
            self.last_error = f'categoryContent fail: {url}'
            return {"list": [], "page": pg, "pagecount": 0, "limit": 0, "total": 0}
        root = etree.HTML(rsp.text)
        if root is None:
            return {"list": [], "page": pg, "pagecount": 0, "limit": 0, "total": 0}
        vodList = []

        try:
            if '/list' in url:
                vodList = self._parse_cards(root)
            elif '/tag?idx=' in url:
                for a in root.xpath('//div[contains(@class,"type-item")]//a[@href]'):
                    href = a.get('href')
                    title_nodes = a.xpath('.//h5/text()') or a.xpath('.//h4/text()')
                    title = self._clean(''.join(title_nodes))
                    img = ''
                    for attr in ['data-src', 'data-original', 'src']:
                        nodes = a.xpath(f'.//img/@{attr}')
                        if nodes:
                            img = self._abs(nodes[0])
                            break
                    if href and title:
                        vodList.append({
                            "vod_id": href, "vod_name": title,
                            "vod_pic": f'{self.plp}{img}',
                            "vod_remarks": self._clean(''.join(a.xpath('.//p/text()'))),
                            "vod_tag": "folder"
                        })
            elif '/actor_list' in url:
                for a in root.xpath('//a[starts-with(@href, "/actor?id=")][not(ancestor::*[contains(@class,"nav-dropdown") or contains(@class,"nav-top") or contains(@class,"navbar") or contains(@class,"footer")])]'):
                    href = a.get('href')
                    name = self._clean(''.join(a.xpath('.//text()')))
                    img = ''
                    for attr in ['data-src', 'data-original', 'src']:
                        nodes = a.xpath(f'.//img/@{attr}')
                        if nodes:
                            img = self._abs(nodes[0])
                            break
                    if href and name:
                        vodList.append({
                            "vod_id": href, "vod_name": name,
                            "vod_pic": f'{self.plp}{img}',
                            "vod_remarks": "", "vod_tag": "folder"
                        })
            elif '/actor?id=' in url:
                vodList = self._sort_by_date(self._parse_cards(root))
            elif '/tag_list?tid=' in url:
                vodList = self._sort_by_date(self._parse_cards(root))
            elif '/video_list_info' in url:
                for item in root.xpath('//div[contains(@class,"div_v_list_item")]'):
                    href_nodes = item.xpath('.//*[@data-href]/@data-href')
                    href = href_nodes[0] if href_nodes else ''
                    title_nodes = item.xpath('.//h3[contains(@class,"h3_item_title")]/text()')
                    title = self._clean(''.join(title_nodes))
                    img = ''
                    for attr in ['data-src', 'data-original', 'src']:
                        nodes = item.xpath(f'.//img/@{attr}')
                        if nodes:
                            img = self._abs(nodes[0])
                            break
                    remarks = ''
                    eye_nodes = item.xpath('.//i[contains(@class,"fa-eye")]/following-sibling::span/text()')
                    date_nodes = item.xpath('.//time/text()')
                    if eye_nodes:
                        remarks = f"👁 {self._clean(eye_nodes[0])}"
                    if date_nodes:
                        d = self._clean(date_nodes[0])
                        remarks = (remarks + (" " if remarks else "") + f"📅 {d}").strip()
                    if href and title:
                        vodList.append({
                            "vod_id": href, "vod_name": title,
                            "vod_pic": f'{self.plp}{img}',
                            "vod_remarks": remarks
                        })
                vodList = self._sort_by_date(vodList)
            elif '/tag_list?fid=' in url:
                vodList = self._sort_by_date(self._parse_cards(root))
            else:
                vodList = self._parse_cards(root)
        except Exception as e:
            self.last_error = f'parse error {url}: {e}'

        return {"list": vodList, "page": pg, "pagecount": 9999, "limit": 90, "total": 999999}

    # ------------------ 详情与播放 ------------------
    def extractVideoUrl(self, html_text):
        try:
            if not html_text:
                return ''
            # 0) JSON 内嵌 "url":"...m3u8"（常见于播放器配置）
            for m in re.finditer(r'"url"\s*:\s*"([^"]+?\.m3u8[^"]*)"', html_text):
                u = m.group(1).replace('\\/', '/').strip()
                if u:
                    if u.startswith('//'):
                        u = 'https:' + u
                    if u.startswith('http'):
                        return u
            # 1) <source data-src / src>（单双引号都兼容）
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
            pass
        return ''

    def detailContent(self, array):
        try:
            tid = array[0]
            url = tid if tid.startswith('http') else f"{self.host}{tid}"
            rsp = self.fetch(url)
            if rsp is None or rsp.status_code != 200:
                return {"list": []}
            root = etree.HTML(rsp.text)
            if root is None:
                return {"list": []}

            title_nodes = root.xpath('//h1[@class="h1_title"]/text()')
            title = self._clean(title_nodes[0]) if title_nodes else ''
            if not title:
                tnodes = root.xpath('//title/text()')
                if tnodes:
                    title = self._clean(tnodes[0].split('｜')[0])
                if not title:
                    alt_nodes = root.xpath('//img/@alt')
                    if alt_nodes:
                        title = self._clean(alt_nodes[0])

            # 修复：海报多级兜底 —— video poster → og:image → 播放器区域首图 → 页面首图
            pic = ''
            pic_nodes = root.xpath('//video/@poster')
            if pic_nodes:
                pic = self._abs(pic_nodes[0])
            if not pic:
                og = root.xpath('//meta[@property="og:image"]/@content')
                if og:
                    pic = self._abs(og[0])
            if not pic:
                for xp in ['//div[contains(@class,"player")]//img/@src',
                           '//div[contains(@class,"video")]//img/@src',
                           '//img/@src']:
                    nodes = root.xpath(xp)
                    if nodes:
                        pic = self._abs(nodes[0])
                        break

            desc_nodes = root.xpath('//div[contains(@class,"info_original")]//p/text() | //div[contains(@class,"entry-content")]//p/text()')
            desc = self._clean(''.join(desc_nodes)) if desc_nodes else ''
            if not desc:
                meta_desc = root.xpath('//meta[@property="og:description"]/@content | //meta[@name="description"]/@content | //meta[@itemprop="description"]/@content')
                if meta_desc:
                    desc = self._clean(meta_desc[0])
            if not desc:
                body_desc_nodes = root.xpath('//div[contains(@class,"post-content")]//p/text() | //article//p/text()')
                if body_desc_nodes:
                    desc = self._clean(''.join(body_desc_nodes))
            if not desc:
                desc = title

            tags = []
            for a in root.xpath('//div[contains(@class,"tagBox")]//a[@href] | //div[contains(@class,"keywords")]//a[@href] | //span[contains(@class,"ctg")]//a[@href]'):
                tag_name = self._clean(''.join(a.xpath('.//text()')))
                href = a.get('href') or ''
                if tag_name and href:
                    tags.append(self._clickable(tag_name, href))
            for a in root.xpath('//div[contains(@class,"info-list")]//li[contains(.,"標籤")]//a[@href]'):
                tag_name = self._clean(''.join(a.xpath('.//text()')))
                href = a.get('href') or ''
                if tag_name and href:
                    tags.append(self._clickable(tag_name, href))
            tag_text = ' '.join(tags)
            if not tag_text:
                meta_kw = root.xpath('//meta[@name="keywords"]/@content')
                if meta_kw:
                    parts = [self._clean(p) for p in (meta_kw[0] or '').split(',')]
                    for p in parts:
                        a = root.xpath(f'//a[normalize-space(text())="{p}"]/@href')
                        if a:
                            tags.append(self._clickable(p, a[0]))
                    tag_text = ' '.join(tags)

            actors = []
            for a in root.xpath('//div[contains(@class,"info-list")]//li[contains(.,"女優")]//a[starts-with(@href, "/actor?id=")][not(ancestor::*[contains(@class,"nav-dropdown") or contains(@class,"nav-top") or contains(@class,"navbar") or contains(@class,"footer")])]'):
                name = self._clean(''.join(a.xpath('.//text()')))
                href = a.get('href') or ''
                if name and href:
                    actors.append(self._clickable(name, href))
            if actors:
                seen = set(); uniq = []
                for t in actors:
                    if t and t not in seen:
                        uniq.append(t); seen.add(t)
                vod_actor = ' '.join(uniq)
            else:
                vod_actor = ''

            factories = []
            for a in root.xpath('//div[contains(@class,"info-list")]//li[(contains(.,"廠商") or contains(.,"發行商") or contains(.,"制作商") or contains(.,"系列"))]//a[starts-with(@href, "/tag_list?fid=")]'):
                name = self._clean(''.join(a.xpath('.//text()')))
                href = a.get('href') or ''
                if name and href and (name not in ["更多發行商", "發行商一覽"]):
                    factories.append(self._clickable(name, href))
            for label in root.xpath('//div[contains(@class,"meta")]//label[contains(text(),"制作商") or contains(text(),"系列") or contains(text(),"發行商") or contains(text(),"廠商")]'):
                for a in label.xpath('./following-sibling::a'):
                    name = self._clean(''.join(a.xpath('.//text()')))
                    href = a.get('href') or ''
                    if name and href and href.startswith('/tag_list?fid='):
                        factories.append(self._clickable(name, href))
            factories = [t for t in factories if ('更多發行商' not in t and '發行商一覽' not in t)]
            if factories:
                seen_f = set(); uniq_f = []
                for t in factories:
                    if t and t not in seen_f:
                        uniq_f.append(t); seen_f.add(t)
                vod_pub = ' '.join(uniq_f)
            else:
                vod_pub = ''

            directors = []
            for a in root.xpath('//div[contains(@class,"info-list")]//li[contains(@class,"my-2") and contains(.,"廠商")]//a[starts-with(@href, "/tag_list?fid=")]'):
                name = self._clean(''.join(a.xpath('.//text()')))
                href = a.get('href') or ''
                if name and href:
                    mfid = re.search(r'tag_list\?fid=(\d+)', href)
                    rel_id = f"/tag_list?fid={mfid.group(1)}" if mfid else href
                    target = json.dumps({"id": rel_id, "name": name}, ensure_ascii=False)
                    directors.append(f"[a=cr:{target}/]{name}[/a]")
            if directors:
                seen_d = set(); uniq_d = []
                for t in directors:
                    if t and t not in seen_d:
                        uniq_d.append(t); seen_d.add(t)
                vod_director = ' '.join(uniq_d)
            else:
                vod_director = ''

            code = ''
            mcode = re.search(r'([A-Za-z]{2,}[ -]?\d{3,})', title or '')
            if not mcode:
                alt_nodes = root.xpath('//img/@alt')
                alt_text = self._clean(alt_nodes[0]) if alt_nodes else ''
                mcode = re.search(r'([A-Za-z]{2,}[ -]?\d{3,})', alt_text)
            if mcode:
                code = mcode.group(1)

            views = ''
            vnodes = root.xpath('//span[contains(@class,"eye")]/text()')
            if vnodes:
                views = self._clean(vnodes[0])
            release_date = ''
            dnodes = root.xpath('//time/text()')
            if dnodes:
                release_date = self._clean(dnodes[0])

            count_text = ''
            cnt_nodes = root.xpath('//div[contains(@class,"vdo_lst_mask")]//text()')
            if cnt_nodes:
                raw = self._clean(' '.join([t for t in cnt_nodes if t and t.strip()]))
                mcnt = re.search(r'(\d+)\s*部', raw)
                if mcnt:
                    count_text = f"{mcnt.group(1)}部"
            if not count_text:
                info_cnt = root.xpath('//div[contains(@class,"info-list")]//li//text()')
                raw2 = self._clean(' '.join(info_cnt)) if info_cnt else ''
                mcnt2 = re.search(r'(\d+)\s*部', raw2)
                if mcnt2:
                    count_text = f"{mcnt2.group(1)}部"

            is_uncensored = bool(root.xpath('//div[contains(@class,"info-list")]//li[contains(. ,"標籤")]//a[contains(text(),"無碼") or contains(text(),"無修正")]'))

            play_url = self.extractVideoUrl(rsp.text)

            content_parts = []
            if tag_text:
                content_parts.append(tag_text)
            if desc:
                content_parts.append(desc)
            vod_content_final = (' '.join([p for p in content_parts if p]).strip()) or (title or '')

            vod = {
                "vod_id": tid,
                "vod_name": title or '未知标题',
                "vod_pic": f'{self.plp}{pic}',
                "vod_content": vod_content_final,
                "vod_play_from": "注意身体",
                "vod_play_url": f"多看少打卡${play_url}",
                "vod_remarks": code,
                "vod_actor": vod_actor,
                "vod_director": vod_director,
                "vod_pub": vod_pub,
                "vod_year": release_date,
            }
            remarks_parts = []
            if count_text:
                remarks_parts.append(count_text)
            if is_uncensored:
                remarks_parts.append('无码')
            if views:
                remarks_parts.append(f"👁 {views}")
            if remarks_parts:
                vod["vod_remarks"] = (vod["vod_remarks"] + (" " if vod["vod_remarks"] else "") + ' '.join(remarks_parts)).strip()

            return {"list": [vod]}
        except Exception as e:
            self.last_error = f'detailContent error: {e}'
            return {"list": []}

    def searchContent(self, key, quick, pg="1"):
        try:
            kw = quote(self._clean(key))
            page = int(pg)
            url = f"{self.host}/search?kw={kw}" if page == 1 else f"{self.host}/search?kw={kw}&page={page}"
            rsp = self.fetch(url)
            if rsp is None or rsp.status_code != 200:
                return {"list": []}
            root = etree.HTML(rsp.text)
            if root is None:
                return {"list": []}
            return {"list": self._parse_cards(root)}
        except Exception:
            return {"list": []}

    def playerContent(self, flag, id, vipFlags):
        result = {}
        if flag == "注意身体":
            try:
                if id.startswith('http') and '.m3u8' in id:
                    result["parse"] = 0
                    result["playUrl"] = ''
                    result["url"] = f'{self.plp}{id}'
                else:
                    url = id if id.startswith('http') else f"{self.host}{id}"
                    rsp = self.fetch(url)
                    play_url = self.extractVideoUrl(rsp.text) if rsp is not None else ''
                    result["parse"] = 0
                    result["playUrl"] = ''
                    result["url"] = self.plp + play_url
            except Exception:
                result["parse"] = 0
                result["playUrl"] = ''
                result["url"] = ''
        result["header"] = self.headers
        return result

    def isVideoFormat(self, url):
        return any(ext in (url or '') for ext in ['.m3u8', '.mp4'])

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return None
