# coding=utf-8
import sys
import re
import urllib.request
import urllib.parse
import http.cookiejar
import gzip
import zlib
import ssl
import html as html_lib

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        def getCache(self, key): return None
        def setCache(self, key, value): return "fail"
        def delCache(self, key): return "fail"

class Spider(SpiderBase):
    def getName(self):
        return "Hanime1(终极自愈+全功能版)"

    def init(self, extend=""):
        self.mirrorPool = [
            "https://hanime1.me",
            "https://www.hanime1.me",
            "https://hanime1.com",
            "https://www.hanime101.com",
            "https://www.hanime999.cc"
        ]
        self.siteUrl = self.mirrorPool[0]
        self.cacheKey = "hanime1_dynamic_site_url"
        self._ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        try:
            self.ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        except Exception:
            pass

        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx)
        )

        cached_site = self.getCache(self.cacheKey)
        if cached_site and str(cached_site).startswith("http"):
            self.siteUrl = str(cached_site).strip().rstrip("/")
        else:
            self._refresh_site_url()
        return True

    # ==========================================
    # 网络容灾自愈模块
    # ==========================================
    def _check_host_alive(self, base_url):
        target = "%s/" % base_url.rstrip("/")
        res = self._fetch(target, check_host=False)
        return res.get("code") == 200

    def _refresh_site_url(self):
        for fallback in self.mirrorPool:
            if self._check_host_alive(fallback):
                self.siteUrl = fallback
                self.setCache(self.cacheKey, fallback)
                return True
        return False

    def _fetch(self, target_url, referer="", check_host=True):
        if not target_url:
            return {"code": 0, "text": ""}
        if target_url.startswith("//"):
            target_url = "https:" + target_url
        elif target_url.startswith("/"):
            target_url = self.siteUrl + target_url

        headers = {
            "User-Agent": self._ua,
            "Referer": referer if referer else (self.siteUrl + "/"),
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }

        domain_retried = False
        for attempt in range(2):
            try:
                req = urllib.request.Request(target_url, headers=headers)
                with self.opener.open(req, timeout=10) as resp:
                    code = resp.getcode()
                    raw = resp.read()
                    enc = getattr(resp, "headers", {}).get("Content-Encoding", "")
                    if raw.startswith(b"\x1f\x8b") or enc == "gzip":
                        raw = gzip.decompress(raw)
                    elif enc == "deflate":
                        try:
                            raw = zlib.decompress(raw)
                        except Exception:
                            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                    try:
                        text = raw.decode("utf-8")
                    except Exception:
                        text = raw.decode("latin1", errors="ignore")
                    return {"code": code, "text": text}
            except urllib.error.HTTPError as e:
                if e.code in (404, 451, 500, 502, 503) and check_host and not domain_retried:
                    old_host = urllib.parse.urlparse(self.siteUrl).netloc
                    self.delCache(self.cacheKey)
                    if self._refresh_site_url():
                        domain_retried = True
                        new_host = urllib.parse.urlparse(self.siteUrl).netloc
                        target_url = target_url.replace(old_host, new_host)
                        continue
                if attempt == 0: continue
                return {"code": e.code, "text": ""}
            except Exception:
                if check_host and not domain_retried:
                    old_host = urllib.parse.urlparse(self.siteUrl).netloc
                    self.delCache(self.cacheKey)
                    if self._refresh_site_url():
                        domain_retried = True
                        new_host = urllib.parse.urlparse(self.siteUrl).netloc
                        target_url = target_url.replace(old_host, new_host)
                        continue
                if attempt == 0: continue
                return {"code": -1, "text": ""}
        return {"code": -1, "text": ""}

    # ==========================================
    # 模块 2：分类路由与高级筛选器
    # ==========================================
    def homeContent(self, filter):
        result = {}
        classes = [
            {"type_name": "里番", "type_id": "裏番"},
            {"type_name": "泡面番", "type_id": "泡麵番"},
            {"type_name": "Motion Anime", "type_id": "Motion Anime"},
            {"type_name": "3DCG", "type_id": "3DCG"},
            {"type_name": "2.5D", "type_id": "2.5D"},
            {"type_name": "AI生成", "type_id": "AI生成"},
            {"type_name": "MMD", "type_id": "MMD"},
            {"type_name": "Cosplay", "type_id": "Cosplay"},
            {"type_name": "新番预告", "type_id": "新番預告"},
            {"type_name": "2D动画", "type_id": "2D動畫"}
        ]
        
        # 1. 排序筛选器
        sort_filter = {
            "key": "sort",
            "name": "排序方式",
            "value": [
                {"n": "最新上传", "v": ""},
                {"n": "本日排行", "v": "本日排行"},
                {"n": "本週排行", "v": "本週排行"},
                {"n": "本月排行", "v": "本月排行"}
            ]
        }
        
        # 2. 节点切换筛选器 (动态读取你的备用池)
        node_choices = [{"n": "自动优选(默认)", "v": ""}]
        for url in self.mirrorPool:
            # 提取域名作为显示名字，比如 hanime1.me
            domain_name = urllib.parse.urlparse(url).netloc
            node_choices.append({"n": domain_name, "v": url})
            
        node_filter = {
            "key": "node",
            "name": "切换线路",
            "value": node_choices
        }
        
        # 把两个菜单都加进去
        filters_dict = {c["type_id"]: [sort_filter, node_filter] for c in classes}

        result['class'] = classes
        result['filters'] = filters_dict
        return result


    # ==========================================
    # 模块 3：UI卡片解析模块 (智能分页与筛选生效)
    # ==========================================
    def categoryContent(self, tid, pg, filter, extend):
        page_num = int(pg) if str(pg).isdigit() else 1
        
        # ==========================================
        # 核心新增：手动切换节点并写入全局记忆
        # ==========================================
        target_node = extend.get("node", "")
        if target_node and target_node.startswith("http"):
            # 如果用户手动选了节点，强制更新当前域名，并存入本地缓存
            self.siteUrl = target_node
            self.setCache(self.cacheKey, target_node)
            
        # 接收 UI 排序参数并自动转码
        query_params = {"genre": tid, "page": str(page_num)}
        sort_val = extend.get("sort", "")
        if sort_val:
            query_params["sort"] = sort_val
            
        query_str = urllib.parse.urlencode(query_params)
        target_url = f"/search?{query_str}"
        
        res = self._fetch(target_url)
        html = res.get("text", "")
        
        videos = []
        seen_ids = set()
        blocks = html.split('/watch?v=')
        for block in blocks[1:]:
            id_match = re.match(r'^([^"&]+)', block)
            if not id_match: continue
            vod_id = id_match.group(1)
            
            if vod_id in seen_ids: continue
            seen_ids.add(vod_id)
            
            chunk = block[:1200]
            pic_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', chunk, re.IGNORECASE)
            pic = pic_match.group(1) if pic_match else ""
            
            title = "未知标题"
            t_match_b = re.search(r'home-rows-videos-title[^>]*>\s*([^<]+)', chunk)
            if t_match_b: title = t_match_b.group(1).strip()
            else:
                t_match_a = re.search(r'class="title"[^>]*>\s*([^<]+)', chunk)
                if t_match_a: title = t_match_a.group(1).strip()

            remarks_list = []
            duration_match = re.search(r'class="duration"[^>]*>\s*([^<]+)\s*</div>', chunk)
            if duration_match: remarks_list.append(duration_match.group(1).strip())
                
            views_match = re.search(r'class="stat-item">\s*([0-9\.]+万?次)\s*</div>', chunk)
            if views_match: remarks_list.append(views_match.group(1).strip())
                
            remarks = " | ".join(remarks_list)
            packed_id = f"{vod_id}@@@{title}@@@{pic}"
            
            videos.append({
                "vod_id": packed_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remarks
            })

        # 0开销数量推断智能分页
        pagecount = page_num + 1 if len(videos) >= 30 else page_num

        return {
            "list": videos,
            "page": page_num,
            "pagecount": pagecount,
            "limit": 40,
            "total": 999999
        }

    # ==========================================
    # 模块 4：播放直连与主副线路分离
    # ==========================================
    def detailContent(self, array):
        raw_id = array[0] if isinstance(array, list) else str(array)
            
        passed_title = ""
        passed_pic = ""
        if "@@@" in raw_id:
            parts = raw_id.split("@@@")
            vod_id = parts[0]
            if len(parts) > 1: passed_title = parts[1]
            if len(parts) > 2: passed_pic = parts[2]
        else:
            vod_id = raw_id
            
        target_url = f"/watch?v={vod_id}"
        res = self._fetch(target_url)
        html = res.get("text", "")

        # 提取标题与封面
        title = passed_title
        if not title:
            title_match = re.search(r'<title>(.*?)</title>', html)
            title = re.split(r'&nbsp;-|-', title_match.group(1))[0].strip() if title_match else vod_id

        pic = passed_pic
        if not pic:
            pic_match = re.search(r'<meta property="og:image" content="([^"]+)"', html)
            pic = pic_match.group(1) if pic_match else ""

        # 新增：提取官方剧情介绍与定制面板
        desc_m = re.search(r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if not desc_m:
            desc_m = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        raw_desc = html_lib.unescape(desc_m.group(1).strip()) if desc_m else "Hanime 动漫原画精品"
        
        full_desc = f"【当前优选节点: {self.siteUrl}】\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n{raw_desc}"

        # ------------------------------------------
        # 线路 1：主线路原画直连 (提取当前 MP4)
        # ------------------------------------------
        source_matches = re.findall(r'<source[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
        parsed_links = []
        for link in set(source_matches):
            res_match = re.search(r'(\d+p)', link, re.IGNORECASE)
            if res_match:
                quality = res_match.group(1).upper()
                weight = int(res_match.group(1)[:-1])
            else:
                quality = "默认画质"
                weight = 0
            parsed_links.append((weight, quality, link))
            
        parsed_links.sort(key=lambda x: x[0], reverse=True)
        play_list = [f"{item[1]}${item[2]}" for item in parsed_links]
        main_play_str = "#".join(play_list) if play_list else "解析失败$http://错误.mp4"
        
        play_from = "🎬 原画直连 (秒播)"
        play_url = main_play_str

        # ------------------------------------------
        # 线路 2：相关推荐副线路 (极速切片精准版)
        # ------------------------------------------
        seen_eps = set([str(vod_id)])  # 排除当前正在播放的主视频
        related_list = []
        ep_counter = 1
        
        # 套用列表页最稳的切片大法
        blocks = html.split('/watch?v=')
        for block in blocks[1:]:
            id_match = re.match(r'^([^"&]+)', block)
            if not id_match: continue
            r_id = id_match.group(1)
            
            if r_id in seen_eps: continue
            seen_eps.add(r_id)
            
            chunk = block[:1200]
            clean_name = ""
            
            # 第一层级：精准寻找标题特有 class
            t_match_b = re.search(r'home-rows-videos-title[^>]*>\s*([^<]+)', chunk)
            if t_match_b: 
                clean_name = t_match_b.group(1).strip()
            else:
                t_match_a = re.search(r'class="title"[^>]*>\s*([^<]+)', chunk)
                if t_match_a: 
                    clean_name = t_match_a.group(1).strip()
                    
            # 第二层级：如果找不到特殊 class，去抓 alt 或 title 属性
            if not clean_name:
                alt_match = re.search(r'(?:title|alt)=["\']([^"\']+)["\']', chunk, re.I)
                if alt_match: 
                    clean_name = alt_match.group(1).strip()
                    
            # 第三层级兜底：如果抓出来的名字太短或者是占位符，自动重命名
            if clean_name.lower() in ["", "thumb", "thum", "img"]:
                clean_name = f"推荐 {ep_counter:02d}"
                
            clean_name = html_lib.unescape(clean_name)
            
            # 拼接格式： 视频名字$/watch?v=12345
            related_list.append(f"{clean_name}$/watch?v={r_id}")
            ep_counter += 1
            if len(related_list) >= 30: break

        # 追加线路
        if related_list:
            play_from += "$$$📺 相关推荐 (连播)"
            play_url += "$$$" + "#".join(related_list)



        vod = {
            "vod_id": vod_id,
            "vod_name": title,
            "vod_pic": pic,
            "vod_type": "通用分类",
            "vod_remarks": "高清",
            "vod_director": "YJ-Gemini",
            "vod_content": full_desc.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
            "vod_play_from": play_from,
            "vod_play_url": play_url
        }
        return {'list': [vod]}

    # ==========================================
    # 模块 5：搜索模块
    # ==========================================
    def searchContent(self, key, quick, pg="1"):
        page_num = int(pg) if str(pg).isdigit() else 1
        encoded_key = urllib.parse.quote(key)
        target_url = f"/search?query={encoded_key}&page={page_num}"
        
        res = self._fetch(target_url)
        html = res.get("text", "")
        
        videos = []
        seen_ids = set()
        blocks = html.split('/watch?v=')
        for block in blocks[1:]:
            id_match = re.match(r'^([^"&]+)', block)
            if not id_match: continue
            vod_id = id_match.group(1)
            
            if vod_id in seen_ids: continue
            seen_ids.add(vod_id)
            
            chunk = block[:1200]
            pic_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', chunk, re.IGNORECASE)
            pic = pic_match.group(1) if pic_match else ""
            
            title = "未知标题"
            t_match_b = re.search(r'home-rows-videos-title[^>]*>\s*([^<]+)', chunk)
            if t_match_b: title = t_match_b.group(1).strip()
            else:
                t_match_a = re.search(r'class="title"[^>]*>\s*([^<]+)', chunk)
                if t_match_a: title = t_match_a.group(1).strip()

            remarks_list = []
            duration_match = re.search(r'class="duration"[^>]*>\s*([^<]+)\s*</div>', chunk)
            if duration_match: remarks_list.append(duration_match.group(1).strip())
                
            views_match = re.search(r'class="stat-item">\s*([0-9\.]+万?次)\s*</div>', chunk)
            if views_match: remarks_list.append(views_match.group(1).strip())
                
            remarks = " | ".join(remarks_list)
            packed_id = f"{vod_id}@@@{title}@@@{pic}"
            
            videos.append({
                "vod_id": packed_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remarks
            })

        return {
            "list": videos,
            "page": page_num,
            "pagecount": page_num + 1 if len(videos) >= 30 else page_num,
            "limit": 40,
            "total": 999999
        }

    # ==========================================
    # 模块 6：播放动态路由防盗链模块
    # ==========================================
    def playerContent(self, flag, id, vipFlags):
        play_url = id
        
        # 新增：如果是“相关推荐”副线路传来的网址（/watch?v=），进行二次动态解析提取直链
        if id.startswith('/watch?v='):
            res = self._fetch(id)
            html = res.get("text", "")
            src_matches = re.findall(r'<source[^>]*src=["\']([^"\']+)["\']', html, re.I)
            
            if src_matches:
                p1080 = [u for u in src_matches if "1080p" in u.lower()]
                play_url = p1080[0] if p1080 else src_matches[0]
            else:
                all_mp4 = re.findall(r'["\'](https?:[^"\']+\.mp4[^"\']*)["\']', html, re.I)
                if all_mp4: play_url = all_mp4[0]
                
        return {
            "parse": 0,
            "playUrl": "",
            "url": play_url,
            "header": {
                "User-Agent": self._ua,
                "Referer": self.siteUrl + "/"
            }
        }
