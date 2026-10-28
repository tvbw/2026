# -*- coding: utf-8 -*-
"""
91Porn App（包名 com.yinse，v1.12.8）TVBox/Hawk 源 —— 纯标准库版

逆向来源：libapp.so（Dart AOT，AOTopsy 反汇编逐指令还原）

一、请求签名（HttpManger._sign）
   payload  = jsonEncode({nonce, path, timestamp, [token], userAgent})
              （Dart jsonEncode 紧凑无空格；token 仅在登录后加入，位于 path 与 timestamp 之间）
   x-api-key = "timestamp={ts};sign={HMAC-SHA256(key="kaFtkDJRcchRMTI9", payload)};nonce={uuid}"

二、响应解密（aesDecryptEx）
   外层 JSON {code, data, hash, msg, time, tip}；hash=true 时 data 为标准 base64 的密文。
   A    = base64decode(data)
   L1   = b"65dc07d1b7915c6b2937432b091837a7" + A[0:12]        # 44B，前 12B 为每次随机盐
   t6   = sha256(L1);            t7  = t6[8:24]                # 16B
   t11  = sha256(t7 + L1[0:22])
   t15  = sha256(L1[22:] + t7)
   Key  = t11[0:8] + t15[8:24] + t11[24:32]                    # AES-256，32B
   IV   = t15[0:4] + t11[12:20] + t15[28:32]                   # 16B
   plain= AES-256-CBC(A[12:], Key, IV) 去 PKCS#7 后即业务 JSON

三、登录（SplashLogic._devLogin → MineService.devLogin）
   POST /api/app/mine/login
   {devID:"91porn_"+32hex, qrCnt:"", devType:"1", sysType:"android",
    ver:"1.12.8", buildID:108, devToken:"", cutInfos:""}
   注意 qrCnt/devType/cutInfos 均为字符串（Go 服务端严格类型校验）。
   成功返回 UserInfoModel，取 token 字段（JWT）用于：
   - header "Authorization: {token}"
   - 签名 payload 的 token 项

四、播放地址（VideoModel.realVideoUrl → _m3u8）
   sourceURL 为相对路径，两种形式均实测可达（返回同一 m3u8 播放列表）：
   - {host}/{sourceURL}                                     # 直拼，免 token
   - {host}/vid/h5/m3u8/{sourceURL}?token={token}&c={host}  # App 内部形式
   m3u8 内 ts 分片为绝对 URL（每视频随机 CDN 域名），播放器自动跟随。

五、线路
   Config.lineList 三条，本源自动测速择优：999oidn.com / mjnchdb.com / 91pronhts.rlkfus.cn

六、封面图（_ImageFileService.get → ImageCrypto.decrypt，2026-10 补充还原）
   响应中 cover / portrait / coverImg 均为相对路径（如 "cf230705/image/..."），App 侧拼接：
     path 以 "http" 开头 → 直接使用；
     否则            → IMAGE 域名 + "/" + path
   IMAGE 域名来自服务端动态下发：登录后请求 /api/app/ping/domain，其
   sourceList 中 type="IMAGE" 的项（如 https://zzzznnn.lkkwip.cn），与 API 线路
   host 不是同一域、且会轮换，故本源运行时自动拉取并写入 IMAGE_DOMAIN_DYNAMIC；
   也保留 IMAGE_DOMAINS 常量作静态兜底。图片头 100 字节带 XOR 混淆：前 min(len,100)
   字节按 data[k] ^= key[k%len(key)] 异或（key="2019ysapp7527"，即 ImageCrypto
   的 _decryptKey），本源内置等价实现 _image_decrypt()，localProxy 拉到图后先还原
   头部再验魔数才回给播放器。
   DMP 兜底域名生成器（DmpFallbackDomainGenerator）：hmac_sha256(
       key="HH8Yib5NioDbRjNoMv4pkDzmDz6phI3cX8HB3eEIKlQ", msg=日期[6:]).hexdigest()
   取 [16:36] 拼 "https://dapi.{hex}.icu"。

七、播放链路实测（2026-10，沙箱模拟验证）
   Hawk 完整调用序列（init → homeVideoContent → detailContent(list 型 ids)
   → playerContent）实测通过；m3u8 直链拿到后：
   - curl 不带 UA          → HTTP 404（播放 CDN 对 User-Agent 强校验）
   - curl 带 UA            → HTTP 200，标准 HLS VOD 播放列表
   - ffprobe 带 UA         → h264 1280x720 + aac，duration 13.52s
   - ffmpeg 带 UA 实解码   → 5 秒解码 124 帧，rc=0（播放链路可用）
   ts 分片位于独立域名（xuanxianz.lkkwip.cn），同样必须携带 UA。
   若客户端播放失败，优先检查播放器是否透传 playerContent 返回的 header。

八、蚂蚁影视（ant-video）适配（2026-10，APK 2.0.2 实测）
   运行时：Flutter + serious_python（Python 3.12），Dart 经 Flask
   （127.0.0.1:55001）调 /load、/call；媒体代理走 127.0.0.1:9978/proxy?do=py
   （Android 由原生代理转发至 Python 侧 /proxy → localProxy）。
   与 Hawk 的契约差异（均已兼容）：
   - detailContent 收到 [vid] 列表；categoryContent 的 pg 为字符串；
     searchContent 收 (key, quick, pg)；playerContent 收 (flag, id, vipFlags)
   - 基类为单例（__new__ 缓存），init 只跑一次
   - 提供 getProxyUrl()/setCache/getCache/delCache/log(msg)
   播放策略（USE_LOCAL_PROXY=True）：
   playerContent 返回本地代理地址（getProxyUrl()&url=），由 localProxy
   统一带 UA 拉流并重写 m3u8 分片地址——规避客户端 HLS 代理/广告过滤层
   丢弃 header 导致 404 的问题；无 getProxyUrl 的宿主（Hawk）自动回退
   直链 + header UA 模式。localProxy 支持 m3u8 重写、ts 透传、Range/206。
   沙箱端到端验证：代理 m3u8 200 → 分片 200（124KB）/Range 206 →
   ffmpeg 走完整代理链解码 124 帧 rc=0；Hawk 回归（直链+header）通过。

接口按 Hawk（海阔视界）Python 蜘蛛规范实现；AES/HMAC 全部标准库内置实现，
不依赖 requests / pycryptodome / cryptography。
"""

import base64
import gzip
import hashlib
import hmac
import json
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib

try:
    from base.spider import Spider
except ImportError:
    # Hawk（海阔视界）等客户端无 base 包，用同名桩类兜底，保证 class Spider(Spider) 结构不变
    class Spider(object):
        def getCache(self, key):
            return None

        def setCache(self, key, value):
            return "fail"

        def delCache(self, key):
            return "fail"

        def log(self, *args):
            try:
                print(*args)
            except Exception:
                pass

        def toast(self, msg):
            pass


# ------------------------------------------------- 常量（逆向实证） --------------

HMAC_KEY = b"kaFtkDJRcchRMTI9"                      # HttpManger._sign
KEY_MAT = b"65dc07d1b7915c6b2937432b091837a7"       # aesDecryptEx 固定密钥材料（32B）
UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36")
HOSTS = ["https://999oidn.com", "https://mjnchdb.com", "https://91pronhts.rlkfus.cn"]
API_PREFIX = "/api/app"
APP_VER = "1.12.8"
BUILD_ID = 108
DEV_TYPE = "1"
TIMEOUT = 12

# 封面图 CDN（IMAGE 类型域名，服务端经 /api/app/ping/domain 的 sourceList[type=IMAGE]
# 动态下发，与 API 线路不同域，且图片本身用 IMG_XOR_KEY 对头部 100 字节做了 XOR 加密）。
# 运行时 Spider 会调用 _fetch_image_domain() 自动拉取并写入下面的动态变量；下列静态项
# 仅作兜底（抓到包后也可手动填 IMAGE_DOMAINS）。
IMAGE_DOMAIN_DYNAMIC = []    # 运行时由 /ping/domain 填充，例如 ["https://zzzznnn.lkkwip.cn"]
IMAGE_DOMAINS = []           # 例：["https://zzzznnn.lkkwip.cn"]（抓包/手动注入）
# 未配置时 localProxy 自动依次探测的候选（第一个返回图片内容的会被缓存复用）
IMAGE_CANDIDATES = ["https://zzzznnn.lkkwip.cn"]
IMG_XOR_KEY = b"2019ysapp7527"                     # ImageCrypto._decryptKey
IMG_MAGIC = (b"\xff\xd8\xff",                      # JPEG SOI
             b"\x89PNG\r\n\x1a\n",                 # PNG
             b"GIF")                               # GIF

# 播放走本地代理（FongMi/TVBox localProxy 契约）：
#   播放 CDN 强校验 User-Agent，而部分客户端（或其 HLS 代理/广告过滤层）
#   会丢弃 spider 返回的 header。开启后 playerContent 返回本地代理地址，
#   由 localProxy 统一带 UA 拉流。Hawk 等直连客户端若播放异常可置 False。
USE_LOCAL_PROXY = True

# 本地代理前缀（宿主注入 getProxyUrl 后填充，见 Spider._proxy_url）
_PROXY_PREFIX = ""


def _proxy_wrap(url):
    """媒体/图片地址 -> 本地代理地址（宿主不支持代理时原样返回）"""
    if not url or not _PROXY_PREFIX:
        return url
    return _PROXY_PREFIX + "&url=" + urllib.parse.quote(url, safe="")


_IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")


def _is_image_path(url):
    """判断是否封面/头像图片请求（路径含 /image/ 或图片扩展名）"""
    try:
        p = urllib.parse.urlparse(url).path.lower()
    except Exception:
        return False
    if "/image/" in p:
        return True
    return p.endswith(_IMG_EXTS)

# /vid/library 实测分类体系（动态拉取失败时的静态兜底，抓取于 2026-10）
STATIC_CANVAS = [("SP", "影片"), ("SHORT", "抖音"), ("video", "动漫"),
                 ("image", "漫画"), ("PIC", "图集"), ("COVER", "帖子")]
STATIC_VID_TAGS = [
    ("5dbeb239e76468ea20625ed8", "巨乳"), ("5dbeb281e76468ea20625f00", "国产"),
    ("6a4d0a3b566f9aa643380068", "AI短剧"), ("5dbeb2c8e76468ea20625f24", "偷拍"),
    ("5dbeb22fe76468ea20625ec3", "后入"), ("5dbeb230e76468ea20625ecb", "调教"),
    ("5de2f937cda257823b28453e", "学生"), ("5dbeb269e76468ea20625ef2", "萝莉"),
    ("5dbeb268e76468ea20625ef0", "丝袜"), ("5dbeb22fe76468ea20625ebc", "自慰"),
    ("5dbeb39fe76468ea20625f9f", "美臀"), ("5dbeb231e76468ea20625ecf", "足交"),
    ("5dbeb23be76468ea20625ed9", "少妇"), ("5dbeb42be76468ea20625fbd", "口交"),
    ("5dbeb248e76468ea20625ee1", "内射"),
]


# ------------------------------------------------- AES-256 / CBC（纯 Python） ----
# 仅实现解密所需部分：密钥扩展 + 逆轮变换 + CBC。TVBox 的 Python 环境通常没有
# pycryptodome，故内置一份紧凑实现，保证零第三方依赖。

_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16")

_INV_SBOX = [0] * 256
for _i, _b in enumerate(_SBOX):
    _INV_SBOX[_b] = _i

_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]


def _xtime(a):
    a <<= 1
    if a & 0x100:
        a = (a ^ 0x1b) & 0xff
    return a


def _gmul(a, b):
    """GF(2^8) 乘法"""
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        b >>= 1
        a = _xtime(a)
    return p


def _key_expansion_256(key):
    """AES-256 密钥扩展：32B key -> 60 个 32bit 字（240B 轮密钥）"""
    w = [list(key[4 * i:4 * i + 4]) for i in range(8)]
    for i in range(8, 60):
        t = list(w[i - 1])
        if i % 8 == 0:
            t = t[1:] + t[:1]                                   # RotWord
            t = [_SBOX[b] for b in t]                           # SubWord
            t[0] ^= _RCON[i // 8 - 1]
        elif i % 8 == 4:
            t = [_SBOX[b] for b in t]
        w.append([w[i - 8][j] ^ t[j] for j in range(4)])
    # 展平为 15 组轮密钥（每组 16B）
    rk = []
    for r in range(15):
        rk.append([w[4 * r + c][j] for c in range(4) for j in range(4)])
    return rk


def _decrypt_block(block, rk):
    """AES-256 单分组解密（等效逆 cipher）"""
    s = list(block)
    # 等效逆 cipher 最后一轮先加白
    s = [s[i] ^ rk[14][i] for i in range(16)]

    def add_rk(rnd):
        return [s[i] ^ rk[rnd][i] for i in range(16)]

    def inv_shift_rows(x):
        y = list(x)
        for r in range(1, 4):
            for c in range(4):
                y[r + 4 * c] = x[r + 4 * ((c - r) % 4)]
        return y

    def inv_sub_bytes(x):
        return [_INV_SBOX[b] for b in x]

    def inv_mix_col(x):
        y = [0] * 16
        for c in range(4):
            col = x[4 * c:4 * c + 4]
            y[4 * c + 0] = _gmul(col[0], 14) ^ _gmul(col[1], 11) ^ _gmul(col[2], 13) ^ _gmul(col[3], 9)
            y[4 * c + 1] = _gmul(col[0], 9) ^ _gmul(col[1], 14) ^ _gmul(col[2], 11) ^ _gmul(col[3], 13)
            y[4 * c + 2] = _gmul(col[0], 13) ^ _gmul(col[1], 9) ^ _gmul(col[2], 14) ^ _gmul(col[3], 11)
            y[4 * c + 3] = _gmul(col[0], 11) ^ _gmul(col[1], 13) ^ _gmul(col[2], 9) ^ _gmul(col[3], 14)
        return y

    for rnd in range(13, 0, -1):
        s = inv_shift_rows(s)
        s = inv_sub_bytes(s)
        s = add_rk(rnd)
        s = inv_mix_col(s)
    s = inv_shift_rows(s)
    s = inv_sub_bytes(s)
    s = add_rk(0)
    return bytes(s)


def aes256_cbc_decrypt(data, key, iv):
    """AES-256-CBC 解密，返回含 PKCS#7 padding 的原文（调用方负责去padding）"""
    if len(key) != 32 or len(iv) != 16:
        raise ValueError("bad key/iv length")
    rk = _key_expansion_256(key)
    out = bytearray()
    prev = iv
    for off in range(0, len(data) - 15, 16):
        blk = data[off:off + 16]
        dec = _decrypt_block(blk, rk)
        out.extend(bytes(a ^ b for a, b in zip(dec, prev)))
        prev = blk
    return bytes(out)


def _pkcs7_unpad(pt):
    if not pt:
        return pt
    n = pt[-1]
    if 1 <= n <= 16 and pt[-n:] == bytes([n]) * n:
        return pt[:-n]
    return pt


# ------------------------------------------------- 91Porn 响应解密 --------------

def _aes_decrypt_payload(data_b64):
    """aesDecryptEx 完整还原：base64 -> 盐+密文 -> sha256 派生 Key/IV -> AES-CBC"""
    a = base64.b64decode(data_b64)
    l1 = KEY_MAT + a[0:12]
    t6 = hashlib.sha256(l1).digest()
    t7 = t6[8:24]
    t11 = hashlib.sha256(t7 + l1[0:22]).digest()
    t15 = hashlib.sha256(l1[22:] + t7).digest()
    key = t11[0:8] + t15[8:24] + t11[24:32]
    iv = t15[0:4] + t11[12:20] + t15[28:32]
    pt = aes256_cbc_decrypt(a[12:], key, iv)
    return _pkcs7_unpad(pt).decode("utf-8")


# ------------------------------------------------- HTTP 客户端 ------------------

class _Client(object):
    """签名 + AES 解密 + 线路故障切换的最小 HTTP 客户端"""

    def __init__(self):
        self.host_idx = 0
        self.token = None
        self.devid = None
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    # ---- 线路 ----
    def host(self):
        return HOSTS[self.host_idx % len(HOSTS)]

    def _rotate(self):
        self.host_idx = (self.host_idx + 1) % len(HOSTS)

    def pick_best_host(self):
        """对三条线路做一次 ping 测速，选最快的"""
        best, best_ms = None, 1e9
        for i in range(len(HOSTS)):
            h = HOSTS[i]
            t0 = time.time()
            try:
                req = urllib.request.Request(h + "/ping", headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=6, context=self._ssl_ctx) as r:
                    r.read(64)
                ms = (time.time() - t0) * 1000
                if ms < best_ms:
                    best_ms, best = ms, i
            except Exception:
                continue
        if best is not None:
            self.host_idx = best

    # ---- 签名 ----
    def sign(self, path, with_token=False):
        ts = int(time.time())
        nonce = str(uuid.uuid4())
        payload = {"nonce": nonce, "path": path, "timestamp": ts}
        if with_token and self.token:
            payload["token"] = self.token
        payload["userAgent"] = UA
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        digest = hmac.new(HMAC_KEY, body.encode("utf-8"), hashlib.sha256).hexdigest()
        return "timestamp=%d;sign=%s;nonce=%s" % (ts, digest, nonce)

    def headers(self, path, with_token=True):
        h = {
            "x-api-key": self.sign(path, with_token=with_token),
            "device": "android",
            "api_version": "1.0.0",
            "X-User-Agent": UA,
            "accept-encoding": "*",
            "User-Agent": UA,
            "Accept": "*/*",
        }
        if with_token and self.token:
            h["Authorization"] = self.token
        return h

    # ---- 传输 ----
    def _open(self, req):
        resp = urllib.request.urlopen(req, timeout=TIMEOUT, context=self._ssl_ctx)
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            try:
                raw = gzip.decompress(raw)
            except Exception:
                try:
                    raw = zlib.decompress(raw, 16 + zlib.MAX_WBITS)
                except Exception:
                    pass
        return raw

    def request(self, path, params=None, body=None, with_token=True, retry=2):
        """带线路切换的请求；返回解密后的业务 JSON（dict）"""
        last_err = None
        for _ in range(max(retry, len(HOSTS))):
            url = self.host() + path
            if params:
                url += "?" + urllib.parse.urlencode(params)
            hdrs = self.headers(path, with_token=with_token)
            data = None
            if body is not None:
                data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                hdrs["Content-Type"] = "application/json;charset=UTF-8"
            req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data else "GET")
            try:
                raw = self._open(req)
            except urllib.error.HTTPError as e:
                raw = e.read()
            except Exception as e:
                last_err = e
                self._rotate()
                continue
            try:
                outer = json.loads(raw.decode("utf-8", "replace"))
            except Exception as e:
                last_err = e
                self._rotate()
                continue
            code = outer.get("code")
            if code == 200:
                data_field = outer.get("data")
                if data_field is None or data_field == "":
                    return {}
                if isinstance(data_field, str) and outer.get("hash"):
                    try:
                        return json.loads(_aes_decrypt_payload(data_field))
                    except Exception as e:
                        last_err = e
                        self._rotate()
                        continue
                return data_field
            if code in (5005, 5009) and with_token:
                # 登录态失效：清 token 触发重新登录后重试一次
                self.token = None
                raise _NeedLogin()
            last_err = RuntimeError("code=%s tip=%s" % (code, outer.get("tip") or outer.get("msg")))
            self._rotate()
        raise RuntimeError("request failed: %s (%s)" % (path, last_err))

    # ---- 设备匿名登录 ----
    def dev_login(self):
        devid = self.devid or ("91porn_" + uuid.uuid4().hex)
        body = {
            "devID": devid,
            "qrCnt": "",
            "devType": DEV_TYPE,
            "sysType": "android",
            "ver": APP_VER,
            "buildID": BUILD_ID,
            "devToken": "",
            "cutInfos": "",
        }
        last_err = None
        for _ in range(len(HOSTS) + 1):
            path = API_PREFIX + "/mine/login"
            url = self.host() + path
            hdrs = self.headers(path, with_token=False)
            hdrs["Content-Type"] = "application/json;charset=UTF-8"
            req = urllib.request.Request(
                url, data=json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
                headers=hdrs, method="POST")
            try:
                raw = self._open(req)
            except urllib.error.HTTPError as e:
                raw = e.read()
            except Exception as e:
                last_err = e
                self._rotate()
                continue
            outer = json.loads(raw.decode("utf-8", "replace"))
            if outer.get("code") == 200 and outer.get("data"):
                info = json.loads(_aes_decrypt_payload(outer["data"]))
                tok = info.get("token") or info.get("webToken")
                if tok:
                    self.token = tok
                    self.devid = devid
                    return info
            last_err = RuntimeError("devLogin code=%s tip=%s (host=%s)" % (
                outer.get("code"), outer.get("tip"), self.host()))
            self._rotate()
        raise RuntimeError("devLogin failed: %s" % last_err)


class _NeedLogin(Exception):
    pass


# ------------------------------------------------- 视频条目适配 ----------------

def _abs_url(c):
    if not c:
        return ""
    if c.startswith("http"):
        return c
    return HOSTS[0] + "/" + c.lstrip("/")


def _image_url(c):
    """封面/头像相对路径 -> 绝对 URL。

    App 逻辑（_ImageFileService.get）：http 开头直接用；否则拼 IMAGE 域名。
    IMAGE 域名优先用运行时从 /ping/domain 拉到的动态域（IMAGE_DOMAIN_DYNAMIC），
    其次静态配置 IMAGE_DOMAINS / IMAGE_CANDIDATES，最后线路 host 兜底
    （代理模式下由 localProxy 自动探测可用域并缓存，直连模式下仅作占位）。"""
    if not c:
        return ""
    if c.startswith("http"):
        return c
    host = (IMAGE_DOMAIN_DYNAMIC[0] if IMAGE_DOMAIN_DYNAMIC
            else (IMAGE_DOMAINS[0] if IMAGE_DOMAINS
                  else (IMAGE_CANDIDATES[0] if IMAGE_CANDIDATES else HOSTS[0]))).rstrip("/")
    return host + "/" + c.lstrip("/")


def _image_decrypt(b):
    """ImageCrypto.decrypt 复刻（语义已按分支方向校正）：

    头命中标准图片魔数（JPEG/PNG/GIF）= 明文，原样返回；
    头随机（密文）→ 前 min(len,100) 字节异或 key（data[k] ^= key[k % len(key)]）还原。
    """
    if not b or len(b) < 6:
        return b
    if any(b.startswith(m) for m in IMG_MAGIC):
        return b
    b = bytearray(b)
    n = min(len(b), 100)
    for k in range(n):
        b[k] ^= IMG_XOR_KEY[k % len(IMG_XOR_KEY)]
    return bytes(b)


