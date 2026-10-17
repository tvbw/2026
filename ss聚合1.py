# -*- coding: utf-8 -*-
# 聚合平台3 - 影视资源 API 聚合
# 对应 聚合平台3 (2).js；结构参考 ppnix.py
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
    def init(self, extend=""):
        self._first_cate = {}

    def getName(self):
        return '聚合平台3'

    def isVideoFormat(self, url):
        if not url:
            return False
        u = str(url).lower()
        if any(x in u for x in ('.mp4', '.m3u8', '.flv', '.mkv')):
            return True
        if u.startswith('magnet:') or u.startswith('ed2k:'):
            return True
        return False

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    UA = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    headers = {'User-Agent': UA}

    # type: 0=XML旧版  1=JSON标准(默认)  2=代理源  3=大地feifei2
    SOURCES = {
        's41': {'name': '🌸精品', 'api': 'https://jp98.vip/api.php/provide/vod/at/m3u8'},
        's5': {'name': '🔥麻花', 'api': 'https://19q.cc/api.php/provide/vod/at/m3u8'},
        's6': {'name': '📺搜AV', 'api': 'https://souavzy.net/api.php/provide/vod/at/m3u8'},
        's8': {'name': '⚡极品', 'api': 'https://jipinvip1.com/api.php/provide/vod/at/m3u8'},
        's32': {'name': '🍃百花', 'api': 'https://bhziyuan.com/api.php/provide/vod/at/m3u8'},
        's25': {'name': '🌸仓库', 'api': 'https://hsckzy888.com/api.php/provide/vod/at/m3u8'},
        's39': {'name': '🐾CK百货', 'api': 'https://ckbh1.xyz/api.php/provide/vod'},
        's42': {'name': '🐾森林', 'api': 'https://slapibf.com/api.php/provide/vod'},
        's29': {'name': '🦅乐播', 'api': 'https://lbapi9.com/api.php/provide/vod'},
        's19': {'name': '📺91AV', 'api': 'https://91av.cyou/api.php/provide/vod/at/m3u8'},
        's43': {'name': '🐾大地', 'api': 'https://dadiapi.com/feifei2/', 'type': 3},
        's18': {'name': '📺155', 'api': 'https://155api.com/api.php/provide/vod/at/m3u8'},
        's21': {'name': '📺小鸡', 'api': 'https://api.xiaojizy.live/provide/vod/'},
        's23': {'name': '📺豆豆', 'api': 'https://api.douapi.cc/api.php/provide/vod/at/m3u8'},
        's1': {'name': '🎬香蕉', 'api': 'https://www.xiangjiaozyw.com/api.php/provide/vod/'},
        's27': {'name': '☁️精东', 'api': 'http://chujia.cc/api.php/provide/vod/'},
        's45': {'name': '🐾滴滴', 'api': 'https://api.ddapi.cc/api.php/provide/vod/at/m3u8'},
        's30': {'name': '⚡JKUN', 'api': 'https://jkunzyapi.com/api.php/provide/vod'},
        's9': {'name': '📺美少女', 'api': 'https://www.msnii.com/api/json.php'},
        's10': {'name': '📺饮水机', 'api': 'https://www.xrbsp.com/api/json.php'},
        's11': {'name': '📺香奶儿', 'api': 'https://www.gdlsp.com/api/json.php'},
        's12': {'name': '🐯白嫖', 'api': 'https://www.kxgav.com/api/json.php'},
        's14': {'name': '📺潢AV', 'api': 'https://www.pgxdy.com/api/json.php'},
        's31': {'name': '👑桃花', 'api': 'https://thzy1.me/api.php/provide/vod/at/m3u8'},
        's4': {'name': '📺鲨鱼', 'api': 'https://shayuzy3.com/api.php/provide/vod/'},
        's22': {'name': '📺大奶', 'api': 'https://apidanaizi.com/api.php/provide/vod/at/m3u8'},
        's24': {'name': '📺黑料', 'api': 'https://heiliaozyapi.com/api.php/provide/vod/at/m3u8'},
        's26': {'name': '🐮玉兔', 'api': 'https://apiyutu.com/api.php/provide/vod/at/m3u8'},
        's33': {'name': '🐾老色', 'api': 'https://apilsbzy1.com/api.php/provide/vod/at/m3u8'},
        's34': {'name': '🐾辣椒', 'api': 'https://apilj.com/api.php/provide/vod/at/m3u8'},
        's35': {'name': '🐾javbus', 'api': 'https://javbus.sbs/api.php/provide/vod/at/m3u8'},
        's37': {'name': '🐾火速', 'api': 'https://api.huosuapi.cc/api.php/provide/vod/at/m3u8'},
        's38': {'name': '🐾聚合2', 'api': 'http://150.109.94.44:1112/api.php/provide/vod/at/m3u8'},
        's16': {'name': '📺CK资源', 'api': 'https://ckzy.me/api.php/provide/vod/at/m3u8'},
        's50': {'name': '🧸嘿嘿', 'api': 'https://api.heiapi.cc/api.php/provide/vod/at/m3u8'},
        's40': {'name': '🐾番茄1', 'api': 'https://fqzy.me/api.php/provide/vod//at/m3u8'},
        's2': {'name': '💧番茄2', 'api': 'http://fhapi9.com/api.php/provide/vod/'},
        's15': {'name': '📺杏吧', 'api': 'https://api.xgbbk8.com/api.php/provide/vod/at/m3u8'},
        's49': {'name': '📺湿园', 'api': 'https://xxavs.com/api.php/provide/vod/at/m3u8'},
    }

    def _text(self, v):
        return str(v if v is not None else '').strip()

    def _build_url(self, base, params=None):
        url = self._text(base).strip(' "\'')
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

    def _safe_json(self, s):
        try:
            if not s:
                return None
            # 大整数 id 保精度
            s2 = re.sub(
                r'"(vod_id|id|type_id|list_id|vodId)"\s*:\s*(\d{16,})',
                r'"\1":"\2"',
                str(s),
            )
            return json.loads(s2)
        except Exception:
            try:
                return json.loads(s)
            except Exception:
                return None

    def _fix_pic(self, url):
        url = self._text(url)
        if not url:
            return ''
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('http://') or url.startswith('https://'):
            return url
        return ''

    def _extract_cdata(self, s):
        if not s:
            return ''
        m = re.search(r'<!\[CDATA\[([\s\S]*?)\]\]>', s)
        if m:
            return m.group(1).strip()
        return re.sub(r'<[^>]+>', '', s).strip()

    def _normalize_vod(self, item):
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
        o['vod_pic'] = self._fix_pic(o.get('vod_pic'))
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
            # 大地 feifei2
            if j.get('status') is not None and (isinstance(j.get('data'), list) or j.get('page')):
                page_obj = j.get('page') or {}
                classes = []
                if isinstance(j.get('list'), list) and j['list']:
                    first = j['list'][0]
                    if first and (first.get('list_id') is not None or first.get('list_name')):
                        classes = [{
                            'type_id': self._text(c.get('list_id') or c.get('type_id') or c.get('id')),
                            'type_name': self._text(c.get('list_name') or c.get('type_name') or c.get('name')),
                        } for c in j['list']]
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

    # ★ 新增：从播放地址里只保留 .m3u8 的剧集
    def _filter_m3u8(self, from_arr, url_arr, source_name):
        """
        输入:
            from_arr: 线路名列表
            url_arr:  与 from_arr 一一对应的播放串（集名$地址#集名$地址...）
        输出:
            new_from, new_url 只保留含 .m3u8 的剧集
        """
        new_from, new_url = [], []
        max_len = max(len(from_arr), len(url_arr))
        for i in range(max_len):
            f = from_arr[i] if i < len(from_arr) else ('%s-线路%d' % (source_name, i + 1))
            u = url_arr[i] if i < len(url_arr) else ''
            if not u:
                continue
            kept = []
            for ep in u.split('#'):
                if not ep:
                    continue
                if '$' in ep:
                    _, url = ep.split('$', 1)
                else:
                    url = ep
                # 核心：包含 .m3u8 就保留（忽略大小写，支持 ?token= 等后缀）
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
            o['vod_id'] = '%s@@%s' % (source_key, o['vod_id'])
        rem = self._text(o.get('vod_remarks'))
        o['vod_remarks'] = '%s | %s' % (source_name, rem)

        source_obj = self.SOURCES.get(source_key) or {}
        # parse=1 的源需要走解析站，最终地址由解析后得到 m3u8，不能在这里过滤
        need_parse = bool(source_obj.get('parse'))

        from_arr = [s.strip() for s in self._text(o.get('vod_play_from')).split('$$$') if s.strip()]
        url_arr = [s.strip() for s in self._text(o.get('vod_play_url')).split('$$$')]

        # ★ 只保留 m3u8
        if self.M3U8_ONLY and not need_parse and (from_arr or any(url_arr)):
            from_arr, url_arr = self._filter_m3u8(from_arr, url_arr, source_name)

        if from_arr:
            from_arr = [x if x.startswith(source_name) else '%s-%s' % (source_name, x) for x in from_arr]
        if not from_arr and any(url_arr):
            from_arr = ['%s-线路%d' % (source_name, i + 1) for i in range(len(url_arr))]
        if from_arr and url_arr:
            while len(url_arr) < len(from_arr):
                url_arr.append('')
            while len(from_arr) < len(url_arr):
                from_arr.append('%s-线路%d' % (source_name, len(from_arr) + 1))
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
    def homeVideoContent(self):
        return {'list': []}

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
            cate_id = self._first_cate[tid]
        if stype in (0, 3):
            params = {'ac': 'videolist', 'pg': pg}
            if cate_id:
                params['t'] = cate_id
            url = self._build_url(source['api'], params)
        elif stype == 5:
            if not cate_id:
                cate_id = self._first_cate.get(tid) or 'site_duoduo'
            params = {'t': cate_id, 'pg': pg, 'categoryId': '1'}
            if isinstance(extend, dict) and extend.get('categoryId') is not None:
                params['categoryId'] = self._text(extend.get('categoryId'))
            url = self._build_url(source['api'], params)
        elif stype in (2, 4):
            params = {'pg': pg}
            if not cate_id:
                cate_id = self._first_cate.get(tid) or 'tv'
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
        if stype == 0:
            html = self._request(self._build_url(source['api'], {'ac': 'videolist', 'ids': real_id}))
        elif stype == 5:
            html = self._request(self._build_url(source['api'], {'ac': 'detail', 'ids': real_id}))
            if not html or not self._parse_response(html).get('list'):
                html = self._request(self._build_url(source['api'], {'ids': real_id}))
        elif stype == 4:
            html = self._request(self._build_url(source['api'], {'ac': 'detail', 'ids': real_id}))
            if not html:
                html = self._request(self._build_url(source['api'], {'ids': real_id}))
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

            # ★ 详情页里，如果过滤后没有 m3u8 播放地址（且非解析源），直接跳过
            if (self.M3U8_ONLY and not source.get('parse')
                    and not self._text(cleaned.get('vod_play_url'))):
                continue

            if not self._text(cleaned.get('vod_play_from')) and self._text(cleaned.get('vod_play_url')):
                segs = self._text(cleaned.get('vod_play_url')).split('$$$')
                cleaned['vod_play_from'] = '$$$'.join(
                    ['%s-线路%d' % (source['name'], i + 1) for i in range(len(segs))]
                )
            out.append(cleaned)
        return {'list': out}

    def searchContent(self, key, quick, pg='1'):
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick, pg=1):
        import time
        pg = int(pg or 1)
        key = self._text(key)
        if not key:
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 40, 'total': 0}
        result = []
        dup_count = {}
        max_page = 1
        priority_keys = ['s43', 's44', 's46', 's47', 's48', 's49', 's50', 's51', 's52', 's53']
        all_items = list(self.SOURCES.items())
        pri = [(k, v) for k, v in all_items if k in priority_keys]
        rest = [(k, v) for k, v in all_items if k not in priority_keys]
        if quick:
            items = pri + rest[:12]
        else:
            items = pri + rest
        SRC_TIMEOUT = 8
        DUP_KEEP = 10
        MAX_TOTAL = 30
        FAST_LIMIT = 30
        TOTAL_LIMIT = 20

        def _norm_name(n):
            return re.sub(r'\s+', '', self._text(n)).lower()

        def _one(sk_so):
            sk, so = sk_so
            try:
                stype = so.get('type') or 1
                extra_to = 15 if sk == 's44' else None
                if stype in (0, 3):
                    url = self._build_url(so['api'], {'ac': 'videolist', 'wd': key, 'pg': pg})
                elif stype == 2:
                    url = self._build_url(so['api'], {'wd': key, 'pg': pg})
                elif stype == 5:
                    url = self._build_url(so['api'], {'wd': key, 'pg': pg})
                elif stype == 4:
                    url = self._build_url(so['api'], {'t': 'tv', 'pg': pg, 'wd': key})
                else:
                    url = self._build_url(so['api'], {'ac': 'detail', 'wd': key, 'pg': pg})
                html = self._request(url, timeout=SRC_TIMEOUT) if extra_to is None \
                    else self._request_timeout(url, extra_to)
                data = self._parse_response(html)
                if not data.get('list') and stype not in (0, 2, 3, 5):
                    data2 = self._parse_response(
                        self._request(self._build_url(so['api'], {'ac': 'videolist', 'wd': key, 'pg': pg}),
                                      timeout=SRC_TIMEOUT)
                    )
                    if data2.get('list'):
                        data = data2
                if not data.get('list') and stype == 2:
                    data2 = self._parse_response(
                        self._request(self._build_url(so['api'], {'ac': 'detail', 'wd': key, 'pg': pg}),
                                      timeout=SRC_TIMEOUT)
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

        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=10)
        start = time.time()
        try:
            from concurrent.futures import as_completed
            futs = [pool.submit(_one, it) for it in items]
            done = 0
            for fut in as_completed(futs):
                done += 1
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
                if done == len(futs):
                    break
                if len(result) >= FAST_LIMIT and el > 3:
                    break
                if el > TOTAL_LIMIT:
                    break
        except Exception as e:
            print('search pool error', e)
        finally:
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
        return {
            'list': result,
            'page': pg,
            'pagecount': max_page,
            'limit': 40,
            'total': 9999,
        }

    def _request_timeout(self, url, timeout=15, extra_headers=None):
        try:
            hdr = dict(self.headers)
            if extra_headers:
                hdr.update(extra_headers)
            if requests is None:
                import urllib.request, ssl
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
        return None