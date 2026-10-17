# -*- coding: utf-8 -*-
# 聚合平台3 - 影视资源 API 聚合【修复优化版3】
# 修改：删除大地s43硬编码错误分类；所有源统一自动提取分类，无任何写死分类
# ===== 1. 先正常 import 所有模块 =====
import json
import random
import re
import sys
import threading
import time
from base64 import b64decode, b64encode
from urllib.parse import urlparse

import requests  # ✅ 先正常 import
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from pyquery import PyQuery as pq
sys.path.append('..')
from base.spider import Spider

# ===== 2. 再放加速头（不能再 import requests） =====
# =================== 极简万能加速头 ===================
import re
from functools import lru_cache

FAST_CDN = "lib.baomitu.com"
DEAD_MAP = {
    "rimg.iomycdn.com": FAST_CDN,
    "rimg.xiakee.com": FAST_CDN,
    "play.abcyun.com": FAST_CDN,
    "video.xyzcdn.com": FAST_CDN,
}

@lru_cache(maxsize=256)
def _auto_cdn(url: str) -> str:
    if not url:
        return ""
    for dead, fast in DEAD_MAP.items():
        url = url.replace(dead, fast)
    if url.startswith("//"):
        url = "https:" + url
    try:
        r = requests.head(url, allow_redirects=True, timeout=2)
        url = r.url
    except:
        pass
    return url

# 注入 requests
_real_get = requests.Session.get
def _patched_get(self, url, *a, **k):
    url = _auto_cdn(url)
    return _real_get(self, url, *a, **k)
requests.Session.get = _patched_get
# =================== 加速头结束 ===================
import json
import re
import sys
from urllib.parse import quote, urlencode

sys.path.append('..')

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider(object):
        def init(self, extend=""):
            pass

try:
    import requests
except ImportError:
    requests = None


