import sys
sys.path.append('..')
from base.spider import Spider
import json
import time
import urllib.parse
import re
import requests
from lxml import etree
from urllib.parse import urljoin
import base64
import hashlib
import random

class Spider(Spider):
    def __init__(self):
        super().__init__()
        # ==============================================================
        # ★★★【单区配置块｜切换z1~z9只修改这里，下面业务代码完全不动】
        # zone_slug: z1/z2/z3/z4/z5/z6/z7/z8/z9
        # init_cfg["mod"]: z4填 "art"，其余全部填 "vod"
        # api_host: z1=https://h5.xxoo475.org ; z2‑z9=https://h5.xxoo168.org
        # subs: 粘贴对应区分类列表
        # ==============================================================
        self.zone_slug = "z2"
        self.init_cfg = {
            "host": "https://6182094.xyz",
            "api_host": "https://h5.xxoo168.org",
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

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Referer': self.host
        }

    def getName(self):
        return f"融合xj101·{self.zone_slug}"

    def init(self, extend=""):
        self.sync_remote_domain_pools()
        self.log(f"初始化完成 zone={self.zone_slug} host={self.host} mod={self.mod}")
        return True

    def log(self, message):
        print(f"[XJ‑{self.zone_slug}] {message}")

    def sync_remote_domain_pools(self):
        """同步远端域名池，取自蝴蝶模板思路，不改动业务解析"""
        try:
            headers = {"User‑Agent": self.headers["User‑Agent"], "Accept": "*/*"}
            req = requests.get(self.remote_pool_js, headers=headers, timeout=6, verify=False)
            text = req.text
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
                self.headers["Referer"] = self.host
                self.log(f"自动切换域名 → {new_host}")
                return new_host
        return self.host

    def html(self, content):
        """【原样保留xj101】将HTML内容转换为可查询的对象"""
        try:
            return etree.HTML(content)
        except:
            self.log("HTML解析失败")
            return None

    def regStr(self, pattern, string, index=1):
        """【原样保留xj101】正则表达式提取字符串"""
        try:
            match = re.search(pattern, string, re.IGNORECASE)
            if match and len(match.groups()) >= index:
                return match.group(index)
        except:
            pass
        return ""

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def homeContent(self, filter):
        """【改写，动态读取init_cfg.subs生成分类；首页list置空，原版逻辑】"""
        result = {}
        classes = []
        for sub in self.init_cfg["subs"]:
            tid_str = f"{self.host}_{sub['v']}"
            classes.append({"type_id": tid_str, "type_name": sub["n"]})
        result['class'] = classes
        result['list'] = []
        return result

    def homeVideoContent(self):
        """【改写，动态读取配置生成分类】"""
        classes = []
        for sub in self.init_cfg["subs"]:
            tid_str = f"{self.host}_{sub['v']}"
            classes.append({"type_id": tid_str, "type_name": sub["n"]})
        return {'class': classes}

    def categoryContent(self, tid, pg, filter, extend):
        """【改写：支持tid=host_typeid；mod自动vod/art；404自动切换域名；其余调用xj101原解析】"""
        try:
            domain, type_id = tid.split('_')
            page = int(pg) if str(pg).isdigit() else 1
            base_path = f"/index.php/{self.mod}/type/id/{type_id}"
            if page == 1:
                url = f"https://{domain}{base_path}.html"
            else:
                url = f"https://{domain}{base_path}/page/{page}.html"
            self.log(f"访问分类URL: {url}")
            rsp = self.fetch(url, headers=self.headers)
            # 404/403触发域名切换重试一次
            if rsp is None or rsp.status_code in (404,403,451):
                old_d = domain
                new_d = self.switch_live_domain()
                url = url.replace(old_d, new_d)
                rsp = self.fetch(url, headers=self.headers)
                domain = new_d
            doc = self.html(rsp.text)
            videos = self._get_videos(doc, category_id=type_id, limit=20)

            pagecount = 50
            try:
                page_elements = doc.xpath('//div[@class="mypage"]/a')
                if page_elements:
                    for elem in page_elements:
                        if elem.text and ('尾页' in elem.text or '最后一页' in elem.text):
                            href = elem.xpath('./@href')[0]
                            match = re.search(r'/page/(\d+)\.html', href)
                            if match:
                                pagecount = int(match.group(1))
                                break
            except Exception:
                pass
            total = pagecount * 20
            return {
                'list': videos,
                'page': int(pg),
                'pagecount': pagecount,
                'limit': 20,
                'total': total
            }
        except Exception as e:
            self.log(f"分类内容获取出错: {str(e)}")
            return {'list': []}

    def searchContent(self, key, quick, pg="1"):
        """【改写：mod动态；其余解析逻辑原样xj101】"""
        try:
            page = int(pg) if str(pg).isdigit() else 1
            search_url = f"{self.host}/index.php/{self.mod}/type/id/1/wd/{urllib.parse.quote(key)}/page/{pg}.html"
            self.log(f"搜索URL: {search_url}")
            rsp = self.fetch(search_url, headers=self.headers)
            if not rsp or rsp.status_code != 200:
                self.log("搜索请求失败")
                return {'list': []}
            doc = self.html(rsp.text)
            if not doc:
                self.log("搜索页面解析失败")
                return {'list': []}
            videos = self._get_videos(doc, limit=20)
            pagecount = 5
            try:
                page_elements = doc.xpath('//div[@class="mypage"]/a')
                if page_elements:
                    for elem in page_elements:
                        if elem.text and ('尾页' in elem.text or '最后一页' in elem.text):
                            href = elem.xpath('./@href')[0]
                            match = re.search(r'/page/(\d+)\.html', href)
                            if match:
                                pagecount = int(match.group(1))
                                break
            except Exception:
                pass
            total = pagecount * 20
            return {
                'list': videos,
                'page': int(pg),
                'pagecount': pagecount,
                'limit': 20,
                'total': total
            }
        except Exception as e:
            self.log(f"搜索出错: {str(e)}")
            return {'list': []}

    # ========================= 下面全部【原样复制你原始xj101代码，一行解析逻辑不修改】 =========================
    def detailContent(self, ids):
        """详情页面 - 特别处理特殊分区的链接【原样保留xj101】"""
        try:
            vid = ids[0]
            if vid.startswith('special_'):
                parts = vid.split('_')
                if len(parts) >= 4:
                    category_id = parts[1]
                    video_id = parts[2]
                    encoded_url = '_'.join(parts[3:])
                    play_url = urllib.parse.unquote(encoded_url)
                    self.log(f"特殊分区视频，直接使用链接: {play_url}")
                    parsed_url = urllib.parse.urlparse(play_url)
                    query_params = urllib.parse.parse_qs(parsed_url.query)
                    video_url = query_params.get('v', [''])[0]
                    pic_url = query_params.get('b', [''])[0]
                    path_parts = parsed_url.path.split('/')
                    if len(path_parts) > 0:
                        encrypted_title = path_parts[-1].replace('.html', '')
                        title = self._decrypt_title(encrypted_title)
                    else:
                        title = "未知标题"
                    return {
                        'list': [{
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
                        }]
                    }
            if '_' in vid and len(vid.split('_')) > 2:
                domain, category_id, video_id = vid.split('_')
            else:
                domain, video_id = vid.split('_')
            detail_url = f"https://{domain}/index.php/{self.mod}/detail/id/{video_id}.html"
            self.log(f"访问详情URL: {detail_url}")
            rsp = self.fetch(detail_url, headers=self.headers)
            doc = self.html(rsp.text)
            video_info = self._get_detail(doc, rsp.text, vid)
            return {'list': [video_info]} if video_info else {'list': []}
        except Exception as e:
            self.log(f"详情获取出错: {str(e)}")
            return {'list': []}

    def playerContent(self, flag, id, vipFlags):
        """播放链接【原样保留xj101】"""
        try:
            self.log(f"获取播放链接: flag={flag}, id={id}")
            if id.startswith('special_'):
                parts = id.split('_')
                if len(parts) >= 4:
                    encoded_url = '_'.join(parts[3:])
                    play_url = urllib.parse.unquote(encoded_url)
                    self.log(f"特殊分区视频，直接使用链接: {play_url}")
                    parsed_url = urllib.parse.urlparse(play_url)
                    query_params = urllib.parse.parse_qs(parsed_url.query)
                    video_url = query_params.get('v', [''])[0]
                    if video_url:
                        if video_url.startswith('//'):
                            video_url = 'https:' + video_url
                        elif not video_url.startswith('http'):
                            video_url = urljoin(self.host, video_url)
                        self.log(f"从特殊链接中提取到视频地址: {video_url}")
                        return {'parse': 0, 'playUrl': '', 'url': video_url}
                    else:
                        self.log(f"未找到视频参数，返回原始链接")
                        return {'parse': 1, 'playUrl': '', 'url': play_url}
            if id.startswith('http'):
                self.log("ID 是一个完整URL，直接解析参数")
                parsed_url = urllib.parse.urlparse(id)
                query_params = urllib.parse.parse_qs(parsed_url.query)
                video_url = query_params.get('v', [''])[0]
                if video_url:
                    video_url = urllib.parse.unquote(video_url)
                    if video_url.startswith('//'):
                        video_url = 'https:' + video_url
                    elif not video_url.startswith('http'):
                        video_url = urljoin(self.host, video_url)
                    self.log(f"从 URL 参数中提取到视频地址: {video_url}")
                    return {'parse': 0, 'playUrl': '', 'url': video_url}
                else:
                    self.log("URL 中没有找到视频参数，返回原始URL")
                    return {'parse': 1, 'playUrl': '', 'url': id}
            if id.count('_') >= 2:
                parts = id.split('_')
                video_id = parts[-1]
                category_id = parts[1]
            else:
                video_id = id.split('_')[-1]
                category_id = ''
            self.log(f"视频ID: {video_id}, 分类ID: {category_id}")
            if category_id in self.special_categories:
                self.log("特殊分类，尝试从详情页提取直接播放链接")
                play_page_url = f"{self.host}/index.php/{self.mod}/play/id/{video_id}.html"
                rsp = self.fetch(play_page_url, headers=self.headers)
                if rsp and rsp.status_code == 200:
                    video_url = self._extract_direct_video_url(rsp.text)
                    if video_url:
                        self.log(f"从播放页面提取到视频地址: {video_url}")
                        return {'parse': 0, 'playUrl': '', 'url': video_url}
                self.log("从播放页面提取失败，尝试API方式")
                return self._get_video_by_api(id, video_id)
            else:
                self.log("使用API方式获取视频地址")
                return self._get_video_by_api(id, video_id)
        except Exception as e:
            self.log(f"播放链接获取出错: {str(e)}")
            if '_' in id:
                domain, play_id = id.split('_')
                play_url = f"https://{domain}/html/kkyd.html?m={play_id}"
            else:
                play_url = f"{self.host}/html/kkyd.html?m={id}"
            return {'parse': 1, 'playUrl': '', 'url': play_url}

    def _get_video_by_api(self, id, video_id):
        """通过API获取视频地址【原样保留xj101】"""
        try:
            api_url = f"{self.api_host}/api/v2/vod/reqplay/{video_id}"
            self.log(f"请求API获取视频地址: {api_url}")
            api_headers = self.headers.copy()
            api_headers.update({
                'Referer': f"{self.host}/",
                'Origin': self.host,
                'X‑Requested‑With': 'XMLHttpRequest'
            })
            api_response = self.fetch(api_url, headers=api_headers)
            if api_response and api_response.status_code == 200:
                data = api_response.json()
                self.log(f"API响应: {data}")
                if data.get('retcode') == 3:
                    video_url = data.get('data', {}).get('httpurl_preview', '')
                else:
                    video_url = data.get('data', {}).get('httpurl', '')
                if video_url:
                    video_url = video_url.replace('?300', '')
                    self.log(f"从API获取到视频地址: {video_url}")
                    return {'parse': 0, 'playUrl': '', 'url': video_url}
                else:
                    self.log("API响应中没有找到视频地址")
            else:
                self.log(f"API请求失败，状态码: {api_response.status_code if api_response else '无响应'}")
            if '_' in id:
                domain, play_id = id.split('_')
                play_url = f"https://{domain}/html/kkyd.html?m={play_id}"
            else:
                play_url = f"{self.host}/html/kkyd.html?m={id}"
            self.log(f"API请求失败，回退到播放页面: {play_url}")
            return {'parse': 1, 'playUrl': '', 'url': play_url}
        except Exception as e:
            self.log(f"API方式获取视频出错: {str(e)}")
            if '_' in id:
                domain, play_id = id.split('_')
                play_url = f"https://{domain}/html/kkyd.html?m={play_id}"
            else:
                play_url = f"{self.host}/html/kkyd.html?m={id}"
            return {'parse': 1, 'playUrl': '', 'url': play_url}

    def _extract_direct_video_url(self, html_content):
        """从HTML内容中提取直接播放链接【原样保留xj101】"""
        try:
            patterns = [
                r'v=([^&]+\.(?:m3u8|mp4))',
                r'"url"\s*:\s*["\']([^"\']+\.(?:mp4|m3u8))["\']',
                r'src\s*=\s*["\']([^"\']+\.(?:mp4|m3u8))["\']',
                r'http[^\s<>"\'?]+\.(?:m3u8|mp4)'
            ]
            for pattern in patterns:
                matches = re.findall(pattern, html_content, re.IGNORECASE)
                for match in matches:
                    if isinstance(match, tuple):
                        match = match[0]
                    extracted_url = match.replace('\\', '')
                    extracted_url = urllib.parse.unquote(extracted_url)
                    if extracted_url.startswith('//'):
                        extracted_url = 'https:' + extracted_url
                    elif extracted_url.startswith('http'):
                        return extracted_url
            return None
        except Exception as e:
            self.log(f"提取直接播放URL出错: {str(e)}")
            return None

    def _get_videos(self, doc, category_id=None, limit=None):
        """获取影片列表【原样保留xj101】"""
        try:
            videos = []
            elements = doc.xpath('//a[@class="vodbox"]')
            self.log(f"找到 {len(elements)} 个vodbox元素")
            for elem in elements:
                video = self._extract_video(elem, category_id)
                if video:
                    videos.append(video)
            return videos[:limit] if limit and videos else videos
        except Exception as e:
            self.log(f"获取影片列表出错: {str(e)}")
            return []

    def _extract_video(self, element, category_id=None):
        """提取影片信息【原样保留xj101】"""
        try:
            link = element.xpath('./@href')[0]
            if link.startswith('/'):
                link = self.host + link
            is_special_link = '/html/dcdc/' in link
            if is_special_link:
                parsed_url = urllib.parse.urlparse(link)
                query_params = urllib.parse.parse_qs(parsed_url.query)
                video_url = query_params.get('v', [''])[0]
                pic_url = query_params.get('b', [''])[0]
                if video_url:
                    video_id_match = re.search(r'/([a‑f0‑9‑]+)/video\.m3u8', video_url)
                    if video_id_match:
                        video_id = video_id_match.group(1)
                    else:
                        video_id = hashlib.md5(video_url.encode()).hexdigest()[:8]
                else:
                    video_id = str(hash(link) % 1000000)
                encoded_link = urllib.parse.quote(link)
                final_vod_id = f"special_{category_id}_{video_id}_{encoded_link}"
                title_elem = element.xpath('.//p[@class="km‑script"]/text()')
                if not title_elem:
                    title_elem = element.xpath('.//p[contains(@class, "script")]/text()')
                    if not title_elem:
                        title_elem = element.xpath('.//p/text()')
                        if not title_elem:
                            title_elem = element.xpath('.//h3/text()')
                            if not title_elem:
                                title_elem = element.xpath('.//h4/text()')
                                if not title_elem:
                                    self.log(f"未找到标题元素，跳过该视频")
                                    return None
                title_encrypted = title_elem[0].strip()
                title = self._decrypt_title(title_encrypted)
                pic_elem = element.xpath('.//img/@data‑original')
                if not pic_elem:
                    pic_elem = element.xpath('.//img/@src')
                pic = pic_elem[0] if pic_elem else pic_url
                if pic:
                    if pic.startswith('//'):
                        pic = 'https:' + pic
                    elif pic.startswith('/'):
                        pic = self.host + pic
                return {
                    'vod_id': final_vod_id,
                    'vod_name': title,
                    'vod_pic': pic,
                    'vod_remarks': '',
                    'vod_year': ''
                }
            else:
                vod_id = self.regStr(r'm=(\d+)', link)
                if not vod_id:
                    vod_id = str(hash(link) % 1000000)
                final_vod_id = f"{self.host.replace('https://','')}_{vod_id}"
                if category_id:
                    final_vod_id = f"{self.host.replace('https://','')}_{category_id}_{vod_id}"
                title_elem = element.xpath('.//p[@class="km‑script"]/text()')
                if not title_elem:
                    title_elem = element.xpath('.//p[contains(@class, "script")]/text()')
                    if not title_elem:
                        title_elem = element.xpath('.//p/text()')
                        if not title_elem:
                            title_elem = element.xpath('.//h3/text()')
                            if not title_elem:
                                title_elem = element.xpath('.//h4/text()')
                                if not title_elem:
                                    self.log(f"未找到标题元素，跳过该视频")
                                    return None
                title_encrypted = title_elem[0].strip()
                title = self._decrypt_title(title_encrypted)
                pic_elem = element.xpath('.//img/@data‑original')
                if not pic_elem:
                    pic_elem = element.xpath('.//img/@src')
                pic = pic_elem[0] if pic_elem else ''
                if pic:
                    if pic.startswith('//'):
                        pic = 'https:' + pic
                    elif pic.startswith('/'):
                        pic = self.host + pic
                return {
                    'vod_id': final_vod_id,
                    'vod_name': title,
                    'vod_pic': pic,
                    'vod_remarks': '',
                    'vod_year': ''
                }
        except Exception as e:
            self.log(f"提取影片信息出错: {str(e)}")
            return None

    def _decrypt_title(self, encrypted_text):
        """解密标题【原样保留xj101】"""
        try:
            decrypted_chars = []
            for char in encrypted_text:
                code_point = ord(char)
                decrypted_code = code_point ^ 128
                decrypted_char = chr(decrypted_code)
                decrypted_chars.append(decrypted_char)
            decrypted_text = ''.join(decrypted_chars)
            decrypted_text = decrypted_text.replace('&nbsp;', ' ')
            return decrypted_text
        except Exception as e:
            self.log(f"标题解密失败: {str(e)}")
            return encrypted_text

    def _get_detail(self, doc, html_content, vid):
        """获取详情信息【原样保留xj101】"""
        try:
            title = self._get_text(doc, ['//h1/text()', '//title/text()'])
            pic = self._get_text(doc, ['//div[contains(@class,"dyimg")]//img/@src', '//img[contains(@class,"poster")]/@src'])
            if pic and pic.startswith('/'):
                pic = self.host + pic
            desc = self._get_text(doc, ['//div[contains(@class,"yp_context")]/text()', '//div[contains(@class,"introduction")]//text()'])
            actor = self._get_text(doc, ['//span[contains(text(),"主演")]/following‑sibling::*/text()'])
            director = self._get_text(doc, ['//span[contains(text(),"导演")]/following‑sibling::*/text()'])
            play_from = []
            play_urls = []
            player_link_patterns = [
                re.compile(r'href="(.*?ar\.html.*?)"'),
                re.compile(r'href="(.*?kkyd\.html.*?)"'),
                re.compile(r'href="(.*?ar‑kk\.html.*?)"'),
                re.compile(r'href="(.*?dcdc/.*?)"')
            ]
            player_links = []
            for pattern in player_link_patterns:
                matches = pattern.findall(html_content)
                player_links.extend(matches)
            if player_links:
                episodes = []
                for link in player_links:
                    full_url = urljoin(self.host, link)
                    episodes.append(f"第1集${full_url}")
                if episodes:
                    play_from.append("默认播放源")
                    play_urls.append('#'.join(episodes))
            if not play_from:
                self.log("未找到播放源元素，无法定位播放源列表")
                return {
                    'vod_id': vid,
                    'vod_name': title,
                    'vod_pic': pic,
                    'type_name': '',
                    'vod_year': '',
                    'vod_area': '',
                    'vod_remarks': '',
                    'vod_actor': actor,
                    'vod_director': director,
                    'vod_content': desc,
                    'vod_play_from': '默认播放源',
                    'vod_play_url': f"第1集${vid}"
                }
            return {
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': pic,
                'type_name': '',
                'vod_year': '',
                'vod_area': '',
                'vod_remarks': '',
                'vod_actor': actor,
                'vod_director': director,
                'vod_content': desc,
                'vod_play_from': '$$$'.join(play_from),
                'vod_play_url': '$$$'.join(play_urls)
            }
        except Exception as e:
            self.log(f"获取详情出错: {str(e)}")
            return None

    def _get_text(self, doc, selectors):
        """通用文本提取【原样保留xj101】"""
        for selector in selectors:
            try:
                texts = doc.xpath(selector)
                for text in texts:
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue
        return ''

    def fetch(self, url, headers=None, method='GET', data=None, timeout=10):
        """网络请求【原样保留xj101】"""
        try:
            if headers is None:
                headers = self.headers
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=timeout, verify=False)
            else:
                response = requests.post(url, headers=headers, data=data, timeout=timeout, verify=False)
            return response
        except Exception as e:
            self.log(f"网络请求失败: {url}, 错误: {str(e)}")

    def localProxy(self, params):
        return [404, "text/plain", "NotImplemented"]
    def action(self, action):
        return {"msg":"运行正常"}
    def liveContent(self): return ""
    def destroy(self): pass
