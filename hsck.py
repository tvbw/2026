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

# ===== 可选依赖：curl_cffi（有则用，无则降级 requests）=====
try:
    from curl_cffi import requests as cffi_requests
    _HAS_CFFI = True
except Exception:
    cffi_requests = None
    _HAS_CFFI = False

# ===== 图片代理 =====
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
            r = _proxy_session.get(real_url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'http://hsck.tv/'}, timeout=20, verify=False)
            ct = r.headers.get('Content-Type', 'image/jpeg')
            self.send_response(200)
            self.send_header('Content-Type', ct)
            self.send_header('Content-Length', len(r.content))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(r.content)
        except Exception:
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
    HOSTS = ('https://hscangku.com',)

    DEFAULT_CATEGORIES = [
        {'type_id':'15','type_name':'国产视频'},{'type_id':'8','type_name':'无码中文字幕'},{'type_id':'26','type_name':'骑兵破解'},
        {'type_id':'10','type_name':'日本无码'},{'type_id':'7','type_name':'日本有码'},{'type_id':'1','type_name':'日韩AV'},
        {'type_id':'9','type_name':'有码中文字幕'},{'type_id':'21','type_name':'欧美高清'},{'type_id':'22','type_name':'动漫剧情'}
    ]

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self._debug = True
        self._categories_cache = list(self.DEFAULT_CATEGORIES)
        self.host = self.HOSTS[0]
        self.session.verify = False
        try:
            self.session.headers.update(self._get_headers())
        except Exception:
            pass
        try:
            detected = self._detect_working_host()
            if detected:
                self.host = detected
        except Exception as e:
            self._log(f'探测异常，使用默认域名: {type(e).__name__}: {e}')
        self._log(f'当前域名: {self.host}, curl_cffi可用={_HAS_CFFI}')

    # ---------- 基础 ----------
    def _log(self, msg):
        if self._debug:
            try:
                print(f'[hsck] {msg}')
            except Exception:
                pass

    def _get_headers(self, referer=None):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': referer or (getattr(self, 'host', self.HOSTS[0]) + '/'),
        }

    def _get_headers_cffi(self, referer=None):
        # curl_cffi 下不传 UA/Accept/Accept-Language，让 impersonate 自己管理
        return {'Referer': referer or (getattr(self, 'host', self.HOSTS[0]) + '/')}

    def _http_request(self, method, url, referer=None, data=None, timeout=15, allow_redirects=True, extra_headers=None):
        """
        统一请求入口：
        1) 优先 curl_cffi（若可用），自动尝试多个 impersonate 版本
        2) 全部失败则降级 requests
        3) 任何异常返回 None，绝不抛出
        """
        # --- curl_cffi ---
        if _HAS_CFFI and cffi_requests is not None:
            for ver in ("chrome124", "chrome120", "chrome110"):
                try:
                    hdrs = self._get_headers_cffi(referer)
                    if extra_headers:
                        hdrs.update(extra_headers)
                    kw = dict(impersonate=ver, timeout=timeout,
                              allow_redirects=allow_redirects,
                              verify=False, headers=hdrs)
                    if method.upper() == "POST":
                        return cffi_requests.post(url, data=data, **kw)
                    return cffi_requests.get(url, **kw)
                except TypeError:
                    continue
                except Exception as e:
                    self._log(f'cffi[{ver}] 失败: {type(e).__name__}: {e}')
                    continue

        # --- requests 降级 ---
        try:
            hdrs = self._get_headers(referer)
            if extra_headers:
                hdrs.update(extra_headers)
            if method.upper() == "POST":
                return self.session.post(url, data=data, timeout=timeout,
                                         allow_redirects=allow_redirects,
                                         verify=False, headers=hdrs)
            return self.session.get(url, timeout=timeout,
                                    allow_redirects=allow_redirects,
                                    verify=False, headers=hdrs)
        except Exception as e:
            self._log(f'requests 失败: {type(e).__name__}: {e}')
            return None

    # ---------- 域名探测 ----------
    def _detect_working_host(self):
        for seed_host in self.HOSTS:
            try:
                r = self._http_request("GET", seed_host, referer=seed_host + '/', timeout=8, allow_redirects=False)
                if r is None:
                    self._log(f'探测 {seed_host} 无响应')
                    continue

                target_url = None
                if r.status_code in (301, 302, 303, 307, 308):
                    target_url = r.headers.get('Location')
                    self._log(f'重定向: {seed_host} -> {target_url}')
                elif r.status_code == 200:
                    if len(r.text) > 2000:
                        self._log(f'无重定向直接可用: {seed_host}')
                        return seed_host
                    self._log(f'无重定向但内容短: {seed_host} len={len(r.text)}')
                    continue
                else:
                    self._log(f'{seed_host} status={r.status_code}')
                    continue

                if not target_url:
                    self._log(f'{seed_host} 重定向无 Location')
                    continue
                if not target_url.startswith('http'):
                    target_url = urljoin(seed_host, target_url)

                parsed = urlparse(target_url)
                new_host = f'{parsed.scheme}://{parsed.netloc}'

                # 二次验证：内页是否可用
                r2 = self._http_request("GET", f'{new_host}/vodtype/1-1.html',
                                        referer=seed_host + '/', timeout=10, allow_redirects=True)
                if r2 is None:
                    self._log(f'{new_host} 内页无响应')
                    continue
                if urlparse(r2.url).path in ('', '/') and r2.url.rstrip('/') == new_host.rstrip('/'):
                    self._log(f'{new_host} 是壳站，跳过')
                    continue
                if r2.status_code == 200 and len(r2.text) > 2000:
                    self._log(f'探测成功: {new_host}')
                    return new_host
                self._log(f'{new_host} 内页验证失败 status={r2.status_code} len={len(r2.text) if r2.text else 0}')
            except Exception as e:
                self._log(f'探测 {seed_host} 异常: {type(e).__name__}: {e}')
                continue
        self._log('探测全部失败，回退默认域名')
        return self.HOSTS[0]

    # ---------- 通用工具 ----------
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

    def _proxy_url(self, url):
        if not url:
            return ''
        if url.startswith('http://127.0.0.1'):
            return url
        return f'http://127.0.0.1:{_proxy_port}/{quote(url, safe="")}'

    def _fetch(self, url, referer=None, retries=3):
        if not url.startswith('http'):
            url = urljoin(self.host, url)
        for attempt in range(retries):
            try:
                r = self._http_request("GET", url, referer=referer or self.host + '/',
                                       timeout=15, allow_redirects=True)
                if r is None:
                    time.sleep(1)
                    continue

                final_url = r.url
                p_final = urlparse(final_url)
                p_req = urlparse(url)
                if p_final.netloc != p_req.netloc:
                    new_host = f'{p_final.scheme}://{p_final.netloc}'
                    self._log(f'域名跳转: {p_req.netloc} -> {p_final.netloc}')
                    self.host = new_host
                    if p_final.path in ('', '/'):
                        corrected = urljoin(new_host, p_req.path + ('?' + p_req.query if p_req.query else ''))
                        r = self._http_request("GET", corrected,
                                               referer=referer or new_host + '/',
                                               timeout=15, allow_redirects=True)
                        if r is not None:
                            final_url = r.url

                if r is not None and r.status_code == 200 and len(r.text) > 1000:
                    try:
                        r.encoding = 'utf-8'
                    except Exception:
                        pass
                    self._log(f'请求成功: {url} -> {final_url} (长度:{len(r.text)})')
                    return r.text
                if r is not None:
                    self._log(f'内容过短: {url} 长度:{len(r.text) if r.text else 0}')
            except Exception as e:
                self._log(f'请求异常 [{attempt+1}]: {url} - {type(e).__name__}: {e}')
            time.sleep(1)

        # 备用域名（当前只有一个，留扩展位）
        for h in self.HOSTS:
            if h == self.host:
                continue
            try:
                new_url = urljoin(h, urlparse(url).path + ('?' + urlparse(url).query if urlparse(url).query else ''))
                r = self._http_request("GET", new_url, referer=referer or h + '/',
                                       timeout=15, allow_redirects=True)
                if r is not None and r.status_code == 200 and len(r.text) > 1000:
                    self.host = h
                    try:
                        r.encoding = 'utf-8'
                    except Exception:
                        pass
                    self._log(f'切换域名成功: {h} 长度:{len(r.text)}')
                    return r.text
            except Exception:
                pass
        return ''

    @staticmethod
    def _decode_b64(s):
        try:
            return base64.b64decode(s).decode('utf-8')
        except Exception:
            return s

    # ---------- 生命周期 ----------
    def init(self, extend=''):
        try:
            self.session.verify = False
            self.session.headers.update(self._get_headers())
        except Exception:
            pass
        try:
            _start_proxy()
        except Exception as e:
            self._log(f'启动图片代理失败: {e}')
        text = self._fetch(self.host + '/')
        if text and len(text) > 2000:
            self._update_categories(text)
        else:
            self._log('首页加载失败或过短，使用默认分类')

    # ---------- 分类 ----------
    def _update_categories(self, text):
        seen_ids = {c['type_id'] for c in self._categories_cache}
        seen_names = {c['type_name'] for c in self._categories_cache}

        def clean_title(raw):
            return re.sub(r'<[^>]+>', '', raw).strip().replace(' ', '')

        try:
            menus = re.findall(r'<ul[^>]*class=["\'][^"\']*(?:pannel__menu|header__menu)[^"\']*["\'][^>]*>(.*?)</ul>', text, re.S)
            scope = '\n'.join(menus) if menus else text
            links = re.findall(r'<a[^>]+href=["\']/vodtype/(\d+)(?:-\d+)?\.html["\'][^>]*>(.*?)</a>', scope, re.S)
            for tid, raw_name in links:
                name = clean_title(re.sub(r'\d+', '', raw_name))
                if not name or name in seen_names:
                    continue
                if name in ('首页', '留言', '求片', 'APP', '专题', '排行榜', '最新'):
                    continue
                if tid not in seen_ids:
                    self._categories_cache.append({'type_id': tid, 'type_name': name})
                    seen_ids.add(tid)
                    seen_names.add(name)
        except Exception as e:
            self._log(f'更新分类异常: {e}')

    def _get_category_name(self, tid):
        for cat in self._categories_cache:
            if cat['type_id'] == str(tid):
                return cat['type_name']
        return f'分类_{tid}'

    # ---------- 列表 ----------
    def _parse_list(self, html):
        items, seen_vids = [], set()
        if not html:
            return items
        try:
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
                if not (href.startswith('/v5/') or href.startswith('/vodplay/')):
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
                    'vod_remarks': remarks,
                })
        except Exception as e:
            self._log(f'解析列表异常: {e}')
        self._log(f'解析到 {len(items)} 个视频')
        return items

    def _get_list(self, tid, page):
        url = f'{self.host}/vodtype/{tid}-{page}.html'
        html = self._fetch(url, referer=f'{self.host}/vodtype/{tid}-1.html')
        return self._parse_list(html) if html else []

    # ---------- 首页 / 分类 ----------
    def homeContent(self, filter):
        try:
            text = self._fetch(self.host + '/')
            if text and len(text) > 2000:
                self._update_categories(text)
        except Exception:
            pass
        cats = list(self._categories_cache)
        items = []
        try:
            if cats:
                items = self._get_list(cats[0]['type_id'], 1)
        except Exception:
            pass
        return {'class': cats, 'filters': {}, 'type': '影视', 'list': items,
                'page': 1, 'pagecount': 1, 'limit': len(items), 'total': len(items)}

    def homeVideoContent(self):
        try:
            if self._categories_cache:
                return {'list': self._get_list(self._categories_cache[0]['type_id'], 1)}
        except Exception:
            pass
        return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg) if pg else 1
        except Exception:
            page = 1
        try:
            items = self._get_list(tid, page)
        except Exception:
            items = []
        return {'list': items, 'page': page, 'pagecount': page + 1,
                'limit': len(items), 'total': page + 1}

    # ---------- 详情 ----------
    def detailContent(self, ids):
        try:
            vid = str(ids[0] if isinstance(ids, list) else ids)
        except Exception:
            vid = ''
        if not vid:
            return {'list': []}
        detail = None
        try:
            detail = self._fetch_detail(vid)
        except Exception as e:
            self._log(f'详情异常: {e}')
        if not detail:
            detail = {
                'vod_id': vid,
                'vod_name': f'视频_{vid}',
                'vod_pic': '',
                'vod_play_from': '在线播放',
                'vod_play_url': f'线路1${self.host}/v5/{vid}-1-1.html',
                'vod_content': '',
            }
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
            title = ' - '.join(parts[:-1]).strip() if len(parts) >= 2 else full_title
        if not title:
            for h3 in re.findall(r'<h3[^>]*class="title"[^>]*>(.*?)</h3>', html, re.S):
                clean = re.sub(r'<[^>]+>', '', h3).strip()
                if clean and clean not in ('目录', '精选内容', ''):
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
        for var in ('AID', 'ASID', 'ANID', 'AK'):
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
        self._log(f'提取参数: AID={aid}, ASID={asid}, ANID={anid}, AK={(ak[:20] + "...") if ak else "empty"}')

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

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags=None):
        try:
            return self._player_content(flag, id, vipFlags)
        except Exception as e:
            self._log(f'playerContent 异常: {e}')
            return {'parse': 1, 'url': id, 'header': {'User-Agent': 'Mozilla/5.0', 'Referer': self.host}}

    def _player_content(self, flag, id, vipFlags):
        self._log(f'playerContent: id={id[:120] if len(id) > 120 else id}')
        if '.m3u8' in id or '.mp4' in id:
            return {'parse': 0, 'url': id, 'header': {'User-Agent': 'Mozilla/5.0', 'Referer': self.host}}

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
            for var in ('AID', 'ASID', 'ANID', 'AK'):
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

        self._log(f'player 参数: AID={aid}, ASID={asid}, ANID={anid}, AK={(ak[:20] + "...") if ak else "empty"}')

        if aid and ak:
            count_url = self.host + '/static/count.php'
            data = {
                'id': aid, 'sid': asid, 'nid': anid, 'tk': ak, 'g': '1',
                'x': random.randint(100, 800),
                'y': random.randint(100, 600),
                'dt': random.randint(2000, 5000),
                'sw': 1920, 'sh': 1080,
                'tz': -480, 't': int(time.time() * 1000),
            }
            for retry in range(3):
                r = self._http_request(
                    "POST", count_url,
                    referer=detail_url, data=data, timeout=15,
                    extra_headers={
                        'X-Requested-With': 'XMLHttpRequest',
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'Origin': self.host,
                    },
                )
                if r is None:
                    time.sleep(1)
                    continue
                self._log(f'count.php 响应: {r.status_code}, 内容: {r.text[:200]}')
                if r.status_code == 200:
                    resp = None
                    try:
                        resp = r.json()
                    except Exception:
                        resp_text = (r.text or '').strip()
                        if resp_text.startswith('{'):
                            try:
                                resp = json.loads(resp_text)
                            except Exception:
                                resp = None
                        if resp is None:
                            try:
                                resp = json.loads(base64.b64decode(resp_text).decode('utf-8'))
                            except Exception:
                                resp = {'ok': False}
                    if isinstance(resp, dict) and resp.get('ok') and resp.get('u'):
                        try:
                            real_url = base64.b64decode(resp['u']).decode('utf-8')
                        except Exception:
                            real_url = ''
                        if real_url.startswith('http'):
                            self._log(f'真实地址: {real_url}')
                            return {'parse': 0, 'url': real_url, 'header': {'Referer': self.host}}
                    else:
                        self._log(f'count.php 返回异常: {resp}')
                time.sleep(1)

        if html:
            all_urls = re.findall(r'(https?://[^\s"\'<>]+\.(?:m3u8|mp4|ts)[^\s"\'<>]*)', html)
            if all_urls:
                return {'parse': 0, 'url': all_urls[0], 'header': {'Referer': self.host}}

        return {'parse': 1, 'url': detail_url, 'header': {'User-Agent': 'Mozilla/5.0', 'Referer': self.host}}

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

    # ---------- 搜索 ----------
    def searchContent(self, key, quick, pg='1'):
        try:
            page = int(pg) if pg else 1
        except Exception:
            page = 1
        try:
            url = f'{self.host}/vodsearch/{quote(key)}-------------{page}---.html'
            html = self._fetch(url, referer=self.host)
            items = self._parse_list(html) if html else []
        except Exception as e:
            self._log(f'搜索异常: {e}')
            items = []
        return {'list': items, 'page': page, 'pagecount': page + 1,
                'limit': len(items), 'total': len(items)}


