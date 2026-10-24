# -*- coding: utf-8 -*-
import sys, re, json, base64, threading, time, random
import requests, urllib3
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import unquote, quote, urljoin, urlparse

urllib3.disable_warnings()
sys.path.append('..')
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider: pass

# ===== 图片代理（不变） =====
_proxy_port = 0; _proxy_started = False
_proxy_session = requests.Session()
_proxy_session.verify = False
class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer): daemon_threads = True
class _ProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            real_url = unquote(self.path[1:])
            if not real_url or not real_url.startswith('http'):
                self.send_response(404); self.end_headers(); return
            r = _proxy_session.get(real_url, headers={'User-Agent':'Mozilla/5.0','Referer':'http://hsck.tv/'}, timeout=20, verify=False)
            ct = r.headers.get('Content-Type','image/jpeg')
            self.send_response(200); self.send_header('Content-Type',ct)
            self.send_header('Content-Length',len(r.content)); self.send_header('Access-Control-Allow-Origin','*')
            self.end_headers(); self.wfile.write(r.content)
        except:
            self.send_response(404); self.end_headers()
    def log_message(self, format, *args): pass
def _start_proxy():
    global _proxy_port, _proxy_started
    if _proxy_started: return
    import socket
    sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sk.bind(('127.0.0.1',0)); _proxy_port = sk.getsockname()[1]; sk.close()
    server = _ThreadedHTTPServer(('127.0.0.1',_proxy_port), _ProxyHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _proxy_started = True

# ===== Spider =====
class Spider(BaseSpider):
    session = requests.Session()
    HOSTS = [
        'https://222.ahyck.cc/'
        'https://hscangku.com',
    ]
    DEFAULT_CATEGORIES = [
        {'type_id':'1','type_name':'日韩AV'},{'type_id':'2','type_name':'国产系列'},
        {'type_id':'3','type_name':'欧美'},{'type_id':'4','type_name':'成人动漫'},
        {'type_id':'8','type_name':'无码中文字幕'},{'type_id':'9','type_name':'有码中文字幕'},
        {'type_id':'10','type_name':'日本无码'},{'type_id':'7','type_name':'日本有码'},
        {'type_id':'26','type_name':'骑兵破解'},{'type_id':'15','type_name':'国产视频'},
        {'type_id':'21','type_name':'欧美高清'},{'type_id':'22','type_name':'动漫剧情'}
    ]

    def __init__(self):
        super().__init__()
        self._debug = True
        self._categories_cache = list(self.DEFAULT_CATEGORIES)
        self.host = self._detect_working_host()
        self._log(f'当前域名: {self.host}')

    def _log(self, msg):
        if self._debug:
            try:
                print(f'[hsck] {msg}')
            except Exception:
                pass

    # ===== 探测辅助（新增：统一探测请求头，避免部分站拒无 UA 请求） =====
    def _get_probe_headers(self, host=None):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': (host or (self.HOSTS[0] if self.HOSTS else 'https://www.baidu.com')) + '/',
        }

    def _validate_host(self, host, timeout=8):
        """验证 host：首页可访问 + 内页不被跳首页（壳站检测）"""
        try:
            r = self.session.get(host, headers=self._get_probe_headers(host),
                                 timeout=timeout, verify=False, allow_redirects=True)
            if r.status_code != 200 or not r.text or len(r.text) < 2000:
                return False, f'首页异常 HTTP={r.status_code} len={len(r.text) if r.text else 0}'

            p = urlparse(r.url)
            final_host = f'{p.scheme}://{p.netloc}'

            test_url = f'{final_host}/vodtype/1-1.html'
            r2 = self.session.get(test_url, headers=self._get_probe_headers(final_host),
                                  timeout=timeout, verify=False, allow_redirects=True)

            if urlparse(r2.url).path in ('', '/'):
                return False, f'壳站（内页跳首页）: {r2.url}'

            if not r2.text or len(r2.text) < 2000:
                return False, f'内页内容太短: {len(r2.text) if r2.text else 0}'

            return True, final_host
        except Exception as e:
            return False, f'异常: {e}'

    def _detect_working_host(self):
        for host in self.HOSTS:
            ok, info = self._validate_host(host)
            if ok:
                self._log(f'探测成功: {info}')
                return info
            self._log(f'探测失败: {host} - {info}')

        fb = self.HOSTS[0] if self.HOSTS else 'https://www.baidu.com/'
        self._log(f'全部探测失败，使用默认: {fb}')
        return fb

    def getName(self): return 'hsck'
    def isVideoFormat(self, url):
        return '.m3u8' in url or '.mp4' in url or '.ts' in url or url.startswith('magnet:')
    def manualVideoCheck(self): return False
    def destroy(self): pass
    def localProxy(self, param): return [404, 'text/plain', '']

    def init(self, extend=''):
        self.session.verify = False
        self.session.headers.update(self._get_headers())
        _start_proxy()
        text = self._fetch(self.host + '/')
        if text and len(text) > 2000:
            self._update_categories(text)
        else:
            self._log('首页加载失败或内容太短，使用默认分类')

    def _get_headers(self, referer=None):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': referer or (self.host + '/' if self.host else 'https://www.baidu.com/'),
        }

    def _proxy_url(self, url):
        if not url: return ''
        if url.startswith('http://127.0.0.1'): return url
        return f'http://127.0.0.1:{_proxy_port}/{quote(url, safe="")}'

    # ===== 核心：带跳转保护的请求（重点重构） =====
    def _fetch(self, url, referer=None, retries=3, _depth=0):
        """
        跳转保护：
          - 302 自动跟随（requests 默认）
          - 跳转深度限制 _depth <= 2，防循环
          - 壳站（内页被跳首页）→ 修正路径重试，**成功才切换 host**
          - 修正失败保持原 host，不污染 self.host
          - referer 原样透传
        """
        if not url.startswith('http'):
            url = urljoin(self.host, url)

        for attempt in range(retries):
            try:
                headers = self._get_headers(referer or self.host + '/')
                r = self.session.get(url, headers=headers, timeout=15, verify=False)
                final_url = r.url
                parsed_final = urlparse(final_url)
                parsed_req = urlparse(url)

                # === 域名跳转处理 ===
                if parsed_final.netloc != parsed_req.netloc:
                    if _depth >= 2:
                        self._log(f'跳转深度超限，放弃: {url} -> {final_url}')
                        return ''

                    new_host = f'{parsed_final.scheme}://{parsed_final.netloc}'

                    # 壳站：内页被跳首页
                    if parsed_final.path in ('', '/') and parsed_req.path not in ('', '/'):
                        corrected_path = parsed_req.path + ('?' + parsed_req.query if parsed_req.query else '')
                        corrected_url = new_host + corrected_path
                        self._log(f'壳站跳转，修正URL重试: {corrected_url}')

                        # 用原 referer 递归请求，深度+1
                        corrected_html = self._fetch(
                            corrected_url, referer=referer, retries=1, _depth=_depth + 1
                        )
                        if corrected_html:
                            old_host = self.host
                            self.host = new_host
                            self._log(f'域名切换确认: {old_host} -> {new_host}')
                            return corrected_html
                        else:
                            self._log(f'修正失败，保持原域名: {self.host}')
                            return ''
                    else:
                        # 内页正常跳转（路径保留），新域名可信
                        old_host = self.host
                        self.host = new_host
                        self._log(f'域名跳转: {old_host} -> {new_host}')

                if r.status_code == 200 and r.text and len(r.text) > 1000:
                    r.encoding = 'utf-8'
                    return r.text

                self._log(f'内容过短/异常: {url} HTTP={r.status_code} len={len(r.text) if r.text else 0}')
            except Exception as e:
                self._log(f'请求失败 [{attempt+1}]: {url} - {e}')
            time.sleep(1)

        # 全部重试失败，尝试备用域名（保持原有兜底）
        base_path = urlparse(url).path
        base_query = ('?' + urlparse(url).query) if urlparse(url).query else ''
        for h in self.HOSTS:
            if h == self.host:
                continue
            try:
                new_url = h + base_path + base_query
                r = self.session.get(new_url, headers=self._get_headers(referer or h + '/'),
                                     timeout=15, verify=False)
                if r.status_code == 200 and r.text and len(r.text) > 1000:
                    self.host = h
                    r.encoding = 'utf-8'
                    self._log(f'切换备用域名成功: {h}')
                    return r.text
            except Exception:
                pass

        return ''

    @staticmethod
    def _decode_b64(s):
        try: return base64.b64decode(s).decode('utf-8')
        except: return s

    # ===== 分类 =====
    def _update_categories(self, text):
        seen_ids = {c['type_id'] for c in self._categories_cache}
        seen_names = {c['type_name'] for c in self._categories_cache}
        def clean_title(raw): return re.sub(r'<[^>]+>', '', raw).strip().replace(' ', '')
        menus = re.findall(r'<ul[^>]*class=["\'][^"\']*(?:pannel__menu|header__menu)[^"\']*["\'][^>]*>(.*?)</ul>', text, re.S)
        scope = '\n'.join(menus) if menus else text
        links = re.findall(r'<a[^>]+href=["\']/vodtype/(\d+)(?:-\d+)?\.html["\'][^>]*>(.*?)</a>', scope, re.S)
        for tid, raw_name in links:
            name = clean_title(re.sub(r'\d+', '', raw_name))
            if not name or name in seen_names or name in ['首页','留言','求片','APP','专题','排行榜','最新']:
                continue
            if tid not in seen_ids:
                self._categories_cache.append({'type_id': tid, 'type_name': name})
                seen_ids.add(tid); seen_names.add(name)

    def _get_category_name(self, tid):
        for cat in self._categories_cache:
            if cat['type_id'] == str(tid): return cat['type_name']
        return f'分类_{tid}'

    # ===== 列表解析（兼容相对/绝对 URL） =====
    def _parse_list(self, html):
        items, seen_vids = [], set()
        if not html:
            return items
        cards = re.findall(r'<li[^>]*>(.*?)</li>', html, re.S)
        for card in cards:
            if 'stui-vodlist__box' not in card:
                continue
            if 'pa-thumb' in card:
                continue

            a_match = re.search(r'<a[^>]+href="([^"]+)"', card)
            if not a_match:
                continue
            href = a_match.group(1).strip()

            # 兼容绝对 URL：统一取 path 判断
            if href.startswith('http'):
                check_path = urlparse(href).path
            else:
                check_path = href.split('?')[0]

            if not (check_path.startswith('/v5/') or check_path.startswith('/vodplay/')):
                continue

            vid_match = re.search(r'/(?:v5|vodplay)/(\d+)', check_path)
            if not vid_match:
                continue
            vid = vid_match.group(1)
            if vid in seen_vids:
                continue
            seen_vids.add(vid)

            title = ''
            h4 = re.search(r'<h4[^>]*class="title"[^>]*>\s*<a[^>]*>(.*?)</a>', card, re.S)
            if h4:
                title = h4.group(1).strip()
            else:
                t_attr = re.search(r'title="([^"]+)"', card)
                if t_attr:
                    title = t_attr.group(1).strip()
                else:
                    inner = re.search(r'<a[^>]*>(.*?)</a>', card, re.S)
                    if inner:
                        title = re.sub(r'<[^>]+>', '', inner.group(1)).strip()
            if not title:
                title = vid

            pic = ''
            img = re.search(r'data-original="([^"]+)"', card)
            if img:
                pic = img.group(1)
                if pic.startswith('//'):
                    pic = 'https:' + pic   # 原为 http:，避免混合内容
                elif pic.startswith('/'):
                    pic = self.host + pic

            remarks = ''
            t_span = re.search(r'<span[^>]*class="[^"]*pic-text[^"]*">(.*?)</span>', card, re.S)
            if t_span:
                remarks = re.sub(r'<[^>]+>', '', t_span.group(1)).strip()

            items.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': self._proxy_url(pic),
                'vod_remarks': remarks,
            })
        self._log(f'解析到 {len(items)} 个视频')
        return items

    def _get_list(self, tid, page):
        url = f'{self.host}/vodtype/{tid}-{page}.html'
        html = self._fetch(url, referer=f'{self.host}/vodtype/{tid}-1.html')
        return self._parse_list(html) if html else []

    # ===== 首页/分类 =====
    def homeContent(self, filter):
        text = self._fetch(self.host + '/')
        if text and len(text) > 2000:
            self._update_categories(text)
        cats = self._categories_cache
        items = self._get_list(cats[0]['type_id'], 1) if cats else []
        return {'class': cats, 'filters': {}, 'type': '影视', 'list': items,
                'page': 1, 'pagecount': 1, 'limit': len(items), 'total': len(items)}

    def homeVideoContent(self):
        if self._categories_cache:
            return {'list': self._get_list(self._categories_cache[0]['type_id'], 1)}
        return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        items = self._get_list(tid, page)
        return {'list': items, 'page': page, 'pagecount': page + 1,
                'limit': len(items), 'total': page + 1}

    # ===== 详情 =====
    def detailContent(self, ids):
        vid = str(ids[0] if isinstance(ids, list) else ids)
        detail = self._fetch_detail(vid)
        if not detail:
            detail = {'vod_id': vid, 'vod_name': f'视频_{vid}', 'vod_pic': '',
                      'vod_play_from': '在线播放',
                      'vod_play_url': f'线路1${self.host}/v5/{vid}-1-1.html',
                      'vod_content': ''}
        elif not detail.get('vod_name'):
            detail['vod_name'] = f'视频_{vid}'
        return {'list': [detail]}

    def _fetch_detail(self, vid):
        url = f'{self.host}/v5/{vid}-1-1.html'
        html = self._fetch(url, referer=self.host)
        if not html:
            url = f'{self.host}/voddetail/{vid}.html'
            html = self._fetch(url, referer=self.host)
        return self._parse_detail(html, vid) if html else None

    def _parse_detail(self, html, vid):
        title = ''
        m = re.search(r'<title>(.*?)</title>', html, re.S)
        if m:
            full_title = m.group(1).strip()
            parts = full_title.split(' - ')
            if len(parts) >= 2:
                title = ' - '.join(parts[:-1]).strip()
            else:
                title = full_title
        if not title:
            h3_matches = re.findall(r'<h3[^>]*class="title"[^>]*>(.*?)</h3>', html, re.S)
            for h3 in h3_matches:
                clean = re.sub(r'<[^>]+>', '', h3).strip()
                if clean and clean not in ['目录', '精选内容', '']:
                    title = clean
                    break
        if not title:
            m = re.search(r'<h1[^>]*class="title"[^>]*>(.*?)</h1>', html, re.S)
            if m:
                title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if not title:
            title = f'视频_{vid}'

        cover = ''
        m = re.search(r'data-original="([^"]+)"', html)
        if m:
            cover = m.group(1)

        aid = asid = anid = ak = ''
        for var in ['AID', 'ASID', 'ANID', 'AK']:
            patterns = [
                r"var\s+" + var + r"\s*=\s*'([^']+)'",
                var + r"\s*=\s*'([^']+)'",
                r'var\s+' + var + r'\s*=\s*"([^"]+)"',
                var + r'\s*=\s*"([^"]+)"',
            ]
            for p in patterns:
                v = re.search(p, html)
                if v:
                    if var == 'AID': aid = v.group(1)
                    elif var == 'ASID': asid = v.group(1)
                    elif var == 'ANID': anid = v.group(1)
                    elif var == 'AK': ak = v.group(1)
                    break

        self._log(f'提取参数: AID={aid}, ASID={asid}, ANID={anid}, AK={ak[:20] if ak else "empty"}...')

        play_url = f'{self.host}/v5/{vid}-1-1.html'
        if aid and ak:
            play_url += f'?aid={aid}&asid={asid}&anid={anid}&ak={ak}'

        return {
            'vod_id': vid,
            'vod_name': title,
            'vod_pic': self._proxy_url(cover) if cover else '',
            'vod_play_from': '在线播放',
            'vod_play_url': f'线路1${play_url}',
            'vod_content': title,
        }

    # ===== 播放器 =====
    def playerContent(self, flag, id, vipFlags=None):
        self._log(f'playerContent: id={id[:120] if len(id) > 120 else id}')
        if '.m3u8' in id or '.mp4' in id:
            return {'parse': 0, 'url': id,
                    'header': {'User-Agent': 'Mozilla/5.0', 'Referer': self.host}}

        detail_url = id
        html = ''

        # 兼容任意域名的完整 URL（原逻辑用 id.startswith(self.host)，host 变了会判错）
        if id.startswith('http'):
            html = self._fetch(id, referer=self.host)
        elif 'aid=' not in id:
            vid_match = re.search(r'/(\d+)-1-1\.html', id)
            if vid_match:
                detail_url = f'{self.host}/v5/{vid_match.group(1)}-1-1.html'
                html = self._fetch(detail_url, referer=self.host)

        if html:
            m = re.search(r'["\'](https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*)["\']', html)
            if m:
                return {'parse': 0, 'url': m.group(1), 'header': {'Referer': self.host}}

        if html:
            m3u8 = self._extract_player_aaaa(html)
            if m3u8:
                return {'parse': 0, 'url': m3u8, 'header': {'Referer': self.host}}

        aid = asid = anid = ak = ''
        if 'aid=' in id:
            try:
                ps = dict(p.split('=') for p in id.split('?')[1].split('&'))
                aid = ps.get('aid', '')
                asid = ps.get('asid', '1')
                anid = ps.get('anid', '1')
                ak = ps.get('ak', '')
            except Exception:
                pass
        elif html:
            for var in ['AID', 'ASID', 'ANID', 'AK']:
                patterns = [
                    r"var\s+" + var + r"\s*=\s*'([^']+)'",
                    var + r"\s*=\s*'([^']+)'",
                    r'var\s+' + var + r'\s*=\s*"([^"]+)"',
                    var + r'\s*=\s*"([^"]+)"',
                ]
                for p in patterns:
                    v = re.search(p, html)
                    if v:
                        if var == 'AID': aid = v.group(1)
                        elif var == 'ASID': asid = v.group(1)
                        elif var == 'ANID': anid = v.group(1)
                        elif var == 'AK': ak = v.group(1)
                        break

        self._log(f'player 提取参数: AID={aid}, ASID={asid}, ANID={anid}, AK={ak[:20] if ak else "empty"}...')

        if aid and ak:
            count_url = self.host + '/static/count.php'
            gx = random.randint(100, 800)
            gy = random.randint(100, 600)
            dt = random.randint(2000, 5000)
            data = {
                'id': aid, 'sid': asid, 'nid': anid, 'tk': ak, 'g': '1',
                'x': gx, 'y': gy, 'dt': dt,
                'sw': 1920, 'sh': 1080,
                'tz': -480, 't': int(time.time() * 1000),
            }
            headers = self._get_headers(referer=detail_url)
            headers.update({
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'Origin': self.host,
            })
            for retry in range(3):
                try:
                    self._log(f'请求 count.php (重试{retry}): id={aid}, sid={asid}, nid={anid}')
                    r = self.session.post(count_url, data=data, headers=headers, timeout=15)
                    self._log(f'count.php 响应: {r.status_code}, 内容: {r.text[:200]}')
                    if r.status_code == 200:
                        try:
                            resp = r.json()
                        except Exception:
                            resp_text = r.text.strip()
                            if resp_text.startswith('{'):
                                resp = json.loads(resp_text)
                            else:
                                try:
                                    decoded = base64.b64decode(resp_text).decode('utf-8')
                                    resp = json.loads(decoded)
                                except Exception:
                                    resp = {'ok': False}
                        if resp.get('ok') and resp.get('u'):
                            real_url = base64.b64decode(resp['u']).decode('utf-8')
                            if real_url.startswith('http'):
                                self._log(f'真实地址: {real_url}')
                                return {'parse': 0, 'url': real_url, 'header': {'Referer': self.host}}
                        else:
                            self._log(f'count.php 返回错误: {resp}')
                except Exception as e:
                    self._log(f'count.php 请求失败: {e}')
                time.sleep(1)

        if html:
            all_urls = re.findall(r'(https?://[^\s"\'<>]+\.(?:m3u8|mp4|ts)[^\s"\'<>]*)', html)
            if all_urls:
                return {'parse': 0, 'url': all_urls[0], 'header': {'Referer': self.host}}

        return {'parse': 1, 'url': detail_url,
                'header': {'User-Agent': 'Mozilla/5.0', 'Referer': self.host}}

    def _extract_player_aaaa(self, html):
        m = re.search(r'var\s+player_aaaa\s*=\s*({.*?});', html, re.S)
        if not m:
            m = re.search(r'player_aaaa\s*=\s*({.*?});', html, re.S)
        if m:
            try:
                cfg = json.loads(m.group(1).replace('\\/', '/'))
                url = cfg.get('url')
                if url and '.m3u8' in url:
                    if not url.startswith('http'):
                        url = urljoin(self.host, url)
                    return url
            except Exception:
                pass
        return None

    # ===== 搜索 =====
    def searchContent(self, key, quick, pg='1'):
        page = int(pg) if pg else 1
        url = f'{self.host}/vodsearch/{quote(key)}-------------{page}---.html'
        html = self._fetch(url, referer=self.host)
        items = self._parse_list(html) if html else []
        return {'list': items, 'page': page, 'pagecount': page + 1,
                'limit': len(items), 'total': len(items)}
