# -*- coding: utf-8 -*-
"""
TVBox 爬虫 —— TMDB 新片盘搜（夸克网盘）
============================================================
数据源: c:\\py\\tmdbpanspider\\tmdbpan_quark.db
        由 c:\\py\\tmdbpabsou\\tmdbpansou.py --export-split --keep 2 生成

原理
----
不抓任何站点，直接读一个 SQLite 库。库里的每条夸克链接都经过「文件级」深度验证：
夸克免登录换 token(sharepage/token) -> 递归 sharepage/detail 列举目录 ->
确认里面真的存在 mkv / mp4 / m2ts / iso 等影片文件才算通过（HTTP 200 不算）。
每部片只保留实测最优的 2 条版本（1 条最高画质 + 1 条不同画质档/来源）。

★★★ 硬性约定 ★★★
    1. 主类必须叫 Spider —— TVBox 的 python 加载器只认这个名字，改名会导致站点
       一片空白且不报错。
    2. 必须实现 init(extend) / getName() 两个生命周期方法。
    3. 播放地址一律 base64 存放，避免 $ 等字符被 TVBox 解析器吃掉。

用法
----
1. 数据库默认与本文件同目录（DB_PATH 只写文件名即可）。TVBox 把 spider 拷到
   别处时，把 db 文件一起带上；也可以写绝对路径。
   查找顺序：本文件目录 -> 当前工作目录 -> %TEMP%\tmdbpan_spider -> ./spider/
2. DB_PATH 也支持 http(s) 地址（电视端推荐）：会自动下载到系统临时目录，
   超过 DB_HTTP_TTL 秒才重新拉取。
3. 播放：本爬虫只输出 push://<网盘链接>，实际解析交给外部 jar（站源里 key=push_agent
   那个站点，或客户端默认 jar）。两种情况才需要动 push 相关配置：
       - 你的 jar 不认 push:// 而走转直链服务：站点 ext 里加
         {"push": "http://192.168.1.10:5443/dl?url={urlenc}"}
         {urlenc}=URL 编码后的分享链（链接自带 ?pwd=，不编码会污染转接服务参数）
       - 想直接把原始网盘链接丢给播放器：ext 里加 {"use_push": false}
4. 不想改文件的话，在 TVBox 站点配置的 ext 里写：
       {"db": "./tmdbpan_quark.db", "base": "http://192.168.1.10:8000/", "push": "...", "use_push": false}
       db    数据库路径; 强烈建议电视端直接写 http 绝对地址, 因为客户端会把 py
             缓存到自己的私有目录, 那里多半没有你拷过去的 db。
       base  站源服务器根地址; 本地找不到库时去这里下载(相对路径写法的兜底)。
5. 命令行自检：
       python TMDBQuark.py                  跑通全流程
       python TMDBQuark.py --home           首页（分类 + 列表）
       python TMDBQuark.py --cat type:movie 电影分类第 1 页
       python TMDBQuark.py --detail movie:1032863
       python TMDBQuark.py --search 蜘蛛侠

★★ 排序 ★★★
    首页和分类页默认「上映最新的排最前面」(DEFAULT_ORDER="date")，同一天的再比画质分。
    站点的筛选里可以切：网盘刚上架(pan) / 更新进度最新(fresh) / 画质最佳(score) /
    年份最新(year)。剧集的日期是 TMDB 首播日，所以正在更新的剧会在角标上额外
    标 "更MM.DD"（网盘上最新的上架日期），免得老剧看着像沉底了。
    不想改文件的话，站点 ext 里加 "order": "score" 就能给整个站换默认顺序。

★★ 站点进去一直转圈 / 一片空白 ★★★
    这种表现基本都是「脚本跑起来了，但库里读不到片子」。现在脚本会直接在首页
    塞一张 【加载失败 x.x.x】TMDB盘搜·xxx 卡片，点进详情能看到版本号、db 路径、
    python 版本、脚本所在目录和具体原因，按它给的提示改就行：
      - 提示"找不到数据库"   -> 用 ext 里的 http 绝对地址，或把 db 拷到 py 同目录
      - 提示"库里没有 titles 表" -> db 被下成了 404 网页/半截文件，重新拷贝
      - 版本号和最新不符     -> 客户端缓存了旧 py，清缓存或改文件名后重新导入
      - 什么卡片也没有、真的一直转圈 -> 脚本连加载都没成功(文件名大小写、
        编码不是 UTF-8、加载器不支持 .py)，或那次 HTTP 请求超时了。
"""

