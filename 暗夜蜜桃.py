#!/usr/bin/python
# coding=utf-8
# 蜜桃视频（honeypeach.cc）TVBox 蜘蛛框架版（修复版）
# 站点：自研 JSON API + HMAC 签名；7 个模块（蜜桃直播/短剧/擦边/视频/动漫/国产/黑料）。
# 鉴权：/api/handshake 先过 PoW 人机挑战（FNV-1a 变体），后续接口 HMAC-SHA256 签名。
# 调试：init 传入 {"debug": true} 可在控制台看到关键日志与 _last_error。
import re, json, time, base64, hashlib, random, string, threading

try:
    from urllib.parse import quote as _quote, unquote as _unquote
except ImportError:
    from urllib import quote as _quote, unquote as _unquote

try:
    import requests as _rq
except Exception:
    _rq = None

try:
    from concurrent.futures import ThreadPoolExecutor as _Pool
except Exception:
    _Pool = None

try:
    import http.cookiejar as _cookiejar
except ImportError:
    try:
        import cookielib as _cookiejar
    except ImportError:
        _cookiejar = None

_BASE = "https://honeypeach.cc/"
_UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
_TIMEOUT = 15

_G_LOCK = threading.Lock()
_G = {"sid": None, "skey": None, "exp": 0.0}


def _hmac_sha256(key, msg):
    if not isinstance(key, bytes):
        key = key.encode()
    if not isinstance(msg, bytes):
        msg = msg.encode()
    block = 64
    if len(key) > block:
        key = hashlib.sha256(key).digest()
    key = key + b"\x00" * (block - len(key))
    o = bytes(x ^ 0x5c for x in key)
    i = bytes(x ^ 0x36 for x in key)
    return hashlib.sha256(o + hashlib.sha256(i + msg).digest()).hexdigest()


def _hp_hash(s):
    h = 0x811c9dc5
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def _hp_pow(chal, nonce):
    h = _hp_hash(chal + ":" + nonce)
    for _ in range(4):
        h = _hp_hash("%08x" % h + chal)
    return "%08x" % h


def _hp_solve(chal, bits):
    try:
        bits = int(bits)
    except Exception:
        bits = 16
    want = "0" * (bits >> 2)
    n = 0
    while n < 20000000:
        nx = "%x" % n
        if _hp_pow(chal, nx).startswith(want):
            return chal + "." + nx
        n += 1
    return ""


def _b64e(s):
    return base64.urlsafe_b64encode(str(s).encode("utf-8")).decode().rstrip("=")


def _b64d(s):
    try:
        k = str(s or "")
        return base64.urlsafe_b64decode((k + "=" * (-len(k) % 4)).encode()).decode("utf-8", "replace")
    except Exception:
        return str(s or "")


def _skey_bytes(skey):
    """兼容十六进制 / base64 / 原始字符串三种 skey 编码。"""
    s = str(skey or "")
    if not s:
        return b""
    try:
        return bytes.fromhex(s)
    except Exception:
        pass
    try:
        return base64.b64decode(s + "=" * (-len(s) % 4))
    except Exception:
        return s.encode("utf-8", "replace")


