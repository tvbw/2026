# -*- coding: utf-8 -*-
# 骚女汇 vfbai.snnvh82.sbs - TVBox/FongMi type=3
# MacCMS v10 saonvhui 模板; 全站文本 document.write(d(base64)) 混淆, 清洗=删 span 垃圾
import base64, json, re, threading, time
try:
    from Crypto.Cipher import AES as _AES
except Exception:
    _AES = None
import urllib.parse, urllib.request, urllib.error, gzip, zlib
try:
    from base.spider import Spider as _BaseSpider
except Exception:
    class _BaseSpider(object):
        pass

class Spider(_BaseSpider):
    # 域名池：该站域名频繁轮换，首页带"新网址/立即跳转"公告
    # 2026-10-19 实测：vfbai.snnvh82.sbs 首页公告跳转 y8ke0.snnvh99.top
    HOSTS = ["https://y8ke0.snnvh99.top", "https://vfbai.snnvh82.sbs"]
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    # 内容屏蔽：偷拍自拍 / 网曝事件 / 强奸乱伦 / 少女萝莉 四类不进目录
    BLOCK_CIDS = {"9530846", "9610856", "9710866", "9760866"}
    BLOCK_KW = ("小孩子", "门事件")
    _PICS = {}
    PNG_1X1 = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

    def __init__(self):
        # ★ 铁律：先调基类 __init__（壳在基类里注入 siteKey / extend），
        #   之后再建自己的状态；否则基类会把 self.extend 设成字符串 ''，
        #   导致 self.extend.get() 直接 AttributeError。
        try:
            # ★ 必须走 super()：壳把 siteKey 注入在基类上，
            #   裸调 _BaseSpider.__init__ 会拿到被替换前的名字 → siteKey 丢失
            super(Spider, self).__init__()
        except Exception:
            try:
                _BaseSpider.__init__(self)
            except Exception:
                pass
        self.host = self.HOSTS[0]
        self.extend = {}
        self._lock = threading.Lock()
        self._proxy_cache = {"val": None, "at": 0.0}

    def init(self, extend=""):
        # 壳在Loader 里 obj.put("siteKey", siteKey) 注入在【基类】上
        # ★ 铁律：子类绝不能覆盖 self.siteKey（会让 localProxy 的 siteKey 路由失效）
        #   → 这里只读不写，需要时用 _site_key() 取
        self.extend = self._parse_extend(extend)
        h = self.extend.get("host")
        if h:
            h = str(h).rstrip("/")
            if h.startswith("//"):
                h = "https:" + h
            elif not h.startswith("http"):
                h = "https://" + h
            self.host = h

    @staticmethod
    def _parse_extend(extend):
        out = {}
        if not extend:
            return out
        if isinstance(extend, dict):
            out.update(extend)
        else:
            s = str(extend).strip()
            if s.startswith("{"):
                try:
                    out.update(json.loads(s))
                except Exception:
                    pass
            elif s.startswith("http"):
                out["host"] = s
        return out

    def action(self, action):
        """壳的动作协议入口：本源不提供动作卡，返回空"""
        return {"list": []}

    def liveContent(self, url):
        """壳的直播入口：本源不做直播，返回空"""
        return ""

    def getName(self):
        return self.extend.get("name") or "骚女汇"

    def isVideoFormat(self, url):
        if not url:
            return False
        low = str(url).lower()
        return any(e in low for e in
                   ('.m3u8', '.mp4', '.flv', '.mkv', '.avi', '.ts', '.mpg', '.webm'))

    def getDependence(self):
        return []

    def manualVideoCheck(self):
        return False

    # 图床镜像：实测 imgnqm.top 在部分网络被墙/连接重置，
    # imgwyn.top 为同图床备用域（14 张样本中 13 张可取回）
    IMG_MIRROR = (("imgnqm.top", "imgwyn.top"),)

    @classmethod
    def _img_variants(cls, url):
        """(tag, url) 列表：原图 -> 各镜像域"""
        out = [("origin", url)]
        for a, b in cls.IMG_MIRROR:
            if a in url:
                out.append((b, url.replace(a, b)))
        return out

    def _proxy_val(self):
        """显式配置的代理；没配返回 None（直连）"""
        p = self.extend.get("proxy")
        if not p:
            p = self.extend.get("proxy_base")
        if not p:
            return None
        p = str(p).strip()
        if not p.startswith("http"):
            p = "http://" + p
        return p

    def _proxy_candidates(self):
        """取图代理候选链：显式配置优先，其次探测本机常见代理端口。
        全部失败 -> 空 dict = 直连（绝不强制代理）"""
        out = []
        p = self._proxy_val()
        if p:
            out.append(p)
        for port in (7890, 7891, 1080, 1087, 10809, 24780, 2333, 6153, 16666, 20170, 9090, 7070):
            cand = "http://127.0.0.1:%d" % port
            if cand not in out:
                out.append(cand)
        return out[:4]          # 只探 4 个，避免整页卡死

    def _open(self, url, headers, timeout, proxies, raw=False):
        """raw=True 返回原始 bytes（取图必须走这里：图片是二进制，
        经 utf-8 decode/encode 往返会被破坏 -> 壳子拿到坏图显示不出来）"""
        op = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies if proxies else {}))
        req = urllib.request.Request(url, headers=headers)
        with op.open(req, timeout=timeout) as resp:
            data = resp.read()
            # ★raw 也要解压：图床常返回 gzip 压缩的图（Content-Encoding:gzip），
            #不解压壳子拿到的是压缩流 -> 显示不出来
            enc = resp.headers.get("Content-Encoding")
            if data[:2] == b"\x1f\x8b":
                try:
                    data = gzip.decompress(data)
                except Exception:
                    pass
            elif data[:2] == b"\x78" and (enc or "").lower() in ("deflate", "gzip", ""):
                try:
                    data = zlib.decompress(data)
                except Exception:
                    pass
            return data if raw else data.decode("utf-8", "ignore")

    # ---------- 前端加密壳解密（AES-GCM 整页壳） ----------
    # 2026-10-19 新架构：整页 HTML 以密文形式塞在 <script> 里，
    #   浏览器用 crypto.subtle(AES-GCM) 解密后 document.write。
    # 结构：const A=[[i,"b64片段"],...]  → 按 i 排序拼接 → atob → 密文
    #   key = base64(A) XOR base64(B)   iv = base64(C)(12B)  aad = base64(D)
    #   密文末尾16字节=GCM tag
    _SH_ARR = re.compile(r'(?:const|let|var)\s+(\w+)\s*=\s*(\[\[.*?\]\])\s*(?:;|,)', re.S)

    @staticmethod
    def _sh_grab(s, name):
        i = s.find(name)
        while i >= 0:
            j = s.find("[[", i)
            if j >= 0 and j - i <= 30:
                k = j; depth = 0
                while k < len(s):
                    if s[k] == "[": depth += 1
                    elif s[k] == "]":
                        depth -= 1
                        if depth == 0: break
                    k += 1
                try:
                    a = json.loads(s[j:k + 1])
                except Exception:
                    a = None
                if isinstance(a, list) and a and isinstance(a[0], list):
                    return a
            i = s.find(name, i + 1)
        return None

    @staticmethod
    def _sh_flat(arr):
        try:
            raw = "".join(x[1] for x in sorted(arr, key=lambda x: x[0]))
            return base64.b64decode(raw + "=" * (-len(raw) % 4))
        except Exception:
            return b""

    def _decrypt_shell(self, html):
        """检测并解开整页 AES-GCM 加密壳；不是壳则原样返回。
        变量名每次请求都变 → 必须按代码引用关系动态解析，不能写死名字。"""
        if not html or "crypto.subtle" not in html or "AES-GCM" not in html:
            return html
        if _AES is None:
            return html
        m = re.search(r'<script[^>]*>(.*?)</script>', html, re.S)
        if not m:
            return html
        s = m.group(1)

        def _arr(name):
            """取出 NAME=[[i,"b64"],...] 的数组。
            必须用 name= 精确锚定：数组名常是变量名的前缀（rbWcoUeW8RB vs rbWcoUeW8RBD）"""
            i = s.find(name + "=")
            while i >= 0:
                j = s.find("[[", i)
                if j >= 0 and j - i <= 30:
                    k = j; depth = 0
                    while k < len(s):
                        if s[k] == "[": depth += 1
                        elif s[k] == "]":
                            depth -= 1
                            if depth == 0: break
                        k += 1
                    try:
                        a = json.loads(s[j:k + 1])
                    except Exception:
                        a = None
                    if isinstance(a, list) and a and isinstance(a[0], list):
                        return a
                i = s.find(name + "=", i + 1)
            return None

        def _bytes_of(name):
            a = _arr(name)
            if not a:
                return None
            try:
                raw = "".join(x[1] for x in sorted(a, key=lambda x: x[0]))
                return base64.b64decode(raw + "=" * (-len(raw) % 4))
            except Exception:
                return None

        # --- 1) 找 key:  const K=new Uint8Array(32); for(...) K[i]=A[i]^B[i]
        #     注意 A/B 的真实数组名与代码里的变量名常差一两个字符（如 rbWcoUeW8RB vs rbWcoUeW8RBD）
        #     → 用 "变量=解码函数(拼接函数(数组名))" 这个模式反查真实数组名
        key = None
        km = re.search(
            r'const\s+(\w+)\s*=\s*new\s+Uint8Array\(32\)\s*;\s*'
            r'for\s*\(let\s+\w+\s*=\s*0\s*;\s*\w+\s*<\s*32\s*;\s*\w+\+\+\s*\)'
            r'\s*\w+\[\w+\]\s*=\s*(\w+)\[\w+\]\s*\^\s*(\w+)\[\w+\]', s)
        if km:
            v1, v2 = km.group(2), km.group(3)
            def _resolve(varname):
                """变量 X=decode(join(ARR)) → 取 ARR 的字节"""
                mm = re.search(re.escape(varname) + r'\s*=\s*\w+\(\w+\((\w+)\)\)', s)
                if mm:
                    bb = _bytes_of(mm.group(1))
                    if bb:
                        return bb
                return _bytes_of(varname)
            b1 = _resolve(v1); b2 = _resolve(v2)
            if b1 and b2 and len(b1) == 32 and len(b2) == 32:
                key = bytes(x ^ y for x, y in zip(b1, b2))

        # --- 2) 找 iv / aad / 密文：按 decrypt({...iv:FLAT(IVNAME), additionalData:FLAT(AADNAME)...},KEY,FLAT(CTNAME)) ---
        iv = aad = ct = None
        dm = re.search(
            r'crypto\.subtle\.decrypt\(\{\s*name\s*:\s*"AES-GCM"\s*,\s*'
            r'iv\s*:\s*\w+\(\w+\((\w+)\)\)\s*,\s*'
            r'additionalData\s*:\s*\w+\(\w+\((\w+)\)\)\s*,\s*'
            r'tagLength\s*:\s*\d+\s*\}\s*,\s*\w+\s*,\s*\w+\(\w+\((\w+)\)\)\)', s)
        if not dm:
            # 宽松版：抓 decrypt 括号内所有 FLAT(NAME)
            d2 = re.search(r'crypto\.subtle\.decrypt\((.{0,600}?)\)\)', s, re.S)
            if d2:
                names = re.findall(r'\w+\(\w+\((\w+)\)\)', d2.group(1))
                if len(names) >= 3:
                    ivn, aadn, ctn = names[0], names[1], names[-1]
                    iv, aad, ct = _bytes_of(ivn), _bytes_of(aadn), _bytes_of(ctn)
        else:
            iv = _bytes_of(dm.group(1))
            aad = _bytes_of(dm.group(2))
            ct = _bytes_of(dm.group(3))

        if key is None or ct is None or len(ct) < 32:
            return html
        if iv is None or len(iv) < 12:
            iv = b"\x00" * 12
        if aad is None:
            aad = b""
        for nonce in (iv[:12], iv[:16], iv):
            try:
                c = _AES.new(key, _AES.MODE_GCM, nonce=nonce)
                if aad:
                    c.update(aad)
                pt = c.decrypt_and_verify(ct[:-16], ct[-16:])
                return pt.decode("utf-8", "ignore")
            except Exception:
                continue
        return html

    # ---------- 域名轮换自愈 ----------
    # 该站是"域名轮换型"站点：首页带「本站已启用新网址 / 立即跳转」公告，
    # 旧域名随时停用。写死域名必然失效 → 每次抓首页都扫公告，自动把新域名入池。
    RE_NEWHOST = re.compile(
        r'<a[^>]+href=["\'](https?://[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})["\'][^>]*>'
        r'(?:\s*<[^>]+>\s*)*(?:立\s*即\s*跳\s*转|立即跳转|新地址|马上访问|点击跳转)', re.I)
    _HOSTLOCK = threading.Lock()
    _DISCOVERED = []          # 运行期发现的新域名（模块级，壳每次 new Spider 也保留）
    _LAST_DISCOVER = 0.0

    def _discover_host(self, html):
        """从首页公告里抠出新域名，插到池子最前面。返回新域名或 None"""
        if not html or "立即跳转" not in html and "新网址" not in html:
            return None
        found = None
        for m in self.RE_NEWHOST.finditer(html):
            d = m.group(1)
            if not d or d == self.host:
                continue
            try:
                host = urllib.parse.urlparse(d).netloc
            except Exception:
                continue
            if not host or host in ("www.w3.org",):
                continue
            # 排除明显第三方（CDN/图床/导航/统计）
            if re.search(r'(imgmbr|\.top/cdn|cloudflare|google|stat|counter|\.js$)', host, re.I):
                continue
            found = "https://" + host
            break
        if not found:
            return None
        with self._HOSTLOCK:
            if found not in self._DISCOVERED:
                self._DISCOVERED.insert(0, found)
            if found not in self.HOSTS:
                self.HOSTS.insert(0, found)
        return found

    def _all_hosts(self):
        with self._HOSTLOCK:
            out = list(self.HOSTS)
            for d in self._DISCOVERED:
                if d not in out:
                    out.insert(0, d)
        return out

    def _fetch(self, url, referer=None, timeout=15, img=False, retries=2):
        headers = {
            "User-Agent": self.UA,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate"}
        if referer:
            headers["Referer"] = referer
        if img:
            headers["Referer"] = referer or (self.host + "/")
            headers["Accept"] = "image/avif,image/webp,image/*,*/*;q=0.8"
            # ★ 直连优先，失败再降级代理（绝不强制代理，否则不开代理的机器全白屏）
            # 直连优先；仅当用户显式配了 proxy 才降级（不盲扫端口，避免 15 次等待）
            cands = [{}]
            pv = self._proxy_val()
            if pv:
                cands.append({"http": pv, "https": pv})
            for n, proxies in enumerate(cands):
                tmo = timeout if n == 0 else min(timeout, 6)
                try:
                    r = self._open(url, headers, tmo, proxies, raw=True)
                    if r and len(r) > 128:
                        return r
                except Exception:
                    pass
            return None
        for i in range(retries + 1):
            try:
                return self._open(url, headers, timeout, {})
            except Exception:
                if i < retries:
                    time.sleep(0.4)
        return None

    def _fetch_any(self, path, referer=None, timeout=15):
        """按域名池顺序抓；主域挂了就自动换下一个域。path 以 / 开头。"""
        hosts = self._all_hosts()
        for idx, h in enumerate(hosts):
            old_host = self.host
            self.host = h
            try:
                html = self._fetch(h + path, referer=referer or (h + "/"), timeout=timeout)
            except Exception:
                html = None
            finally:
                self.host = old_host
            if html and len(html) > 200:
                # 整页加密壳 → 先解开
                if "crypto.subtle" in html:
                    dec = self._decrypt_shell(html)
                    if dec and len(dec) > 200:
                        html = dec
                # 抓到了就顺手扫公告，可能又要换域
                self._discover_host(html)
                if idx > 0:
                    self.host = h          # 锁定到活着的域
                return html
        return None

    @staticmethod
    def _body(raw, enc):
        if raw[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        elif raw[:2] == b"\x78":
            try:
                raw = zlib.decompress(raw)
            except Exception:
                pass
        return raw.decode("utf-8", "ignore")

    def _dec(self, b64):
        try:
            s = base64.b64decode(b64).decode("utf-8", "ignore")
        except Exception:
            return ""
        s = re.sub(r"<span[^>]*>.*?</span>", "", s, flags=re.S)
        s = re.sub(r"<[^>]+>", "", s)
        s = s.replace("&nbsp;", " ").replace("&amp;", "&")
        return re.sub(r"\s+", " ", s).strip()

    def _blocked(self, title):
        t = title or ""
        for kw in self.BLOCK_KW:
            if kw in t:
                return True
        return False

    @staticmethod
    def _clean(t):
        t = (t or "").replace("$", "＄").replace("#", "＃")
        return re.sub(r"\s+", " ", t).strip()

    RE_CAT = re.compile(
        r'(?:https?://[^"/]+)?/list\.php\?id=(\d+)&page=1"?\s*>\s*'
        r'(?:<script[^>]*>document\.write\(d\(\'([^\']+)\'\)|([^<]+))')
    RE_ZONE = re.compile(r'<dt><a href="javascript:;">(.*?)</a></dt>(.*?)</dl>', re.S)

    def _classes(self):
        html = self._fetch_any("/")
        # 首页公告里可能带新网址 → 自动入池（域名轮换自愈）
        if html:
            self._discover_host(html)
        if html:
            out = []
            for _z, body in self.RE_ZONE.findall(html):
                for cid, b64, raw in self.RE_CAT.findall(body):
                    n = self._dec(b64) if b64 else self._clean(raw)
                    if n:
                        out.append({"type_id": cid, "type_name": n})
            out = [c for c in out if c["type_id"] not in self.BLOCK_CIDS]
            if out:
                return out
        return [{"type_id": "9500846", "type_name": "精品推荐"},
                {"type_id": "9540846", "type_name": "熟女少妇"},
                {"type_id": "9550846", "type_name": "无码专区"},
                {"type_id": "9560846", "type_name": "欧美性爱"},
                {"type_id": "9730866", "type_name": "女同性恋"}]

    RE_CARD = re.compile(
        r'<a class="thumbnail" href="/video\.php\?id=(\d+)"[^>]*>'
        r'<img[^>]+src="([^"]+)"[^>]*>.*?</a>\s*<div class="video-info">\s*<h5>'
        r'\s*<a href="/video\.php\?id=\d+"[^>]*>'
        r'(?:<script[^>]*>document\.write\(d\(\'([^\']+)\'\)|([^<]*))', re.S)
    RE_TOTAL = re.compile(r'共(\d+)条数据,当前\d+/(\d+)页')
    RE_LAST = re.compile(r'page=(\d+)"[^>]*>\s*尾页')

    def _parse_list(self, html):
        items, seen = [], set()
        if not html:
            return items
        for vid, pic, b64, txt in self.RE_CARD.findall(html):
            if vid in seen:
                continue
            name = self._dec(b64) if b64 else self._clean(txt)
            if not name:
                continue
            name = self._clean(name)
            if self._blocked(name):
                continue
            seen.add(vid)
            items.append({"vod_id": vid, "vod_name": name,
                          "vod_pic": self._pic(pic), "vod_remarks": "正片"})
        return items

    def _count(self, html):
        m = self.RE_TOTAL.search(html or "")
        if m:
            return int(m.group(1)), int(m.group(2))
        m2 = self.RE_LAST.search(html or "")
        return 0, (int(m2.group(1)) if m2 else 1)

    def _pic(self, url):
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith("http"):
            url = self.host + "/" + url.lstrip("/")
        # ★ 图床域在部分网络被墙，默认走本地代理（proxy 内含图床镜像 + 解压），
        #   由我们控制请求头并可换镜像域；壳子直连图床必空白。
        #   mode=0 -> 全部代理（默认，最稳）| 1 -> 仅换镜像域(直连URL) | 2 -> 同0兼容旧配置
        # img_mode:
        #   0(默认) 只把被墙图床域换成镜像域，URL仍交给壳子直连 -> 不依赖localProxy
        #   1        全部改走本地代理（我们控请求头，可换域/解压 gzip）
        #   2        混合：先给镜像域直连 URL，本地代理作为「不可用时」体现
        mode = str(self.extend.get("img_mode", "0"))
        for a, b in self.IMG_MIRROR:
            if a in url:
                url = url.replace(a, b)
        if mode == "1":
            return self._proxy_img(url)
        return url

    def _site_key(self):
        """取壳注入的 siteKey（只读，绝不写回 self.siteKey）"""
        v = getattr(self, "siteKey", "")
        if v:
            return str(v)
        return str(self.extend.get("sitekey", "") or "")

    def _proxy_img(self, url):
        b = base64.b64encode(url.encode("utf-8")).decode("ascii")
        b = urllib.parse.quote(b, safe="")
        # ★ BaseLoader.proxy: params 里有 siteKey 就走 getSpider(siteKey) 分支，
        #   不依赖 PyLoader.recent（recent==null 会直接返回 null → Invalid proxy response）
        sk = self._site_key()
        if sk:
            return "%s?do=py&siteKey=%s&type=img&url=%s" % (self._proxy_base(), sk, b)
        return "%s?do=py&type=img&url=%s" % (self._proxy_base(), b)

    def _proxy_base(self):
        pb = self.extend.get("proxy_base")
        if pb:
            return str(pb).rstrip("/")
        try:
            from com.github.catvod import Proxy
            u = Proxy.getUrl(True)
            if u:
                return str(u).split("?")[0]
        except Exception:
            pass
        return "http://127.0.0.1:9978"

    def _remember(self, items):
        try:
            for it in items or []:
                if it.get("vod_pic"):
                    self._PICS[it["vod_id"]] = it["vod_pic"]
        except Exception:
            pass

    def homeContent(self, filter=False):
        cls = self._classes()
        html = self._fetch_any("/")
        vod = self._parse_list(html)[:36]
        self._remember(vod)
        return {"class": cls, "vod": vod}

    def homeVideoContent(self):
        html = self._fetch_any("/")
        vod = self._parse_list(html)[:36]
        self._remember(vod)
        return {"list": vod, "page": 1, "pagecount": 1,
                "limit": len(vod), "total": len(vod)}

    @staticmethod
    def _norm_tid(tid, extend):
        t = str(tid or "").strip()
        if t.startswith("http"):
            m = re.search(r"id=(\d+)", t)
            return m.group(1) if m else t
        if t.isdigit():
            return t
        if isinstance(extend, dict) and extend.get(t):
            m = re.search(r"(\d{6,})", str(extend[t]))
            return m.group(1) if m else t
        return t

    def categoryContent(self, tid, pg, filter, extend):
        cid = self._norm_tid(tid, extend)
        pg = max(1, int(pg or 1))
        if cid in self.BLOCK_CIDS:
            return {"list": [], "page": pg, "pagecount": 1,
                    "limit": 0, "total": 0}
        html = self._fetch_any("/list.php?id=%s&page=%d" % (cid, pg))
        items = self._parse_list(html)
        total, pc = self._count(html)
        if not items:
            pc = pg
        self._remember(items)
        return {"list": items, "page": pg, "pagecount": max(1, pc),
                "limit": len(items), "total": total}

    def _extract_m3u8(self, html):
        for pat in (r"loadSource\(['\"](https?://[^'\"]+\.m3u8[^'\"]*)",
                    r"src\s*=\s*['\"](https?://[^'\"]+\.m3u8[^'\"]*)",
                    r"(https?://[^\s'\"\\<>]+\.m3u8[^\s'\"\\<>]*)"):
            m = re.search(pat, html)
            if m:
                return m.group(1).replace("\\/", "/").strip()
        return ""

    @staticmethod
    def _page_title(html):
        """取页面标题：兼容 旧站 document.title=d('b64') 与 新站明文 <title>"""
        name = ""
        m = re.search(r"document\.title\s*=\s*d\('([^']+)'\)", html)
        if m:
            try:
                name = base64.b64decode(m.group(1)).decode("utf-8", "ignore")
            except Exception:
                name = ""
        if not name:
            m = re.search(r"<title>([^<]{1,200})</title>", html, re.S)
            if m:
                name = m.group(1)
        name = re.sub(r"^\[[^\]]*\]\s*", "", name).strip()
        # 去掉「- 骚女汇」这类站点后缀
        name = re.sub(r"\s*[-_|]\s*骚女汇\s*$", "", name).strip()
        return name

    def detailContent(self, ids):
        vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        html = self._fetch_any("/video.php?id=%s" % vid)
        if not html:
            return {"list": [{"vod_id": vid, "vod_name": "加载失败", "vod_pic": "",
                              "vod_play_from": "骚女汇", "vod_play_url": "正片$"}]}
        name = self._page_title(html)
        if self._blocked(name):
            return {"list": [{"vod_id": vid, "vod_name": "已屏蔽",
                              "vod_pic": "", "vod_play_from": "骚女汇",
                              "vod_play_url": "正片$"}]}
        # 封面四级兜底: 列表登记(本片真图) -> 番号回搜 -> 标题回搜 -> 详情页首图
        pic = self._PICS.get(vid, "")
        if not pic:
            pic = self._find_pic(name, vid, html)
        # 新架构：详情页也是加密壳 → 先解开
        if "crypto.subtle" in html:
            d2 = self._decrypt_shell(html)
            if d2 and len(d2) > 200:
                html = d2
                name = self._page_title(html)
        # 回源页地址（供原页嗅探线用）
        src_url = "%s/video.php?id=%s" % (self.host, vid)
        play = self._extract_m3u8(html)
        ep = "正片$%s" % play if play else "正片$s0@@%s" % src_url
        return {"list": [{"vod_id": vid, "vod_name": name or ("影片 " + vid),
                          "vod_pic": pic, "vod_remarks": "正片",
                          "vod_play_from": "骚女汇·直连$$$骚女汇·原页",
                          "vod_play_url": ep}]}

    RE_CODE = re.compile(r'(?<![A-Za-z0-9])([A-Z]{2,6})[-_]?(\d{2,5})(?!\d)')
    BAD_CODE = ("ID", "MV", "HD", "TV", "3D", "UK", "US", "JP", "CN", "XX", "4K")

    def _find_pic(self, name, vid, html):
        """详情页自身无封面(og/meta/上传目录都没有)，用番号或标题回列表反查本片真图"""
        cands = []
        m = self.RE_CODE.search(name or "")
        if m and m.group(1).upper() not in self.BAD_CODE:
            cands.append(m.group(1).upper() + "-" + m.group(2))
        if name:
            cands.append(name.split(" ")[0][:24])
        for kw in cands[:2]:
            if not kw:
                continue
            url = "%s/search.php?content=%s" % (
                self.host, urllib.parse.quote(kw))
            target = self._redirect(url)
            if not target:
                continue
            m2 = re.search(r"id=(\d+)", target)
            if not m2:
                continue
            lh = self._fetch("%s/list.php?id=%s&page=1" % (
                self.host, m2.group(1)), referer=self.host + "/")
            for it in self._parse_list(lh or ""):
                if it["vod_id"] == vid:
                    return it["vod_pic"]
        # 最后一档: 详情页第一张非模板图(可能是相关推荐，但有图总比空白好)
        for u in re.findall(r'<img[^>]+src="([^"]+)"', html or ""):
            if "/template/" in u or not u.startswith("http"):
                continue
            return self._pic(u)
        return ""

    def playerContent(self, flag, id, vipFlags):
        id = str(id or "")
        if id.startswith("s0@@"):
            return {"parse": 0, "url": id[4:], "header": {"User-Agent": self.UA}}
        if self.isVideoFormat(id):
            return {"parse": 0, "url": id,
                    "header": {"User-Agent": self.UA, "Referer": self.host + "/"}}
        return {"parse": 1, "url": id, "header": {"User-Agent": self.UA}}

    def _redirect(self, url):
        try:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *a, **k):
                    return None
            op = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
            req = urllib.request.Request(url, headers={"User-Agent": self.UA})
            try:
                op.open(req, timeout=12)
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303, 307, 308):
                    loc = e.headers.get("Location")
                    if loc:
                        return urllib.parse.urljoin(self.host + "/", loc)
        except Exception:
            return None
        return None

    def searchContent(self, key, quick, pg="1"):
        pg = max(1, int(pg or 1))
        if self._blocked(str(key)):
            return {"list": [], "page": pg, "pagecount": 1, "limit": 0, "total": 0}
        url = "%s/search.php?content=%s" % (self.host, urllib.parse.quote(str(key)))
        target = self._redirect(url)
        if not target:
            return {"list": [], "page": pg, "pagecount": 1, "limit": 0, "total": 0}
        m = re.search(r"id=(\d+)", target)
        if not m:
            html = self._fetch(target, referer=self.host + "/")
            items = self._parse_list(html)
            self._remember(items)
            return {"list": items, "page": 1, "pagecount": 1,
                    "limit": len(items), "total": len(items)}
        return self.categoryContent(m.group(1), pg, False, {})

    def localProxy(self, param=None):
        try:
            if isinstance(param, str):
                raw = param.split("?", 1)[1] if "?" in param else param
                q = urllib.parse.parse_qs(raw)
            else:
                q = param if isinstance(param, dict) else None
                if q is None:
                    return [404, "text/plain", b"", {}]

            def _pv(key):
                v = q.get(key)
                if isinstance(v, list):
                    v = v[0] if v else ""
                return v or ""

            u = _pv("url")
            if not u:
                return [404, "text/plain", b"", {}]
            u = urllib.parse.unquote(str(u))
            # _proxy_img 传的是 base64，必须先解回来才是真实 URL
            try:
                if not u.lower().startswith("http"):
                    u = base64.b64decode(u).decode("utf-8", "ignore")
            except Exception:
                pass
            if str(_pv("type")) != "img":
                return [404, "text/plain", b"", {}]
            last = self._img_variants(u)
            for idx, (tag, cu) in enumerate(last):
                if idx:
                    time.sleep(0.12)# 轻微节流，避免打限流
                body = self._fetch(cu, referer=cu.split("/")[0] + "/",
                                   timeout=6 if idx else 8, img=True, retries=0)
                if body and len(body) > 128 and body[:1] not in (b"<", b" "):
                    mime = "image/jpeg"
                    if body[:8] == b"\x89PNG\r\n\x1a\n":
                        mime = "image/png"
                    elif body[:6] in (b"GIF87a", b"GIF89a"):
                        mime = "image/gif"
                    elif body[:4] == b"RIFF" and body[8:12] == b"WEBP":
                        mime = "image/webp"
                    return [200, mime, body,
                            {"Content-Type": mime, "Cache-Control": "max-age=86400"}]
            return [200, "image/png", self.PNG_1X1,
                    {"Content-Type": "image/png", "Cache-Control": "max-age=600"}]
        except Exception:
            return [404, "text/plain", b"", {}]
