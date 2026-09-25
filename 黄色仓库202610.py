#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re, json, base64, sqlite3, threading, time, hashlib
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty

import requests
from pyquery import PyQuery as pq
from tqdm import tqdm

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
                   "Mobile/15E148 Safari/604.1"),
    "Referer": "https://hsck123.com/"
}

CLASSES = [
    {"type_name": "日韩AV", "type_id": "1"},
    {"type_name": "国产系列", "type_id": "2"},
    {"type_name": "欧美", "type_id": "3"},
    {"type_name": "成人动漫", "type_id": "4"},
    {"type_name": "日本有码", "type_id": "7"},
    {"type_name": "人人碰", "type_id": "8"},
    {"type_name": "有码中文字幕", "type_id": "9"},
    {"type_name": "日本无码", "type_id": "10"},
    {"type_name": "国产视频", "type_id": "15"},
    {"type_name": "欧美高清", "type_id": "21"},
    {"type_name": "动漫剧情", "type_id": "22"}
]

SITE_PREFIX = "hsck"  # 网站标识前缀

def get_dynamic_host() -> str:
    init_host = base64.b64decode('aHR0cDovL2hzY2submV0').decode()
    try:
        html = requests.get(init_host, headers=HEADERS, timeout=10).text
        m = re.search(r'strU="(.*?)"', html)
        if not m:
            return init_host
        location_u = f"{m.group(1)}{init_host.rstrip('/')}/&p=/"
        r = requests.get(location_u, headers=HEADERS, allow_redirects=False, timeout=10)
        return r.headers.get('location', init_host)
    except Exception:
        return "http://6590ck.cc/"