# ==================================================================
# ★★★ 配置区（只用改这里）★★★
# ==================================================================

DB_PATH = "tmdbpan_quark.db"                       # 默认取本文件同目录; 也可写绝对路径或 http(s) 地址
SERVICE = "quark"                                   # 库里 links.service 过滤值
SITE_NAME = "TMDB盘搜·夸克网盘"
PAN_LABEL = "夸克网盘"
VER = "2026-09-24.2"    # 版本号会打印在日志和排错卡片里, 用来确认设备上跑的是哪一版
DB_HTTP_TTL = 6 * 3600                              # 远程库本地缓存有效期(秒)
DB_BASE_URL = ""        # 站源服务器根地址, 如 "http://192.168.1.10:8000/"; 留空则本地找不到库时自动探测
DB_HTTP_TIMEOUT = 10    # 拉库超时(秒); 必须明显小于客户端的超时, 否则电视端只会一直转圈

USE_PUSH = True             # 默认输出 push://，由外部 jar(push_agent) 承接解析
PUSH_PREFIX = "push://"     # USE_PUSH=True 且没配 push 模板时的前缀
PUSH_TMPL = ""              # 仅在没有 jar、改用转直链服务时填: "http://IP:5443/dl?url={urlenc}"
PAGE_SIZE = 20              # 每页部数
DEFAULT_ORDER = "date"      # 默认排序: date=上映最新 / fresh=上映或更新取新 / pan=网盘刚上架 / score=画质最佳 / year=年份最新
MAX_LINES = 4               # 每部最多展示几条网盘线路（库里每部只有 2 条）
CARD_STYLE = {"type": "rect", "ratio": 0.75}

CATEGORIES = [("type:all", "新片全部"), ("type:movie", "电影"), ("type:tv", "剧集")]

# ==================================================================

import base64
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urlparse

try:
    from base.spider import Spider as _Spider  # TVBox 环境
except Exception:
    class _Spider:  # 独立运行时
        def __init__(self, *a, **kw):
            pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_NET_BAD = {}   # {url: 冷却截止时间戳} 拉库失败后短时间不再重试


def _b64_encode(s):
    return base64.b64encode(str(s or "").encode("utf-8")).decode("utf-8")


def _b64_decode(s):
    try:
        return base64.b64decode(str(s or "").encode("utf-8")).decode("utf-8")
    except Exception:
        return ""


def _log(msg):
    print("[%s %s] %s" % (SITE_NAME, VER, msg))


# ------------------------------------------------------------------
# 数据库
# ------------------------------------------------------------------

def _here():
    """本文件所在目录; 加载器 exec 源码时可能没有 __file__, 退回当前目录"""
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()


def _server_base():
    """站源 JSON 里写相对路径时，爬虫收到的 db 也是字面量 './x.db'，它不知道 JSON
    从哪下发。部分 python 加载器(hipy/drpy 系)会把站点 api 的地址放进模块全局，
    借它当基准地址去同一台服务器取库；取不到就退回本地查找。"""
    if DB_BASE_URL.startswith("http"):
        return DB_BASE_URL.rsplit("/", 1)[0] + "/"
    for k in ("BASE_URL", "SPIDER_URL", "spiderUrl", "baseUrl", "apiUrl", "API_URL",
              "HOST_URL", "hostUrl", "SITE_URL", "siteUrl"):
        try:
            v = globals().get(k)
        except Exception:
            v = None
        if isinstance(v, str) and v.startswith("http"):
            return v.rsplit("/", 1)[0] + "/"
    return ""


def _db_dirs(url):
    """本地可能藏库的路径: 原样 -> 本文件目录 -> 当前目录 -> 临时缓存 -> spider/ -> 上三级目录"""
    here = _here()
    out = [url, os.path.join(here, url), os.path.join(os.getcwd(), url),
           os.path.join(tempfile.gettempdir(), "tmdbpan_spider", os.path.basename(url)),
           os.path.join(here, "spider", url)]
    p, fn = here, os.path.basename(url)
    for _ in range(3):          # 客户端常把 py 放进 spider/ 子目录, 而 db 落在上一层
        p = os.path.dirname(p)
        if not p or p == here:
            break
        out.append(os.path.join(p, fn))
        out.append(os.path.join(p, "spider", fn))
    return out


def _resolve_db(url):
    """相对路径按「本文件目录 -> 当前目录 -> 临时目录 -> 站源服务器同目录」查找;
    http(s) 下载到临时目录并按 TTL 刷新"""
    url = str(url or "").strip()
    if not url:
        return ""
    if url.startswith("http"):
        return _fetch_db(url)
    for p in _db_dirs(url):
        try:
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                return os.path.abspath(p)
        except Exception:
            continue
    base = _server_base()
    if base:
        _log("本地无库 %s, 尝试从站源服务器取 %s" % (os.path.basename(url), base))
        return _fetch_db(base + os.path.basename(url))
    _log("找不到数据库 %s：请把 db 与 py 放同一目录，或在站点 ext 里写 "
         "\"db\": \"http://电脑IP:端口/%s\"" % (url, os.path.basename(url)))
    _note("找不到数据库 %s（py 同目录/上层目录/临时目录都没有）。"
          "解决：把 %s 和 py 放同一目录，或站点 ext 写 "
          '{"db":"http://电脑IP:端口/%s"}' % (url, os.path.basename(url), os.path.basename(url)))
    return ""