class Spider(BaseSpider):
    UA = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    headers = {'User-Agent': UA}

    # ★ 只保留 m3u8 资源的总开关，默认开启
    M3U8_ONLY = True

    # type: 0=XML旧版  1=JSON标准(默认)  2=代理源  3=大地feifei2
    # ==========【字典顺序 = 首页源 + 解析优先前5源 + 自动子分类开启的前5源，调换条目顺序即可切换】==========
    SOURCES = {
        's41': {'name': '🌸精品', 'api': 'https://jp98.vip/api.php/provide/vod/at/m3u8'},
        's15': {'name': '📺杏吧', 'api': 'https://api.xgbbk8.com/api.php/provide/vod/at/m3u8'},
        's29': {'name': '🦅乐播', 'api': 'https://lbapi9.com/api.php/provide/vod/at/m3u8'},
        's8': {'name': '⚡极品', 'api': 'https://jipinvip2.com/api.php/provide/vod/?ac=list'},
        's32': {'name': '🍃百花', 'api': 'https://bhziyuan.com/api.php/provide/vod/at/m3u8'},
        's25': {'name': '🌸仓库', 'api': 'https://hsckzy888.com/api.php/provide/vod/from/hsckm3u8/'},
        's43': {'name': '🐾大地', 'api': 'https://dadiapi.com/feifei2/', 'type': 3},
        's50': {'name': '🧸动漫', 'api': 'https://api.heiapi.cc/api.php/provide/vod/at/m3u8'},
        's18': {'name': '📺155', 'api': 'https://155api.com/api.php/provide/vod/at/m3u8'},
        's21': {'name': '📺小鸡', 'api': 'https://api.xiaojizy.live/provide/vod/?ac=list'},
        's23': {'name': '📺豆豆', 'api': 'https://api.douapi.cc/api.php/provide/vod/at/m3u8'},
        's27': {'name': '☁️精东', 'api': 'http://chujia.cc/api.php/provide/vod/at/m3u8'},
        's45': {'name': '🐾滴滴', 'api': 'https://api.ddapi.cc/api.php/provide/vod/at/m3u8'},
        's30': {'name': '⚡JKUN', 'api': 'https://jkunzyapi.com/api.php/provide/vod/at/m3u8'},
        's39': {'name': '🐾CK百货', 'api': 'https://ckbh1.xyz/api.php/provide/vod/?ac=list'},
        's42': {'name': '🐾森林', 'api': 'https://slapibf.com/api.php/provide/vod/?ac=list'},
        's40': {'name': '🐾番茄', 'api': 'https://fqzy.me/api.php/provide/vod/at/m3u8'},
        's9': {'name': '📺美少女', 'api': 'https://www.msnii.com/api/json.php'},
        's10': {'name': '📺饮水机', 'api': 'https://www.xrbsp.com/api/json.php'},
        's11': {'name': '📺香奶儿', 'api': 'https://www.gdlsp.com/api/json.php'},
        's12': {'name': '🐯白嫖', 'api': 'https://www.kxgav.com/api/json.php'},
        's14': {'name': '📺潢AV', 'api': 'https://www.pgxdy.com/api/json.php'},
        's31': {'name': '👑桃花', 'api': 'https://thzy1.me/api.php/provide/vod/at/m3u8'},
        's4': {'name': '📺鲨鱼', 'api': 'https://shayuzy5.com/api.php/provide/vod/at/m3u8'},
        's22': {'name': '📺大奶', 'api': 'https://apidanaizi.com/api.php/provide/vod/at/m3u8'},
        's24': {'name': '📺黑料', 'api': 'https://heiliaozyapi.com/api.php/provide/vod/at/m3u8'},
        's26': {'name': '🐮玉兔', 'api': 'https://apiyutu.com/api.php/provide/vod/at/m3u8'},
        's33': {'name': '🐾老色', 'api': 'https://apilsbzy1.com/api.php/provide/vod/at/m3u8'},
        's34': {'name': '🐾辣椒', 'api': 'https://apilj.com/api.php/provide/vod/?ac=list'},
        's19': {'name': '📺91AV', 'api': 'https://91av.cyou/api.php/provide/vod/at/m3u8'},
        's35': {'name': '🐾javbus', 'api': 'https://javbus.sbs/api.php/provide/vod/at/m3u8'},
        's37': {'name': '🐾火速', 'api': 'https://api.huosuapi.cc/api.php/provide/vod/at/m3u8'},
        's38': {'name': '🐾聚合2', 'api': 'http://150.109.94.44:1112/api.php/provide/vod/?ac=list'},
        's16': {'name': '📺CK资源', 'api': 'https://ckzy.me/api.php/provide/vod/at/m3u8'},
        's6': {'name': '📺搜AV', 'api': 'https://souavzy.net/api.php/provide/vod/at/m3u8'},
        's49': {'name': '📺湿园', 'api': 'https://xxavs.com/api.php/provide/vod/at/m3u8'},
    }

    def init(self, extend=""):
        self._first_cate = {}

    def getName(self):
        return '聚合平台3'

    @staticmethod
    def isVideoFormat(url):
        if not url:
            return False
        u = str(url).lower()
        if any(x in u for x in ('.mp4', '.m3u8', '.flv', '.mkv')):
            return True
        if u.startswith(('magnet:', 'ed2k:')):
            return True
        return False

    @staticmethod
    def _text(v):
        return str(v if v is not None else '').strip()

    @staticmethod
    def _build_url(base, params=None):
        url = Spider._text(base).strip(' "\'')
        params = params or {}
        keys = [k for k, v in params.items() if v is not None and str(v) != '']
        if not keys:
            return url
        qs = urlencode({k: str(params[k]) for k in keys})
        return url + ('&' if '?' in url else '?') + qs

    def _request(self, url, extra_headers=None, timeout=12):
        try:
            hdr = dict(self.headers)
            if extra_headers:
                hdr.update(extra_headers)
            if requests is None:
                import urllib.request
                import ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(url, headers=hdr)
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                    return r.read().decode('utf-8', 'ignore')
            r = requests.get(url, headers=hdr, timeout=timeout, verify=False)
            r.encoding = 'utf-8'
            return r.text if r.status_code == 200 else ''
        except Exception as e:
            print('request error', url, e)
            return ''

    @staticmethod
    def _safe_json(s):
        if not s:
            return None
        s2 = re.sub(
            r'"(vod_id|id|type_id|list_id|vodId)"\s*:\s*(\d{16,})',
            r'"\1":"\2"',
            str(s),
        )
        try:
            return json.loads(s2)
        except Exception:
            try:
                return json.loads(s)
            except Exception:
                return None

    @staticmethod
    def _fix_pic(url):
        url = Spider._text(url)
        if not url:
            return ''
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith(('http://', 'https://')):
            return url
        return ''

    @staticmethod
    def _extract_cdata(s):
        if not s:
            return ''
        m = re.search(r'<!\[CDATA\[([\s\S]*?)\]\]>', s)
        if m:
            return m.group(1).strip()
        return re.sub(r'<[^>]+>', '', s).strip()

    @staticmethod
    def _normalize_vod(item):
        if not item or not isinstance(item, dict):
            return item
        o = dict(item)
        if not o.get('vod_play_from') and o.get('vod_play'):
            o['vod_play_from'] = o['vod_play']
        if not o.get('vod_play_url') and o.get('vod_url'):
            o['vod_play_url'] = o['vod_url']
        if not o.get('vod_id') and o.get('id'):
            o['vod_id'] = o['id']
        if o.get('vod_id') is not None:
            o['vod_id'] = str(o['vod_id'])
        if not o.get('vod_name') and o.get('name'):
            o['vod_name'] = o['name']
        if not o.get('vod_name') and o.get('title'):
            o['vod_name'] = o['title']
        if not o.get('vod_pic') and o.get('pic'):
            o['vod_pic'] = o['pic']
        if not o.get('vod_pic') and o.get('cover'):
            o['vod_pic'] = o['cover']
        if not o.get('vod_remarks') and o.get('remarks'):
            o['vod_remarks'] = o['remarks']
        if not o.get('vod_remarks') and o.get('note'):
            o['vod_remarks'] = o['note']
        if not o.get('vod_remarks') and o.get('vod_continu'):
            o['vod_remarks'] = o['vod_continu']
        if not o.get('vod_content') and o.get('content'):
            o['vod_content'] = o['content']
        if not o.get('vod_content') and o.get('des'):
            o['vod_content'] = o['des']
        if not o.get('vod_actor') and o.get('actor'):
            o['vod_actor'] = o['actor']
        if not o.get('vod_director') and o.get('director'):
            o['vod_director'] = o['director']
        if not o.get('vod_year') and o.get('year'):
            o['vod_year'] = o['year']
        if not o.get('vod_year') and o.get('d_year'):
            o['vod_year'] = o['d_year']
        if not o.get('vod_area') and o.get('area'):
            o['vod_area'] = o['area']
        if not o.get('type_name') and o.get('list_name'):
            o['type_name'] = o['list_name']
        if not o.get('type_name') and o.get('type'):
            o['type_name'] = o['type']
        o['vod_pic'] = Spider._fix_pic(o.get('vod_pic'))
        return o

    def _parse_xml(self, html):
        empty = {'list': [], 'page': 1, 'pagecount': 1, 'pagesize': 20, 'total': 0, 'class': []}
        if not html or ('<rss' not in html and '<video>' not in html):
            return empty
        page, pagecount, pagesize, total = 1, 1, 20, 0
        lm = re.search(r'<list\s+[^>]*>', html, re.I)
        if lm:
            attrs = lm.group(0)
            m = re.search(r'page="(\d+)"', attrs, re.I)
            if m:
                page = int(m.group(1))
            m = re.search(r'pagecount="(\d+)"', attrs, re.I)
            if m:
                pagecount = int(m.group(1))
            m = re.search(r'pagesize="(\d+)"', attrs, re.I)
            if m:
                pagesize = int(m.group(1))
            m = re.search(r'recordcount="(\d+)"', attrs, re.I)
            if m:
                total = int(m.group(1))
        classes = []
        cb = re.search(r'<class>([\s\S]*?)</class>', html, re.I)
        if cb:
            for m in re.finditer(r'<ty\s+id=["\']?(\d+)["\']?>([^<]+)</ty>', cb.group(1), re.I):
                classes.append({'type_id': m.group(1), 'type_name': m.group(2).strip()})
        lst = []
        for vm in re.finditer(r'<video>([\s\S]*?)</video>', html, re.I):
            v = vm.group(1)

            def get(tag):
                m = re.search(r'<%s[^>]*>([\s\S]*?)</%s>' % (tag, tag), v, re.I)
                return self._extract_cdata(m.group(1)) if m else ''

            vid, name = get('id'), get('name')
            if not vid or not name:
                continue
            dt = get('dt')
            play_from, play_url = [], []
            dl = re.search(r'<dl>([\s\S]*?)</dl>', v, re.I)
            if dl:
                for dm in re.finditer(
                        r'<dd[^>]*?(?:flag=["\']([^"\']+)["\']|flag=([^\s>]+))[^>]*>([\s\S]*?)</dd>',
                        dl.group(1), re.I
                ):
                    flag = self._text(dm.group(1) or dm.group(2) or dt or '播放')
                    content = self._extract_cdata(dm.group(3) or '')
                    if content:
                        play_from.append(flag)
                        play_url.append(content)
            if not play_from and dt:
                play_from.append(dt)
                play_url.append('')
            lst.append(self._normalize_vod({
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': get('pic'),
                'vod_remarks': get('note') or get('type') or '',
                'vod_year': get('year'),
                'vod_area': get('area'),
                'vod_actor': get('actor'),
                'vod_director': get('director'),
                'vod_content': get('des'),
                'vod_play_from': '$$$'.join(play_from),
                'vod_play_url': '$$$'.join(play_url),
                'type_name': get('type'),
            }))
        return {
            'list': lst, 'page': page, 'pagecount': pagecount,
            'pagesize': pagesize, 'total': total, 'class': classes,
        }

    def _parse_response(self, html):
        empty = {'list': [], 'page': 1, 'pagecount': 1, 'pagesize': 20, 'total': 0, 'class': []}
        if not html:
            return empty
        j = self._safe_json(html)
        if j:
            if j.get('status') is not None and (isinstance(j.get('data'), list) or j.get('page')):
                page_obj = j.get('page') or {}
                classes = []
                raw = j['data'] if isinstance(j.get('data'), list) else []
                return {
                    'list': [self._normalize_vod(x) for x in raw],
                    'page': int(page_obj.get('pageindex') or page_obj.get('page') or 1),
                    'pagecount': int(page_obj.get('pagecount') or 1),
                    'pagesize': int(page_obj.get('pagesize') or 20),
                    'total': int(page_obj.get('recordcount') or page_obj.get('total') or len(raw)),
                    'class': classes,
                }
            if isinstance(j.get('list'), list) or isinstance(j.get('class'), list) or j.get('filters'):
                raw = j['list'] if isinstance(j.get('list'), list) else []
                classes = j['class'] if isinstance(j.get('class'), list) else []
                if raw and raw[0] and raw[0].get('list_id') is not None and not raw[0].get('vod_id') and not raw[0].get('vod_name'):
                    classes = [{
                        'type_id': self._text(c.get('list_id') or c.get('type_id')),
                        'type_name': self._text(c.get('list_name') or c.get('type_name')),
                    } for c in raw]
                    raw = []
                else:
                    raw = [self._normalize_vod(x) for x in raw]
                classes = [{
                    'type_id': self._text(c.get('type_id') or c.get('list_id') or c.get('id')),
                    'type_name': self._text(c.get('type_name') or c.get('list_name') or c.get('name')),
                } for c in (classes or [])]
                return {
                    'list': raw,
                    'page': int(j.get('page') or 1),
                    'pagecount': int(j.get('pagecount') or 1),
                    'pagesize': int(j.get('limit') or j.get('pagesize') or 20),
                    'total': int(j.get('total') or 0),
                    'class': classes,
                }
        return self._parse_xml(html)

    def _filter_m3u8(self, from_arr, url_arr, source_name):
        new_from, new_url = [], []
        max_len = max(len(from_arr), len(url_arr))
        for i in range(max_len):
            f = from_arr[i] if i < len(from_arr) else f'{source_name}-线路{i + 1}'
            u = url_arr[i] if i < len(url_arr) else ''
            if not u:
                continue
            kept = []
            for ep in u.split('#'):
                if not ep:
                    continue
                _, url = ep.split('$', 1) if '$' in ep else ('', ep)
                if '.m3u8' in url.lower():
                    kept.append(ep)
            if kept:
                new_from.append(f)
                new_url.append('#'.join(kept))
        return new_from, new_url

    def _clean_item(self, item, source_key, source_name, is_detail=False):
        o = self._normalize_vod(dict(item))
        o['vod_id'] = self._text(o.get('vod_id'))
        if not is_detail:
            o['vod_id'] = f'{source_key}@@{o["vod_id"]}'
        rem = self._text(o.get('vod_remarks'))
        o['vod_remarks'] = f'{source_name} | {rem}'
        source_obj = self.SOURCES.get(source_key) or {}
        need_parse = bool(source_obj.get('parse'))
        from_arr = [s.strip() for s in self._text(o.get('vod_play_from')).split('$$$') if s.strip()]
        url_arr = [s.strip() for s in self._text(o.get('vod_play_url')).split('$$$')]
        if self.M3U8_ONLY and not need_parse and (from_arr or any(url_arr)):
            from_arr, url_arr = self._filter_m3u8(from_arr, url_arr, source_name)
        if from_arr:
            from_arr = [x if x.startswith(source_name) else f'{source_name}-{x}' for x in from_arr]
        if not from_arr and any(url_arr):
            from_arr = [f'{source_name}-线路{i + 1}' for i in range(len(url_arr))]
        while len(url_arr) < len(from_arr):
            url_arr.append('')
        while len(from_arr) < len(url_arr):
            from_arr.append(f'{source_name}-线路{len(from_arr) + 1}')
        o['vod_play_from'] = '$$$'.join(from_arr)
        o['vod_play_url'] = '$$$'.join(url_arr)
        o.pop('vod_down_from', None)
        o.pop('vod_down_url', None)
        return o

    def _load_filter(self, source_key, source_obj):
        stype = source_obj.get('type') or 1
        if stype == 2:
            url = self._build_url(source_obj['api'], {})
        else:
            url = self._build_url(source_obj['api'], {'ac': 'list'})
        data = self._parse_response(self._request(url))
        vals = [{'n': '全部(最新)', 'v': ''}]
        first_cate = ''
        for c in (data.get('class') or []):
            cid = self._text(c.get('type_id'))
            name = self._text(c.get('type_name'))
            if cid or name:
                vals.append({'n': name or cid, 'v': cid})
                if not first_cate and cid:
                    first_cate = cid
        return vals, first_cate

    def homeContent(self, filter):
        classes = []
        filters = {}
        self._first_cate = {}
        default_vals = [{'n': '全部(最新)', 'v': ''}]
        # 自动获取前5个源key，仅这5个发起网络请求拉取分类，其余源只显示全部(最新)
        top5_keys = list(self.SOURCES.keys())[:5]

        for sk, so in self.SOURCES.items():
            classes.append({'type_id': sk, 'type_name': so['name']})
            if sk in top5_keys:
                # ✅前5源（包括大地s43）统一远程自动拉取真实分类
                try:
                    vals, first_c = self._load_filter(sk, so)
                    filters[sk] = [{'key': 'cateId', 'name': '分类', 'value': vals}]
                    if first_c:
                        self._first_cate[sk] = first_c
                except Exception:
                    filters[sk] = [{'key': 'cateId', 'name': '分类', 'value': list(default_vals)}]
            else:
                # ❗其余源不访问网络，只保留全部(最新)，防止并发崩溃
                filters[sk] = [{'key': 'cateId', 'name': '分类', 'value': list(default_vals)}]
        return {'class': classes, 'filters': filters if filter else {}}

    def homeVideoContent(self):
        """首页：自动取SOURCES字典第一个源的最新更新，调换SOURCES顺序即可切换首页源"""
        if not self.SOURCES:
            return {"list": []}
        first_key = list(self.SOURCES.keys())[0]
        source = self.SOURCES[first_key]
        stype = source.get('type') or 1
        cate_id = self._first_cate.get(first_key, '')
        if stype in (0,3):
            params = {"ac":"videolist","pg":1}
            if cate_id:
                params['t'] = cate_id
            url = self._build_url(source['api'], params)
        elif stype ==2:
            params = {"pg":1}
            if cate_id:
                params['t'] = cate_id
            url = self._build_url(source['api'], params)
        else:
            params = {"ac":"videolist","pg":1}
            if cate_id:
                params['t'] = cate_id
            url = self._build_url(source['api'], params)
        resp = self._request(url)
        data = self._parse_response(resp)
        out = []
        for it in data.get("list",[]):
            item = self._clean_item(it, first_key, source['name'], False)
            item['vod_pic'] = self._fix_pic(item.get('vod_pic'))
            out.append(item)
        return {"list": out}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        source = self.SOURCES.get(str(tid))
        if not source:
            return {'list': [], 'page': pg, 'pagecount': 0}
        cate_id = ''
        if isinstance(extend, dict):
            cate_id = self._text(extend.get('cateId'))
        elif isinstance(filter, dict):
            cate_id = self._text(filter.get('cateId'))
        stype = source.get('type') or 1
        if not cate_id and stype == 2 and self._first_cate.get(tid):
            cate_id = self._first_cate.get(tid)
        if stype in (0, 3):
            params = {'ac': 'videolist', 'pg': pg}
            if cate_id:
                params['t'] = cate_id
            url = self._build_url(source['api'], params)
        elif stype ==2:
            params = {'pg': pg}
            if not cate_id:
                cate_id = self._first_cate.get(tid) or ''
            params['t'] = cate_id
            url = self._build_url(source['api'], params)
        else:
            params = {'ac': 'detail', 'pg': pg}
            if cate_id:
                params['t'] = cate_id
            url = self._build_url(source['api'], params)
        data = self._parse_response(self._request(url))
        if stype == 2 and not data.get('list'):
            fc = self._first_cate.get(tid)
            if fc and fc != cate_id:
                data = self._parse_response(
                    self._request(self._build_url(source['api'], {'pg': pg, 't': fc}))
                )
        out = []
        for it in (data.get('list') or []):
            cleaned = self._clean_item(it, tid, source['name'], False)
            cleaned['vod_pic'] = self._fix_pic(cleaned.get('vod_pic'))
            out.append(cleaned)
        return {
            'list': out,
            'page': int(data.get('page') or pg),
            'pagecount': int(data.get('pagecount') or 1),
            'limit': int(data.get('pagesize') or 20),
            'total': int(data.get('total') or len(out)),
        }

    def detailContent(self, ids):
        raw = ids[0] if isinstance(ids, list) else ids
        if '@@' not in str(raw):
            return {'list': []}
        source_key, real_id = str(raw).split('@@', 1)
        source = self.SOURCES.get(source_key)
        if not source:
            return {'list': []}
        stype = source.get('type') or 1
        html = ''
        if stype == 0:
            html = self._request(self._build_url(source['api'], {'ac': 'videolist', 'ids': real_id}))
        elif stype == 3:
            html = self._request(self._build_url(source['api'], {'ac': 'videolist', 'ids': real_id}))
            tmp = self._parse_response(html)
            first = (tmp.get('list') or [None])[0]
            if not first or not self._text(first.get('vod_play_url') or first.get('vod_url')):
                html2 = self._request(self._build_url(source['api'], {'ac': 'detail', 'ids': real_id}))
                if html2:
                    html = html2
        else:
            html = self._request(self._build_url(source['api'], {'ac': 'detail', 'ids': real_id}))
            tmp0 = self._parse_response(html)
            first0 = (tmp0.get('list') or [None])[0]
            if not first0 or not self._text(first0.get('vod_play_url') or first0.get('vod_url')):
                html_vl = self._request(self._build_url(source['api'], {'ac': 'videolist', 'ids': real_id}))
                dvl = self._parse_response(html_vl)
                if (dvl.get('list') or [None])[0] and self._text(
                        (dvl['list'][0].get('vod_play_url') or dvl['list'][0].get('vod_url') or '')
                ):
                    html = html_vl
            if stype == 2:
                tmp = self._parse_response(html)
                first = (tmp.get('list') or [None])[0]
                no_play = not first or not self._text(first.get('vod_play_url') or first.get('vod_url'))
                if no_play and re.search(r'https?://', real_id, re.I):
                    nm = re.search(r'/(\d+)/?$', real_id) or re.search(r'(\d{4,})', real_id)
                    if nm:
                        html3 = self._request(
                            self._build_url(source['api'], {'ac': 'detail', 'ids': nm.group(1)})
                        )
                        if html3:
                            d3 = self._parse_response(html3)
                            if (d3.get('list') or [None])[0] and self._text(
                                    (d3['list'][0].get('vod_play_url') or d3['list'][0].get('vod_url') or '')
                            ):
                                html = html3
        data = self._parse_response(html)
        out = []
        for it in (data.get('list') or []):
            cleaned = self._clean_item(it, source_key, source['name'], True)
            cleaned['vod_id'] = str(raw)
            cleaned['vod_pic'] = self._fix_pic(cleaned.get('vod_pic'))
            if (self.M3U8_ONLY and not source.get('parse')
                    and not self._text(cleaned.get('vod_play_url'))):
                continue
            if not self._text(cleaned.get('vod_play_from')) and self._text(cleaned.get('vod_play_url')):
                segs = self._text(cleaned.get('vod_play_url')).split('$$$')
                cleaned['vod_play_from'] = '$$$'.join(
                    [f'{source["name"]}-线路{i + 1}' for i in range(len(segs))]
                )
            out.append(cleaned)
        return {'list': out}

    def searchContentPage(self, key, quick, pg=1):
        import time
        pg = int(pg or 1)
        key = self._text(key)
        if not key:
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 40, 'total': 0}
        result = []
        dup_count = {}
        max_page = 1
        # 搜索防崩溃参数
        DUP_KEEP = 10      # 同一个片名最多保留10条结果，防止多源重复刷屏
        MAX_TOTAL = 40     # 总结果上限
        FAST_LIMIT = 30
        TOTAL_LIMIT = 18   # 全局超时秒数，防止卡死
        SRC_TIMEOUT =7

        priority_keys = ['s43']
        all_items = list(self.SOURCES.items())
        pri = [(k, v) for k, v in all_items if k in priority_keys]
        rest = [(k, v) for k, v in all_items if k not in priority_keys]
        if quick:
            items = pri + rest[:10]
        else:
            items = pri + rest

        def _norm_name(n):
            return re.sub(r'\s+', '', self._text(n)).lower()

        def _one(sk_so):
            sk, so = sk_so
            try:
                stype = so.get('type') or 1
                if stype in (0, 3):
                    url = self._build_url(so['api'], {'ac': 'videolist', 'wd': key, 'pg': pg})
                elif stype == 2:
                    url = self._build_url(so['api'], {'wd': key, 'pg': pg})
                else:
                    url = self._build_url(so['api'], {'ac': 'detail', 'wd': key, 'pg': pg})
                html = self._request(url, timeout=SRC_TIMEOUT)
                data = self._parse_response(html)
                if not data.get('list') and stype not in (0, 2, 3):
                    data2 = self._parse_response(
                        self._request(self._build_url(so['api'], {'ac': 'videolist', 'wd': key, 'pg': pg}),timeout=SRC_TIMEOUT)
                    )
                    if data2.get('list'):
                        data = data2
                lst = []
                for it in (data.get('list') or []):
                    cleaned = self._clean_item(it, sk, so['name'], False)
                    cleaned['vod_pic'] = self._fix_pic(cleaned.get('vod_pic'))
                    lst.append(cleaned)
                return lst, int(data.get('pagecount') or 1)
            except Exception as e:
                print('search skip', sk, e)
                return [], 1

        from concurrent.futures import ThreadPoolExecutor, as_completed
        pool = ThreadPoolExecutor(max_workers=8)
        start = time.time()
        futs = [pool.submit(_one, it) for it in items]
        try:
            for fut in as_completed(futs):
                try:
                    lst, pc = fut.result()
                except Exception:
                    lst, pc = [], 1
                for it in lst:
                    if len(result) >= MAX_TOTAL:
                        break
                    nk = _norm_name(it.get('vod_name')) + '|' + self._text(it.get('vod_year'))
                    if not nk.strip('|'):
                        continue
                    c = dup_count.get(nk, 0)
                    if c >= DUP_KEEP:
                        continue
                    dup_count[nk] = c + 1
                    result.append(it)
                if pc > max_page:
                    max_page = pc
                el = time.time() - start
                if len(result) >= FAST_LIMIT and el > 2.5:
                    break
                if el > TOTAL_LIMIT:
                    break
        except Exception as e:
            print('search pool error', e)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        return {
            'list': result,
            'page': pg,
            'pagecount': max_page,
            'limit': 40,
            'total': 9999,
        }

    def searchContent(self, key, quick, pg='1'):
        return self.searchContentPage(key, quick, pg)

    def _parse_url(self, token_url, prefer=''):
        """解析优先顺序取自SOURCES前5个源，调换字典顺序自动变化"""
        from urllib.parse import quote
        if not token_url:
            return ''
        if re.search(r'\.(m3u8|mp4|flv|mkv)(\?|$)', token_url, re.I):
            return token_url

        source_items = list(self.SOURCES.items())[:5]
        parsers = []
        for _, s in source_items:
            api_base = s['api']
            sep = '&' if '?' in api_base else '?'
            parsers.append({
                "name": s['name'],
                "api": f"{api_base}{sep}url="
            })

        cands = []
        if prefer:
            for p in parsers:
                if prefer in p['api'] or prefer in p.get('name', ''):
                    cands.append(p)
        cands += [p for p in parsers if p not in cands]

        urls_try = [token_url]
        try:
            enc = quote(token_url, safe='')
            if enc != token_url:
                urls_try.append(enc)
        except Exception:
            pass

        for p in cands:
            for tu in urls_try:
                try:
                    txt = self._request(p['api'] + tu)
                    if not txt:
                        continue
                    data = self._safe_json(txt)
                    if isinstance(data, dict):
                        code = data.get('code')
                        ok = True
                        if code is not None:
                            try:
                                ok = int(code) in (200, 0, 1, 2000)
                            except Exception:
                                ok = True
                        if ok:
                            for k in ('url', 'Url', 'URL', 'play_url', 'play', 'm3u8', 'data'):
                                v = data.get(k)
                                if isinstance(v, dict):
                                    v = v.get('url') or v.get('play')
                                if isinstance(v, str) and v.startswith('http'):
                                    return v.replace('\\/', '/')
                    for m in re.finditer(r'"(?:url|Url|URL|play_url|data|play)"\s*:\s*"([^"]+)"', txt):
                        v = m.group(1).replace('\\/', '/')
                        if re.search(r'\.(m3u8|mp4)', v, re.I) or v.startswith('http'):
                            return v
                    m = re.search(r'https?://[^"\'\s<>]+?\.(?:m3u8|mp4)[^"\'\s<>]*', txt.replace('\\/', '/'))
                    if m:
                        return m.group(0)
                except Exception:
                    continue
        return ''

    def playerContent(self, flag, id, vipFlags):
        play_url = self._text(id)
        if ';' in play_url and re.search(r'https?://', play_url, re.I):
            first = play_url.split(';')[0]
            if re.match(r'^https?://', first, re.I):
                play_url = first
        if ('|' in play_url and '@@' in play_url) or (
                'pan.baidu.com' in play_url or 'pan.quark.cn' in play_url or 'drive.uc.cn' in play_url
        ):
            api = self.SOURCES.get('s44', {}).get('api') or ''
            fl = self._text(flag)
            if '-' in fl:
                fl = fl.split('-', 1)[-1]
            resp = self._request(self._build_url(api, {'flag': fl or '', 'play': play_url}))
            j = self._safe_json(resp) or {}
            real = j.get('url')
            if isinstance(real, list):
                real = ''
                for x in j.get('url', []):
                    xs = self._text(x)
                    if xs.startswith('http'):
                        real = xs
                        break
            else:
                real = self._text(real or '')
            hdr = {'User-Agent': self.UA}
            hraw = j.get('header')
            if isinstance(hraw, str):
                try:
                    hraw = json.loads(hraw)
                except Exception:
                    hraw = None
            if isinstance(hraw, dict):
                hdr.update({k: v for k, v in hraw.items() if v})
            if real:
                return {'parse': 0, 'jx': 0, 'url': real, 'header': hdr}
            return {'parse': 0, 'jx': 0, 'url': play_url, 'header': hdr}
        if play_url.startswith('/play/') or re.match(r'^\d+-ep\d+', play_url):
            path = play_url if play_url.startswith('/') else '/play/' + play_url
            fl = self._text(flag)
            if '-' in fl:
                fl = fl.split('-', 1)[-1]
            if not fl or fl.startswith('🐾') or fl.startswith('s') or '荐片' in fl or '独播' in fl:
                fl = '独播库内网'
            api = 'http://bob2.hkt.net.cn/miraplay/dbo.php'
            dbo_hdr = {
                'User-Agent': self.UA,
                'Referer': 'https://www.dbkk.cc/',
                'Origin': 'https://www.dbkk.cc',
            }
            resp = self._request(
                self._build_url(api, {'flag': fl, 'play': path}),
                extra_headers=dbo_hdr,
            )
            j = self._safe_json(resp) or {}
            real = self._text(j.get('url') or '')
            hdr = {
                'User-Agent': self.UA,
                'Referer': 'https://www.dbkk.cc/',
                'Origin': 'https://www.dbkk.cc',
            }
            hraw = j.get('header')
            if isinstance(hraw, str):
                try:
                    hraw = json.loads(hraw)
                except Exception:
                    hraw = None
            if isinstance(hraw, dict):
                for k, v in hraw.items():
                    if v:
                        hdr[k] = v
            if real:
                return {'parse': 0, 'jx': 0, 'url': real, 'header': hdr}
            if path.startswith('/play/'):
                resp2 = self._request(
                    self._build_url(api, {'flag': fl, 'play': path[6:]}),
                    extra_headers=dbo_hdr,
                )
                j2 = self._safe_json(resp2) or {}
                real2 = self._text(j2.get('url') or '')
                if real2:
                    return {'parse': 0, 'jx': 0, 'url': real2, 'header': hdr}
            return {'parse': 0, 'jx': 0, 'url': '', 'header': hdr}
        need_parse = not self.isVideoFormat(play_url)
        if not need_parse:
            return {
                'parse': 0, 'jx': 0, 'url': play_url,
                'header': {'User-Agent': self.UA},
            }
        prefer = ''
        fl = self._text(flag)
        for sk, so in self.SOURCES.items():
            if so.get('parse') and (sk in fl or so['name'].replace('🐾', '') in fl or so['name'] in fl):
                prefer = so.get('parser') or ''
                break
        real = self._parse_url(play_url, prefer)
        if real:
            return {
                'parse': 0, 'jx': 0, 'url': real,
                'header': {'User-Agent': self.UA},
            }
        return {
            'parse': 1, 'jx': 1, 'url': play_url,
            'header': {'User-Agent': self.UA},
        }
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
