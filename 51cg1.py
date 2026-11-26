class Config:
    # ----------------------【导航探测标准模板配置】----------------------
    SITE_NAME     = "51吃瓜10"
    SITE_KEYWORDS = ["51吃瓜10", "51吃瓜"]
    PLAY_FROM = "51吃瓜1"
    PLAY_FALLBACK_TITLE  = "51吃瓜10"

    HOST_CACHE_KEY = "51cg10_host_v1"
    PUB_CACHE_KEY  = "51cg10_pub_v1"

    # ========== 按照业务优先级填入网址 ==========
    # PUBLISH_URLS：二级【真正发布页导航页，有效期约6个月】主发布源
    PUBLISH_URLS = [
        "https://www.sunkdjlla.cc/",
        "https://www.gvhafcbw.cc/",
    ]
    # SECONDARY_PUBLISH_URLS：一级【跳转域名，保底，有效期约1年，会跳转至二级发布页】
    SECONDARY_PUBLISH_URLS = [
        "https://51cgf24.com/",
    ]
    # SEED_HOSTS：三级【直达内容站，速度最快，有效期最短约1个月，优先直接探测】
    SEED_HOSTS = [
        "https://d2bklv1j32lvpc.cloudfront.net/",
    ]
    FALLBACK_HOST = None

    # 探测超时参数（模板标准）
    PUBLISH_TIMEOUT   = 12
    PROBE_TIMEOUT     = 12
    FAST_TIMEOUT      = 8
    PROBE_MIN_HTML    = 1500
    PROBE_MIN_ARTICLE = 1
    PROBE_PATHS       = ("/",)
    MAX_JUMP          = 3   # 跳转链最大追踪层数，满足 一级域名跳转→二级发布页 的跳转需求

    VALID_TLDS = {
        'com', 'net', 'org', 'cc', 'xyz', 'lol', 'vip', 'app', 'top', 'cn',
        'co', 'io', 'me', 'tv', 'club', 'site', 'online', 'info', 'biz',
        'pro', 'link', 'live', 'shop', 'fun', 'work', 'icu', 'life',
        'world', 'store', 'tech', 'space', 'website', 'host', 'pw', 'tk',
        'ml', 'ga', 'cf', 'gq', 'su', 'ws', 'ly', 'to', 'st', 'in', 'tw',
        'hk', 'jp', 'kr', 'ru', 'us', 'uk', 'de', 'fr', 'nl', 'eu', 'au',
        'ca', 'sg', 'my', 'sbs', 'bet', 'cam', 'one', 'plus', 'now',
        'today', 'pub', 'dev', 'cool', 'cloud',
    }
    DOMAIN_BLACKLIST = (
        'google', 'gstatic', 'bing.com', 'baidu.com', 'so.com', 'sogou.com',
        'yandex', 'facebook', 'fbcdn', 'instagram', 'twitter', 'twimg',
        'youtube', 'ytimg', 't.me', 'telegram', 'whatsapp', 'discord',
        'reddit', 'tiktok', 'pinterest', 'apple.com', 'icloud', 'microsoft',
        'windows', 'amazonaws', 'cloudflare', 'cloudfront', 'azureedge',
        'github', 'gitlab', 'gitee', 'bitbucket', 'w3.org', 'wikipedia',
        'mozilla.org', 'stackoverflow', 'jsdelivr', 'unpkg', 'bootstrapcdn',
        'jquery', 'fontawesome', 'gmail', 'outlook', 'hotmail', 'yahoo',
        'protonmail', 'qq.com', '163.com', '126.com', 'sina.com',
        'weibo.com', 'statcounter', 'google-analytics', 'umeng', 'cnzz',
        'beian.miit.gov.cn', 'wordpress.org', 'wix.com', 'weebly',
        'shopify', '51.la', 'cnzz.com', '51yes', 'navone.cloud',
    )
    EXTRA_BLACKLIST = ('beian.miit.gov.cn', 'w3.org', 'example.com')

    VERIFY_SSL = False
    @classmethod
    def match_keyword(cls, text):
        if not text:
            return False
        for kw in cls.SITE_KEYWORDS:
            try:
                if hasattr(kw, "search"):
                    if kw.search(text):
                        return True
                elif kw and kw in text:
                    return True
            except Exception:
                continue
        return False

    # ----------------------【51cg1原有全部业务配置，完整保留不动】----------------------
    SITE_MARKERS = [
        "post-title", "entry-title", "<article", 'class="post',
        "realtime-card", "candid-video", "video-card",
    ]
    NAV_PAGE_KEYWORDS = (
        "线路一", "线路二", "线路三", "推荐访问", "线路正常",
        "官方导航", "发布页", "备用线路", "地址发布页", "永久地址", "最新地址",
    )
    SEL_ARTICLE      = (
        "#index article, #archive article, article, "
        ".realtime-card, .video-card, .video-item, .post-item, .card-item"
    )
    SEL_ARTICLE_HOME = (
        "#index article, article, "
        ".realtime-card, .video-card, .video-item, .post-item, .card-item"
    )
    SEL_PLAYER       = ".dplayer"
    SEL_CONTENT      = ".post-content, article, .realtime-content"
    SEL_TAGS         = ".post-tags a, .tags a, .keywords a"
    SEL_SUMMARY      = ".post-content"
    SEL_TITLE        = ".post-title, h1"
    SEL_NAV_ROOT = "ul.navbar-nav.mr-auto"
    SEL_NAV_ITEM = "li.nav-item"
    SEL_NAV_LINK = "a.nav-link"
    SEL_NAV_TOGGLE = "button.nav-link"
    SEL_SUB_MENU_ITEM = "li.dropdown-item a"
    NAV_VALID_PREFIXES = ("/category/",)
    SEL_NAV = [
        "ul.navbar-nav.mr-auto > li.nav-item > a.nav-link",
        "ul.navbar-nav > li.nav-item > a.nav-link",
        "ul.navbar-nav li a.nav-link",
        "#navbarCollapse a.nav-link",
        ".navbar-nav a.nav-link",
        ".realtime-tabs a",
        ".category-tabs a",
        ".category-list ul li",
        ".nav-menu li",
        ".menu li",
        ".tabs a",
        "nav ul li",
        "header nav a",
        "nav a",
    ]
    SEL_SUB_NAV = [
        "ul.navbar-nav.mr-auto li.nav-item.dropdown > ul.dropdown-menu > li.dropdown-item > a",
        "ul.dropdown-menu > li.dropdown-item > a",
        ".dropdown-menu a",
    ]
    DEFAULT_CATEGORY = {"type_name": "首页", "type_id": "/"}
    LINK_KEYWORDS = (
        "点击观看", "点击播放", "点击进入", "进入观看", "前往观看",
        "观看", "播放", "视频", "立即观看", "在线观看", "在线播放",
        "完整版", "高清",
        "第一弹", "第二弹", "第三弹", "第四弹", "第五弹",
        "第六弹", "第七弹", "第八弹", "第九弹", "第十弹",
        "第1集", "第2集", "第3集", "第4集", "第5集",
        "第6集", "第7集", "第8集", "第9集", "第10集",
        "第1话", "第2话", "第3话", "第4话", "第5话",
        "episode", "watch", "play", "full",
    )
    LINK_URL_PATTERNS = (
        r"/vodplay/", r"/vodplay\b", r"/v/\d+", r"/play/",
        r"/video/", r"/watch/", r"/player/", r"\.m3u8",
    )
    IMG_AES_KEYS = [
        (b"f5d965df75336270", b"97b60394abc2fbe1"),
        (b"75336270f5d965df", b"abc2fbe197b60394"),
    ]
    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }
