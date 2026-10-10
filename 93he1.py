#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🦋 一锅端·12站实测固化版 — 参考模板重构版
按《参考代码.py》模板结构全量重写：
  - 类级常量集中管理 (UA / headers / 站点库 / 搜索源)
  - 工具链：_text / _build_url / _request / _safe_json / _fix_pic
            / _normalize_item / _clean_item / _format_remarks
  - 搜索升级为 ThreadPoolExecutor 并发聚合（同模板 searchContentPage）
  - 底部统一注册块
契约保留（遮天/TVBox 兼容）：
  - getDependence()
  - localProxy 返回四元组 [status, mime, body, header]，param 兼容 str/dict
  - 可无参实例化 / 无 base.spider 时自动降级
后端：https://av.telstra.com.cv 聚合 API
"""
import sys
import re
import json
import time
import gzip
import zlib
import ssl
import http.cookiejar
import urllib.request
import urllib.error
from urllib.parse import quote, unquote, urlencode

sys.path.append('..')
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider(object):
        def init(self, extend=""):
            pass
        def getCache(self, key):
            return None
        def setCache(self, key, value):
            return "fail"
        def delCache(self, key):
            return "fail"


class Spider(BaseSpider):
    # ==================== 类级常量（模板风格集中管理） ====================
    UA = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
    )
    headers = {'User-Agent': UA}

    SITE_URL = 'https://av.telstra.com.cv'
    TG_GROUP = 'https://t.me/tvshare23'
    BRAND = '蝴蝶影视'
    BRAND_ACTOR = '🦋 TG群: @tvshare23'
    BRAND_DIRECTOR = '🦋 蝴蝶影视'

    # 顶层一级纯净文件夹分类契约（纯内存直出）
    TOP_CLASSES = [
        {'type_name': '全部', 'type_id': 'all', 'type_flag': '1'},
        {'type_name': '短剧', 'type_id': 'short', 'type_flag': '1'},
        {'type_name': '影视', 'type_id': 'drama', 'type_flag': '1'},
        {'type_name': '成人', 'type_id': 'adult', 'type_flag': '1'},
        {'type_name': '音频', 'type_id': 'audio', 'type_flag': '1'},
        {'type_name': '动漫', 'type_id': 'anime', 'type_flag': '1'},
    ]

    # 短剧大类下站点优先顺序（实测有数据的靠前）
    SHORT_PRIORITY = ['huangdou', 'kuangbiao', 'yidouge', 'xifu', 'xingya']

    # 搜索优先聚合的健康源站
    SEARCH_TARGETS = [
        'cj', 'imaoyou', 'iyf', 'huangdou', 'xifu', 'xingya',
        'yidouge', 'kuangbiao', 'asmrhoney', 'avxq', 'b8xx6', 'djuu',
    ]

    # ==============================================================
    # 全量源站分类数据字典 (12 站实测更新 + 原始库全量保留，已剔除 avgood/baogua/nuomi)
    # ==============================================================
    SITES_CONFIG_DATA = {
        # --- 阶段一与二：已实测打通的核心 6 站 ---
        'asmrhoney': {'name': 'ASMRHoney', 'platform': 'adult', 'categories': [{'n': '最新更新', 'v': 'latest'}, {'n': '中文ASMR', 'v': 'lang_zh'}, {'n': '日语ASMR', 'v': 'lang_ja'}, {'n': '韩语ASMR', 'v': 'lang_ko'}, {'n': '英语ASMR', 'v': 'lang_en'}, {'n': '混合语言', 'v': 'lang_mixed'}, {'n': '舔耳', 'v': 'tag_ear_licking'}, {'n': '口腔音', 'v': 'tag_mouth_sounds'}, {'n': '触发音', 'v': 'tag_trigger_sounds'}, {'n': '角色扮演', 'v': 'tag_roleplay'}, {'n': '耳语', 'v': 'tag_whisper'}, {'n': '丝袜', 'v': 'tag_pantyhose'}, {'n': '刮擦', 'v': 'tag_scratching'}, {'n': '性感', 'v': 'tag_sexy'}, {'n': 'SFW全年龄', 'v': 'tag_sfw'}, {'n': 'NSFW', 'v': 'tag_nsfw'}, {'n': '耳吃', 'v': 'tag_eareating'}, {'n': '舌头', 'v': 'tag_tongue'}, {'n': '助眠', 'v': 'tag_sleep_aid'}, {'n': '呼吸音', 'v': 'tag_breathing'}, {'n': '足部', 'v': 'tag_feet'}, {'n': '亲吻', 'v': 'tag_kiss'}, {'n': '音频专辑', 'v': 'audio_albums'}, {'n': '音频单曲', 'v': 'audio_tracks'}]},
        'avxq': {'name': 'AV星球', 'platform': 'adult', 'categories': [{'n': '学生萝莉', 'v': '66'}, {'n': '日本AV', 'v': '44'}, {'n': '口交自慰', 'v': '62'}, {'n': '群交多P', 'v': '63'}, {'n': '强奸迷奸', 'v': '67'}, {'n': '丝袜制服', 'v': '68'}, {'n': '国产AV', 'v': '46'}, {'n': '乱伦系列', 'v': '45'}, {'n': '素人特摄', 'v': '65'}, {'n': '探花约炮', 'v': '47'}, {'n': '日韩精选', 'v': '61'}, {'n': 'VR专区', 'v': '64'}, {'n': '主播大秀', 'v': '48'}, {'n': '反差母狗', 'v': '70'}, {'n': '国产传媒', 'v': '50'}, {'n': '网曝吃瓜', 'v': '49'}, {'n': '异域风情', 'v': '71'}, {'n': '中文字幕', 'v': '53'}, {'n': '偷拍偷窥', 'v': '51'}, {'n': '色情动漫', 'v': '55'}]},
        'b8xx6': {'name': '8XX6', 'platform': 'adult', 'categories': [{'n': '国产', 'v': '901179'}, {'n': '有码', 'v': '911179'}, {'n': '无码', 'v': '921179'}, {'n': '欧美', 'v': '931179'}, {'n': '传媒', 'v': '941179'}, {'n': '探花', 'v': '951179'}, {'n': '中文', 'v': '961179'}, {'n': '动漫', 'v': '971179'}]},
        'cj': {'name': '初8影视', 'platform': 'drama', 'categories': [{'n': '电影', 'v': '1'}, {'n': '剧集', 'v': '15'}, {'n': '动漫', 'v': '30'}, {'n': '短剧', 'v': '47'}, {'n': '综艺', 'v': '24'}, {'n': '纪录片', 'v': '63'}]},
        'imaoyou': {'name': '猫又影视', 'platform': 'drama', 'categories': [{'n': '电影', 'v': '1'}, {'n': '电视剧', 'v': '2'}, {'n': '综艺', 'v': '3'}, {'n': '动漫', 'v': '4'}, {'n': '短剧', 'v': '5'}]},
        'iyf': {'name': '爱壹帆影视', 'platform': 'drama', 'categories': [{'n': '电影', 'v': '1'}, {'n': '电视剧', 'v': '2'}, {'n': '综艺', 'v': '3'}, {'n': '动漫', 'v': '4'}, {'n': '纪录片', 'v': '5'}]},

        # --- 阶段三：实测打通的短剧与音频 6 站 ---
        'djuu': {'name': 'DJ呦呦', 'platform': 'audio', 'categories': [{'n': '热歌榜', 'v': '1'}, {'n': 'DJ舞曲', 'v': '2'}, {'n': '英文DJ', 'v': '3'}, {'n': '中文DJ', 'v': '4'}]},
        'huangdou': {'name': '黄豆短剧', 'platform': 'short', 'categories': [{'n': '全部短剧', 'v': 'all'}, {'n': '黄豆原创', 'v': 'yuandou'}, {'n': '魔改短剧', 'v': 'mod'}, {'n': '擦边短剧', 'v': 'caibian'}, {'n': '真人短剧', 'v': 'zhenren'}, {'n': '动漫', 'v': 'erciyuan'}, {'n': '影院', 'v': 'aiman'}, {'n': '贤者', 'v': 'zongyi'}, {'n': '黑料', 'v': 'heiliao'}]},
        'kuangbiao': {'name': '狂飙短剧', 'platform': 'short', 'categories': [{'n': '成人短剧', 'v': 'adult_short'}, {'n': '正规短剧', 'v': 'normal_short'}, {'n': '短剧', 'v': 't-5jxcit'}]},
        'xifu': {'name': '喜福短剧', 'platform': 'short', 'categories': [{'n': '爽剧', 'v': '3'}, {'n': '甜宠', 'v': '6'}, {'n': '逆袭', 'v': '5'}, {'n': '现代言情', 'v': '1'}, {'n': '都市', 'v': '4'}, {'n': '玄幻', 'v': '23'}, {'n': '古代言情', 'v': '16'}]},
        'xingya': {'name': '星芽短剧', 'platform': 'short', 'categories': [{'n': '剧场', 'v': '1'}, {'n': '新剧', 'v': '3'}, {'n': '热播', 'v': '2'}, {'n': '星选', 'v': '7'}, {'n': '阳光', 'v': '5'}]},
        'yidouge': {'name': '一兜糖短剧', 'platform': 'short', 'categories': [{'n': '最新发布', 'v': '1'}, {'n': '热播精选', 'v': '2'}]},

        # --- 其余完整保留的备用站点库 ---
        'avtoday': {'name': 'AVToday', 'platform': 'adult', 'categories': [{'n': '中文字幕', 'v': '中文字幕'}, {'n': '無碼', 'v': '無碼'}, {'n': 'FC2', 'v': 'FC2'}, {'n': '長腿', 'v': '長腿'}, {'n': '巨乳', 'v': '巨乳'}, {'n': '多人', 'v': '多人'}, {'n': '素人', 'v': '素人'}]},
        'hanime1': {'name': 'hanime1动漫(源超时)', 'platform': 'anime', 'categories': [{'n': '首页推荐', 'v': 'home'}, {'n': '最新', 'v': 'latest'}]},
        'jable': {'name': 'Jable直播放', 'platform': 'adult', 'categories': [{'n': '最近更新', 'v': 'latest-updates'}, {'n': '热门影片', 'v': 'hot'}, {'n': '最新上市', 'v': 'new-release'}, {'n': '中文字幕', 'v': 'chinese-subtitle'}, {'n': '角色剧情', 'v': 'roleplay'}, {'n': '制服诱惑', 'v': 'uniform'}, {'n': '丝袜美腿', 'v': 'pantyhose'}, {'n': '无码解放', 'v': 'uncensored'}]},
        'missav': {'name': 'MissAV', 'platform': 'adult', 'categories': [{'n': '国产', 'v': '20'}, {'n': '日本有码', 'v': '21'}, {'n': '日本无码', 'v': '22'}, {'n': '中文字幕', 'v': '28'}, {'n': '欧美', 'v': '23'}, {'n': '动漫', 'v': '24'}, {'n': '伦理', 'v': '25'}]},
        '91porn': {'name': '91Porn', 'platform': 'adult', 'categories': [{'n': '最新', 'v': 'watch'}, {'n': '91原创', 'v': 'ori'}, {'n': '当前最热', 'v': 'hot'}, {'n': '本月最热', 'v': 'top'}, {'n': '10分钟以上', 'v': 'long'}, {'n': '高清', 'v': 'hd'}]},
        'baxx': {'name': '8X8X', 'platform': 'adult', 'categories': [{'n': '大陆', 'v': '1'}, {'n': '日韩', 'v': '2'}, {'n': '欧美', 'v': '3'}, {'n': '动漫', 'v': '4'}, {'n': '三级', 'v': '5'}]},
        'chinax': {'name': '中国X站', 'platform': 'adult', 'categories': [{'n': '国产传媒', 'v': 'domestic-media'}, {'n': '日本AV', 'v': 'japanese-av'}, {'n': '无码视频', 'v': 'uncensored-video'}, {'n': '中文字幕', 'v': 'chinese-subtitles'}]},
        'ddys': {'name': '高端视频', 'platform': 'adult', 'categories': [{'n': '一区-日韩无码', 'v': '12028759'}, {'n': '一区-中文字幕', 'v': '12198759'}, {'n': '一区-国产自拍', 'v': '12008759'}, {'n': '二区-91探花', 'v': '12468839'}, {'n': '三区-国产精品', 'v': '12038769'}]},
        'flt': {'name': '福利天堂', 'platform': 'adult', 'categories': [{'n': '偷拍', 'v': '1'}, {'n': '国产', 'v': '6'}, {'n': '韩国', 'v': '3'}, {'n': '无码', 'v': '4'}, {'n': '动漫', 'v': '5'}, {'n': '中文', 'v': '7'}]},
        'tnaflix': {'name': 'TNAFlix', 'platform': 'adult', 'categories': [{'n': '最新视频', 'v': '1'}, {'n': 'Asian 亚洲', 'v': '5'}, {'n': 'Japanese 日本', 'v': '34'}, {'n': 'Hentai 动漫', 'v': '30'}, {'n': 'Homemade 自拍', 'v': '31'}]},
        'youav': {'name': 'YouAV', 'platform': 'adult', 'categories': [{'n': '日本AV', 'v': '22'}, {'n': '巨乳', 'v': '20'}, {'n': '熟女人妻', 'v': '21'}, {'n': '中文字幕', 'v': '23'}, {'n': '少女蘿莉', 'v': '24'}, {'n': '國產素人自拍', 'v': '30'}]},
        'apilj': {'name': '辣椒资源', 'platform': 'adult', 'categories': [{'n': '国产自拍', 'v': '1'}, {'n': '欧美极品', 'v': '2'}, {'n': '日韩无码', 'v': '3'}, {'n': 'AV明星', 'v': '4'}, {'n': '中文字幕', 'v': '20'}]},
        'fhzy': {'name': '番号资源', 'platform': 'adult', 'categories': [{'n': '制服丝袜', 'v': '1'}, {'n': '群交淫乱', 'v': '2'}, {'n': '无码专区', 'v': '3'}, {'n': '偷拍自拍', 'v': '4'}, {'n': '中文字幕', 'v': '6'}]},
        'jpzy': {'name': '极品资源', 'platform': 'adult', 'categories': [{'n': '视频一区', 'v': '1'}, {'n': '日韩无码', 'v': '54'}, {'n': '国产精品', 'v': '55'}, {'n': '自拍偷拍', 'v': '60'}, {'n': '中文字幕', 'v': '62'}]},
        '91md': {'name': '91麻豆', 'platform': 'adult', 'categories': [{'n': '麻豆视频', 'v': '1'}, {'n': '91制片厂', 'v': '2'}, {'n': '天美传媒', 'v': '3'}, {'n': '蜜桃传媒', 'v': '4'}, {'n': '星空传媒', 'v': '6'}]},
        'aosika': {'name': '奥斯卡资源', 'platform': 'adult', 'categories': [{'n': '国产视频', 'v': '20'}, {'n': '中文字幕', 'v': '21'}, {'n': '国产传媒', 'v': '22'}, {'n': '日本有码', 'v': '23'}, {'n': '日本无码', 'v': '24'}]},
        'ddzy': {'name': '滴滴资源', 'platform': 'adult', 'categories': [{'n': '国产专区', 'v': '20'}, {'n': '国产厂商', 'v': '21'}, {'n': '日本无码', 'v': '23'}, {'n': '中文字幕', 'v': '25'}]},
        'douzy': {'name': '豆豆资源', 'platform': 'adult', 'categories': [{'n': '国产视频', 'v': '47'}, {'n': '国产传媒', 'v': '48'}, {'n': '日本有码', 'v': '53'}, {'n': '少妇人妻', 'v': '74'}]},
        'heizy': {'name': '嘿嘿资源', 'platform': 'adult', 'categories': [{'n': '国产视频', 'v': '48'}, {'n': '国产自拍', 'v': '49'}, {'n': '黑料吃瓜', 'v': '54'}, {'n': '麻豆传媒', 'v': '56'}]},
        'souav': {'name': '搜av资源', 'platform': 'adult', 'categories': [{'n': '中文传媒', 'v': '1'}, {'n': '国产', 'v': '2'}, {'n': '欧美AV', 'v': '3'}, {'n': '日本AV', 'v': '4'}, {'n': '传媒-麻豆传媒', 'v': '6'}]},
        'danaizi': {'name': '大奶子资源', 'platform': 'adult', 'categories': [{'n': '视频一区', 'v': '1'}, {'n': '精品推荐', 'v': '20'}, {'n': '自拍偷拍', 'v': '23'}, {'n': '制服丝袜', 'v': '24'}]},
        'lsb': {'name': '老色逼资源', 'platform': 'adult', 'categories': [{'n': '精品推荐', 'v': '20'}, {'n': '国产精品', 'v': '21'}, {'n': '日本有码', 'v': '23'}, {'n': '中文字幕', 'v': '25'}]},
        'yutu': {'name': '玉兔资源', 'platform': 'adult', 'categories': [{'n': '精品推荐', 'v': '20'}, {'n': '国产精品', 'v': '21'}, {'n': '日本有码', 'v': '23'}, {'n': '中文字幕', 'v': '25'}]},
        'fqzy': {'name': '番茄资源', 'platform': 'adult', 'categories': [{'n': '欧美精品', 'v': '3'}, {'n': '偷拍自拍', 'v': '6'}, {'n': '高清无码', 'v': '13'}, {'n': '中文字幕', 'v': '14'}]},
        'heiliao': {'name': '黑料资源', 'platform': 'adult', 'categories': [{'n': '中文字幕', 'v': '1'}, {'n': '日本有码', 'v': '2'}, {'n': '日本无码', 'v': '3'}, {'n': '自拍偷拍', 'v': '29'}]},
        'hsck': {'name': '黄色仓库', 'platform': 'adult', 'categories': [{'n': '国产区', 'v': '1'}, {'n': 'AV区', 'v': '2'}, {'n': '欧美区', 'v': '3'}, {'n': '日本无码', 'v': '10'}]},
        'naixx': {'name': '奶香香资源', 'platform': 'adult', 'categories': [{'n': '精品国产', 'v': '1'}, {'n': '精品日韩', 'v': '2'}, {'n': '日韩无码', 'v': '28'}]},
        'slzy': {'name': '森林资源', 'platform': 'adult', 'categories': [{'n': '精品推荐', 'v': '20'}, {'n': '国产色情', 'v': '22'}, {'n': '亚洲无码', 'v': '24'}]},
        'thzy': {'name': '桃花资源', 'platform': 'adult', 'categories': [{'n': '国产精品', 'v': '6'}, {'n': '华语AV', 'v': '7'}, {'n': '日本无码', 'v': '25'}]},
        'jpx': {'name': '精品X资源', 'platform': 'adult', 'categories': [{'n': '国产', 'v': '1'}, {'n': '日本', 'v': '2'}, {'n': '动漫', 'v': '4'}, {'n': '高清无码', 'v': '20'}]},
        'xingba': {'name': '杏吧资源', 'platform': 'adult', 'categories': [{'n': '日韩无码', 'v': '54'}, {'n': '国产主播', 'v': '55'}, {'n': '中文字幕', 'v': '62'}]},
        'subo2': {'name': '速播资源B', 'platform': 'adult', 'categories': [{'n': '电影', 'v': '1'}, {'n': '电视剧', 'v': '2'}, {'n': '短剧', 'v': '27'}]},
        'niuniuzy': {'name': '牛牛资源', 'platform': 'adult', 'categories': [{'n': '电影', 'v': '1'}, {'n': '电视剧', 'v': '2'}, {'n': '国产剧', 'v': '13'}]},
        'zuidapi': {'name': '最大资源', 'platform': 'adult', 'categories': [{'n': '电影', 'v': '1'}, {'n': '电视剧', 'v': '2'}, {'n': '动作片', 'v': '6'}]},
        'jszy': {'name': '极速资源', 'platform': 'adult', 'categories': [{'n': '电视剧', 'v': '1'}, {'n': '电影', 'v': '2'}, {'n': '短剧', 'v': '38'}]},
        'ffzy': {'name': '非凡资源', 'platform': 'adult', 'categories': [{'n': '电影片', 'v': '1'}, {'n': '连续剧', 'v': '2'}, {'n': '短剧', 'v': '36'}]},
        'xgzy': {'name': '西瓜资源', 'platform': 'adult', 'categories': [{'n': '电影片', 'v': '1'}, {'n': '连续剧', 'v': '2'}, {'n': '短剧', 'v': '36'}]},
        'jxzy': {'name': '量子资源', 'platform': 'adult', 'categories': [{'n': '电影片', 'v': '1'}, {'n': '连续剧', 'v': '2'}, {'n': '短剧', 'v': '46'}]},
        'tyyszy': {'name': '甜晕资源', 'platform': 'adult', 'categories': [{'n': '电影', 'v': '1'}, {'n': '电视剧', 'v': '2'}, {'n': '短剧', 'v': '54'}]},
    }

    # ==================== 宿主契约 ====================
    def init(self, extend=""):
        self.options = {}
        if isinstance(extend, dict):
            self.options = extend
        elif extend:
            try:
                self.options = json.loads(extend)
            except Exception:
                self.options = {}
        return True

    def getName(self):
        return '🦋 一锅端·12站实测固化版'

    def getDependence(self):
        # 遮天/TVBox 契约：宿主可能在 init 前调用
        return []

    def isVideoFormat(self, url):
        low = (url or '').lower()
        return any(k in low for k in ('.m3u8', '.mp4', '.mp3', '.m4a', '.flv', '.mkv', '.avi', '.ts', '.mpd', 'index.png'))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self.options = {}
        if hasattr(self, '_opener'):
            try:
                self._opener.close()
            except Exception:
                pass
            del self._opener

    # ==================== 工具链（模板风格） ====================
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

    def _get_opener(self):
        """懒加载：SSL 忽略校验 + CookieJar 会话（保持原 _fetch 行为）"""
        if getattr(self, '_opener', None) is None:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self._opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                urllib.request.HTTPSHandler(context=ctx),
            )
        return self._opener

    def _request(self, url, extra_headers=None, timeout=8, referer=''):
        """核心请求：返回 {code, text, bytes, headers}；gzip/deflate 自动解压；最多重试 2 次"""
        if not url:
            return {'code': 0, 'text': '', 'bytes': b'', 'headers': {}}
        if url.startswith('//'):
            url = 'https:' + url
        elif url.startswith('/') and not url.startswith('/upload'):
            url = self.SITE_URL + url

        hdr = dict(self.headers)
        hdr['Referer'] = referer if referer else (self.SITE_URL + '/')
        hdr['Accept'] = '*/*'
        hdr['Accept-Encoding'] = 'gzip, deflate'
        hdr['Connection'] = 'keep-alive'
        if extra_headers:
            hdr.update(extra_headers)

        opener = self._get_opener()
        for _ in range(2):
            try:
                req = urllib.request.Request(url, headers=hdr)
                with opener.open(req, timeout=timeout) as resp:
                    raw = resp.read()
                    resp_headers = dict(resp.headers)
                    enc = resp_headers.get('Content-Encoding', '')
                    if raw.startswith(b'\x1f\x8b') or enc == 'gzip':
                        try:
                            raw = gzip.decompress(raw)
                        except Exception:
                            pass
                    elif enc == 'deflate':
                        try:
                            raw = zlib.decompress(raw)
                        except Exception:
                            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                    return {
                        'code': resp.getcode(),
                        'text': raw.decode('utf-8', errors='ignore'),
                        'bytes': raw,
                        'headers': resp_headers,
                    }
            except urllib.error.HTTPError as e:
                return {'code': e.code, 'text': '', 'bytes': b'', 'headers': dict(e.headers)}
            except Exception:
                continue
        return {'code': -1, 'text': '', 'bytes': b'', 'headers': {}}

    def _safe_json(self, s):
        try:
            if not s:
                return None
            return json.loads(str(s))
        except Exception:
            return None

    def _dummy_pic(self, text, color='1e293b'):
        return 'https://dummyimage.com/400x600/%s/ffffff.png&text=%s' % (color, quote(str(text).upper()))

    def _folder(self, vod_id, vod_name, vod_remarks, color='1e293b', text='FOLDER'):
        """folder 卡片统一构造（站点文件夹 / 瞬切卡 / 提示卡）"""
        return {
            'vod_id': vod_id,
            'vod_name': vod_name,
            'vod_pic': self._dummy_pic(text, color),
            'vod_remarks': vod_remarks,
            'vod_tag': 'folder',
            'style': {'type': 'rect', 'ratio': 1.78},
        }

    def _fix_pic(self, src_key, raw_pic):
        """精准海报分流引擎：支持已打通 12 站直连与官方代理"""
        if not raw_pic:
            return self._dummy_pic(src_key)
        raw_pic = str(raw_pic).strip()

        # 修复初8影视 (cj) 的相对图片路径
        if src_key == 'cj' and raw_pic.startswith('/upload/'):
            return 'https://cjysw.cc' + raw_pic

        if raw_pic.startswith('//'):
            raw_pic = 'https:' + raw_pic
        elif raw_pic.startswith('/') and not raw_pic.startswith('/api/'):
            raw_pic = self.SITE_URL + raw_pic

        # 实测合规且直连秒开的优质图床名单
        direct_pass_domains = [
            'asmrhoney.com', 'cdn202511.com', 'pic.892539.xyz', 'cdn-xj.cc',
            'img.picbf.com', 'hongniuzyimage.com', 'cjysw.cc', 'img.djuu.com',
            'cloudfront.net', 'shorttv.online', 'contentchina.com',
            'rongjuwh.cn', 'images.weserv.nl',
        ]
        if any(d in raw_pic for d in direct_pass_domains):
            return raw_pic

        # 其余阻断站点走官方代理通道
        return '%s/api/v1/spiders/%s/proxy?type=img&url=%s' % (self.SITE_URL, src_key, quote(raw_pic))

    def _normalize_item(self, item):
        """聚合 API 字段归一：兼容 name/vod_name、pic/vod_pic、remarks/duration 等别名"""
        o = dict(item) if isinstance(item, dict) else {}
        o['id'] = self._text(o.get('id') or o.get('vod_id'))
        o['name'] = self._text(o.get('name') or o.get('vod_name')) or '未知片名'
        o['pic'] = self._text(o.get('pic') or o.get('vod_pic'))
        o['remarks'] = self._text(
            o.get('remarks') or o.get('vod_remarks') or o.get('duration') or o.get('vod_duration')
        )
        return o

    def _clean_item(self, item, src_key):
        """列表/搜索条目统一清洗：打包 vod_id + 品牌备注 + 海报分流"""
        o = self._normalize_item(item)
        return {
            'vod_id': '%s@@%s' % (src_key, o['id']),
            'vod_name': o['name'],
            'vod_pic': self._fix_pic(src_key, o['pic']),
            'vod_remarks': self._format_remarks(self.BRAND, o['remarks']),
            'style': {'type': 'rect', 'ratio': 1.78},
        }

    def _format_remarks(self, brand='', meta=''):
        brand = brand or self.BRAND
        clean_meta = self._text(meta)
        clean_meta = re.sub(r'[\r\n\t]+', ' ', clean_meta).strip()
        if clean_meta:
            return '%s | %s' % (brand, clean_meta)
        return brand

    def _get_spiders_for_plat(self, plat_id):
        """获取属于指定大类的站点列表；短剧按健康源优先级排序"""
        matched = []
        for skey, sinfo in self.SITES_CONFIG_DATA.items():
            if plat_id == 'all' or sinfo.get('platform') == plat_id:
                matched.append({
                    'key': skey,
                    'name': sinfo.get('name', skey),
                    'cat_count': len(sinfo.get('categories', [])),
                })
        if plat_id == 'short':
            def _sk(item):
                try:
                    return self.SHORT_PRIORITY.index(item['key'])
                except ValueError:
                    return 99
            matched.sort(key=_sk)
        return matched

    # ==================== TVBox 接口 ====================
    def homeContent(self, filter):
        return {'class': self.TOP_CLASSES, 'filters': {}}

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        del filter, extend
        tid_str = str(tid).strip('/')
        page = int(pg) if str(pg).isdigit() else 1

        # ==============================================================
        # 阶段一：处于顶层大类 -> 瀑布流只展现站点文件夹卡片
        # ==============================================================
        if tid_str in ('all', 'adult', 'drama', 'short', 'anime', 'audio'):
            folder_items = []
            for sp in self._get_spiders_for_plat(tid_str):
                skey, sname, cat_num = sp['key'], sp['name'], sp['cat_count']
                s_cats = self.SITES_CONFIG_DATA.get(skey, {}).get('categories', [])
                # 初始进入站点默认指向第一个子分类
                init_target = 'site/' + skey
                if s_cats:
                    init_target = 'site/%s/cat/%s' % (skey, quote(s_cats[0]['v']))
                folder_items.append(self._folder(
                    init_target, '📁 ' + sname, '%d个细分类' % cat_num, text=skey
                ))
            return {
                'page': 1,
                'pagecount': 1,
                'limit': len(folder_items),
                'total': len(folder_items),
                'list': folder_items,
            }

        # ==============================================================
        # 阶段二：具体站点瀑布流 + 原地瞬切置顶卡
        # ==============================================================
        src_key = 'cj'
        target_sub_tid = ''

        clean_path = tid_str.replace('site/', '')
        if '/cat/' in clean_path:
            parts = clean_path.split('/cat/')
            src_key = parts[0]
            target_sub_tid = unquote(parts[1])
        else:
            src_key = clean_path

        site_info = self.SITES_CONFIG_DATA.get(src_key, {})
        valid_cats = site_info.get('categories', [])

        # 定位当前分类在列表中的索引位置
        current_idx = 0
        if valid_cats:
            for idx, c in enumerate(valid_cats):
                if c['v'] == target_sub_tid:
                    current_idx = idx
                    break
            if not target_sub_tid:
                target_sub_tid = valid_cats[0]['v']
            cur_cat_name = valid_cats[current_idx]['n']
        else:
            cur_cat_name = '默认'
            target_sub_tid = target_sub_tid or '1'

        req_url = self._build_url(
            '%s/api/v1/spiders/%s/category' % (self.SITE_URL, src_key),
            {'tid': target_sub_tid, 'pg': page},
        )
        cat_res = self._request(req_url)
        vod_list = []

        # 首页置顶瞬切卡片 (vod_tag='folder')
        if page == 1 and len(valid_cats) > 1:
            next_idx = (current_idx + 1) % len(valid_cats)
            next_cat = valid_cats[next_idx]
            vod_list.append(self._folder(
                'site/%s/cat/%s' % (src_key, quote(next_cat['v'])),
                '🔄【当前: %s】' % cur_cat_name,
                '点我瞬切: %s (%d/%d)' % (next_cat['n'], current_idx + 1, len(valid_cats)),
                color='3b82f6', text='SWITCH',
            ))

        try:
            data = json.loads(cat_res.get('text', '{}'))
            items = data.get('list') or []

            # 兜底：若该子分类无数据，回退取 home 推荐列表
            if not items and page == 1:
                home_res = self._request('%s/api/v1/spiders/%s/home' % (self.SITE_URL, src_key))
                home_data = json.loads(home_res.get('text', '{}'))
                items = home_data.get('list') or []

            page_count = int(data.get('pagecount', 1)) if data.get('pagecount') else 1
            total = int(data.get('total', len(items))) if data.get('total') else len(items)

            for item in items:
                vod_list.append(self._clean_item(item, src_key))

            return {
                'page': page,
                'pagecount': page_count if page_count > 0 else 1,
                'limit': len(vod_list),
                'total': total,
                'list': vod_list,
            }
        except Exception:
            tip = [self._folder(
                'site/%s' % src_key,
                '⚠️ 源站暂无数据或超时',
                '请换其他源站',
                color='7f1d1d', text='EMPTY',
            )]
            return {'page': 1, 'pagecount': 1, 'limit': 1, 'total': 1, 'list': tip}

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) else str(ids)

        # 拦截 folder 瞬切卡片
        if str(raw_id).startswith('site/'):
            return self.categoryContent(raw_id, 1, None, None)

        src_key = 'cj'
        real_id = str(raw_id)
        if '@@' in raw_id:
            src_key, real_id = raw_id.split('@@', 1)

        detail_url = '%s/api/v1/spiders/%s/detail?id=%s' % (self.SITE_URL, src_key, quote(real_id))
        v = self._safe_json(self._request(detail_url).get('text')) or {}
        if isinstance(v.get('list'), list) and v['list']:
            v = v['list'][0]
        elif isinstance(v.get('data'), dict):
            v = v['data']
        if not isinstance(v, dict):
            v = {}

        v_name = v.get('name') or v.get('vod_name') or real_id
        v_pic = self._fix_pic(src_key, v.get('pic') or v.get('vod_pic'))
        v_content = v.get('content') or v.get('vod_content') or '蝴蝶聚合源站极速穿透播放。'
        v_category = v.get('category') or v.get('type_name') or ''
        v_remarks = self._format_remarks(self.BRAND, v.get('remarks') or v.get('vod_remarks'))

        full_content = (
            '【🦋 官方交流群: %s】\n'
            '━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
            '【当前源站】: %s\n'
            '【影片类别】: %s\n'
            '%s'
        ) % (self.TG_GROUP, src_key.upper(), v_category, v_content)

        episodes = v.get('episodes') or []
        play_entries = []

        if episodes:
            for ep in episodes:
                ep_name = str(ep.get('name', '正片')).replace('$', '_').replace('#', '_')
                ep_val = str(ep.get('id') or ep.get('url') or real_id)
                play_entries.append('%s$%s@@%s@@%s' % (ep_name, src_key, real_id, quote(ep_val)))
        elif v.get('vod_play_url'):
            raw_play_urls = str(v.get('vod_play_url')).split('#')
            for sub_p in raw_play_urls:
                if '$' in sub_p:
                    ep_name, ep_val = sub_p.split('$', 1)
                else:
                    ep_name, ep_val = '正片', sub_p
                play_entries.append('%s$%s@@%s@@%s' % (
                    ep_name.replace('$', '_').replace('#', '_'), src_key, real_id, quote(ep_val)
                ))
        else:
            play_entries.append('正片$%s@@%s@@%s' % (src_key, real_id, real_id))

        play_from = '蝴蝶·%s' % src_key.upper()
        play_url_str = '#'.join(play_entries)

        return {
            'list': [{
                'vod_id': raw_id,
                'vod_name': v_name,
                'vod_pic': v_pic,
                'vod_type': v_category,
                'vod_remarks': v_remarks,
                'vod_actor': self.BRAND_ACTOR,
                'vod_director': self.BRAND_DIRECTOR,
                'vod_content': full_content,
                'vod_play_from': play_from,
                'vod_play_url': play_url_str,
            }]
        }

    def playerContent(self, flag, id, vipFlags):
        del flag, vipFlags
        raw_play_param = str(id).strip()

        src_key = 'cj'
        real_id = raw_play_param
        ep_target = raw_play_param

        if '@@' in raw_play_param:
            parts = raw_play_param.split('@@')
            src_key = parts[0]
            real_id = parts[1]
            if len(parts) >= 3:
                ep_target = unquote(parts[2])

        clean_id = real_id
        if '/' in clean_id and not clean_id.startswith('http'):
            clean_id = clean_id.rstrip('/').split('/')[-1].replace('.html', '')

        # 优先使用选集中的 ep_target 作为 play 请求标识
        play_param_id = ep_target if (
            ep_target.startswith('http') or '-' in ep_target or '|' in ep_target or '@' in ep_target
        ) else clean_id
        play_api_url = '%s/api/v1/spiders/%s/play?id=%s' % (self.SITE_URL, src_key, quote(play_param_id))
        play_res = self._request(play_api_url)

        final_url = ep_target
        header_dict = {
            'User-Agent': self.UA,
            'Referer': self.SITE_URL + '/',
        }
        need_parse = 0

        play_json = self._safe_json(play_res.get('text')) or {}
        if play_json.get('url'):
            final_url = str(play_json.get('url')).strip()
        # 严格透传官方防盗链签名 Header (含 imaoyou / iyf / xifu 等所有 x-aggr-sig)
        if isinstance(play_json.get('header'), dict):
            header_dict.update(play_json.get('header'))
        try:
            need_parse = int(play_json.get('parse', 0))
        except Exception:
            need_parse = 0

        # 针对初8影视 (cj) 嗅探页透传专属 Referer
        if src_key == 'cj':
            header_dict['Referer'] = 'https://cjysw.cc/'

        # 针对喜福短剧透传来源 Referer
        if src_key == 'xifu':
            header_dict['Referer'] = 'https://minidrama.contentchina.com/'

        # 相对路径补齐基准站域名
        if final_url.startswith('/api/v1/spiders/'):
            final_url = self.SITE_URL + final_url
            need_parse = 0

        # 标准音视频流直接放行 parse: 0
        if self.isVideoFormat(final_url) or any(
            k in final_url.lower() for k in ('.mp3', '.m4a', '.aac', '.wav')
        ):
            need_parse = 0

        return {
            'parse': need_parse,
            'playUrl': '',
            'url': final_url,
            'header': header_dict,
        }

    def searchContent(self, key, quick, pg='1'):
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick, pg=1):
        """多源并发聚合搜索（模板 ThreadPoolExecutor 结构）"""
        del quick
        pg = int(pg or 1)
        key = self._text(key)
        if pg > 1 or not key:
            return {'page': pg, 'pagecount': pg, 'limit': 0, 'total': 0, 'list': []}

        SRC_TIMEOUT = 4       # 单源搜索超时（秒）
        PER_SRC_LIMIT = 4     # 每源最多收录条数
        MAX_TOTAL = 48        # 总结果上限
        FAST_LIMIT = 20       # 结果达到该条数且已跑 3 秒 → 立即返回
        TOTAL_LIMIT = 8       # 搜索整体最长等待（秒）
        DUP_KEEP = 2          # 同一剧名最多保留的源数量（先返回 = 速度最快）

        def _norm_name(n):
            return re.sub(r'\s+', '', self._text(n)).lower()

        def _one(src_key):
            try:
                s_url = self._build_url(
                    '%s/api/v1/spiders/%s/search' % (self.SITE_URL, src_key),
                    {'wd': key, 'pg': 1},
                )
                data = self._safe_json(self._request(s_url, timeout=SRC_TIMEOUT).get('text')) or {}
                return [self._clean_item(item, src_key) for item in (data.get('list') or [])[:PER_SRC_LIMIT]]
            except Exception:
                return []

        # 不用 with，确保可以提前返回而不等待慢源
        from concurrent.futures import ThreadPoolExecutor, as_completed
        pool = ThreadPoolExecutor(max_workers=8)
        result = []
        dup_count = {}
        start = time.time()
        try:
            futs = [pool.submit(_one, sk) for sk in self.SEARCH_TARGETS]
            for fut in as_completed(futs):
                try:
                    lst = fut.result()
                except Exception:
                    lst = []
                # 同一剧名最多保留 DUP_KEEP 个源（先返回的源 = 速度最快）
                for it in lst:
                    if len(result) >= MAX_TOTAL:
                        break
                    nk = _norm_name(it.get('vod_name'))
                    if not nk:
                        continue
                    c = dup_count.get(nk, 0)
                    if c >= DUP_KEEP:
                        continue
                    dup_count[nk] = c + 1
                    result.append(it)
                el = time.time() - start
                if len(result) >= FAST_LIMIT and el > 3:
                    break
                if el > TOTAL_LIMIT:
                    break
        except Exception:
            pass
        finally:
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

        return {
            'page': 1,
            'pagecount': 1,
            'limit': len(result),
            'total': len(result),
            'list': result,
        }

    def localProxy(self, param):
        # 遮天契约：param 可能是 dict 或 JSON 字符串；返回必须是四元组
        if isinstance(param, str):
            try:
                param = json.loads(param)
            except Exception:
                param = {}
        if not isinstance(param, dict):
            param = {}
        url = param.get('url', '') or param.get('do', '')
        if not url:
            return [404, 'text/plain; charset=utf-8', b'Missing url parameter', {}]
        res = self._request(url)
        body = res.get('bytes', b'') or b''
        code = res.get('code', 200) or 200
        mime = 'image/jpeg'
        if body.startswith(b'\x89PNG'):
            mime = 'image/png'
        elif body.startswith(b'\xff\xd8'):
            mime = 'image/jpeg'
        elif body.startswith(b'GIF'):
            mime = 'image/gif'
        elif body.startswith(b'RIFF') and b'WEBP' in body[:16]:
            mime = 'image/webp'
        return [code, mime, body, {'Access-Control-Allow-Origin': '*'}]

    def action(self, action):
        return {'msg': 'ok'}

    def liveContent(self):
        return ''


# 注册爬虫
if __name__ == '__main__':
    from base.spider import Spider as BaseSpider
    BaseSpider.register(Spider())