class Spider:
    def __init__(self):
        self.site = _BASE
        self.name = "蜜桃视频"
        self.header = {"User-Agent": _UA, "Accept": "application/json"}
        self.s = self.session = self.sess = _rq.Session() if _rq else None
        self._extend = {}
        self._dev = None
        self._mods = []
        self._mods_at = 0.0
        self._debug = False
        self._last_error = ""

    # ---------- 日志 ----------
    def _log(self, msg):
        if self._debug:
            try:
                print("[蜜桃] " + str(msg))
            except Exception:
                pass

    def _err(self, msg):
        self._last_error = str(msg)
        self._log(self._last_error)

    # ---------- 框架约定 ----------
    def getDependence(self):
        return []

    def manualVideoCheck(self):
        return False

    def isVideoFormat(self, url):
        return bool(url) and re.search(r"(?i)\.(mp4|m3u8|flv|mkv|avi|ts|mov|mpd)(\?.*)?$", str(url)) is not None

    def destroy(self):
        try:
            if self.s is not None:
                self.s.close()
        except Exception:
            pass
        self.s = None

    def action(self, action):
        return {}

    # ---------- 设备 / 鉴权 ----------
    def _dev_id(self):
        if not self._dev:
            self._dev = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(12)) \
                + format(int(time.time() * 1000), "x")
        return self._dev

    def _shake_done(self, d):
        if d and d.get("sid") and d.get("skey"):
            _G["sid"] = d["sid"]
            _G["skey"] = d["skey"]
            exp = float(d.get("exp") or 0)
            if exp > 1e12:  # 服务端若返回毫秒时间戳则换算
                exp = exp / 1000.0
            _G["exp"] = exp
            self._log("handshake ok sid=%s exp=%s" % (d["sid"], exp))
            return True
        return False

    def _shake_once(self):
        url0 = _BASE + "/api/handshake?dev=" + _quote(self._dev_id())
        h = {"User-Agent": _UA, "Accept": "application/json"}

        # 优先 requests（保留 Cookie 会话）
        if _rq is not None:
            s = None
            try:
                s = _rq.Session()
                r = s.get(url0, headers=h, timeout=_TIMEOUT)
                if r.status_code != 200:
                    self._err("shake http %s" % r.status_code)
                    return False
                try:
                    d = r.json()
                except Exception:
                    self._err("shake json err: %r" % (r.text[:200],))
                    return False
                if not d.get("need_chal"):
                    return self._shake_done(d)
                self._log("shake chal=%s bits=%s solving..." % (d.get("need_chal"), d.get("bits")))
                tok = _hp_solve(str(d["need_chal"]), d.get("bits") or 16)
                if not tok:
                    self._err("shake pow fail chal=%s bits=%s" % (d.get("need_chal"), d.get("bits")))
                    return False
                self._log("shake pow solved: %s" % tok[:40])
                r = s.get(url0 + "&c=" + _quote(tok), headers=h, timeout=_TIMEOUT)
                if r.status_code != 200:
                    self._err("shake2 http %s" % r.status_code)
                    return False
                try:
                    d = r.json()
                except Exception:
                    self._err("shake2 json err: %r" % (r.text[:200],))
                    return False
                return self._shake_done(d)
            except Exception as e:
                self._err("shake requests err: %r" % (e,))
            finally:
                try:
                    if s is not None:
                        s.close()
                except Exception:
                    pass

        # urllib fallback（带 CookieJar 维持会话）
        try:
            import urllib.request
            if _cookiejar is not None:
                cj = _cookiejar.CookieJar()
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            else:
                opener = urllib.request.build_opener()
            req = urllib.request.Request(url0, headers=h)
            with opener.open(req, timeout=_TIMEOUT) as resp:
                if resp.getcode() != 200:
                    self._err("shake urllib http %s" % resp.getcode())
                    return False
                body = resp.read().decode("utf-8", "replace")
            try:
                d = json.loads(body)
            except Exception:
                self._err("shake urllib json err: %r" % (body[:200],))
                return False
            if not d.get("need_chal"):
                return self._shake_done(d)
            self._log("shake urllib chal=%s bits=%s solving..." % (d.get("need_chal"), d.get("bits")))
            tok = _hp_solve(str(d["need_chal"]), d.get("bits") or 16)
            if not tok:
                self._err("shake urllib pow fail chal=%s bits=%s" % (d.get("need_chal"), d.get("bits")))
                return False
            req = urllib.request.Request(url0 + "&c=" + _quote(tok), headers=h)
            with opener.open(req, timeout=_TIMEOUT) as resp:
                if resp.getcode() != 200:
                    self._err("shake2 urllib http %s" % resp.getcode())
                    return False
                body = resp.read().decode("utf-8", "replace")
            try:
                d = json.loads(body)
            except Exception:
                self._err("shake2 urllib json err: %r" % (body[:200],))
                return False
            return self._shake_done(d)
        except Exception as e:
            self._err("shake urllib err: %r" % (e,))
            return False

    def _ensure_auth(self):
        now = time.time()
        if _G["sid"] and _G["skey"] and now < _G["exp"] - 60:
            return True
        with _G_LOCK:
            now = time.time()
            if _G["sid"] and _G["skey"] and now < _G["exp"] - 60:
                return True
            for _ in range(3):
                if self._shake_once():
                    return True
            self._err("ensure_auth failed after 3 tries")
            return False

    def _sign_headers(self, path, query):
        sid, skey = _G["sid"], _G["skey"]
        if not sid or not skey:
            return {}
        ts = str(int(time.time()))
        nonce = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8)) \
            + format(int(time.time() * 1000), "x")
        bh = hashlib.sha256(b"").hexdigest()
        canon = "GET\n%s\n%s\n%s\n%s\n%s\n%s" % (path, query, bh, ts, nonce, sid)
        return {
            "X-Hp-Sid": sid,
            "X-Hp-Ts": ts,
            "X-Hp-Nonce": nonce,
            "X-Hp-Sign": _hmac_sha256(_skey_bytes(skey), canon.encode()),
        }

    # ---------- 网络 ----------
    def _raw_get(self, url, headers=None, timeout=_TIMEOUT):
        h = dict(self.header)
        if headers:
            h.update(headers)
        if self.s is not None:
            try:
                r = self.s.get(url, headers=h, timeout=timeout)
                return r.status_code, r.text
            except Exception as e:
                self._log("requests get err: %r" % (e,))
        try:
            import urllib.request
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.getcode(), resp.read().decode("utf-8", "replace")
        except Exception as e:
            self._err("urllib get err: %r url=%s" % (e, url))
            return 0, ""

    def _api(self, path, query=""):
        try:
            if not self._ensure_auth():
                self._log("api %s without auth, last_error=%s" % (path, self._last_error))
            url = _BASE + path + (("?" + query) if query else "")
            h = self._sign_headers(path, query)
            st, txt = self._raw_get(url, h)
            if st == 401:
                with _G_LOCK:
                    _G["sid"] = _G["skey"] = None
                    _G["exp"] = 0.0
                if self._ensure_auth():
                    h = self._sign_headers(path, query)  # 重新签名，避免旧 nonce 复用
                    st, txt = self._raw_get(url, h)
            try:
                return st, json.loads(txt) if txt else {}
            except Exception:
                self._err("api json parse %s -> %r" % (path, txt[:200] if txt else ""))
                return st, {}
        except Exception as e:
            self._err("api %s err: %r" % (path, e))
            return 0, {}

    # ---------- 编码 / 解包 ----------
    def _full(self, u):
        if not u:
            return ""
        u = str(u)
        return u if u.startswith("http") else _BASE + u

    def _enc_id(self, key, iid, src="", sub=""):
        return _b64e("|".join([str(key), str(iid), str(src or ""), str(sub or "")]))

    def _dec_id(self, vid):
        p = (_b64d(vid).split("|") + ["", "", "", ""])[:4]
        return p[0], p[1], p[2], p[3]

    def _enc_play(self, key, iid, ep, src="", sub=""):
        return _b64e("|".join([str(key), str(iid), str(ep), str(src or ""), str(sub or "")]))

    def _dec_play(self, vid):
        p = (_b64d(vid).split("|") + ["", "", "", "", ""])[:5]
        return p[0], p[1], p[2], p[3], p[4]

    def _vod(self, it, key, src="", sub=""):
        iid = it.get("id")
        if iid is None:
            return None
        return {"vod_id": self._enc_id(key, iid, it.get("src") or src, sub),
                "vod_name": str(it.get("title") or ""),
                "vod_pic": self._full(it.get("cover") or ""),
                "vod_remarks": str(it.get("remark") or "")}

    def _get_modules(self):
        now = time.time()
        if self._mods and now - self._mods_at < 3600:
            return self._mods
        st, d = self._api("/api/home", "")
        mods = []
        if isinstance(d, dict):
            for m in d.get("modules") or []:
                if isinstance(m, dict) and m.get("key"):
                    mods.append((str(m["key"]), str(m.get("name") or m["key"])))
        if mods:
            self._mods, self._mods_at = mods, now
        else:
            self._log("_get_modules empty: st=%s type=%s keys=%s" %
                      (st, type(d).__name__, list(d.keys()) if isinstance(d, dict) else ""))
        return self._mods or mods

    def _cats(self, key):
        st, d = self._api("/api/cats", "key=%s&v=4" % key)
        cats = []
        if isinstance(d, dict):
            for c in d.get("cats") or []:
                if not isinstance(c, dict):
                    continue
                if (c.get("kind") or "vod") not in ("vod", "tags"):
                    continue
                cats.append({"code": str(c.get("code") or ""),
                             "name": str(c.get("name") or c.get("code") or ""),
                             "src": str(c.get("src") or ""),
                             "sub": c.get("sub")})
        else:
            self._log("_cats %s empty st=%s" % (key, st))
        return cats

    # ---------- 框架接口 ----------
    def init(self, extend=""):
        self._extend = {}
        if isinstance(extend, dict):
            self._extend = extend
        elif isinstance(extend, str) and extend.strip():
            try:
                e = json.loads(extend)
                if isinstance(e, dict):
                    self._extend = e
            except Exception:
                pass
        self._debug = bool(self._extend.get("debug"))
        self._log("init debug=%s" % self._debug)

    def homeContent(self, filter=None):
        try:
            if not self._ensure_auth():
                self._log("homeContent auth failed: %s" % self._last_error)
            mods = self._get_modules()
            classes = []

            def one(km):
                key, mname = km
                out = []
                for c in self._cats(key):
                    if not c["code"]:
                        continue
                    out.append({"type_id": self._enc_id(key, c["code"], c["src"], c["sub"] or ""),
                                "type_name": mname + "·" + c["name"]})
                return out

            if _Pool is not None and len(mods) > 1:
                try:
                    with _Pool(max_workers=min(7, len(mods))) as ex:
                        for out in ex.map(one, mods):
                            classes.extend(out)
                except Exception as e:
                    self._err("homeContent pool err: %r" % (e,))
                    for km in mods:
                        classes.extend(one(km))
            else:
                for km in mods:
                    classes.extend(one(km))
            self._log("homeContent mods=%d classes=%d" % (len(mods), len(classes)))
            return {"class": classes, "filters": {}}
        except Exception as e:
            self._err("homeContent err: %r" % (e,))
            return {"class": [], "filters": {}}

    def homeVideoContent(self):
        try:
            if not self._ensure_auth():
                self._log("homeVideoContent auth failed")
            for key, _ in self._get_modules():
                st, d = self._api("/api/module", "key=%s&page=1" % key)
                if isinstance(d, dict) and d.get("list"):
                    return {"list": [v for v in
                                     (self._vod(it, key) for it in d["list"][:12]) if v]}
            return {"list": []}
        except Exception as e:
            self._err("homeVideoContent err: %r" % (e,))
            return {"list": []}

    def categoryContent(self, tid, pg=1, filter=None, extend=None):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        try:
            key, cat, src, sub = self._dec_id(tid)
            if not key or not cat:
                self._log("categoryContent bad tid=%s" % tid)
                return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}
            q = "key=%s&cat=%s&page=%d" % (key, _quote(cat), pg)
            if src:
                q += "&src=" + _quote(src)
            if sub not in ("", None):
                q += "&sub=" + _quote(str(sub))
            st, d = self._api("/api/module", q)
            lst, pc = [], 1
            if isinstance(d, dict):
                for it in d.get("list") or []:
                    v = self._vod(it, key, src, sub)
                    if v:
                        lst.append(v)
                pc = int(d.get("pages") or 1)
            else:
                self._log("categoryContent %s empty st=%s" % (tid, st))
            self._log("categoryContent %s pg=%s -> %d items pages=%s" % (tid, pg, len(lst), pc))
            return {"list": lst, "page": pg, "pagecount": pc, "limit": 20, "total": len(lst)}
        except Exception as e:
            self._err("categoryContent err: %r" % (e,))
            return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}

    def detailContent(self, ids):
        try:
            vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
            vid = str(vid or "").strip()
            if vid.startswith("["):
                try:
                    vid = str(json.loads(vid)[0])
                except Exception:
                    vid = vid.split(",")[0].strip("[]\"' ")
            if "$" in vid:
                vid = vid.split("$")[-1].strip()
            key, iid, src, sub = self._dec_id(_unquote(vid))
            if not key or not iid:
                self._log("detailContent bad vid=%s" % vid)
                return {"list": []}
            q = ""
            if src:
                q += "src=" + _quote(src)
            if sub not in ("", None):
                q += ("&" if q else "") + "sub=" + _quote(str(sub))
            st, d = self._api("/api/detail/%s/%s" % (key, _quote(str(iid))), q)
            det = (d.get("detail") or {}) if isinstance(d, dict) else {}
            if not det:
                self._log("detailContent empty key=%s iid=%s st=%s" % (key, iid, st))
                return {"list": []}
            eps = det.get("episodes") or [{"ep": 1, "name": "正片"}]
            lines = []
            for e in eps:
                if not isinstance(e, dict):
                    continue
                ep = e.get("ep", 1)
                name = re.sub(r"[$#]", " ", str(e.get("name") or "第%s集" % ep)).strip() or str(ep)
                lines.append("%s$%s" % (name, self._enc_play(key, iid, ep, src, sub)))
            self._log("detailContent ok %s eps=%d" % (det.get("title"), len(lines)))
            return {"list": [{"vod_id": vid, "vod_name": str(det.get("title") or ""),
                               "vod_pic": self._full(det.get("cover") or ""),
                               "vod_year": str(det.get("date") or ""),
                               "vod_remarks": ("共%s集" % det.get("ep_count")) if det.get("ep_count") else "",
                               "vod_content": str(det.get("desc") or ""),
                               "type_name": str(det.get("code") or ""),
                               "vod_play_from": "蜜桃",
                               "vod_play_url": "#".join(lines)}]}
        except Exception as e:
            self._err("detailContent err: %r" % (e,))
            return {"list": []}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        try:
            kw = str(key or "").strip()
            if not kw:
                return {"list": [], "page": pg}
            mods = [k for k, _ in self._get_modules() if k != "live"] or \
                ["video", "duanju", "caibian", "shortv", "guochan"]

            def one(k):
                st, d = self._api("/api/search", "key=%s&kw=%s&page=%d" % (k, _quote(kw), pg))
                out = []
                if isinstance(d, dict):
                    for it in d.get("list") or []:
                        v = self._vod(it, k)
                        if v:
                            out.append(v)
                return out

            items, seen = [], set()
            if _Pool is not None and len(mods) > 1:
                try:
                    with _Pool(max_workers=min(6, len(mods))) as ex:
                        results = list(ex.map(one, mods))
                except Exception as e:
                    self._err("searchContent pool err: %r" % (e,))
                    results = [one(k) for k in mods]
            else:
                results = [one(k) for k in mods]
            for rs in results:
                for v in rs:
                    if v["vod_id"] not in seen:
                        seen.add(v["vod_id"])
                        items.append(v)
            self._log("searchContent kw=%s -> %d items" % (kw, len(items)))
            return {"list": items, "page": pg, "pagecount": 1, "limit": len(items), "total": len(items)}
        except Exception as e:
            self._err("searchContent err: %r" % (e,))
            return {"list": [], "page": pg}

    def playerContent(self, flag, ids, vipFlags=None):
        try:
            u = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
            u = str(u or "").strip()
            if "$" in u:
                u = u.split("$")[-1].strip()
            key, iid, ep, src, sub = self._dec_play(_unquote(u))
            if not key or not iid:
                self._log("playerContent bad ids=%s" % ids)
                return {"parse": 0, "url": "", "header": "{}"}
            q = ""
            if src:
                q += "src=" + _quote(src)
            if sub not in ("", None):
                q += ("&" if q else "") + "sub=" + _quote(str(sub))
            st, d = self._api("/api/play/%s/%s/%s" % (key, _quote(str(iid)), _quote(str(ep))), q)
            pl = (d.get("play") or {}) if isinstance(d, dict) else {}
            url = str(pl.get("src") or "")
            if not url or pl.get("locked"):
                self._log("playerContent empty key=%s iid=%s ep=%s st=%s locked=%s"
                          % (key, iid, ep, st, pl.get("locked")))
                return {"parse": 0, "url": "", "header": "{}"}
            full_url = self._full(url)
            is_direct = bool(re.search(r"(?i)\.(mp4|m3u8|flv|mkv|avi|ts|mov|mpd)(\?.*)?$", full_url))
            hdr = json.dumps({"User-Agent": _UA, "Referer": _BASE + "/"})
            self._log("playerContent ok parse=%s url=%s" % (0 if is_direct else 1, full_url[:120]))
            return {"parse": 0 if is_direct else 1, "url": full_url, "header": hdr}
        except Exception as e:
            self._err("playerContent err: %r" % (e,))
            return {"parse": 0, "url": "", "header": "{}"}

    def localProxy(self, param):
        try:
            p = json.loads(param) if isinstance(param, str) else (param or {})
            u = _unquote(p.get("url", ""))
            if not u:
                return [502, "text/plain", b"", {}]
            hdr = p.get("header") or {}
            if isinstance(hdr, str):
                try:
                    hdr = json.loads(hdr)
                except Exception:
                    hdr = {}
            code, txt = self._raw_get(u if u.startswith("http") else self._full(u), hdr, 20)
            body = txt.encode("utf-8", "replace") if isinstance(txt, str) else b""
            if code != 200:
                return [502, "text/plain", b"", {}]
            return [200, "application/octet-stream", body, {"Content-Length": str(len(body))}]
        except Exception as e:
            self._err("localProxy err: %r" % (e,))
            return [502, "text/plain", b"", {}]