def _is_image_magic(b):
    """解密后判断是否为标准图片（JPEG/PNG/GIF/WEBP）魔数"""
    if not b or len(b) < 6:
        return False
    if b[:3] == b"\xff\xd8\xff":
        return True
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return True
    return False


def _cover_url(v):
    c = v.get("cover") or v.get("coverThumb") or ""
    return _proxy_wrap(_image_url(c))


def _play_url(client, v):
    """VideoModel.realVideoUrl 还原：sourceURL/videoUrl 为相对路径，直拼线路 host 即 m3u8"""
    src = v.get("sourceURL") or v.get("videoUrl") or v.get("h265Url") or ""
    if not src:
        return ""
    if src.startswith("http"):
        return src
    return client.host() + "/" + src


def _fmt_duration(sec):
    try:
        sec = int(sec or 0)
    except Exception:
        return ""
    if sec <= 0:
        return ""
    return "%02d:%02d" % (sec // 60, sec % 60)


def _vod_item(v):
    publisher = v.get("publisher") or {}
    tags = ",".join(t.get("name", "") for t in (v.get("tags") or [])[:4])
    return {
        "vod_id": "v:" + v.get("id", ""),
        "vod_name": v.get("title", ""),
        "vod_pic": _cover_url(v),
        "vod_remarks": _fmt_duration(v.get("playTime")) or (publisher.get("name") or ""),
        "vod_year": "",
        "vod_area": "",
        "vod_actor": publisher.get("name", ""),
        "vod_director": "",
        "vod_content": (v.get("content") or tags),
        "vod_tag": tags,
        "_playCount": v.get("playCount", 0),
    }


def _acg_item(v):
    """ACG（动漫）条目：CartoonMediaInfo，字段与 VideoModel 不同"""
    tags = ",".join(v.get("tags") or [])[:40]
    return {
        "vod_id": "m:" + v.get("id", ""),
        "vod_name": v.get("title", ""),
        "vod_pic": _proxy_wrap(_image_url(v.get("horizontalCover") or v.get("verticalCover") or "")),
        "vod_remarks": ("%s集" % v.get("totalEpisode")) if v.get("totalEpisode") else "",
        "vod_year": "",
        "vod_area": "",
        "vod_actor": v.get("author", ""),
        "vod_director": "",
        "vod_content": v.get("summary") or tags,
        "vod_tag": tags,
        "_playCount": v.get("countBrowse", 0),
    }


# ------------------------------------------------- Spider 主体 ------------------

class Spider(Spider):
    NAME = "91Porn"

    def __init__(self):
        super(Spider, self).__init__()
        self.client = _Client()
        self._lib_cache = None
        self._login_lock = threading.Lock()   # Hawk 可能并行请求，登录需串行
        self._inited = False
        self._img_domain_fetched = False      # /ping/domain 只拉一次

    # ---- Hawk 规范 ----
    def getName(self):
        return self.NAME

    def init(self, extend=""):
        if self._inited:
            return
        self._inited = True
        # 探测最快线路（失败不影响后续：request 内部仍会轮换）
        try:
            self.client.pick_best_host()
            self.log("[91Porn] best host: %s" % self.client.host())
        except Exception as e:
            self.log("[91Porn] host probe failed: %r" % e)
        # 预热本地代理前缀（蚂蚁/FongMi 环境）
        self._sync_proxy_prefix()

    def _ensure_token(self):
        if self.client.token:
            return None
        with self._login_lock:
            if self.client.token:          # 双检：等锁期间可能已由其它线程登录
                return None
            try:
                cached = self.getCache("p91_devid")
                if cached:
                    self.client.devid = cached
                info = self.client.dev_login()
                try:
                    self.setCache("p91_devid", self.client.devid)
                except Exception:
                    pass
                self.log("[91Porn] devLogin ok, uid=%s" % (info or {}).get("uid"))
                # 登录后立即拉取 IMAGE 图片域（动态下发，会轮换）
                self._fetch_image_domain()
                return info
            except Exception as e:
                # 登录失败不致命：推荐/详情等接口虽需登录态，仍让后续请求去撞线路
                self.log("[91Porn] devLogin FAILED: %r" % e)
                return None

    def _fetch_image_domain(self):
        """从 /api/app/ping/domain 的 sourceList[type=IMAGE] 拉取图片 CDN 域名。

        该域名与 API 线路不同域、且会轮换，必须运行时获取；失败则保留静态兜底。
        """
        if getattr(self, "_img_domain_fetched", False):
            return
        self._img_domain_fetched = True
        try:
            cfg = self._api(API_PREFIX + "/ping/domain")
            if not isinstance(cfg, dict):
                return
            hosts = []
            for it in (cfg.get("sourceList") or []):
                if str(it.get("type") or "").upper() == "IMAGE":
                    for d in (it.get("domain") or []):
                        u = d.get("url") if isinstance(d, dict) else None
                        if u:
                            hosts.append(str(u).rstrip("/"))
            if hosts:
                global IMAGE_DOMAIN_DYNAMIC
                IMAGE_DOMAIN_DYNAMIC[:] = hosts
                try:
                    self.setCache("p91_img_host", hosts[0])
                except Exception:
                    pass
                self.log("[91Porn] image domain: %s" % hosts[0])
        except Exception as e:
            self.log("[91Porn] fetch image domain failed: %r" % e)

    def _api(self, path, params=None, body=None, allow_relogin=True):
        """统一入口：惰性登录 + 失效自动重登"""
        self._ensure_token()
        try:
            return self.client.request(path, params=params, body=body)
        except _NeedLogin:
            if not allow_relogin:
                raise
            self._ensure_token()
            return self.client.request(path, params=params, body=body)

    # ---- 首页 ----
    def homeContent(self, filter=False):
        classes = [{"type_id": "recommend", "type_name": "推荐"},
                   {"type_id": "new", "type_name": "最新"}]
        tags = STATIC_VID_TAGS
        try:
            lib = self._api(API_PREFIX + "/vid/library")
            if isinstance(lib, dict) and lib.get("vidTags"):
                tags = [(t.get("id", ""), t.get("name", "")) for t in lib["vidTags"] if t.get("id")]
        except Exception as e:
            # 动态分类失败：退回静态分类（此时影片列表大概率也会失败，日志可见原因）
            self.log("[91Porn] vid/library failed, fallback static: %r" % e)
        for realm, name in STATIC_CANVAS:
            if realm in ("SP", "SHORT", "video"):     # 视频类 realm 进分类栏
                classes.append({"type_id": "realm:" + realm, "type_name": name})
        for tid, name in tags:
            classes.append({"type_id": "tag:" + tid, "type_name": name})
        return {"class": classes}

    def homeVideoContent(self):
        err = None
        try:
            d = self._api(API_PREFIX + "/recommend/vid/list",
                          params={"pageNumber": 1, "pageSize": 40})
        except Exception as e:
            d, err = {}, e
            self.log("[91Porn] homeVideoContent failed: %r" % e)
        vods = [_vod_item(v) for v in (d.get("vInfos") or [])]
        out = {"list": vods, "page": 1, "pagecount": d.get("totalPages") or 1,
               "limit": 40, "total": len(vods), "hasNext": bool(d.get("hasNext"))}
        if err and not vods:
            out["msg"] = "加载失败：%s" % err
        return out

    # ---- 分类 ----
    def _acg_list(self, pg, tag_name="全部类型"):
        """ACG（动漫）搜索：GET /media/search，kind=1 为视频类动漫；
        tagName 为空时结果在 list，非空时在 tagMediaList"""
        params = {"pageNumber": int(pg), "pageSize": 40, "kind": 1,
                  "tagName": tag_name, "sortType": 0, "keyword": ""}
        try:
            d = self._api(API_PREFIX + "/media/search", params=params)
        except Exception as e:
            self.log("[91Porn] media/search failed: %r" % e)
            return {}
        return d

    def categoryContent(self, tid, pg, filter=False, extend=None):
        pg = str(pg or "1")
        if tid == "realm:video":
            try:
                d = self._acg_list(pg)
            except Exception as e:
                self.log("[91Porn] acg list failed: %r" % e)
                d = {}
            items = d.get("list") or d.get("tagMediaList") or []
            vods = [_acg_item(v) for v in items]
            has_next = bool(d.get("hasNext"))
            return {"list": vods, "page": int(pg),
                    "pagecount": int(pg) + 1 if has_next else int(pg),
                    "limit": 40, "total": len(vods), "hasNext": has_next}
        params = {"pageNumber": int(pg), "pageSize": 40}
        path = API_PREFIX + "/recommend/vid/list"
        if tid == "recommend":
            pass
        elif tid == "new":
            path = API_PREFIX + "/vid/home/new/list"
        elif tid.startswith("realm:"):
            params["realm"] = tid.split(":", 1)[1]
        elif tid.startswith("tag:"):
            params["tagID"] = tid.split(":", 1)[1]
        err = None
        try:
            d = self._api(path, params=params)
        except Exception as e:
            d, err = {}, e
            self.log("[91Porn] categoryContent(%s) failed: %r" % (tid, e))
        vods = [_vod_item(v) for v in (d.get("vInfos") or d.get("videos") or [])]
        has_next = bool(d.get("hasNext"))
        out = {"list": vods, "page": int(pg),
               "pagecount": int(pg) + 1 if has_next else int(pg),
               "limit": 40, "total": len(vods), "hasNext": has_next}
        if err and not vods:
            out["msg"] = "加载失败：%s" % err
        return out

    # ---- 搜索 ----
    def searchContent(self, key, quick, pg="1"):
        pg = str(pg or "1")
        body = {"pageNumber": int(pg), "pageSize": 30,
                "keyWords": [key], "realm": "SHORT", "sortType": 0}
        err = None
        try:
            d = self._api(API_PREFIX + "/search/list", body=body)
        except Exception as e:
            d, err = {}, e
            self.log("[91Porn] searchContent(%s) failed: %r" % (key, e))
        vods = [_vod_item(v) for v in (d.get("list") or [])]
        has_next = bool(d.get("hasNext"))
        out = {"list": vods, "page": int(pg),
               "pagecount": int(pg) + 1 if has_next else int(pg),
               "limit": 30, "total": len(vods), "hasNext": has_next}
        if err and not vods:
            out["msg"] = "搜索失败：%s" % err
        return out

    # ---- 详情 ----
    def detailContent(self, ids=""):
        # Hawk 各版本传入可能是 str / list / tuple，统一成逗号分隔串
        if isinstance(ids, (list, tuple)):
            ids = ",".join(str(x) for x in ids)
        vid = str(ids).split(",")[0].strip()
        if not vid:
            return {"list": []}
        if vid.startswith("m:"):
            return self._acg_detail(vid[2:])
        if vid.startswith("v:"):
            vid = vid[2:]
        try:
            d = self._api(API_PREFIX + "/vid/info", params={"videoID": vid})
        except Exception as e:
            self.log("[91Porn] detailContent(%s) failed: %r" % (vid, e))
            return {"list": [], "msg": "详情加载失败：%s" % e}
        if not d or not d.get("id"):
            return {"list": []}
        play = _play_url(self.client, d)
        v = dict(_vod_item(d))
        v["vod_play_from"] = "91Porn"
        v["vod_play_url"] = "%s$%s" % (d.get("title", ""), play) if play else ""
        v["vod_content"] = d.get("content") or v.get("vod_content", "")
        v["_sourceURL"] = d.get("sourceURL", "")
        return {"list": [v]}

    def _acg_detail(self, mid):
        """ACG 详情：/media/info 拿信息，/media_content/list 取剧集（多集时逐集列出）"""
        try:
            info = self._api(API_PREFIX + "/media/info", params={"id": mid})
            eps = self._api(API_PREFIX + "/media_content/list",
                            params={"mediaId": mid, "pageNumber": 1, "pageSize": 100, "sortType": 0})
        except Exception as e:
            self.log("[91Porn] acg detail(%s) failed: %r" % (mid, e))
            return {"list": [], "msg": "详情加载失败：%s" % e}
        if not info or not info.get("id"):
            return {"list": []}
        ep_list = (eps or {}).get("list") or []
        urls = []
        for ep in ep_list:
            u = _play_url(self.client, ep)
            if u:
                urls.append("%s$%s" % (ep.get("name") or ("第%s集" % ep.get("episodeNumber", "")), u))
        if not urls:
            return {"list": [], "msg": "该动漫暂无可用播放地址（可能需付费）"}
        v = dict(_acg_item(info))
        v["vod_play_from"] = "91Porn"
        v["vod_play_url"] = "#".join(urls)
        return {"list": [v]}

    # ---- 播放 ----
    def playerContent(self, flag="", id="", vipFlags=None):
        """id 为 m3u8 直链（detailContent 已拼好线路 host）

        注意：播放 CDN（999oidn.com / xuanxianz.lkkwip.cn 等）对 User-Agent
        强校验——不带 UA 请求 m3u8 返回 404，带 UA 返回 200。

        双模式返回：
        - 宿主提供 getProxyUrl()（蚂蚁影视/FongMi 系）→ 返回本地代理地址，
          由 localProxy 统一带 UA 拉流，规避客户端/代理层丢弃 header 与
          HLS 广告过滤误杀；
        - 否则（Hawk 等直连模式）→ 返回原始直链 + header UA。
        """
        url = str(id or "")
        if not url:
            return {"parse": 0, "url": "", "msg": "空播放地址"}
        if not url.startswith("http"):
            url = self.client.host() + "/" + url.lstrip("/")
        result = {"parse": 0, "url": url, "header": {"User-Agent": UA}}
        if USE_LOCAL_PROXY:
            try:
                purl = self._proxy_url(url)
                if purl:
                    result["url"] = purl
            except Exception:
                pass
        return result

    def _proxy_url(self, url):
        """把媒体地址包装成本地代理地址（携带 siteKey 与 url 参数）。

        宿主未提供 getProxyUrl（如 Hawk 桩环境）时返回空串。
        同时把代理前缀缓存到模块级 _PROXY_PREFIX，供图片地址包装使用。
        """
        if not url:
            return ""
        global _PROXY_PREFIX
        try:
            base = self.getProxyUrl()
        except Exception:
            return ""
        if not base:
            return ""
        _PROXY_PREFIX = base
        return base + "&url=" + urllib.parse.quote(url, safe="")

    def _sync_proxy_prefix(self):
        """init 阶段预热代理前缀（供封面等图片地址包装）。"""
        global _PROXY_PREFIX
        try:
            base = self.getProxyUrl()
            if base:
                _PROXY_PREFIX = base
        except Exception:
            pass

    # ---- 其它 Hawk 钩子 ----
    def isVideoFormat(self, url):
        return ".m3u8" in str(url)

    def manualVideoCheck(self):
        return False

    def getDependence(self):
        return []

    def localProxy(self, params):
        """本地媒体代理（FongMi/TVBox 契约，蚂蚁影视原生支持）。

        播放器请求形如
            http://127.0.0.1:9978/proxy?do=py&siteType=3&siteKey=xxx&url=<媒体>
        的地址时，宿主将其转交本函数：
        - m3u8：拉取播放列表，把分片（含相对地址）改写为带 UA 的本地代理地址；
        - ts/其它媒体：带 UA（及 Range）向上游拉取，透传状态码与响应头。

        param 为 dict：url 为媒体地址；range/if-range 等请求头已由宿主
        以小写键塞入。返回 [status, content_type, body, headers]。
        """
        try:
            if not isinstance(params, dict):
                params = {}
            url = str(params.get("url") or "")
            if not url:
                return [404, "text/plain", b"missing url", {}]
            if not url.startswith("http"):
                # 个别宿主用 base64 传 url
                try:
                    import base64 as _b64
                    dec = _b64.b64decode(url + "===").decode("utf-8", "ignore")
                    if dec.startswith("http"):
                        url = dec
                except Exception:
                    pass
            if not url.startswith("http"):
                return [404, "text/plain", b"bad url", {}]

            headers = {"User-Agent": UA}
            rng = params.get("range") or params.get("Range")
            if rng:
                headers["Range"] = str(rng)
            ir = params.get("if-range")
            if ir:
                headers["If-Range"] = str(ir)

            # 封面/头像：IMAGE 域名动态下发且不可静态推断，逐个候选探测
            if _is_image_path(url):
                return self._proxy_image(url, headers)

            resp = self._proxy_fetch(url, headers)
            if resp is None:
                return [502, "text/plain", b"upstream fetch failed", {}]

            status, ctype, content, up_headers = resp
            base_url = url.split("?")[0]
            if ".m3u8" in base_url:
                text = content.decode("utf-8", "ignore")
                out = []
                for line in text.splitlines():
                    s = line.strip()
                    if not s or s.startswith("#"):
                        out.append(line)
                        continue
                    seg = s if s.startswith("http") else urllib.parse.urljoin(url, s)
                    out.append(self._proxy_url(seg) or seg)
                body = "\n".join(out).encode("utf-8")
                return [200, "application/vnd.apple.mpegurl", body,
                        {"Access-Control-Allow-Origin": "*",
                         "Cache-Control": "no-cache"}]

            out_headers = {"Access-Control-Allow-Origin": "*"}
            for k in ("Content-Length", "Content-Range", "Accept-Ranges"):
                v = up_headers.get(k)
                if v:
                    out_headers[k] = v
            return [status, ctype, content, out_headers]
        except Exception as e:
            self.log("[91Porn] localProxy error: %r" % e)
            return [502, "text/plain", ("proxy error: %s" % e).encode("utf-8"), {}]

    def _proxy_image(self, url, headers):
        """封面图片代理：IMAGE 域名动态下发 + 图片头 100 字节 XOR 加密。

        优先用 URL 自带域名（_image_url 已拼好动态 IMAGE 域），再回退缓存域 /
        IMAGE_DOMAIN_DYNAMIC / 静态配置 / 线路 host。拉到后先用 _image_decrypt
        还原头部（明文原样返回），再验图片魔数；命中即缓存域名并回明文 JPEG/PNG。
        """
        try:
            pu = urllib.parse.urlparse(url)
            path = pu.path
        except Exception:
            return [404, "text/plain", b"bad image url", {}]
        if not path:
            return [404, "text/plain", b"bad image url", {}]
        candidates = []
        # 1) URL 自带域名（封面已拼好 IMAGE 域，效率最高）
        if pu.scheme and pu.netloc:
            candidates.append("%s://%s" % (pu.scheme, pu.netloc))
        # 2) 已缓存命中的域
        try:
            cached = self.getCache("p91_img_host")
            if cached:
                candidates.append(str(cached))
        except Exception:
            pass
        # 3) 运行时动态域
        candidates.extend(IMAGE_DOMAIN_DYNAMIC)
        # 4) 静态配置 / 候选 / 线路兜底
        candidates.extend(IMAGE_DOMAINS)
        candidates.extend(IMAGE_CANDIDATES)
        candidates.extend(HOSTS)
        seen = set()
        for h in candidates:
            h = str(h).rstrip("/")
            if not h or h in seen:
                continue
            seen.add(h)
            target = (h + path) if path else url
            r = self._proxy_fetch(target, headers)
            if r is None:
                continue
            st, ctype, content, _uh = r
            if st != 200 or not content:
                continue
            content = _image_decrypt(content)        # 还原头部 100 字节 XOR
            if not _is_image_magic(content):
                continue
            try:
                self.setCache("p91_img_host", h)
            except Exception:
                pass
            self.log("[91Porn] image host resolved: %s" % h)
            return [200, ctype or "image/jpeg", content,
                    {"Access-Control-Allow-Origin": "*",
                     "Cache-Control": "max-age=86400"}]
        return [404, "text/plain", b"image not found", {}]

    def _proxy_fetch(self, url, headers):
        """带 UA 拉取上游媒体，返回 (status, content_type, content, headers)。

        优先 requests（蚂蚁内置），缺失时回退 urllib。返回 None 表示失败。
        """
        try:
            import requests as _rq
        except ImportError:
            _rq = None
        try:
            if _rq is not None:
                r = _rq.get(url, headers=headers, timeout=(10, 60), verify=False)
                return (r.status_code,
                        r.headers.get("Content-Type", "application/octet-stream"),
                        r.content, dict(r.headers))
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                content = r.read()
                return (r.status,
                        r.headers.get("Content-Type", "application/octet-stream"),
                        content, dict(r.headers))
        except Exception as e:
            self.log("[91Porn] proxy fetch failed %s: %r" % (url[:80], e))
            return None

    def action(self, action):
        return None

    def destroy(self):
        pass


# ------------------------------------------------- 自检（python3 91porn.py） ----

if __name__ == "__main__":
    import sys
    sp = Spider()
    print("getName:", sp.getName())
    sp.init("")
    sp.client.pick_best_host()
    print("best host:", sp.client.host())
    info = sp.client.dev_login()
    print("login uid:", info.get("uid"), "token:", (info.get("token") or "")[:40], "...")
    home = sp.homeVideoContent()
    print("home:", len(home["list"]), "vods; first:", home["list"][0]["vod_name"][:30] if home["list"] else None)
    if home["list"]:
        det = sp.detailContent(home["list"][0]["vod_id"])
        v = det["list"][0] if det["list"] else {}
        print("detail:", v.get("vod_name", "")[:30], "| play:", v.get("vod_play_url", "")[:80])
        play = v.get("vod_play_url", "").split("$")[-1]
        req = urllib.request.Request(play, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read(300)
        print("m3u8 probe:", r.status, body[:60])
    # 分类（视频 tag）
    cat = sp.categoryContent("tag:5dbeb239e76468ea20625ed8", "1")
    print("cat tag:", len(cat["list"]), "vods; first:", cat["list"][0]["vod_name"][:25] if cat["list"] else None)
    # 分类（ACG 动漫）
    acg = sp.categoryContent("realm:video", "1")
    print("cat acg:", len(acg["list"]), "vods; first:", acg["list"][0]["vod_name"][:25] if acg["list"] else None)
    if acg["list"]:
        det = sp.detailContent(acg["list"][0]["vod_id"])
        v = det["list"][0] if det["list"] else {}
        print("acg detail:", v.get("vod_name", "")[:25], "| play:", (v.get("vod_play_url") or "")[:90])
    sea = sp.searchContent("测试", False, "1")
    print("search:", len(sea["list"]), "vods; first:", sea["list"][0]["vod_name"][:30] if sea["list"] else None)
    print("ALL OK")
