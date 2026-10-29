# coding: utf-8

import base64
import hashlib
import json
import os
import random
import re
import string
import tempfile
import time
import uuid
from urllib.parse import parse_qsl, quote

from base.spider import Spider as BaseSpider


# ---------------- 纯 Python AES-128（FIPS-197，标准库实现） ----------------
_SBOX = [
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16]
_SBOX_INV = [0] * 256
for _i in range(256):
    _SBOX_INV[_SBOX[_i]] = _i
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]


def _xtime(b):
    return ((b << 1) ^ 0x11b) & 0xff if b & 0x80 else (b << 1) & 0xff


def _gf_mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xtime(a)
        b >>= 1
    return r & 0xff


def _sub_bytes(st, sbox):
    for i in range(16):
        st[i] = sbox[st[i]]


def _shift_rows(st):
    st[1], st[5], st[9], st[13] = st[5], st[9], st[13], st[1]
    st[2], st[6], st[10], st[14] = st[10], st[14], st[2], st[6]
    st[3], st[7], st[11], st[15] = st[15], st[3], st[7], st[11]


def _inv_shift_rows(st):
    st[1], st[5], st[9], st[13] = st[13], st[1], st[5], st[9]
    st[2], st[6], st[10], st[14] = st[10], st[14], st[2], st[6]
    st[3], st[7], st[11], st[15] = st[7], st[11], st[15], st[3]


def _mix_cols(st):
    for c in range(0, 16, 4):
        a0, a1, a2, a3 = st[c], st[c + 1], st[c + 2], st[c + 3]
        st[c] = _gf_mul(a0, 2) ^ _gf_mul(a1, 3) ^ a2 ^ a3
        st[c + 1] = a0 ^ _gf_mul(a1, 2) ^ _gf_mul(a2, 3) ^ a3
        st[c + 2] = a0 ^ a1 ^ _gf_mul(a2, 2) ^ _gf_mul(a3, 3)
        st[c + 3] = _gf_mul(a0, 3) ^ a1 ^ a2 ^ _gf_mul(a3, 2)


def _inv_mix_cols(st):
    for c in range(0, 16, 4):
        a0, a1, a2, a3 = st[c], st[c + 1], st[c + 2], st[c + 3]
        st[c] = _gf_mul(a0, 14) ^ _gf_mul(a1, 11) ^ _gf_mul(a2, 13) ^ _gf_mul(a3, 9)
        st[c + 1] = _gf_mul(a0, 9) ^ _gf_mul(a1, 14) ^ _gf_mul(a2, 11) ^ _gf_mul(a3, 13)
        st[c + 2] = _gf_mul(a0, 13) ^ _gf_mul(a1, 9) ^ _gf_mul(a2, 14) ^ _gf_mul(a3, 11)
        st[c + 3] = _gf_mul(a0, 11) ^ _gf_mul(a1, 13) ^ _gf_mul(a2, 9) ^ _gf_mul(a3, 14)


