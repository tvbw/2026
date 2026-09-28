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
_proxy_port = 0
_proxy_started = False
_proxy_session = requests.Session()
_proxy_session.verify = False


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class _ProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            real_url = unquote(self.path[1:])
            if not real_url or not real_url.startswith('http'):
                self.send_response(404); self.end_headers(); return
            r = _proxy_session.get(
                real_url,
                headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'http://hsck.tv/'},
                timeout=20, verify=False)
            ct = r.headers.get('Content-Type', 'image/jpeg')
            self.send_response(200)
            self.send_header('Content-Type', ct)
            self.send_header('Content-Length', len(r.content))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(r.content)
        except:
            self.send_response(404); self.end_headers()

    def log_message(self, format, *args):
        pass


def _start_proxy():
    global _proxy_port, _proxy_started
    if _proxy_started:
        return
    import socket
    sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sk.bind(('127.0.0.1', 0))
    _proxy_port = sk.getsockname()[1]
    sk.close()
    server = _ThreadedHTTPServer(('127.0.0.1', _proxy_port), _ProxyHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _proxy_started = True


# ===== Spider =====
class Spider(BaseSpider):
    session = requests.Session()
    # 【修改】HOSTS 现在只作为"种子域名"使用，运行中 self.host 会被动态更新
    HOSTS = [
        'https://69ck.net/',
        'https://68ck.net/',
        'http://hsck.net',
        'http://hsck.us',
    ]
    DEFAULT_CATEGORIES = [
        {'type_id': '21', 'type_name': '欧美高清'},
        {'type_id': '22', 'type_name': '动漫剧情'}
    ]

    def __init__(self):
        super().__init__()
        self._debug = True
        self._categories_cache = list(self.DEFAULT_CATEGORIES)
        self.host = self._detect_working_host()
        self._log(f'当前域名: {self.host}')

    def _log(self, msg):
        if self._debug:
            print(f'[hsck] {msg}')

    # ==================== 【修改】域名探测 ====================
    def _detect_working_host(self):
        """
        探测可用域名，优先找能正常访问内页（不跨域 301 丢路径）的站点。
        【修改】返回的 host 是重定向后的真实域名，而不是种子域名。
        """
        for host in self.HOSTS:
            try:
                # 1) 先测首页
                r = self.session.get(host, timeout=8, verify=False, allow_redirects=True)
                if r.status_code != 200 or len(r.text) <= 2000:
                    self._log(f'探测失败(首页异常): {host}')
                    continue

                final_parsed = urlparse(r.url.rstrip('/'))
                final_host = f'{final_parsed.scheme}://{final_parsed.netloc}'
                self._log(f'首页OK: {host} -> {final_host} (长度:{len(r.text)})')

                # 2) 再测一个内页，看是否会被重定向到首页（壳站特征）
                test_url = f'{final_host}/vodtype/1-1.html'
                r2 = self.session.get(test_url, timeout=8, verify=False, allow_redirects=True)
                r2_parsed = urlparse(r2.url)

                # 如果内页最终 URL 变成纯域名（路径丢失），说明是壳站，跳过
                if r2_parsed.path in ('', '/') and \
                        r2_parsed.netloc.endswith(('.com', '.xyz', '.net', '.us', '.cc', '.tv')):
                    self._log(f'探测到壳站(内页301丢路径): {host} -> {r2.url}')
                    # 【修改】即使判定为壳站，如果它明确把我们送到了另一个域名，
                    # 也把那个域名记下来，作为后续候选
                    real_host = f'{r2_parsed.scheme}://{r2_parsed.netloc}'
                    if real_host != final_host:
                        self._log(f'  但发现新域名，作为候选: {real_host}')
                        # 用新域名再试一次内页
                        try:
                            r3 = self.session.get(
                                f'{real_host}/vodtype/1-1.html',
                                timeout=8, verify=False, allow_redirects=True)
                            if len(r3.text) > 2000 and \
                                    urlparse(r3.url).path not in ('', '/'):
                                self._log(f'  候选域名可用: {real_host}')
                                return real_host
                        except Exception as e:
                            self._log(f'  候选域名失败: {e}')
                    continue

                if len(r2.text) > 2000:
                    self.host = final_host
                    self._log(f'探测成功: {final_host} (首页:{len(r.text)}, 分类页:{len(r2.text)})')
                    return final_host
                else:
                    self._log(f'探测失败(分类页内容短): {final_host}')
            except Exception as e:
                self._log(f'探测失败: {host} - {e}')
        # 全部失败，返回第一个种子域名兜底
        return self.HOSTS[0]

    # ==================== 【修改】从 HTML 中提取数字域名 ====================
    def _extract_domain_from_html(self, html):
        """
        从页面 HTML 中提取数字域名（如 69ck.net, 68ck.net 等），
        作为备用候选域名。用于网站动态换域名时的自愈。
        """
        if not html:
            return None
        # 匹配 https:// 或 http:// 后面跟数字+ck+后缀 的域名
        domains = re.findall(
            r'https?://(\d{1,3}ck\.(?:net|com|xyz|us|cc|tv|top|vip))',
            html, re.I)
        if not domains:
            return None
        # 去重，且与当前 host 不同
        cur_netloc = urlparse(self.host).netloc
        for d in domains:
            if d.lower() != cur_netloc.lower():
                return f'https://{d}/'
        return None

    # ==================== 基础方法（不变） ====================
    def getName(self):
        return 'hsck'

    def isVideoFormat(self, url):
        return '.m3u8' in url or '.mp4' in url or '.ts' in url or url.startswith('magnet:')

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def localProxy(self, param):
        return [404, 'text/plain', '']

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
            'Referer': referer or (self.host + '/')
        }

    def _proxy_url(self, url):
        if not url:
            return ''
        if url.startswith('http://127.0.0.1'):
            return url
        return f'http://127.0.0.1:{_proxy_port}/{quote(url, safe="")}'

    # ==================== 【核心修改】_fetch 支持递归重定向 ====================
    def _fetch(self, url, referer=None, retries=3, _redirect_depth=0):
        """
        带自愈能力的 HTTP 请求：
        - 检测跨域 301/302；
        - 一旦发现新域名，立即更新 self.host 并递归用新域名 + 原路径请求；
        - 递归深度超过 5 层时停止，防止死循环；
        - 全部失败时尝试种子域名列表和 HTML 中提取的新域名。
        """
        if _redirect_depth > 5:
            self._log(f'重定向深度超过限制: {url}')
            return ''

        # 相对路径 -> 绝对路径（使用当前 self.host）
        if not url.startswith('http'):
            url = urljoin(self.host, url)

        for attempt in range(retries):
            try:
                headers = self._get_headers(referer or self.host + '/')
                r = self.session.get(url, headers=headers, timeout=15,
                                     verify=False, allow_redirects=True)
                final_url = r.url
                parsed_final = urlparse(final_url)
                parsed_req = urlparse(url)

                # ---- 检测跨域重定向 ----
                if parsed_final.netloc != parsed_req.netloc:
                    new_host = f'{parsed_final.scheme}://{parsed_final.netloc}'
                    self._log(f'域名跳转: {parsed_req.netloc} -> {parsed_final.netloc}')
                    # 【关键】持久化新域名，后续所有请求都走这里
                    self.host = new_host

                    # 如果路径被丢了（变成首页），用新域名 + 原路径重新请求
                    if parsed_final.path in ('', '/'):
                        corrected_path = parsed_req.path
                        if parsed_req.query:
                            corrected_path += '?' + parsed_req.query
                        corrected_url = urljoin(new_host, corrected_path)
                        self._log(f'路径丢失，递归修正URL: {corrected_url}')
                        return self._fetch(corrected_url,
                                           referer=new_host + '/',
                                           retries=retries,
                                           _redirect_depth=_redirect_depth + 1)
                    # 路径没丢，说明重定向本身就是有效页面，直接返回
                    if r.status_code == 200 and len(r.text) > 1000:
                        r.encoding = 'utf-8'
                        self._log(f'请求成功(重定向后): {url} -> {final_url} (长度:{len(r.text)})')
                        return r.text

                # ---- 正常返回 ----
                if r.status_code == 200 and len(r.text) > 1000:
                    r.encoding = 'utf-8'
                    self._log(f'请求成功: {url} -> {final_url} (长度:{len(r.text)})')
                    return r.text
                else:
                    self._log(f'请求内容过短: {url} 长度:{len(r.text) if r.text else 0}')
                    # 【新增】内容过短时，尝试从返回的HTML里提取新域名
                    if r.text:
                        new_domain = self._extract_domain_from_html(r.text)
                        if new_domain and new_domain != self.host:
                            self._log(f'从页面提取到新域名: {new_domain}')
                            self.host = new_domain
                            corrected_path = parsed_req.path
                            if parsed_req.query:
                                corrected_path += '?' + parsed_req.query
                            corrected_url = urljoin(new_domain, corrected_path)
                            return self._fetch(corrected_url,
                                               referer=new_domain + '/',
                                               retries=retries,
                                               _redirect_depth=_redirect_depth + 1)
            except Exception as e:
                self._log(f'请求失败 [{attempt+1}]: {url} - {e}')
            time.sleep(1)

        # ---- 备用域名切换（使用种子域名 + 从已获取内容里提取的域名） ----
        parsed_req = urlparse(url)
        fallback_hosts = list(self.HOSTS)
        for h in fallback_hosts:
            if h.rstrip('/') == self.host.rstrip('/'):
                continue
            try:
                new_url = urljoin(
                    h,
                    parsed_req.path + ('?' + parsed_req.query if parsed_req.query else '')
                )
                self._log(f'尝试备用域名: {new_url}')
                r = self.session.get(new_url,
                                     headers=self._get_headers(referer=h + '/'),
                                     timeout=15, verify=False, allow_redirects=True)
                if r.status_code == 200 and len(r.text) > 1000:
                    # 记录真实域名
                    rp = urlparse(r.url)
                    self.host = f'{rp.scheme}://{rp.netloc}'
                    r.encoding = 'utf-8'
                    self._log(f'切换域名成功: {self.host} -> 长度:{len(r.text)}')
                    return r.text
            except Exception:
                pass
        return ''

    # ==================== 工具方法 ====================
    @staticmethod
    def _decode_b64(s):
        try:
            return base64.b64decode(s).decode('utf-8')
        except:
            return s

    # ===== 分类 =====
    def _update_categories(self, text):
        seen_ids = {c['type_id'] for c in self._categories_cache}
        seen_names = {c['type_name'] for c in self._categories_cache}

        def clean_title(raw):
            return re.sub(r'<[^>]+>', '', raw).strip().replace(' ', '')

        menus = re.findall(
            r'<ul[^>]*class=["\'][^"\']*(?:pannel__menu|header__menu)[^"\']*["\'][^>]*>(.*?)</ul>',
            text, re.S)
        scope = '\n'.join(menus) if menus else text
        links = re.findall(
            r'<a[^>]+href=["\']/vodtype/(\d+)(?:-\d+)?\.html["\'][^>]*>(.*?)</a>',
            scope, re.S)
        for tid, raw_name in links:
            name = clean_title(re.sub(r'\d+', '', raw_name))
            if not name or name in seen_names or name in ['首页', '留言', '求片', 'APP', '专题', '排行榜', '最新']:
                continue
            if tid not in seen_ids:
                self._categories_cache.append({'type_id': tid, 'type_name': name})
                seen_ids.add(tid)
                seen_names.add(name)

    def _get_category_name(self, tid):
        for cat in self._categories_cache:
            if cat['type_id'] == str(tid):
                return cat['type_name']
        return f'分类_{tid}'

    # ===== 列表解析（过滤广告 pa-thumb） =====
    def _parse_list(self, html):
        items, seen_vids = [], set()
        cards = re.findall(r'<li[^>]*>(.*?)</li>', html, re.S)
        for card in cards:
            if 'stui-vodlist__box' not in card:
                continue
            a_match = re.search(r'<a[^>]+href="([^"]+)"', card)
            if not a_match:
                continue
            href = a_match.group(1).strip()
            if not (href.startswith('/v5/') or href.startswith('/vodplay/')):
                continue
            if 'pa-thumb' in card:
                continue
            vid_match = re.search(r'/(?:v5|vodplay)/(\d+)', href)
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
                    pic = 'http:' + pic
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
                'vod_remarks': remarks
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
        return {
            'class': cats, 'filters': {}, 'type': '影视',
            'list': items, 'page': 1, 'pagecount': 1,
            'limit': len(items), 'total': len(items)
        }

    def homeVideoContent(self):
        if self._categories_cache:
            return {'list': self._get_list(self._categories_cache[0]['type_id'], 1)}
        return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        items = self._get_list(tid, page)
        return {
            'list': items, 'page': page, 'pagecount': page + 1,
            'limit': len(items), 'total': page + 1
        }

    # ===== 详情 =====
    def detailContent(self, ids):
        vid = str(ids[0] if isinstance(ids, list) else ids)
        detail = self._fetch_detail(vid)
        if not detail:
            detail = {
                'vod_id': vid,
                'vod_name': f'视频_{vid}',
                'vod_pic': '',
                'vod_play_from': '在线播放',
                'vod_play_url': f'线路1${self.host}/v5/{vid}-1-1.html',
                'vod_content': ''
            }
        else:
            if not detail.get('vod_name'):
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
                    if var == 'AID':
                        aid = v.group(1)
                    elif var == 'ASID':
                        asid = v.group(1)
                    elif var == 'ANID':
                        anid = v.group(1)
                    elif var == 'AK':
                        ak = v.group(1)
                    break

        self._log(f'提取参数: AID={aid}, ASID={asid}, ANID={anid}, '
                  f'AK={ak[:20] if ak else "empty"}...')

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
        if id.startswith(self.host):
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
            except:
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
                        if var == 'AID':
                            aid = v.group(1)
                        elif var == 'ASID':
                            asid = v.group(1)
                        elif var == 'ANID':
                            anid = v.group(1)
                        elif var == 'AK':
                            ak = v.group(1)
                        break

        self._log(f'player 提取参数: AID={aid}, ASID={asid}, ANID={anid}, '
                  f'AK={ak[:20] if ak else "empty"}...')

        if aid and ak:
            count_url = self.host + '/static/count.php'
            gx = random.randint(100, 800)
            gy = random.randint(100, 600)
            dt = random.randint(2000, 5000)
            data = {
                'id': aid, 'sid': asid, 'nid': anid, 'tk': ak, 'g': '1',
                'x': gx, 'y': gy, 'dt': dt,
                'sw': 1920, 'sh': 1080,
                'tz': -480, 't': int(time.time() * 1000)
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
                        except:
                            resp_text = r.text.strip()
                            if resp_text.startswith('{'):
                                resp = json.loads(resp_text)
                            else:
                                try:
                                    decoded = base64.b64decode(resp_text).decode('utf-8')
                                    resp = json.loads(decoded)
                                except:
                                    resp = {'ok': False}
                        if resp.get('ok') and resp.get('u'):
                            real_url = base64.b64decode(resp['u']).decode('utf-8')
                            if real_url.startswith('http'):
                                self._log(f'真实地址: {real_url}')
                                return {'parse': 0, 'url': real_url,
                                        'header': {'Referer': self.host}}
                        else:
                            self._log(f'count.php 返回错误: {resp}')
                except Exception as e:
                    self._log(f'count.php 请求失败: {e}')
                time.sleep(1)

        if html:
            all_urls = re.findall(
                r'(https?://[^\s"\'<>]+\.(?:m3u8|mp4|ts)[^\s"\'<>]*)', html)
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
            except:
                pass
        return None


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
    BaseSpider.register(Spider())