class YellowCrawler:
    def __init__(self, page_workers=64, video_workers=128):
        self.host = get_dynamic_host()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

        self.page_q = Queue()
        self.video_q = Queue()

        self.conn = sqlite3.connect("yellow.db", check_same_thread=False)
        self.lock = threading.Lock()
        self.batch_buffer = []
        
        # 创建MacCMS标准表结构
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS mac_type(
               type_id INTEGER PRIMARY KEY,
               type_name TEXT
            )
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS mac_vod(
               vod_id TEXT PRIMARY KEY,
               type_id TEXT,
               type_id_1 TEXT,
               group_id TEXT,
               vod_name TEXT,
               vod_sub TEXT,
               vod_en TEXT,
               vod_status TEXT,
               vod_letter TEXT,
               vod_color TEXT,
               vod_tag TEXT,
               vod_class TEXT,
               vod_pic TEXT,
               vod_pic_thumb TEXT,
               vod_pic_slide TEXT,
               vod_pic_screenshot TEXT,
               vod_actor TEXT,
               vod_director TEXT,
               vod_writer TEXT,
               vod_behind TEXT,
               vod_blurb TEXT,
               vod_remarks TEXT,
               vod_pubdate TEXT,
               vod_total TEXT,
               vod_serial TEXT,
               vod_tv TEXT,
               vod_weekday TEXT,
               vod_area TEXT,
               vod_lang TEXT,
               vod_year TEXT,
               vod_version TEXT,
               vod_state TEXT,
               vod_author TEXT,
               vod_jumpurl TEXT,
               vod_tpl TEXT,
               vod_tpl_play TEXT,
               vod_tpl_down TEXT,
               vod_isend TEXT,
               vod_lock TEXT,
               vod_level TEXT,
               vod_copyright TEXT,
               vod_points TEXT,
               vod_points_play TEXT,
               vod_points_down TEXT,
               vod_hits TEXT,
               vod_hits_day TEXT,
               vod_hits_week TEXT,
               vod_hits_month TEXT,
               vod_duration TEXT,
               vod_up TEXT,
               vod_down TEXT,
               vod_score TEXT,
               vod_score_all TEXT,
               vod_score_num TEXT,
               vod_time TEXT,
               vod_time_add TEXT,
               vod_time_hits TEXT,
               vod_time_make TEXT,
               vod_trysee TEXT,
               vod_douban_id TEXT,
               vod_douban_score TEXT,
               vod_reurl TEXT,
               vod_rel_vod TEXT,
               vod_rel_art TEXT,
               vod_pwd TEXT,
               vod_pwd_url TEXT,
               vod_pwd_play TEXT,
               vod_pwd_play_url TEXT,
               vod_pwd_down TEXT,
               vod_pwd_down_url TEXT,
               vod_content TEXT,
               vod_play_from TEXT,
               vod_play_server TEXT,
               vod_play_note TEXT,
               vod_play_url TEXT,
               vod_down_from TEXT,
               vod_down_server TEXT,
               vod_down_note TEXT,
               vod_down_url TEXT,
               vod_plot TEXT,
               vod_plot_name TEXT,
               vod_plot_detail TEXT,
               type_name TEXT
            )
        """)
        
        # 创建索引
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_vod_id ON mac_vod(vod_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_vod_name ON mac_vod(vod_name)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_type_id ON mac_vod(type_id)")
        
        # 数据库性能优化
        self.conn.execute("PRAGMA synchronous = 0;")
        self.conn.execute("PRAGMA journal_mode = MEMORY;")
        self.conn.execute("PRAGMA temp_store = MEMORY;")
        self.conn.execute("PRAGMA cache_size = -64000;")
        
        self.conn.commit()

        self.page_counter = 0
        self.video_counter = 0
        self.page_pbar = tqdm(total=0, desc="Pages scanned", unit="pg", position=0)
        self.video_pbar = tqdm(total=0, desc="Videos parsed", unit="vid", position=1)

        self.page_pool = ThreadPoolExecutor(max_workers=page_workers)
        self.video_pool = ThreadPoolExecutor(max_workers=video_workers)

    # ---------- 工具 ----------
    def full(self, url: str) -> str:
        if url.startswith("http"):
            return url
        if url.startswith("//"):
            return "https:" + url
        return self.host.rstrip("/") + url

    def fetch(self, url: str, retry=3) -> str:
        for _ in range(retry):
            try:
                r = self.session.get(url, timeout=8)
                if r.status_code == 200:
                    return r.text
            except Exception:
                time.sleep(0.1)
        return ""

    def generate_vod_id(self, original_url: str) -> str:
        """生成唯一的vod_id：网站前缀 + URL的MD5哈希前12位"""
        url_hash = hashlib.md5(original_url.encode()).hexdigest()[:12]
        return f"{SITE_PREFIX}_{url_hash}"

    def update_progress(self, is_page: bool):
        with self.lock:
            if is_page:
                self.page_counter += 1
                self.page_pbar.n = self.page_counter
                self.page_pbar.refresh()
            else:
                self.video_counter += 1
                self.video_pbar.n = self.video_counter
                self.video_pbar.refresh()

    def commit_batch(self):
        if len(self.batch_buffer) >= 500:
            with self.lock:
                self.conn.executemany(
                    """INSERT OR IGNORE INTO mac_vod (
                        vod_id, type_id, vod_name, vod_pic, vod_play_url, 
                        vod_content, type_name, vod_time, vod_time_add, vod_play_from
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    self.batch_buffer
                )
                self.conn.commit()
                self.batch_buffer.clear()

    # ---------- 页面扫描 ----------
    def scan_page(self, cate: dict, page: int):
        url = f"{self.host.rstrip('/')}/vodtype/{cate['type_id']}-{page}.html"
        html = self.fetch(url)
        if not html:
            return
        root = pq(html)
        items = root('.stui-vodlist li')

        # 最后一页判断
        if len(items) == 0 or len(items) < 20:
            return

        videos_found = 0
        for li in items.items():
            href = li.find('a').attr('href')
            if href and href.startswith('/vodplay/'):
                self.video_q.put((cate, href))
                videos_found += 1

        if videos_found > 0 and page < 9999:
            self.page_q.put((cate, page + 1))
        self.update_progress(True)

    # ---------- 详情解析 ----------
    def extract_m3u8(self, script: str) -> str:
        """提取m3u8播放地址"""
        player_patterns = [
            r'var\s+player_aaaa\s*=\s*({.*?});',
            r'player_aaaa\s*=\s*({.*?});',
            r'var\s+player_aaaa\s*=\s*({.*?})\s*<\/script>',
            r'player_aaaa\s*=\s*({.*?})\s*<\/script>'
        ]
        for pattern in player_patterns:
            match = re.search(pattern, script, re.DOTALL)
            if match:
                try:
                    data_str = match.group(1).replace('\\/', '/')
                    player_data = json.loads(data_str)
                    url = player_data.get('url', '')
                    if '.m3u8' in url:
                        return self.full(url)
                except Exception:
                    pass
        
        m3u8_patterns = [
            r'"url"\s*:\s*"([^"]+\.m3u8[^"]*)"',
            r'url\s*:\s*"([^"]+\.m3u8[^"]*)"',
            r'src\s*:\s*"([^"]+\.m3u8[^"]*)"',
            r'file\s*:\s*"([^"]+\.m3u8[^"]*)"',
            r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*'
        ]
        for pattern in m3u8_patterns:
            matches = re.findall(pattern, script)
            for match in matches:
                if '.m3u8' in match:
                    return self.full(match) if not match.startswith('http') else match
        
        full_html_match = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', script)
        if full_html_match:
            return full_html_match.group(0)
        return ""

    def parse_video(self, cate: dict, href: str):
        url = self.full(href)
        html = self.fetch(url)
        if not html:
            self.update_progress(False)
            return
        root = pq(html)
        
        # 提取标题
        title = (root('.stui-pannel__head .title').text()
                 or root('title').text().split(' - ')[0])
        title = re.sub(r'^目录\s*', '', title).strip()
        title = re.sub(r'\s*为你推荐$', '', title).strip()

        # 提取封面图
        pic = (root('.stui-vodlist__thumb').attr('data-original')
               or root('.stui-vodlist__thumb').attr('src')
               or "")
        
        # 提取简介/描述
        content = root('.detail-content').text() or root('.desc').text() or ""
        
        # 提取播放地址
        script = root('script').text()
        play_url = self.extract_m3u8(script)
        
        if not play_url:
            iframe_src = root('iframe').attr('src') or ""
            if iframe_src:
                iframe_full = self.full(iframe_src)
                iframe_html = self.fetch(iframe_full)
                if iframe_html:
                    iframe_m3u8 = self.extract_m3u8(iframe_html)
                    if iframe_m3u8:
                        play_url = iframe_m3u8
                if not play_url:
                    play_url = iframe_full

        if not play_url:
            play_url = url

        # 生成唯一vod_id
        vod_id = self.generate_vod_id(url)
        
        # 获取当前时间戳
        current_time = str(int(time.time()))
        
        # 播放来源
        play_from = "m3u8"
        
        # 准备数据（按照MacCMS标准格式）
        video_data = (
            vod_id,                    # vod_id
            str(cate['type_id']),      # type_id
            title,                      # vod_name
            self.full(pic),            # vod_pic
            play_url,                  # vod_play_url
            content,                   # vod_content
            cate['type_name'],         # type_name
            current_time,              # vod_time
            current_time,              # vod_time_add
            play_from                  # vod_play_from
        )
        
        self.batch_buffer.append(video_data)
        self.commit_batch()
        self.update_progress(False)

    # ---------- 调度 ----------
    def run(self):
        # 填充分类表
        with self.lock:
            self.conn.executemany(
                "INSERT OR IGNORE INTO mac_type (type_id, type_name) VALUES (?, ?)",
                [(cate['type_id'], cate['type_name']) for cate in CLASSES]
            )
            self.conn.commit()

        # 初始化页面队列
        for cate in CLASSES:
            self.page_q.put((cate, 1))

        # 启动工作线程
        for _ in range(self.page_pool._max_workers):
            self.page_pool.submit(self.page_worker)
        for _ in range(self.video_pool._max_workers):
            self.video_pool.submit(self.video_worker)

        # 等待队列清空
        self.page_q.join()
        self.video_q.join()
        self.page_pool.shutdown(wait=True)
        self.video_pool.shutdown(wait=True)
        
        # 提交剩余缓存
        if self.batch_buffer:
            self.conn.executemany(
                """INSERT OR IGNORE INTO mac_vod (
                    vod_id, type_id, vod_name, vod_pic, vod_play_url, 
                    vod_content, type_name, vod_time, vod_time_add, vod_play_from
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                self.batch_buffer
            )
            self.conn.commit()
        
        # 优化数据库
        self.conn.execute("ANALYZE;")
        self.conn.commit()
        
        self.page_pbar.close()
        self.video_pbar.close()
        self.conn.close()
        print(f"\n爬取完成！总扫描页面: {self.page_counter}，总解析视频: {self.video_counter}")

    def page_worker(self):
        while True:
            try:
                cate, page = self.page_q.get(timeout=5)
            except Empty:
                return
            self.scan_page(cate, page)
            self.page_q.task_done()

    def video_worker(self):
        while True:
            try:
                cate, href = self.video_q.get(timeout=8)
            except Empty:
                return
            self.parse_video(cate, href)
            self.video_q.task_done()

if __name__ == "__main__":
    crawler = YellowCrawler(page_workers=64, video_workers=128)
    crawler.run()
