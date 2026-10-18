#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
sys.path.append('..')
from base.spider import Spider
import json
import time
import urllib.parse
import re
import requests
import hashlib
import random
from lxml import etree
from urllib.parse import urljoin


class Spider(Spider):
    def __init__(self):
        super().__init__()
        # ==============================================================
        # ★★★ 单区配置块：切换 z1~z9 只改这里，下方业务代码完全不动
        # zone_slug: z1 / z2 ... z9
        # mod: z4 一般填 art，其余 vod（本模板会自动尝试 vod/art 兜底）
        # subs: 该区分类列表
        # special_categories: 该区需要“直接解析播放页”的分类 ID
        # ==============================================================
        self.zone_slug = "z1"
        self.cfg = {
            "host": "https://6182094.xyz",
            "api_host": "https://h5.xxoo475.org",
            "mod": "vod",
            "subs": [
                    {"n": "全部视频", "v": "1"}, {"n": "香蕉精品", "v": "13"}, {"n": "制服诱惑", "v": "22"},
                    {"n": "国产视频", "v": "6"}, {"n": "清纯少女", "v": "8"}, {"n": "辣妹大奶", "v": "9"},
                    {"n": "女同专属", "v": "10"}, {"n": "素人出演", "v": "11"}, {"n": "角色扮演", "v": "12"},
                    {"n": "人妻熟女", "v": "20"}, {"n": "日韩剧情", "v": "23"}, {"n": "经典伦理", "v": "21"},
                    {"n": "成人动漫", "v": "7"}, {"n": "精品二区", "v": "14"}, {"n": "精品三区", "v": "40"}
            ],
            "special_categories": ['13', '14', '33', '53', '32', '52', '9', '40', '44'],
        }
        # -------------------------- 域名池配置【禁止修改】--------------------------
        self.remote_pool_js = "https://webimgg.jiekrrj.cn/cf230705/image/2n8/108/18d/2pz/440fca8bd2f8b9b6342e412746428d85.jpg"
        self.zone_order = ["z1", "z2", "z3", "z4", "z5", "z6", "z7", "z8", "z9"]
        self.domain_pools = {zid: [] for zid in self.zone_order}
        # -------------------------------------------------------------------------
        self.host = self.cfg["host"]
        self.api_host = self.cfg["api_host"]
        self.mod = self.cfg["mod"]
        self.special_categories = self.cfg.get("special_categories", [])
        # 注意：全部使用 ASCII 连字符，避免全角字符导致请求头失效
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Referer': self.host
        }

    # ==================== 基础与工具 ====================
    def getName(self):
        return f"苹果视频·{self.zone_slug}"

    def init(self, extend=""):
        self.sync_remote_domain_pools()
        self.log(f"初始化完成｜zone={self.zone_slug}｜host={self.host}｜mod={self.mod}｜special={self.special_categories}")
        return True

    def log(self, message):
        print(f"[SINGLE-{self.zone_slug}] {message}")

    @staticmethod
    def _fmt_host(n):
        """把远端数字格式化为完整域名，兼容 '041' 与 '618041' 两种写法"""
        n = str(n).strip()
        if not n:
            return None
        if n.startswith("http"):
            return n.rstrip("/")
        if n.startswith("618"):
            return f"https://{n}.xyz"
        return f"https://618{n}.xyz"

    def _netloc(self, host=None):
        h = host or self.host
        if "://" in h:
            return urllib.parse.urlparse(h).netloc
        return h.split("/")[0]

    @staticmethod
    def _fix_url(url, domain):
        """把 // 、/、相对路径补全为绝对 URL"""
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("http"):
            return url
        base = f"https://{domain}" if not domain.startswith("http") else domain
        if url.startswith("/"):
            return base + url
        return base + "/" + url

    def sync_remote_domain_pools(self):
        """同步远端域名池（只做数据准备，不碰解析逻辑）"""
        try:
            headers = {"User-Agent": self.headers["User-Agent"], "Accept": "*/*"}
            rsp = requests.get(self.remote_pool_js, headers=headers, timeout=6, verify=False)
            text = rsp.text
            m = re.search(r'const\s+zuArr\s*=\s*(\[\[[\s\S]*?\]\]);', text)
            if m:
                raw = m.group(1).replace("'", '"')
                arr = json.loads(raw)
                for idx, num_list in enumerate(arr):
                    if idx < len(self.zone_order):
                        z = self.zone_order[idx]
                        hosts = []
                        for n in num_list:
                            h = self._fmt_host(n)
                            if h:
                                hosts.append(h)
                        self.domain_pools[z] = hosts
                self.log("域名池同步完成: " + str({k: len(v) for k, v in self.domain_pools.items()}))
            else:
                self.log("未在远端脚本中匹配到 zuArr，域名池为空")
        except Exception as e:
            self.log(f"域名池同步异常:{str(e)}")

    def switch_live_domain(self, current=None):
        """切换当前区的一个可用域名，返回完整 https:// 域名"""
        slug = self.zone_slug
        pool = self.domain_pools.get(slug, [])
        if not pool:
            self.sync_remote_domain_pools()
            pool = self.domain_pools.get(slug, [])
        old = current or self.host
        old_norm = old.rstrip("/")
        candidates = [h for h in pool if h.rstrip("/") != old_norm]
        if not candidates:
            return old_norm
        new_host = random.choice(candidates)
        self.host = new_host
        self.headers["Referer"] = self.host
        self.log(f"自动切换域名 → {new_host}")
        return new_host

    def html(self, content):
        try:
            return etree.HTML(content)
        except Exception:
            self.log("HTML解析失败")
            return None

    def regStr(self, pattern, string, index=1):
        try:
            match = re.search(pattern, string, re.IGNORECASE)
            if match and len(match.groups()) >= index:
                return match.group(index)
        except Exception:
            pass
        return ""

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def fetch(self, url, headers=None, method='GET', data=None, timeout=10):
        try:
            if headers is None:
                headers = self.headers
            if method == 'GET':
                return requests.get(url, headers=headers, timeout=timeout, verify=False)
            return requests.post(url, headers=headers, data=data, timeout=timeout, verify=False)
        except Exception as e:
            self.log(f"网络请求失败: {url}, 错误: {str(e)}")
            return None

    # ==================== 分类与首页 ====================
    def _build_classes(self):
        classes = []
        netloc = self._netloc()
        for sub in self.cfg["subs"]:
            classes.append({
                "type_id": f"{netloc}_{sub['v']}",
                "type_name": sub["n"]
            })
        return classes

    def homeContent(self, filter):
        result = {"class": self._build_classes()}
        try:
            rsp = self.fetch(self.host, headers=self.headers)
            doc = self.html(rsp.text) if rsp else None
            result["list"] = self._get_videos(doc, domain=self._netloc(), limit=20)
        except Exception as e:
            self.log(f"首页获取出错: {str(e)}")
            result["list"] = []
        return result

    def homeVideoContent(self):
        return {"class": self._build_classes()}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            domain_key, type_id = tid.split("_", 1)
            real_domain = f"https://{domain_key}"
            base_path = f"/index.php/{self.mod}/type/id/{type_id}"
            if pg and pg != '1':
                url = f"{real_domain}{base_path}/page/{pg}.html"
            else:
                url = f"{real_domain}{base_path}.html"
            self.log(f"访问分类URL: {url}")

            rsp = self.fetch(url, headers=self.headers)
            doc = self.html(rsp.text) if (rsp and rsp.status_code == 200) else None
            videos = self._get_videos(doc, category_id=type_id, domain=domain_key, limit=20)
            used_doc = doc

            # 空页：切域名重试
            if not videos:
                new_host = self.switch_live_domain(real_domain)
                if new_host.rstrip("/") != real_domain.rstrip("/"):
                    new_domain_key = self._netloc(new_host)
                    url2 = url.replace(real_domain, new_host.rstrip("/"))
                    rsp2 = self.fetch(url2, headers=self.headers)
                    doc2 = self.html(rsp2.text) if (rsp2 and rsp2.status_code == 200) else None
                    videos = self._get_videos(doc2, category_id=type_id, domain=new_domain_key, limit=20)
                    if videos:
                        used_doc = doc2

            # 仍空且当前是 vod：尝试 art 模块
            if not videos and self.mod == "vod":
                url3 = url.replace("/vod/", "/art/")
                self.log(f"尝试 art 模块: {url3}")
                rsp3 = self.fetch(url3, headers=self.headers)
                doc3 = self.html(rsp3.text) if (rsp3 and rsp3.status_code == 200) else None
                videos = self._get_videos(doc3, category_id=type_id, domain=domain_key, limit=20)
                if videos:
                    used_doc = doc3

            pagecount = 50
            try:
                page_elements = used_doc.xpath('//div[contains(@class,"mypage")]/a') if used_doc is not None else []
                for elem in page_elements:
                    if elem.text and ('尾页' in elem.text or '最后一页' in elem.text):
                        href = elem.xpath('./@href')[0]
                        mm = re.search(r'/page/(\d+)\.html', href)
                        if mm:
                            pagecount = int(mm.group(1))
                            break
            except Exception:
                pass

            return {
                'list': videos,
                'page': int(pg) if str(pg).isdigit() else 1,
                'pagecount': pagecount,
                'limit': 20,
                'total': pagecount * 20
            }
        except Exception as e:
            self.log(f"分类内容获取出错: {str(e)}")
            return {'list': []}

    def searchContent(self, key, quick, pg="1"):
        try:
            search_url = f"{self.host}/index.php/vod/type/id/1/wd/{urllib.parse.quote(key)}/page/{pg}.html"
            self.log(f"搜索URL: {search_url}")
            rsp = self.fetch(search_url, headers=self.headers)
            if not rsp or rsp.status_code != 200:
                self.log("搜索请求失败")
                return {'list': []}
            doc = self.html(rsp.text)
            videos = self._get_videos(doc, domain=self._netloc(), limit=20)

            pagecount = 5
            try:
                for elem in doc.xpath('//div[contains(@class,"mypage")]/a'):
                    if elem.text and ('尾页' in elem.text or '最后一页' in elem.text):
                        href = elem.xpath('./@href')[0]
                        mm = re.search(r'/page/(\d+)\.html', href)
                        if mm:
                            pagecount = int(mm.group(1))
                            break
            except Exception:
                pass

            return {
                'list': videos,
                'page': int(pg) if str(pg).isdigit() else 1,
                'pagecount': pagecount,
                'limit': 20,
                'total': pagecount * 20
            }
        except Exception as e:
            self.log(f"搜索出错: {str(e)}")
            return {'list': []}

    # ==================== 详情 ====================
    def detailContent(self, ids):
        try:
            vid = ids[0]

            # 特殊直链
            if vid.startswith("special_"):
                parts = vid.split("_")
                if len(parts) >= 4:
                    category_id = parts[1]
                    video_id = parts[2]
                    encoded_url = "_".join(parts[3:])
                    play_url = urllib.parse.unquote(encoded_url)

                    parsed = urllib.parse.urlparse(play_url)
                    qs = urllib.parse.parse_qs(parsed.query)
                    pic_url = qs.get('b', [''])[0]

                    path_parts = parsed.path.split("/")
                    encrypted_title = path_parts[-1].replace(".html", "") if path_parts else ""
                    title = self._decrypt_title(encrypted_title) if encrypted_title else f"视频{video_id}"
                    if not title or not title.strip():
                        title = f"视频{video_id}"

                    return {'list': [{
                        'vod_id': vid,
                        'vod_name': title,
                        'vod_pic': pic_url,
                        'vod_remarks': '',
                        'vod_year': '',
                        'vod_area': '',
                        'vod_actor': '',
                        'vod_director': '',
                        'vod_content': '',
                        'vod_play_from': '直接播放',
                        'vod_play_url': f"第1集${play_url}"
                    }]}

            # 常规：{domain}_{cat}_{id} 或 {domain}_{id}
            if vid.count('_') >= 2:
                domain, category_id, video_id = vid.split('_', 2)
            elif '_' in vid:
                domain, video_id = vid.split('_', 1)
                category_id = ''
            else:
                domain, video_id = self._netloc(), vid
                category_id = ''

            detail_url = f"https://{domain}/index.php/vod/detail/id/{video_id}.html"
            self.log(f"访问详情URL: {detail_url}")
            rsp = self.fetch(detail_url, headers=self.headers)
            if not rsp or rsp.status_code != 200:
                # 详情页 404 时用播放页兜底
                play_url = f"https://{domain}/index.php/vod/play/id/{video_id}.html"
                self.log(f"详情失败，回退播放页: {play_url}")
                return {'list': [{
                    'vod_id': vid, 'vod_name': f"视频{video_id}", 'vod_pic': '',
                    'vod_remarks': '', 'vod_year': '', 'vod_area': '',
                    'vod_actor': '', 'vod_director': '', 'vod_content': '',
                    'vod_play_from': '默认播放源',
                    'vod_play_url': f"第1集${play_url}"
                }]}
            doc = self.html(rsp.text)
            video_info = self._get_detail(doc, rsp.text, vid, domain)
            return {'list': [video_info]} if video_info else {'list': []}
        except Exception as e:
            self.log(f"详情获取出错: {str(e)}")
            return {'list': []}

    # ==================== 播放 ====================
    def playerContent(self, flag, id, vipFlags):
        try:
            self.log(f"获取播放链接: flag={flag}, id={id}")

            # 特殊直链
            if id.startswith("special_"):
                parts = id.split("_")
                if len(parts) >= 4:
                    encoded_url = "_".join(parts[3:])
                    play_url = urllib.parse.unquote(encoded_url)
                    parsed = urllib.parse.urlparse(play_url)
                    qs = urllib.parse.parse_qs(parsed.query)
                    video_url = qs.get('v', [''])[0]
                    if video_url:
                        video_url = self._fix_url(video_url, self._netloc())
                        self.log(f"特殊直链视频地址: {video_url}")
                        return {'parse': 0, 'playUrl': '', 'url': video_url}
                    return {'parse': 1, 'playUrl': '', 'url': play_url}

            # 完整 URL
            if id.startswith("http"):
                parsed = urllib.parse.urlparse(id)
                qs = urllib.parse.parse_qs(parsed.query)
                video_url = qs.get('v', [''])[0]
                if video_url:
                    video_url = urllib.parse.unquote(video_url)
                    video_url = self._fix_url(video_url, self._netloc())
                    self.log(f"URL 参数视频地址: {video_url}")
                    return {'parse': 0, 'playUrl': '', 'url': video_url}
                return {'parse': 1, 'playUrl': '', 'url': id}

            # 常规 vod_id：{domain}_{cat}_{vid} 或 {domain}_{vid}
            if id.count('_') >= 2:
                domain, category_id, video_id = id.split('_', 2)
            elif '_' in id:
                domain, video_id = id.split('_', 1)
                category_id = ''
            else:
                domain, video_id, category_id = self._netloc(), id, ''

            self.log(f"视频ID: {video_id}, 分类ID: {category_id}, 域名: {domain}")

            # 特殊分类：优先直接从播放页提取直链
            if category_id in self.special_categories:
                play_page_url = f"https://{domain}/index.php/vod/play/id/{video_id}.html"
                rsp = self.fetch(play_page_url, headers=self.headers)
                if rsp and rsp.status_code == 200:
                    video_url = self._extract_direct_video_url(rsp.text)
                    if video_url:
                        self.log(f"播放页提取到直链: {video_url}")
                        return {'parse': 0, 'playUrl': '', 'url': video_url}
                self.log("播放页未提取到直链，回退 API")
                return self._get_video_by_api(id, video_id, domain)

            return self._get_video_by_api(id, video_id, domain)

        except Exception as e:
            self.log(f"播放链接获取出错: {str(e)}")
            domain = self._netloc()
            if '_' in id and not id.startswith("special_"):
                domain = id.split('_', 1)[0]
            play_url = f"https://{domain}/html/kkyd.html?m={id}"
            return {'parse': 1, 'playUrl': '', 'url': play_url}

    def _get_video_by_api(self, id, video_id, domain=None):
        domain = domain or self._netloc()
        try:
            api_url = f"{self.api_host}/api/v2/vod/reqplay/{video_id}"
            self.log(f"请求API: {api_url}")
            api_headers = self.headers.copy()
            api_headers.update({
                'Referer': f"https://{domain}/",
                'Origin': f"https://{domain}",
                'X-Requested-With': 'XMLHttpRequest'
            })
            api_response = self.fetch(api_url, headers=api_headers)
            if api_response and api_response.status_code == 200:
                try:
                    data = api_response.json()
                except Exception:
                    data = {}
                self.log(f"API响应: {data}")
                if data.get('retcode') == 3:
                    video_url = data.get('data', {}).get('httpurl_preview', '')
                else:
                    video_url = data.get('data', {}).get('httpurl', '')
                if video_url:
                    video_url = video_url.replace('?300', '')
                    self.log(f"API视频地址: {video_url}")
                    return {'parse': 0, 'playUrl': '', 'url': video_url}
                self.log("API响应中无视频地址")
            else:
                self.log(f"API请求失败: {api_response.status_code if api_response else '无响应'}")
        except Exception as e:
            self.log(f"API方式出错: {str(e)}")

        play_url = f"https://{domain}/html/kkyd.html?m={video_id}"
        return {'parse': 1, 'playUrl': '', 'url': play_url}

    def _extract_direct_video_url(self, html_content):
        try:
            patterns = [
                r'v=([^&"\']+\.(?:m3u8|mp4))',
                r'"url"\s*:\s*["\']([^"\']+\.(?:mp4|m3u8))["\']',
                r'src\s*=\s*["\']([^"\']+\.(?:mp4|m3u8))["\']',
                r'https?://[^\s<>"\'?]+\.(?:mp4|m3u8)'
            ]
            for pattern in patterns:
                for match in re.findall(pattern, html_content, re.IGNORECASE):
                    if isinstance(match, tuple):
                        match = match[0]
                    url = urllib.parse.unquote(match.replace('\\', ''))
                    url = self._fix_url(url, self._netloc())
                    if url.startswith("http"):
                        return url
            return None
        except Exception as e:
            self.log(f"提取直链出错: {str(e)}")
            return None

    # ==================== 列表提取（宽松版） ====================
    def _get_videos(self, doc, category_id=None, domain=None, limit=None):
        try:
            if doc is None:
                return []
            domain = domain or self._netloc()
            selectors = [
                '//a[contains(@class,"vodbox")]',
                '//a[contains(@class,"public-list-box")]',
                '//div[contains(@class,"public-list-box")]/a',
                '//li[contains(@class,"col")]/a[contains(@href,"/vod/detail/")]',
                '//a[contains(@href,"/index.php/vod/detail/id/")]',
                '//a[contains(@href,"/html/dcdc/")]',
                '//a[contains(@href,"/html/") and .//img]',
            ]
            elements = []
            hit_sel = ""
            for sel in selectors:
                elements = doc.xpath(sel)
                if elements:
                    hit_sel = sel
                    break
            self.log(f"列表选择器命中: {hit_sel or '无'} -> {len(elements)} 条")

            videos = []
            for elem in elements:
                v = self._extract_video(elem, category_id, domain)
                if v:
                    videos.append(v)
            return videos[:limit] if limit and videos else videos
        except Exception as e:
            self.log(f"获取影片列表出错: {str(e)}")
            return []

    def _extract_video(self, element, category_id=None, domain=None):
        try:
            domain = domain or self._netloc()

            if element.tag == 'a':
                hrefs = element.xpath('./@href')
            else:
                hrefs = element.xpath('.//a/@href')
            if not hrefs:
                return None
            link = self._fix_url(hrefs[0].strip(), domain)

            # 标题：多选择器 + contains，找不到给默认值，绝不丢弃
            title_encrypted = ''
            for sel in [
                './/p[contains(@class,"km-script")]/text()',
                './/p[contains(@class,"script")]/text()',
                './/p[contains(@class,"title")]/text()',
                './/h3/text()',
                './/h4/text()',
                './/img/@alt',
            ]:
                t = element.xpath(sel)
                if t and t[0].strip():
                    title_encrypted = t[0].strip()
                    break

            # 图片：多属性
            pic = ''
            for sel in [
                './/img/@data-original',
                './/img/@data-src',
                './/img/@data-lazy-src',
                './/img/@src',
            ]:
                p = element.xpath(sel)
                if p and p[0].strip():
                    pic = self._fix_url(p[0].strip(), domain)
                    break

            m = re.search(r'[?&]m=(\d+)', link)
            # 无 m=数字：按特殊直链处理
            if not m:
                parsed = urllib.parse.urlparse(link)
                qs = urllib.parse.parse_qs(parsed.query)
                video_url = qs.get('v', [''])[0]
                pic_url = qs.get('b', [''])[0]
                if video_url:
                    vm = re.search(r'/([a-f0-9-]+)/video\.m3u8', video_url)
                    vid = vm.group(1) if vm else hashlib.md5(video_url.encode()).hexdigest()[:8]
                else:
                    vid = hashlib.md5(link.encode()).hexdigest()[:8]
                if not pic and pic_url:
                    pic = self._fix_url(pic_url, domain)
                title = self._decrypt_title(title_encrypted) if title_encrypted else f"视频{vid}"
                if not title or not title.strip():
                    title = f"视频{vid}"
                cat = category_id or '0'
                encoded_link = urllib.parse.quote(link, safe='')
                return {
                    'vod_id': f"special_{cat}_{vid}_{encoded_link}",
                    'vod_name': title,
                    'vod_pic': pic,
                    'vod_remarks': '',
                    'vod_year': ''
                }

            # 常规链接
            vod_id = m.group(1)
            title = self._decrypt_title(title_encrypted) if title_encrypted else f"视频{vod_id}"
            if not title or not title.strip():
                title = f"视频{vod_id}"
            if category_id:
                final_id = f"{domain}_{category_id}_{vod_id}"
            else:
                final_id = f"{domain}_{vod_id}"
            return {
                'vod_id': final_id,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': '',
                'vod_year': ''
            }
        except Exception as e:
            self.log(f"提取影片信息出错: {str(e)}")
            return None

    def _decrypt_title(self, encrypted_text):
        try:
            return ''.join(chr(ord(c) ^ 128) for c in encrypted_text).replace('&nbsp;', ' ')
        except Exception as e:
            self.log(f"标题解密失败: {str(e)}")
            return encrypted_text

    # ==================== 详情提取 ====================
    def _get_detail(self, doc, html_content, vid, domain=None):
        domain = domain or self._netloc()
        try:
            title = self._get_text(doc, ['//h1/text()', '//title/text()'])
            pic = self._get_text(doc, [
                '//div[contains(@class,"dyimg")]//img/@src',
                '//img[contains(@class,"poster")]/@src',
                '//div[contains(@class,"pic")]//img/@src'
            ])
            pic = self._fix_url(pic, domain) if pic else ''
            desc = self._get_text(doc, [
                '//div[contains(@class,"yp_context")]/text()',
                '//div[contains(@class,"introduction")]//text()',
                '//div[contains(@class,"desc")]//text()'
            ])
            actor = self._get_text(doc, ['//span[contains(text(),"主演")]/following-sibling::*/text()'])
            director = self._get_text(doc, ['//span[contains(text(),"导演")]/following-sibling::*/text()'])

            player_link_patterns = [
                re.compile(r'href="([^"]*?ar\.html[^"]*?)"'),
                re.compile(r'href="([^"]*?kkyd\.html[^"]*?)"'),
                re.compile(r'href="([^"]*?ar-kk\.html[^"]*?)"'),
                re.compile(r'href="([^"]*?dcdc/[^"]*?)"'),
            ]
            player_links = []
            for pattern in player_link_patterns:
                player_links.extend(pattern.findall(html_content))

            play_from, play_urls = [], []
            if player_links:
                episodes = []
                seen = set()
                for link in player_links:
                    full_url = self._fix_url(link, domain)
                    if full_url in seen:
                        continue
                    seen.add(full_url)
                    episodes.append(f"第1集${full_url}")
                if episodes:
                    play_from.append("默认播放源")
                    play_urls.append('#'.join(episodes))

            if not play_from:
                self.log("未找到播放源链接，回退到播放页")
                fallback = f"https://{domain}/index.php/vod/play/id/{vid.split('_')[-1]}.html"
                return {
                    'vod_id': vid, 'vod_name': title, 'vod_pic': pic,
                    'type_name': '', 'vod_year': '', 'vod_area': '', 'vod_remarks': '',
                    'vod_actor': actor, 'vod_director': director, 'vod_content': desc,
                    'vod_play_from': '默认播放源',
                    'vod_play_url': f"第1集${fallback}"
                }

            return {
                'vod_id': vid, 'vod_name': title, 'vod_pic': pic,
                'type_name': '', 'vod_year': '', 'vod_area': '', 'vod_remarks': '',
                'vod_actor': actor, 'vod_director': director, 'vod_content': desc,
                'vod_play_from': '$$$'.join(play_from),
                'vod_play_url': '$$$'.join(play_urls)
            }
        except Exception as e:
            self.log(f"获取详情出错: {str(e)}")
            return None

    def _get_text(self, doc, selectors):
        for selector in selectors:
            try:
                for text in doc.xpath(selector):
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue
        return ''

    # ==================== 框架兼容 ====================
    def localProxy(self, params):
        return [404, "text/plain", "NotImplemented"]

    def action(self, action):
        return {"msg": "运行正常"}

    def liveContent(self):
        return ""

    def destroy(self):
        pass