def _fetch_db(url):
    """远程库: 下载到系统临时目录, 超过 DB_HTTP_TTL 才重新拉取; 失败做负缓存免得反复卡超时"""
    fn = os.path.basename(urlparse(url).path) or "pan.db"
    cache = os.path.join(tempfile.gettempdir(), "tmdbpan_spider")
    try:
        os.makedirs(cache, exist_ok=True)
    except Exception:
        return ""
    dst = os.path.join(cache, fn)
    if os.path.exists(dst) and os.path.getsize(dst) > 0 \
            and time.time() - os.path.getmtime(dst) < DB_HTTP_TTL:
        return dst
    if _NET_BAD.get(url, 0) > time.time():
        return dst if os.path.exists(dst) else ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=DB_HTTP_TIMEOUT) as resp, \
                open(dst + ".part", "wb") as f:
            f.write(resp.read())
        os.replace(dst + ".part", dst)
        _log("已更新数据库 %s (%d KB)" % (fn, os.path.getsize(dst) // 1024))
    except Exception as e:
        _NET_BAD[url] = time.time() + 300        # 5 分钟内不再重试
        _log("数据库下载失败 %s: %s" % (url, e))
        _note("远程库下载失败 %s: %s" % (url, e))
    return dst if os.path.isfile(dst) and os.path.getsize(dst) > 0 else ""


def _uri(p):
    """SQLite URI 只对路径部分做百分号编码, 保留盘符后的冒号"""
    s = os.path.abspath(p).replace("\\", "/")
    try:
        from urllib.request import pathname2url
        s = pathname2url(s)
    except Exception:
        pass
    return "file:%s?mode=ro" % s


def _conn(db_path):
    if not db_path:
        return None
    try:
        con = sqlite3.connect(_uri(db_path), uri=True)
    except Exception as e:
        _note("数据库打开失败 %s: %s" % (db_path, e))
        _log("数据库打开失败 %s: %s" % (db_path, e))
        return None
    con.row_factory = sqlite3.Row
    for t in ("titles", "links"):          # 下错成 HTML 报错页 / 截断文件时提前发现
        try:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                               (t,)).fetchall():
                con.close()
                _note("库 %s 里没有 %s 表, 可能不是本项目的 db" % (os.path.basename(db_path), t))
                _log("库 %s 缺表 %s" % (db_path, t))
                return None
        except Exception as e:
            con.close()
            _note("库 %s 读取异常: %s" % (os.path.basename(db_path), e))
            _log("库 %s 读取异常: %s" % (db_path, e))
            return None
    return con


def _note(msg):
    """把失败原因攒起来, 首页以卡片形式显示出来, 免得客户端只剩一个转圈"""
    msg = str(msg or "")
    if msg and msg not in _DIAG:
        _DIAG.append(msg)
    return msg


_DIAG = []


def _rows(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except Exception as e:
        _log("查询异常 %s: %s" % (sql.strip()[:60], e))
        return []


# ------------------------------------------------------------------
# 版本标签
# ------------------------------------------------------------------

def _vod_id(row):
    return "%s:%s" % (row["media_type"], row["tmdb_id"])


def _quality_label(link):
    """由 score_detail + 实测容量拼一个短标签: 4K原盘 18.7GB"""
    try:
        d = json.loads(link["score_detail"] or "{}")
    except Exception:
        d = {}
    res = d.get("res") or ""
    src = {"REMUX/原盘": "原盘", "WEB-DL": "WEB-DL"}.get(d.get("src") or "", "")
    parts = [(res + src) if (res and src) else (res or src)]
    if d.get("hdr"):
        parts.append("HDR")
    if d.get("groups"):
        parts.append("/".join(d["groups"][:2]))
    gb = link["deep_size_gb"] or link["size_gb"] or 0
    if gb:
        parts.append("%.1fGB" % gb)
    return " ".join([p for p in parts if p]) or "普通版本"


def _note_head(note):
    """只取分享标题段，丢掉 TG 帖子的剧情简介/标签尾巴"""
    s = re.split(r"📜|介绍[:：]|剧情|💾|🏷|网盘专搜|下载", note or "", maxsplit=1)[0]
    return re.sub(r"^[#＃\s]+", "", s).strip()


def _with_pwd(url, pwd):
    if not pwd or re.search(r"[?&]pwd=", url or "", re.I):
        return url or ""
    return (url or "") + ("&" if "?" in (url or "") else "?") + "pwd=" + pwd


# ------------------------------------------------------------------
# Spider
# ------------------------------------------------------------------

class Spider(_Spider):
    """读 SQLite 的 TVBox 站源：TMDB 新片 + 已验证网盘链接"""

    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
        except Exception:
            pass
        self.db_path = DB_PATH
        self.service = SERVICE
        self.site_name = SITE_NAME
        self.pan_label = PAN_LABEL
        self.default_order = DEFAULT_ORDER
        self.push_tmpl = PUSH_TMPL
        self.use_push = USE_PUSH
        self.ext_headers = {"User-Agent": UA}
        self._last_picture = ""

    # -------------------- 生命周期 --------------------

    def init(self, extend=""):
        self._apply_extend(extend)
        return True

    def getName(self):
        return self.site_name

    def isVideoFormat(self, url):
        return True

    def manualVideoCheck(self):
        return False

    def destroy(self):
        return None

    def localProxy(self, param):
        return None

    def _apply_extend(self, extend):
        """站点配置里的 ext 优先于文件常量

        支持的键: db(库路径或 http 地址) / base(站源服务器根地址) / service(网盘类型)
                  / name(站点显示名) / label(线路前缀) / order(默认排序)
                  / push(转直链模板) / use_push / ua
        只挂一个 py 也能同时供百度、夸克两个站点用：
            {"db":"http://IP:8000/tmdbpan_baidu.db","service":"baidu",
             "name":"TMDB盘搜·百度云","label":"百度网盘"}
        """
        if isinstance(extend, str):
            s = extend.strip()
            if not s or s.lower() in ("true", "false", "null", "none"):
                return
            try:
                extend = json.loads(s)
            except Exception:
                return
        if not isinstance(extend, dict):
            return
        global DB_BASE_URL
        if extend.get("db"):
            self.db_path = str(extend["db"]).strip()
        if extend.get("service"):
            self.service = str(extend["service"]).strip()
        if extend.get("name"):
            self.site_name = str(extend["name"]).strip()
        if extend.get("label"):
            self.pan_label = str(extend["label"]).strip()
        if extend.get("order"):
            self.default_order = str(extend["order"]).strip()
        if extend.get("base") and str(extend["base"]).startswith("http"):
            DB_BASE_URL = str(extend["base"]).strip()
        if extend.get("push"):
            self.push_tmpl = str(extend["push"]).strip()
        if "use_push" in extend:
            self.use_push = bool(extend["use_push"])
        if extend.get("ua"):
            self.ext_headers["User-Agent"] = str(extend["ua"])

    def _db(self):
        return _resolve_db(self.db_path)

    # -------------------- 列表 --------------------

    _LIST_SQL = """
        SELECT t.tmdb_id, t.media_type, t.title_cn, t.title_orig, t.year,
               t.release_date, t.poster, COUNT(*) AS n, MAX(l.score) AS best,
               SUBSTR(MAX(l.pan_datetime), 1, 10) AS newest_day,
               MAX(COALESCE(t.release_date, ''), COALESCE(SUBSTR(MAX(l.pan_datetime), 1, 10), '')) AS fresh,
               (SELECT l2.id FROM links l2
                 WHERE l2.tmdb_id=t.tmdb_id AND l2.media_type=t.media_type
                   AND l2.service=? ORDER BY l2.score DESC LIMIT 1) AS top_id
        FROM titles t JOIN links l
          ON l.tmdb_id=t.tmdb_id AND l.media_type=t.media_type AND l.service=?
        WHERE COALESCE(l.alive,'alive')!='dead' {cond}
        GROUP BY t.tmdb_id, t.media_type
        ORDER BY {order}
        LIMIT ? OFFSET ?
    """

    # 排序表; DEFAULT_ORDER 决定首页/分类页的默认顺序 —— 最新的排最前面
    _ORDER = {
        "fresh": "fresh DESC, best DESC",                          # 上映或更新取新(默认)
        "date": "t.release_date DESC, best DESC",                  # 只看 TMDB 上映日
        "pan": "newest_day DESC, t.release_date DESC",             # 网盘刚上架
        "score": "best DESC, t.release_date DESC",                 # 画质最佳
        "year": "CAST(t.year AS INTEGER) DESC, best DESC",
    }

    def _query(self, con, type_id, pg, order):
        args = [self.service, self.service]
        cond = ""
        type_id = str(type_id or "").split(":")[-1]
        if type_id in ("movie", "tv"):
            cond = "AND t.media_type=?"
            tail = [type_id]
        else:
            tail = []
        order_sql = self._ORDER.get(order, self._ORDER.get(self.default_order,
                                                       self._ORDER["date"]))
        try:
            pg = max(1, int(pg or 1))
        except Exception:
            pg = 1
        base = self._LIST_SQL.format(cond=cond, order=order_sql)
        rows = _rows(con, base, args + tail + [PAGE_SIZE, (pg - 1) * PAGE_SIZE])
        total = _rows(
            con,
            "SELECT COUNT(*) FROM (SELECT t.tmdb_id FROM titles t JOIN links l "
            "ON l.tmdb_id=t.tmdb_id AND l.media_type=t.media_type AND l.service=? "
            "WHERE COALESCE(l.alive,'alive')!='dead' " + cond +
            " GROUP BY t.tmdb_id, t.media_type)", [self.service] + tail)
        n = total[0][0] if total else 0
        return rows, n, pg

    @staticmethod
    def _col(row, name, default=""):
        try:
            v = row[name]
        except Exception:
            v = None
        return default if v is None else v

    def _to_vod(self, con, row, link=None):
        if link is None:
            top = _rows(con, "SELECT * FROM links WHERE id=?", (row["top_id"],))
            link = top[0] if top else None
        label = _quality_label(link) if link else ""
        name = row["title_cn"] or row["title_orig"] or ""
        date = self._col(row, "release_date")[:10]
        newest = self._col(row, "newest_day")[:10]
        if (self._col(row, "media_type") == "tv" and len(date) >= 4
                and newest > date):                # 剧集在更: 上映日是首播日, 另标网盘进度
            stamp = "%s 更%s" % (date[:4], newest[5:].replace("-", "."))
        else:
            stamp = date or newest
        vod = {
            "vod_id": _vod_id(row),
            "vod_name": name,
            "vod_pic": row["poster"] or "",
            "vod_remarks": " · ".join([x for x in (stamp, label) if x]),
            "vod_class": "电影" if row["media_type"] == "movie" else "剧集",
            "type_id": "type:" + row["media_type"],
            "vod_year": row["year"] or "",
            "vod_douban_id": str(row["tmdb_id"]),
        }
        if CARD_STYLE:
            vod["style"] = dict(CARD_STYLE)
        return vod

    def _diag_vod(self):
        """库打不开/列表为空时，把原因当成一张卡片显示到首页，
        免得客户端只剩一个转圈，看不出问题在哪。"""
        why = " | ".join(_DIAG[-3:]) if _DIAG else "数据库能打开但没有查到片子"
        return {"vod_id": "diag:%s" % self.service,
                "vod_name": "【加载失败 %s】%s" % (VER, self.site_name),
                "vod_pic": "",
                "vod_remarks": ("原因: " + why)[:80],
                "vod_content": ("版本: %s\n站点: %s\napi: %s\n数据库: %s\npython: %s\n目录: %s\n\n%s"
                                % (VER, self.site_name, self.service, self.db_path,
                                   sys.version.split()[0], _here(),
                                   "\n".join(_DIAG) or "(无错误记录)"))[:900],
                "type_id": "type:all",
                "vod_year": "",
                "vod_douban_id": ""}

    def homeContent(self, filter):
        self._apply_extend(filter if isinstance(filter, dict) else {})
        con = _conn(self._db())
        classes = [{"type_id": tid, "type_name": nm} for tid, nm in CATEGORIES]
        lst, n = [], 0
        if con is not None:
            rows, n, pg = self._query(con, "type:all", 1, self.default_order)
            lst = [self._to_vod(con, r) for r in rows]
            con.close()
        if not lst:
            lst = [self._diag_vod()]
        return {"class": classes, "list": lst, "page": 1,
                "pagecount": max(1, -(-n // PAGE_SIZE)) if n else 1}

    def homeVideoContent(self):
        return self.categoryContent("type:all", 1, {}, {})

    def getFilter(self, tid):
        return [{"key": "order", "name": "排序", "value": [
            {"n": "上映最新" + ("（默认）" if self.default_order == "date" else ""), "v": "date"},
            {"n": "网盘刚上架", "v": "pan"},
            {"n": "更新进度最新", "v": "fresh"},
            {"n": "画质最佳", "v": "score"},
            {"n": "年份最新", "v": "year"},
        ]}]

    def categoryContent(self, tid, pg, filter, extend):
        self._apply_extend(extend)
        order = self.default_order
        for src in (filter, extend):
            if isinstance(src, str) and src.strip():
                try:
                    src = json.loads(src)
                except Exception:
                    src = None
            if isinstance(src, dict):
                order = str(src.get("order") or src.get("orderby") or order)
        try:
            pg = max(1, int(pg or 1))
        except Exception:
            pg = 1
        con = _conn(self._db())
        if con is None:
            return {"list": [self._diag_vod()], "page": pg, "pagecount": 1,
                    "total": 0, "limit": 1,
                    "msg": "数据库不可读: %s" % self.db_path}
        rows, total, pg = self._query(con, str(tid or "type:all"), pg, order)
        lst = [self._to_vod(con, r) for r in rows]
        con.close()
        if not lst and pg == 1:
            lst = [self._diag_vod()]
        return {"list": lst, "page": pg, "total": total, "limit": max(len(lst), 1),
                "pagecount": max(1, -(-total // PAGE_SIZE))}

    # -------------------- 详情 --------------------

    def detailContent(self, ids):
        vid = str((ids or [""])[0])
        if vid.startswith("diag:"):           # 首页那张排错卡片, 点进去看完整说明
            d = self._diag_vod()
            d["vod_play_from"] = d["vod_play_url"] = ""
            return {"list": [d]}
        mt, _, tmdb_id = vid.partition(":")
        if not tmdb_id:
            tmdb_id, mt = vid, ""
        con = _conn(self._db())
        if con is None:
            return {"list": [self._diag_vod()]}
        t = _rows(con, "SELECT * FROM titles WHERE tmdb_id=? "
                       "AND (media_type=? OR ?='')", (tmdb_id, mt, mt))
        if not t:
            con.close()
            return {"list": []}
        t = t[0]
        links = _rows(con, "SELECT * FROM links WHERE tmdb_id=? AND media_type=? "
                           "AND service=? AND COALESCE(alive,'alive')!='dead' "
                           "ORDER BY score DESC", (tmdb_id, t["media_type"], self.service))
        if not links:
            con.close()
            return {"list": []}
        try:
            tmdb_id = int(tmdb_id)
        except Exception:
            tmdb_id = 0
        row = dict(tmdb_id=tmdb_id, media_type=t["media_type"],
                   title_cn=t["title_cn"], title_orig=t["title_orig"],
                   year=t["year"], release_date=t["release_date"], poster=t["poster"],
                   newest_day=max([(l["pan_datetime"] or "")[:10] for l in links] or [""]))
        vod = self._to_vod(con, row, link=links[0])
        con.close()

        froms, urls, notes = [], [], []
        labels = {}
        for i, l in enumerate(links[:MAX_LINES]):
            lab = _quality_label(l)
            labels[lab] = labels.get(lab, 0) + 1
            if labels[lab] > 1:
                lab = "%s (%d)" % (lab, labels[lab])
            froms.append("%s·%s" % (self.pan_label, lab))
            ep = _note_head(l["note"])[:26] or ("第%d版" % (i + 1))
            urls.append("%s$%s" % (ep.replace("$", " "),
                                   _b64_encode(_with_pwd(l["url"], l["password"]))))
            notes.append(self._version_note(i + 1, l))
        vod["vod_play_from"] = "$$$".join(froms)
        vod["vod_play_url"] = "$$$".join(urls)
        vod["vod_content"] = ((row["title_orig"] or "") + "\n\n"
                              + (t["overview"] or "") + "\n\n" + "\n".join(notes))
        self._last_picture = vod["vod_pic"]
        return {"list": [vod]}

    @staticmethod
    def _version_note(i, l):
        try:
            files = json.loads(l["deep_detail"] or "[]")
        except Exception:
            files = []
        seg = ["【版本%d】%s" % (i, _quality_label(l))]
        seg.append("实测: " + ("已进入共享目录确认有影片文件"
                             if l["deep_status"] == "ok_video" else str(l["deep_status"])))
        if l["deep_files"]:
            seg.append("列出影片 %s 个" % l["deep_files"])
        if l["deep_size_gb"]:
            seg.append("实测 %.2f GB" % l["deep_size_gb"])
        if files:
            seg.append("样例: " + " | ".join(str(x)[:60] for x in files[:2]))
        seg.append("分享标题: " + _note_head(l["note"]))
        if l["pan_source"]:
            seg.append("来源 %s · 发布 %s" % (l["pan_source"], (l["pan_datetime"] or "")[:10]))
        return "\n".join(seg)

    # -------------------- 搜索 --------------------

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = max(1, int(pg or 1))
        except Exception:
            pg = 1
        kw = str(key or "").strip()
        if not kw:
            return {"list": [], "page": pg, "pagecount": 1, "total": 0}
        con = _conn(self._db())
        if con is None:
            return {"list": [], "page": pg, "pagecount": 1, "total": 0}
        like = "%" + kw + "%"
        ids = _rows(con, self._LIST_SQL.format(cond="AND (t.title_cn LIKE ? OR "
                    "t.title_orig LIKE ? OR l.note LIKE ?)",
                    order=self._ORDER.get(self.default_order, self._ORDER["date"])),
                    [self.service, self.service] + [like] * 3 + [PAGE_SIZE, (pg - 1) * PAGE_SIZE])
        total = _rows(con, "SELECT COUNT(*) FROM (SELECT 1 FROM titles t JOIN links l "
                      "ON l.tmdb_id=t.tmdb_id AND l.media_type=t.media_type AND l.service=? "
                      "WHERE COALESCE(l.alive,'alive')!='dead' AND (t.title_cn LIKE ? OR "
                      "t.title_orig LIKE ? OR l.note LIKE ?) GROUP BY t.tmdb_id, t.media_type)",
                      [self.service] + [like] * 3)
        n = total[0][0] if total else 0
        lst = [self._to_vod(con, r) for r in ids]
        con.close()
        return {"list": lst, "page": pg, "pagecount": max(1, -(-n // PAGE_SIZE)), "total": n}

    # -------------------- 播放 --------------------

    def playerContent(self, flag, id, vipFlags):
        raw = _b64_decode(id) or str(id or "")
        if raw.startswith("http"):
            if self.push_tmpl:
                url = self.push_tmpl.replace("{url}", raw).replace(
                    "{urlenc}", urllib.request.quote(raw))
            elif self.use_push:
                url = PUSH_PREFIX + raw
            else:
                url = raw
        else:
            url = raw
        return {"parse": 0, "playUrl": "", "url": url, "header": self.ext_headers,
                "pic": self._last_picture}


def create():
    return Spider()


TMDBPanSpider = Spider


if __name__ == "__main__":
    s = Spider()
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    db = s._db()
    print("数据库: %s (%s)" % (db or "(不可读)",
          "%d KB" % (os.path.getsize(db) // 1024) if db and os.path.exists(db) else "-"))

    def _show(o):
        for line in json.dumps(o, ensure_ascii=False, indent=2).splitlines():
            print(line[:150])

    if arg == "--home":
        _show(s.homeContent(None))
    elif arg.startswith("--cat"):
        _show(s.categoryContent(sys.argv[2] if len(sys.argv) > 2 else "type:all",
                               int(sys.argv[3]) if len(sys.argv) > 3 else 1, {}, {}))
    elif arg.startswith("--detail"):
        _show(s.detailContent([sys.argv[2] if len(sys.argv) > 2 else "movie:1032863"]))
    elif arg.startswith("--search"):
        _show(s.searchContent(sys.argv[2] if len(sys.argv) > 2 else "", 1, 1))
    elif arg.startswith("--player"):
        _show(s.playerContent("", _b64_encode(sys.argv[2] if len(sys.argv) > 2
                                              else "https://pan.quark.cn/s/abcdef123456"), []))
    else:
        kw = "蜘蛛侠"
        print("== 自检: %s ==" % SITE_NAME)
        home = s.homeContent(None)
        print("分类 %d 个: %s" % (len(home["class"]),
              "、".join(c["type_name"] for c in home["class"])))
        print("首页 %d 条 / 共 %s 页" % (len(home["list"]), home["pagecount"]))
        for v in home["list"][:5]:
            print("  - %-22s %-14s %s" % (v["vod_name"][:22], v["vod_remarks"][:14],
                                          "有海报" if v["vod_pic"] else "无海报"))
        if home["list"]:
            d = s.detailContent([home["list"][0]["vod_id"]])
            if d["list"]:
                v = d["list"][0]
                print("详情: %s" % v["vod_name"])
                print("  线路: %s" % v["vod_play_from"])
                print("  地址: %s" % v["vod_play_url"][:110])
                p = s.playerContent("", v["vod_play_url"].split("$$$")[0].split("$", 1)[1], [])
                print("  播放: %s" % p["url"][:110])
            else:
                print("!! 详情为空，检查库里 links 是否有该 tmdb_id 的 %s 记录" % SERVICE)
        r = s.searchContent(kw, 1, 1)
        print("搜索「%s」: %d 条 / 共 %d 部" % (kw, len(r["list"]), r["total"]))
        for v in r["list"][:3]:
            print("  - %s | %s" % (v["vod_name"], v["vod_remarks"]))