# ===== PAGE_PLAYLIST_START =====
def _pl_install(_C):
    if getattr(_C, "_pl_patched", False):
        return _C
    _C._pl_patched = True
    _orig_init = getattr(_C, "init", None)
    _orig_home = getattr(_C, "homeContent", None)
    _orig_homev = getattr(_C, "homeVideoContent", None)
    _orig_cate = getattr(_C, "categoryContent", None)
    _orig_detail = getattr(_C, "detailContent", None)
    _orig_search = getattr(_C, "searchContent", None)
    _orig_searchp = getattr(_C, "searchContentPage", None)
    _orig_player = getattr(_C, "playerContent", None)

    def _ensure(self):
        if not hasattr(self, "page_cache"):
            self.page_cache = {}
            self.page_index = {}
            self.page_keys = []
            self._src_cache = {}

    def _clean(s):
        return str(s or "").replace("$", " ").replace("#", " ").strip()

    def _enc(s):
        try:
            from urllib.parse import quote
            return quote(str(s or ""), safe="")
        except Exception:
            return str(s or "")

    def _dec(s):
        try:
            from urllib.parse import unquote
            return unquote(str(s or ""))
        except Exception:
            return str(s or "")

    def _cache_page(self, key, items):
        _ensure(self)
        out = []
        for x in items or []:
            if isinstance(x, dict) and x.get("vod_id"):
                out.append(x)
        if not out:
            return
        self.page_cache[key] = out
        if key in self.page_keys:
            self.page_keys.remove(key)
        self.page_keys.append(key)
        for it in out:
            self.page_index[str(it["vod_id"])] = key
        while len(self.page_keys) > 30:
            old = self.page_keys.pop(0)
            self.page_cache.pop(old, None)

    def _page_of(self, vid):
        _ensure(self)
        key = self.page_index.get(str(vid))
        if key in self.page_cache:
            return list(self.page_cache[key])
        return []

    def _as_result(r):
        if r is None:
            return {}
        if isinstance(r, dict):
            return r
        if isinstance(r, (bytes, bytearray)):
            r = r.decode("utf-8", "ignore")
        if isinstance(r, str):
            s = r.strip()
            if s.startswith("{") or s.startswith("["):
                try:
                    import json as _j
                    return _j.loads(s)
                except Exception:
                    return {}
        return {}

    def _split_sources(vod):
        fr = str((vod or {}).get("vod_play_from") or "").split("$$$")
        ur = str((vod or {}).get("vod_play_url") or "").split("$$$")
        while len(ur) < len(fr):
            ur.append("")
        sources = []
        for i, name in enumerate(fr):
            parts = []
            for p in (ur[i] or "").split("#"):
                if not p:
                    continue
                if "$" in p:
                    n, u = p.split("$", 1)
                else:
                    n, u = str(i + 1), p
                parts.append((_clean(n), u))
            sources.append((_clean(name) or ("线路%d" % (i + 1)), parts))
        return [x for x in sources if x[1]]

    def _call_detail(self, vid):
        if not _orig_detail:
            return {}
        try:
            return _as_result(_orig_detail(self, [vid]))
        except TypeError:
            try:
                return _as_result(_orig_detail(self, vid))
            except Exception:
                return {}
        except Exception:
            return {}

    def _load_src(self, vid):
        _ensure(self)
        vid = str(vid)
        if vid in self._src_cache:
            return self._src_cache[vid]
        r = self._pl_call_detail(vid)
        vod = ((r.get("list") or [None])[0]) or {}
        sources = _split_sources(vod)
        self._src_cache[vid] = sources
        return sources

    def _item_parts(self, it, src_idx, current_sources, current_vid):
        iid = str(it.get("vod_id") or "")
        if not iid:
            return []
        name = _clean(it.get("vod_name") or iid) or iid
        if iid == str(current_vid):
            eps = []
            if current_sources:
                if src_idx < len(current_sources) and current_sources[src_idx][1]:
                    eps = current_sources[src_idx][1]
                else:
                    eps = current_sources[0][1]
            if len(eps) > 1:
                out = []
                for i, (en, u) in enumerate(eps):
                    label = _clean("%s %s" % (name, en or ("%02d" % (i + 1))))
                    out.append("%s$%s" % (label, u))
                return out
            if eps:
                return ["%s$%s" % (name, eps[0][1])]
            return ["%s$nid:%s" % (name, _enc(iid))]
        return ["%s$nid:%s" % (name, _enc(iid))]

    def _apply_playlist(self, vid, vod, items):
        sources = _split_sources(vod)
        _ensure(self)
        self._src_cache[str(vid)] = sources
        if not items:
            return vod
        ordered = [x for x in items if str(x.get("vod_id")) == str(vid)]
        ordered += [x for x in items if str(x.get("vod_id")) != str(vid)]
        plist, seen = [], set()
        for it in ordered:
            iid = str(it.get("vod_id") or "")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            plist.append(it)
        if not plist:
            return vod
        if not sources:
            sources = [("线路1", [("播放", "nid:%s" % _enc(vid))])]
        play_from, play_urls = [], []
        for i, (sname, _eps) in enumerate(sources):
            parts = []
            for it in plist:
                parts.extend(self._pl_item_parts(it, i, sources, vid))
            if not parts:
                continue
            play_from.append(sname or ("线路%d" % (i + 1)))
            play_urls.append("#".join(parts))
        if not play_from:
            return vod
        vod = dict(vod)
        vod["vod_play_from"] = "$$$".join(play_from)
        vod["vod_play_url"] = "$$$".join(play_urls)
        return vod

    def init(self, *args, **kwargs):
        _ensure(self)
        if _orig_init:
            try:
                return _orig_init(self, *args, **kwargs)
            except Exception:
                return None

    def homeContent(self, *args, **kwargs):
        _ensure(self)
        try:
            r = _orig_home(self, *args, **kwargs) if _orig_home else {}
        except Exception:
            r = {}
        try:
            _cache_page(self, ("home",), _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def homeVideoContent(self, *args, **kwargs):
        _ensure(self)
        try:
            r = _orig_homev(self, *args, **kwargs) if _orig_homev else {"list": []}
        except Exception:
            r = {"list": []}
        try:
            _cache_page(self, ("homev",), _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def categoryContent(self, *args, **kwargs):
        _ensure(self)
        try:
            r = _orig_cate(self, *args, **kwargs) if _orig_cate else {"list": []}
        except Exception:
            r = {"list": []}
        try:
            tid = args[0] if args else kwargs.get("tid", "")
            pg = args[1] if len(args) > 1 else kwargs.get("pg", "1")
            ext = args[3] if len(args) > 3 else kwargs.get("extend", "")
            _cache_page(self, ("cate", str(tid), str(pg), str(ext)), _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def searchContent(self, *args, **kwargs):
        _ensure(self)
        if not _orig_search:
            return {"list": []}
        try:
            r = _orig_search(self, *args, **kwargs)
        except Exception:
            r = {"list": []}
        try:
            key = args[0] if args else kwargs.get("key", "")
            pg = args[2] if len(args) > 2 else kwargs.get("pg", "1")
            _cache_page(self, ("search", str(key), str(pg)), _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def searchContentPage(self, *args, **kwargs):
        _ensure(self)
        if not _orig_searchp:
            return {"list": []}
        try:
            r = _orig_searchp(self, *args, **kwargs)
        except Exception:
            r = {"list": []}
        try:
            key = args[0] if args else kwargs.get("key", "")
            pg = args[2] if len(args) > 2 else kwargs.get("page", kwargs.get("pg", "1"))
            _cache_page(self, ("searchp", str(key), str(pg)), _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def detailContent(self, ids, *args, **kwargs):
        _ensure(self)
        if isinstance(ids, (list, tuple)):
            vid = str(ids[0]) if ids else ""
            call_ids = list(ids)
        else:
            vid = str(ids)
            call_ids = [vid]
        if vid.startswith("nid:"):
            vid = _dec(vid[4:])
            call_ids[0] = vid
        cached = _page_of(self, vid)
        if _orig_detail:
            try:
                r = _orig_detail(self, call_ids, *args, **kwargs)
            except TypeError:
                r = _orig_detail(self, call_ids)
            except Exception:
                r = {"list": []}
        else:
            r = {"list": []}
        try:
            rr = _as_result(r)
            lst = rr.get("list") or []
            if not lst or not isinstance(lst[0], dict):
                return r
            vod = dict(lst[0])
            vod["vod_id"] = str(vod.get("vod_id") or vid)
            if not vod.get("vod_name"):
                hit = next((x for x in cached if str(x.get("vod_id")) == vid), None)
                if hit:
                    vod["vod_name"] = hit.get("vod_name") or vid
            if cached:
                vod = self._pl_apply_playlist(vid, vod, cached)
            rr = dict(rr)
            rr["list"] = [vod]
            if isinstance(r, dict) or r is None:
                return rr
            try:
                import json as _j
                return _j.dumps(rr, ensure_ascii=False)
            except Exception:
                return rr
        except Exception:
            return r

    def playerContent(self, flag, id, vipFlags=None, *args, **kwargs):
        _ensure(self)
        s = str(id)
        if s.startswith("nid:"):
            vid = _dec(s[4:])
            sources = self._pl_load_src(vid)
            real = ""
            if sources:
                picked = None
                for name, eps in sources:
                    if str(name) == str(flag) and eps:
                        picked = eps
                        break
                if not picked:
                    picked = sources[0][1]
                if picked:
                    real = picked[0][1]
            if real and not str(real).startswith("nid:"):
                id = real
            else:
                id = vid
        if not _orig_player:
            return {"parse": 0, "url": id}
        try:
            return _orig_player(self, flag, id, vipFlags, *args, **kwargs)
        except TypeError:
            try:
                return _orig_player(self, flag, id, vipFlags)
            except TypeError:
                return _orig_player(self, flag, id)
        except Exception:
            return {"parse": 1, "url": id, "header": {"Referer": getattr(self, "host", "")}}

    _C._pl_call_detail = _call_detail
    _C._pl_load_src = _load_src
    _C._pl_item_parts = _item_parts
    _C._pl_apply_playlist = _apply_playlist
    if _orig_init:    _C.init = init
    if _orig_home:    _C.homeContent = homeContent
    if _orig_homev:   _C.homeVideoContent = homeVideoContent
    if _orig_cate:    _C.categoryContent = categoryContent
    if _orig_search:  _C.searchContent = searchContent
    if _orig_searchp: _C.searchContentPage = searchContentPage
    if _orig_detail:  _C.detailContent = detailContent
    if _orig_player:  _C.playerContent = playerContent
    return _C


try:
    _pl_install(Spider)
except Exception:
    pass
# ===== PAGE_PLAYLIST_END =====