def _key_expand(key):
    nk = 4
    w = [list(key[i * 4:(i + 1) * 4]) for i in range(nk)]
    for i in range(nk, 44):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= _RCON[i // nk - 1]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return w


def _add_round_key(st, w, rnd):
    base = 4 * rnd
    for i in range(16):
        st[i] ^= w[base + i // 4][i % 4]


def _encrypt_block(block, w):
    st = list(block)
    _add_round_key(st, w, 0)
    for rnd in range(1, 10):
        _sub_bytes(st, _SBOX)
        _shift_rows(st)
        _mix_cols(st)
        _add_round_key(st, w, rnd)
    _sub_bytes(st, _SBOX)
    _shift_rows(st)
    _add_round_key(st, w, 10)
    return st


def _decrypt_block(block, w):
    st = list(block)
    _add_round_key(st, w, 10)
    _inv_shift_rows(st)
    _sub_bytes(st, _SBOX_INV)
    for rnd in range(9, 0, -1):
        _add_round_key(st, w, rnd)
        _inv_mix_cols(st)
        _inv_shift_rows(st)
        _sub_bytes(st, _SBOX_INV)
    _add_round_key(st, w, 0)
    return st


def _aes_ecb_encrypt(plain, key):
    w = _key_expand(key)
    padded = plain + bytes([16 - len(plain) % 16]) * (16 - len(plain) % 16)
    out = b""
    for i in range(0, len(padded), 16):
        out += bytes(_encrypt_block(padded[i:i + 16], w))
    return out


def _aes_ecb_decrypt(data, key):
    w = _key_expand(key)
    out = bytearray()
    for i in range(0, len(data), 16):
        out += bytes(_decrypt_block(data[i:i + 16], w))
    padn = out[-1] if out else 0
    if 0 < padn <= 16:
        out = out[:-padn]
    return bytes(out)


def _aes_cbc_decrypt(data, key, iv):
    w = _key_expand(key)
    prev = list(iv)
    out = bytearray()
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        dec = _decrypt_block(blk, w)
        out += bytes([dec[j] ^ prev[j] for j in range(16)])
        prev = list(blk)
    padn = out[-1] if out else 0
    if 0 < padn <= 16:
        out = out[:-padn]
    return bytes(out)


# 封面/图片是「整文件 XOR」加密的，密钥全站通用（WebP 与 JPEG 同一把）
PIC_KEY = b"2020-zq3-888"
PIC_HEAD = 100
PIC_CACHE_MAX = 8 * 1024 * 1024
IMG_MAGIC = ((b"\xff\xd8\xff", "image/jpeg"),
             (b"RIFF", "image/webp"),
             (b"\x89PNG\r\n\x1a\n", "image/png"),
             (b"GIF8", "image/gif"))

API_TIMEOUT = 10          # 单次请求超时（秒），避免 DNS 挂起拖死整个列表
API_RETRIES = 3           # 换域重试次数（含首次）


def _xor_pic(data):
    """⚠ 站点只把**前 100 字节**做了循环异或，图片主体本来就是明文。"""
    n = len(data)
    if not n:
        return b""
    m = min(PIC_HEAD, n)
    out = bytearray(data)
    for i in range(m):
        out[i] ^= PIC_KEY[i % len(PIC_KEY)]
    return bytes(out)


def _xor_pic_full(data):
    """整文件解密（兜底）。少数图可能是全文件加密，用大整数一次算完。"""
    n = len(data)
    if not n:
        return b""
    k = (PIC_KEY * (n // len(PIC_KEY) + 1))[:n]
    return (int.from_bytes(data, "big") ^ int.from_bytes(k, "big")).to_bytes(n, "big")


def _img_type(data):
    for magic, ctype in IMG_MAGIC:
        if data.startswith(magic):
            return ctype
    return ""


class Spider(BaseSpider):
    def getName(self):
        return "社区-暴走黑料"

    def getDependence(self):
        return []

    # ---------------- 初始化 & 抗封锁入口 ----------------
    def _new_host(self):
        """生成一个随机子域入口（服务端泛解析，任意子域均通）。"""
        sub = ''.join(random.choice(string.ascii_lowercase + string.digits)
                      for _ in range(random.randint(5, 8)))
        return "https://%s.opf1x78l.work" % sub

    def _load_device_id(self, extend):
        """device_id 持久化：extend 显式传 → 本地缓存文件 → 首次随机并落盘。

        原版每次 init 都 uuid4()，等于每次重启都是新设备，容易被服务端当异常设备标记。
        这里优先复用，落盘失败（沙盒无写权限）时退回随机，不影响功能。
        """
        ext = str(extend or "")
        m = re.search(r"(?:^|[&?])deviceId=([^&]+)", ext)
        if m:
            return m.group(1)

        candidates = []
        for base in (tempfile.gettempdir(), os.path.expanduser("~")):
            if base:
                candidates.append(os.path.join(base, ".spider_community_devid"))

        for p in candidates:
            try:
                if os.path.isfile(p):
                    with open(p, "r") as f:
                        s = f.read().strip()
                    if len(s) >= 16:
                        return s
            except Exception:
                continue

        nid = uuid.uuid4().hex
        for p in candidates:
            try:
                d = os.path.dirname(p)
                if d and not os.path.isdir(d):
                    continue
                with open(p, "w") as f:
                    f.write(nid)
                break
            except Exception:
                continue
        return nid

    def init(self, extend=""):
        self.extend = extend or ""
        self.host = self._new_host()
        self.ua = ("Mozilla/5.0 (Linux; Android 14; 22127RK46C Build/TP1A.220624.014; wv) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
                   "Chrome/120.0.0.0 Mobile Safari/537.36/SuiRui/twitter/ver=3.1.1")
        self.device_id = self._load_device_id(extend)
        self.token = None
        self._domain = None
        self._auth_domain = None
        self._classes_cache = None
        self._pic_cache = {}
        self._pic_size = 0
        self._play_vid = None       # localProxy 兜底用，避免未播先代理时 AttributeError
        self._host_rotations = 0    # 仅统计，便于排查

    # ---------------- 统一请求层（带超时 / 换域重试） ----------------
    def _fetch(self, url, headers=None, method="GET", data=None, timeout=API_TIMEOUT):
        """统一入口：优先带 timeout；老客户端不支持 timeout 时自动降级。"""
        kw = {"headers": headers or {}}
        if method == "POST":
            kw["data"] = data
        fn = self.post if method == "POST" else self.fetch
        try:
            return fn(url, timeout=timeout, **kw)
        except TypeError:
            return fn(url, **kw)

    def _fetch_api(self, path, method="GET", data=None, headers=None,
                   timeout=API_TIMEOUT, tries=API_RETRIES):
        """API 请求：连接异常 / 5xx / 429 时换子域重试；4xx 原样交上层判 token。

        只有"入口层面"的失败才换域，业务错误（如 token 失效）不浪费随机子域，
        否则一次 401 会把所有可用子域全试一遍，反而增加暴露面。
        """
        last = None
        for i in range(max(1, tries)):
            try:
                r = self._fetch(self.host + path,
                                headers=headers if headers is not None else self._headers(),
                                method=method, data=data, timeout=timeout)
            except Exception as e:
                last = e
            else:
                if r is None:
                    last = None
                else:
                    try:
                        sc = int(getattr(r, "status_code", 200) or 200)
                    except Exception:
                        sc = 200
                    if 200 <= sc < 300:
                        return r
                    if sc == 429 or sc >= 500:
                        last = r              # 入口/限流问题，值得换域
                    else:
                        return r              # 4xx 交给上层（token 失效走重登）
            if i < tries - 1:
                self.host = self._new_host()
                self.token = None              # 保守：不确定 token 是否与 Host 绑定
                self._host_rotations += 1
        return last

    # ---------------- 加密/鉴权工具 ----------------
    @staticmethod
    def _b64d(s):
        return base64.b64decode(s)

    @staticmethod
    def _b64e(b):
        return base64.b64encode(b).decode()

    def _login_key(self, epoch):
        path = format(epoch, "x")[:8] + uuid.uuid4().hex[:16]
        off = epoch % 8
        return path, path[off:16 + off][::-1]

    def _ensure_token(self):
        if self.token:
            return
        epoch = int(time.time())
        path, ek = self._login_key(epoch)
        req = json.dumps({"deviceId": self.device_id, "tt": "a"}, separators=(",", ":"))
        enc = self._b64e(_aes_ecb_encrypt(req.encode(), ek.encode()))
        h = self._headers()
        h["Content-Type"] = "application/json"
        h["Accept"] = "application/json"
        try:
            r = self._fetch_api("/api/user/traveler/" + path + "/login",
                                method="POST",
                                data=json.dumps({"encStr": enc}, separators=(",", ":")),
                                headers=h)
            if r is None:
                self.token = None
                return
            j = json.loads(r.text)
            if j.get("code") == 200 and j.get("data"):
                plain = _aes_ecb_decrypt(self._b64d(j["data"]), ek.encode())
                ui = json.loads(plain.decode("utf-8", "ignore"))
                self.token = ui.get("token")
        except Exception:
            self.token = None

    def _headers(self, with_aut=True):
        t = str(int(time.time() * 1000))
        s = hashlib.md5(t[3:8].encode()).hexdigest()
        h = {
            "User-Agent": self.ua,
            "Accept": "application/json, text/plain, */*",
            "deviceId": self.device_id,
            "t": t,
            "s": s,
        }
        if with_aut and self.token:
            h["aut"] = self.token
        return h

    def _req(self, path):
        """GET 业务接口：自动登录 + encData 解密"""
        if not self.token:
            self._ensure_token()
        r = self._fetch_api(path, headers=self._headers())
        if r is None:
            return None
        txt = r.text
        try:
            j = json.loads(txt)
        except Exception:
            return None
        # token 失效重登一次
        if j.get("code") in (400, 1001) and j.get("msg") and "token" in str(j.get("msg")):
            self.token = None
            self._ensure_token()
            if not self.token:
                return j
            r = self._fetch_api(path, headers=self._headers())
            if r is None:
                return None
            try:
                j = json.loads(r.text)
            except Exception:
                return None
        if j.get("encData"):
            try:
                dec = _aes_cbc_decrypt(self._b64d(j["encData"]), self.token[2:18].encode(),
                                       self.token[2:18].encode())
                dj = json.loads(dec.decode("utf-8", "ignore"))
                if isinstance(dj, dict):
                    self._domain = dj.get("domain") or self._domain
                    self._auth_domain = dj.get("authDomain") or self._auth_domain
                return dj
            except Exception:
                return j
        return j

    def _m3u8(self, vid):
        if not self.token:
            self._ensure_token()
        r = self._fetch_api("/api/m3u8/decode/by/id?videoId=%s" % vid,
                            headers=self._headers())
        if r is None:
            return ""
        txt = r.text
        if txt.startswith("#EXTM3U"):
            return txt
        try:
            j = json.loads(txt)
            if j.get("encData"):
                dec = _aes_cbc_decrypt(self._b64d(j["encData"]), self.token[2:18].encode(),
                                       self.token[2:18].encode())
                return dec.decode("utf-8", "ignore")
        except Exception:
            pass
        return txt

    # ---------------- 数据映射 ----------------
    def _pic(self, rel, auth=False):
        """封面走 localProxy：原图是 XOR 加密的，客户端直接加载只会得到一张乱码图。"""
        if not rel:
            return ""
        if rel.startswith("http"):
            return rel
        rel = rel.split("?", 1)[0]          # auth_key 60 秒过期，一律丢掉，代理里用裸路径
        return self._proxy_url(type="pic", p=rel)

    def _proxy_url(self, **params):
        """构造本地代理地址（必须走 getProxyUrl，否则 FongMi 侧 500）。"""
        from urllib.parse import urlencode
        q = urlencode(params)
        try:
            base = str(self.getProxyUrl())
            if base:
                sep = "&" if "?" in base else "?"
                return base + sep + q
        except Exception:
            pass
        try:
            return str(self.getProxyUrl(params, True))
        except Exception:
            pass
        return "http://127.0.0.1:9978/proxy?" + q

    def _pic_candidates(self, rel):
        """按可用性排序列出候选地址。

        - domain 裸路径免签名，优先；
        - authDomain 必须带 auth_key（但我们在代理里丢签名，实测也能取到，作次选）；
        - 最后追加硬编码域 + 当前随机 API 子域，作为业务域被封时的兜底。
        """
        out = []
        if rel.startswith("http"):
            return [rel]
        rel = rel.split("?", 1)[0]
        for d in (self._domain, self._auth_domain,
                  "https://972pb3r10qxz.dfgwsx.com/", self.host):
            if d:
                u = d.rstrip("/") + "/" + rel.lstrip("/")
                if u not in out:
                    out.append(u)
        return out

    def _load_pic(self, rel):
        """下载并解密封面，带内容缓存。"""
        hit = self._pic_cache.get(rel)
        if hit:
            return hit
        raw = b""
        for url in self._pic_candidates(rel):
            try:
                r = self._fetch(url, headers={"User-Agent": self.ua}, timeout=API_TIMEOUT)
                if r is not None and r.content:
                    raw = r.content
                    break
            except Exception:
                continue
        if not raw:
            return (None, None)
        out = _xor_pic(raw)
        ctype = _img_type(out)
        if not ctype:
            alt = _xor_pic_full(raw)
            ct2 = _img_type(alt)
            if ct2:
                out, ctype = alt, ct2
        if not ctype:
            out, ctype = raw, "image/jpeg"
        if self._pic_size + len(out) > PIC_CACHE_MAX and self._pic_cache:
            self._pic_cache.clear()
            self._pic_size = 0
        self._pic_cache[rel] = (out, ctype)
        self._pic_size += len(out)
        return (out, ctype)

    def _vod(self, v):
        tags = " ".join(v.get("tagTitles") or [])
        pt = v.get("playTime") or 0
        remark = tags[:18] if tags else ("%d分钟" % int(pt // 60) if pt else "")
        pic = self._pic((v.get("coverImg") or [None])[0] or "")
        if not pic:
            pic = self._pic((v.get("authCoverImg") or [None])[0] or "", auth=True)
        return {
            "vod_id": str(v.get("videoId") or v.get("id")),
            "vod_name": v.get("title") or "",
            "vod_pic": pic,
            "vod_remarks": remark,
        }

    # ---------------- 接口 ----------------
    def homeContent(self, filter):
        classes = []
        try:
            d = self._req("/api/video/classifyList")
            data = d.get("data") if isinstance(d, dict) else None
            if isinstance(data, list):
                self._domain = d.get("domain") or self._domain
                for c in data:
                    if c.get("classifyId") and c.get("classifyTitle"):
                        classes.append({"type_id": str(c["classifyId"]),
                                        "type_name": str(c["classifyTitle"])})
        except Exception:
            pass
        self._classes_cache = classes
        lst = []
        try:
            d2 = self._req("/api/video/queryVideos?pageSize=20&page=1&classifyId=2")
            data2 = d2.get("data") if isinstance(d2, dict) else None
            if isinstance(data2, list):
                lst = [self._vod(v) for v in data2]
        except Exception:
            pass
        return {"class": classes, "filters": {}, "list": lst}

    def homeVideoContent(self):
        lst = []
        try:
            d = self._req("/api/video/queryVideos?pageSize=20&page=1&classifyId=2")
            data = d.get("data") if isinstance(d, dict) else None
            if isinstance(data, list):
                lst = [self._vod(v) for v in data]
        except Exception:
            pass
        return {"list": lst}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg or 1)
        lst = []
        try:
            d = self._req("/api/video/queryVideos?pageSize=20&page=%d&classifyId=%s" % (page, tid))
            data = d.get("data") if isinstance(d, dict) else None
            if isinstance(data, list):
                lst = [self._vod(v) for v in data]
        except Exception:
            pass
        return {"list": lst, "page": page, "pagecount": page + 1,
                "limit": 20, "total": (page + 1) * 20}

    def detailContent(self, ids):
        vid = str(ids[0]).split("://")[-1]
        vod = {"vod_id": vid, "vod_name": "", "vod_pic": "", "vod_content": "",
               "vod_play_from": "", "vod_play_url": ""}
        try:
            d = self._req("/api/video/getVideoById?videoId=%s" % vid)
            if isinstance(d, dict):
                vod["vod_name"] = d.get("title") or vod["vod_name"]
                pic = self._pic((d.get("coverImg") or [None])[0] or "")
                if not pic:
                    pic = self._pic((d.get("authCoverImg") or [None])[0] or "", auth=True)
                vod["vod_pic"] = pic
                tags = " ".join([t.get("videoTagValue") for t in d.get("videoTags") or [] if t.get("videoTagValue")])
                vod["vod_content"] = tags or (d.get("subtitle") or "")
                if d.get("videoUrl"):
                    vod["vod_play_from"] = "在线播放"
                    vod["vod_play_url"] = "%s$%s" % (vod["vod_name"] or "在线播放", "m3u8://" + vid)
        except Exception:
            pass
        return {"list": [vod]}

    def searchContent(self, key, quick, pg="1"):
        """用 keyWordVideo（返回完整对象、支持分页），而不是 keyWordVideoTitle。"""
        page = int(pg or 1)
        lst = []
        try:
            d = self._req("/api/search/keyWordVideo?searchWord=%s&pageSize=20&page=%d"
                          % (quote(key), page))
            data = d.get("data") if isinstance(d, dict) else None
            if isinstance(data, list):
                lst = [self._vod(v) for v in data]
        except Exception:
            pass
        return {"list": lst, "page": page, "pagecount": page + 1,
                "limit": 20, "total": (page + 1) * 20}

    def playerContent(self, flag, id, vipFlags):
        vid = str(id).split("://")[-1]
        self._play_vid = vid
        return {"parse": 0,
                "url": self._proxy_url(type="m3u8", vid=vid),
                "header": {"User-Agent": self.ua}}

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        # ⚠ 返回格式踩过的坑，别再动：
        #   一律回 4 元组 [code, ctype, bytes, headers]，list[2] 必须是**原始字节**。
        #   封面 → 拿到 base64 文本当图片会白图；m3u8 → 拿到 base64 文本解析不出分片。
        #   不要用 isinstance(param, dict) 判断客户端类型（新版 FongMi 也会传 dict）。
        def _pack(code, ctype, body, headers=None):
            if body is None:
                body = b""
            if isinstance(body, str):
                body = body.encode("utf-8")
            return [code, ctype, body, headers or {}]

        if not isinstance(param, dict):
            try:
                param = dict(parse_qsl(str(param or "").lstrip("?"), keep_blank_values=True))
            except Exception:
                param = {}
        typ = param.get("type") or ""
        # ---- 封面代理：下载 → XOR 解密 → 回真图 ----
        if typ == "pic":
            rel = param.get("p") or param.get("u") or ""
            if not rel:
                return _pack(404, "text/plain", b"no pic")
            try:
                data, ctype = self._load_pic(rel)
            except Exception:
                return _pack(502, "text/plain", b"pic fail")
            if not data:
                return _pack(404, "text/plain", b"pic empty")
            return _pack(200, ctype, data, {"Cache-Control": "max-age=86400"})
        # ---- 播放代理：接口直出完整 m3u8 ----
        vid = str(param.get("vid") or "")
        if not vid:
            url = str(param.get("url") or "")
            m = re.search(r"[?&]vid=([^&]+)", url)
            vid = m.group(1) if m else (self._play_vid or "")
        if not vid:
            return _pack(200, "application/vnd.apple.mpegurl", "")
        try:
            m3 = self._m3u8(vid)
            return _pack(200, "application/vnd.apple.mpegurl", m3.encode("utf-8"),
                         {"User-Agent": self.ua})
        except Exception:
            return _pack(200, "application/vnd.apple.mpegurl", "")

    def destroy(self):
        pass


if __name__ == "__main__":
    # ---- 本地自检：直接跑 python 社区.py ----
    import urllib.parse as _up

    sp = Spider()
    sp.init("")
    print("host:", sp.host)
    print("device_id:", sp.device_id[:16] + "...")

    h = sp.homeContent(True)
    print("[分类] %d 个: %s" % (len(h["class"]),
                              ", ".join(c["type_name"] for c in h["class"][:8])))
    print("[首页] %d 条" % len(h["list"]))

    ok_pic = 0
    for it in h["list"][:5]:
        pic = it["vod_pic"]
        if not pic.startswith("http://127.0.0.1:9978/proxy"):
            print("  [封面] 形态错误:", pic[:80])
            continue
        q = pic.split("?", 1)[1]
        param = {k: _up.unquote(v) for k, v in (x.split("=", 1) for x in q.split("&"))}
        rs = sp.localProxy(param)
        body = rs[2]
        if isinstance(body, str):
            body = base64.b64decode(body) if body else b""
        kind = "JPEG" if body[:3] == b"\xff\xd8\xff" else ("WEBP" if body[:4] == b"RIFF" else "?")
        good = rs[0] == 200 and kind != "?"
        ok_pic += 1 if good else 0
        print("  [封面] %s %-10s %7d 字节 %s" % (rs[0], rs[1], len(body), kind if good else "乱码!"))
    print("[封面] %d/%d 可解密" % (ok_pic, min(5, len(h["list"]))))

    if h["list"]:
        first = h["list"][0]
        dc = sp.detailContent([first["vod_id"]])["list"][0]
        print("[详情] %s | 线路=%s" % (dc["vod_name"][:26], dc["vod_play_from"]))
        print("[详情] 封面是代理:", dc["vod_pic"].startswith("http://127.0.0.1:9978/proxy"))
        flag = dc["vod_play_from"].split("$$$")[0]
        pid = dc["vod_play_url"].split("$$$")[0].split("$", 1)[1]
        pc = sp.playerContent(flag, pid, None)
        print("[取流] parse=%s url=%s" % (pc["parse"], pc["url"][:88]))
        vid = pid.split("://")[-1]
        m3 = sp.localProxy({"type": "m3u8", "vid": vid})
        mb = m3[2]
        if isinstance(mb, str):
            mb = base64.b64decode(mb) if mb else b""
        txt = mb.decode("utf-8", "ignore")
        print("[取流] m3u8 %d 行, 含分片=%s" % (len(txt.splitlines()), ".ts" in txt))

    sr = sp.searchContent("黑料", False)
    print("[搜索] 条数=%d 有封面=%d" % (len(sr["list"]),
                                     sum(1 for x in sr["list"] if x["vod_pic"])))
    print("[搜索] 首条:", sr["list"][0]["vod_name"][:30] if sr["list"] else "-")
    print("[统计] 本次运行换域次数 =", sp._host_rotations)
    print("自检结束。")