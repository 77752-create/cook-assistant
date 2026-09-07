# -*- coding: utf-8 -*-
"""
做菜助手核心逻辑：搜索视频 -> 提取文字 -> 整理成菜谱模板
"""
import os
import re
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import io

import httpx

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RECIPE_DIR = os.path.join(os.path.dirname(BASE_DIR), "菜谱")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

UA_CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
UA_SPIDER = "Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)"

os.makedirs(RECIPE_DIR, exist_ok=True)


# ---------------------------------------------------------------- 配置

DEFAULTS = {
    "openai_api_key": "",
    "openai_base_url": "",
    "llm_model": "gpt-4o-mini",
    "stt_model": "gpt-4o-transcribe",
    "stt_api_key": "",
    "stt_base_url": "",
    "douyin_cookie": "",
    "allow_temp_download": True,
    "use_mediacrawler": False,
    "settings_pin_hash": "",
    # 传模型名时 faster-whisper 会在首次使用时下载模型；也可填写已有模型目录。
    "whisper_model_dir": "small",
    "mediacrawler_dir": r"D:\AI\codex\MediaCrawler",
}


def clean_cookie(c):
    """清洗误粘贴的 Cookie：去掉开头的 cookie/Cookie: 行和所有换行"""
    c = (c or "").strip()
    if not c:
        return ""
    lines = [l.strip() for l in c.splitlines() if l.strip()]
    if lines and re.match(r"^cookie:?$", lines[0], re.I):
        lines = lines[1:]
    c = " ".join(lines).strip()
    c = re.sub(r"\s+", " ", c)
    return c


def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    cfg["douyin_cookie"] = clean_cookie(cfg.get("douyin_cookie", ""))
    # 环境变量优先（云端部署时无需改文件）
    if os.environ.get("OPENAI_API_KEY"):
        cfg["openai_api_key"] = os.environ["OPENAI_API_KEY"].strip()
    if os.environ.get("OPENAI_BASE_URL"):
        cfg["openai_base_url"] = os.environ["OPENAI_BASE_URL"].strip()
    if os.environ.get("LLM_MODEL"):
        cfg["llm_model"] = os.environ["LLM_MODEL"].strip()
    if os.environ.get("STT_API_KEY"):
        cfg["stt_api_key"] = os.environ["STT_API_KEY"].strip()
    if os.environ.get("STT_BASE_URL"):
        cfg["stt_base_url"] = os.environ["STT_BASE_URL"].strip()
    if os.environ.get("STT_MODEL"):
        cfg["stt_model"] = os.environ["STT_MODEL"].strip()
    if os.environ.get("DOUYIN_COOKIE"):
        cfg["douyin_cookie"] = clean_cookie(os.environ["DOUYIN_COOKIE"])
    return cfg


def save_config(cfg):
    data = dict(DEFAULTS)
    data.update(cfg or {})
    data["douyin_cookie"] = clean_cookie(data.get("douyin_cookie", ""))
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 工具

def clean_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def clean_text(s):
    s = clean_html(s)
    s = re.sub(r"https?://\S+", "", s)          # 去掉网址
    s = re.sub(r"#\S+", "", s)                   # 去掉话题标签
    s = re.sub(r"@\S+", "", s)                   # 去掉 @
    s = re.sub(r"[ \t\ufeff]+", "", s)           # 去掉空格/制表符，保留换行
    s = re.sub(r"\n{2,}", "\n", s).strip("\n")
    return s


def strip_douyin_stats(desc):
    """去掉抖音简介尾巴：- 作者于20260122发布在抖音，已经收获了XX个喜欢..."""
    m = re.search(r"[-—–]\s*[^-—–]{0,30}?于\d{8}发布在抖音", desc or "")
    if m:
        return (desc[:m.start()]).strip(" -—–")
    return desc


def looks_like_recipe(text):
    """判断一段简介/文字是否本身就像菜谱"""
    t = text or ""
    if re.search(r"(^|\n)\s*[0-9一二三四五六七八九十]+[\.、．]", t):
        return True
    if ("食材" in t or "步骤" in t) and len(t) > 30:
        return True
    if len(t) > 60 and re.search(r"下锅|热锅|起锅|加入|放入|翻炒|出锅", t):
        return True
    return False


def http_client():
    return httpx.Client(timeout=30, verify=False, follow_redirects=True,
                        headers={"User-Agent": UA_CHROME, "Accept-Language": "zh-CN,zh;q=0.9"})


def _client_mobile():
    ua = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
    return httpx.Client(timeout=25, verify=False, follow_redirects=True,
                        headers={"User-Agent": ua, "Accept-Language": "zh-CN,zh;q=0.9"})


def fmt_count(n):
    try:
        n = int(n)
    except Exception:
        return str(n)
    if n >= 10000:
        return "%.1f万" % (n / 10000)
    return str(n)


# ---------------------------------------------------------------- B站搜索

def search_bilibili(keyword, limit=15):
    """搜索B站视频，返回候选列表"""
    items = []
    with http_client() as c:
        try:
            c.get("https://www.bilibili.com/")  # 拿 cookie
            r = c.get("https://api.bilibili.com/x/web-interface/search/type",
                      params={"search_type": "video", "keyword": keyword, "page": 1,
                              "order": "totalrank", "page_size": limit},
                      headers={"Referer": "https://www.bilibili.com/"})
            data = r.json()
            result = (data.get("data") or {}).get("result") or []
        except Exception as e:
            return {"ok": False, "error": "B站搜索失败：%s" % e}

    tokens = [t for t in re.split(r"[\s、，,]+", keyword) if len(t) >= 2]
    for it in result:
        bvid = it.get("bvid")
        title = clean_html(it.get("title", ""))
        if not bvid or not title:
            continue
        # 过滤明显不相关的视频
        if tokens and not any(t in title for t in tokens):
            if not re.search(r"家常|教程|美食|做法|厨房|做菜|下饭|炒|菜", title):
                continue
        items.append({
            "source": "bilibili",
            "id": bvid,
            "title": title,
            "author": it.get("author", ""),
            "play": fmt_count(it.get("play", 0)),
            "duration": it.get("duration", ""),
            "url": "https://www.bilibili.com/video/%s" % bvid,
        })
    # 去掉重复标题
    seen, uniq = set(), []
    for it in items:
        if it["title"] not in seen:
            seen.add(it["title"])
            uniq.append(it)
    return {"ok": True, "items": uniq[:limit]}


def bilibili_view(bvid):
    """B站视频详情：标题、简介、作者"""
    with http_client() as c:
        r = c.get("https://api.bilibili.com/x/web-interface/view",
                  params={"bvid": bvid}, headers={"Referer": "https://www.bilibili.com/"})
        d = r.json().get("data") or {}
    return {
        "title": d.get("title", ""),
        "desc": d.get("desc", ""),
        "author": (d.get("owner") or {}).get("name", ""),
        "duration": d.get("duration", 0),
        "cid": d.get("cid", 0),
    }


# ---------------------------------------------------------------- 链接解析 + 抖音搜索

def extract_url_from_text(text):
    m = re.search(r"https?://[^\s\u4e00-\u9fff\"'<>]+", text or "")
    return m.group(0) if m else (text or "").strip()


def resolve_short(url):
    try:
        with _client_mobile() as c:
            r = c.get(url)
            return str(r.url)
    except Exception:
        return url


def parse_video_input(text):
    """从粘贴的文字/链接里识别抖音或B站视频，返回规范化信息"""
    url = extract_url_from_text(text)
    if not url:
        return {"ok": False, "error": "没找到链接，请粘贴完整的视频链接或分享文案"}
    low = url.lower()
    if any(s in low for s in ("v.douyin.com", "b23.tv", "t.cn")):
        url = resolve_short(url)
        low = url.lower()
    m = re.search(r"/(?:video|shipin)/(\d+)", url) or re.search(r"/share/video/(\d+)", url)
    if "douyin.com" in low and m:
        vid = m.group(1)
        return {"ok": True, "source": "douyin", "id": vid,
                "url": "https://www.douyin.com/video/%s" % vid}
    if "douyin.com" in low:
        return {"ok": False, "error": "抖音链接识别失败，请复制视频的完整分享链接"}
    m = re.search(r"(BV[0-9A-Za-z]{10})", url)
    if m:
        return {"ok": True, "source": "bilibili", "id": m.group(1),
                "url": "https://www.bilibili.com/video/%s" % m.group(1)}
    if "bilibili.com" in low:
        return {"ok": False, "error": "B站链接识别失败"}
    return {"ok": False, "error": "暂不支持这个链接，目前支持抖音 / B站"}


def search_douyin(keyword, limit=8):
    """用百度移动搜索找抖音视频（抖音本身需要登录签名，搜不了）"""
    seen = set()
    queries = ["%s 抖音", "%s 做法 抖音", "%s 教程 抖音", "%s 抖音 家常菜"]
    with _client_mobile() as c:
        for q in queries:
            q = q % keyword
            try:
                r = c.get("https://m.baidu.com/s", params={"word": q})
                html = r.text
                if len(html) < 10000 or "百度安全验证" in html:
                    time.sleep(0.8)
                    continue
                for u in re.findall(r'&quot;dataUrl&quot;:&quot;([^&]+)&quot;', html):
                    u = u.replace("&amp;", "&")
                    m = re.search(r"/(?:video|share/video)/(\d+)", u)
                    if m:
                        seen.add(m.group(1))
            except Exception:
                pass
            time.sleep(0.8)
    vids = list(seen)[:limit]

    def _fetch_title(vid):
        url = "https://www.douyin.com/video/%s" % vid
        title = "抖音视频"
        try:
            html = fetch_page(url)
            tm = re.search(r"<title[^>]*>([^<]+)</title>", html)
            if tm:
                title = clean_html(tm.group(1)).replace(" - 抖音", "")
        except Exception:
            pass
        return {"source": "douyin", "id": vid, "title": title,
                "author": "", "play": "", "duration": "", "url": url}

    items = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for it in pool.map(_fetch_title, vids):
            items.append(it)
    return {"ok": True, "items": items}


NODE_BIN = r"C:\Users\deng\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
_MC_FAIL_UNTIL = 0.0


def _mc_venv_python():
    mc = load_config().get("mediacrawler_dir") or r"D:\AI\codex\MediaCrawler"
    venv_py = os.path.join(mc, "venv", "Scripts", "python.exe")
    if os.path.isdir(mc) and os.path.exists(venv_py) and os.path.exists(os.path.join(mc, "main.py")):
        return mc, venv_py
    return None, None


def search_douyin_mc(keyword, limit=8):
    """用 MediaCrawler 跑抖音官方搜索（需要登录 Cookie），失败返回 None 让上层回退"""
    global _MC_FAIL_UNTIL
    cfg = load_config()
    if not cfg.get("use_mediacrawler"):
        return None
    mc, venv_py = _mc_venv_python()
    if not mc:
        return None
    cookie = cfg.get("douyin_cookie", "")
    if not cookie:
        return None
    out_dir = tempfile.mkdtemp(prefix="mc_dy_")
    try:
        env = dict(os.environ)
        env["PATH"] = NODE_BIN + os.pathsep + env.get("PATH", "")
        cmd = [venv_py, "main.py",
               "--platform", "dy", "--lt", "cookie", "--cookies", cookie,
               "--type", "search", "--keywords", keyword,
               "--crawler_max_notes_count", str(limit),
               "--get_comment", "no",
               "--save_data_option", "jsonl",
               "--save_data_path", out_dir,
               "--headless", "yes"]
        proc = subprocess.run(cmd, cwd=mc, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=100, env=env)
        items = []
        for fn in os.listdir(out_dir):
            if not fn.endswith(".jsonl"):
                continue
            with io.open(os.path.join(out_dir, fn), encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    vid = d.get("aweme_id") or d.get("awemeId") or d.get("video_id") or ""
                    if not vid:
                        continue
                    title = (d.get("title") or d.get("desc") or "抖音视频").strip()
                    title = re.sub(r"\s+", " ", title)
                    items.append({
                        "source": "douyin",
                        "id": str(vid),
                        "title": title,
                        "author": d.get("nickname") or d.get("author") or "",
                        "play": fmt_count(d.get("digg_count") or d.get("like_count") or 0),
                        "duration": "",
                        "url": "https://www.douyin.com/video/%s" % vid,
                    })
        seen, uniq = set(), []
        for it in items:
            key = it["id"]
            if key not in seen:
                seen.add(key)
                uniq.append(it)
        if uniq:
            return {"ok": True, "items": uniq[:limit], "via": "mediacrawler"}
        _MC_FAIL_UNTIL = time.time() + 300
        return {"ok": False,
                "error": "MediaCrawler 没搜到结果：%s" % _redact_cookie((proc.stdout or proc.stderr or "")[-300:])}
    except Exception as e:
        _MC_FAIL_UNTIL = time.time() + 300
        return {"ok": False, "error": "MediaCrawler 抖音搜索失败：%s" % _redact_cookie(str(e))}
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def _redact_cookie(text):
    """把错误信息里的 Cookie 值打码，防止泄露"""
    cookie = load_config().get("douyin_cookie", "")
    if cookie and cookie in text:
        text = text.replace(cookie, "<COOKIE-REDACTED>")
    return text


def search(keyword):
    """搜索：抖音（MediaCrawler 官方通道优先，失败退回百度）优先，B站补充"""
    items = []
    dy = None
    if time.time() >= _MC_FAIL_UNTIL:
        dy = search_douyin_mc(keyword)
    if not (dy and dy.get("ok")):
        dy = search_douyin(keyword)
    bili = search_bilibili(keyword)
    if dy.get("ok"):
        items += dy.get("items", [])
    if bili.get("ok"):
        items += bili.get("items", [])
    if not items:
        return {"ok": False,
                "error": dy.get("error") or bili.get("error") or "没有搜到相关视频，换个关键词试试"}
    return {"ok": True, "items": items}


# ---------------------------------------------------------------- 在线提取（不下载）

def bilibili_subtitles(bvid, cid):
    """B站字幕（CC字幕），直接在线拿文字，不下载视频"""
    try:
        with http_client() as c:
            r = c.get("https://api.bilibili.com/x/player/v2",
                      params={"bvid": bvid, "cid": cid},
                      headers={"Referer": "https://www.bilibili.com/"})
            data = r.json().get("data") or {}
            subs = ((data.get("subtitle") or {}).get("subtitles") or [])
            for s in subs:
                url = s.get("subtitle_url", "")
                if not url:
                    continue
                if url.startswith("//"):
                    url = "https:" + url
                jr = c.get(url)
                body = jr.json().get("body") or []
                text = "".join(x.get("content", "") for x in body)
                if text:
                    return text
    except Exception:
        pass
    return ""


def extract_bilibili(url, progress=None):
    """B站：在线提取（字幕 -> 简介）；没有就临时下载转写（自动删除）"""
    m = re.search(r"(BV[0-9A-Za-z]+)", url)
    if not m:
        raise RuntimeError("无法识别B站视频链接")
    bvid = m.group(1)
    info = bilibili_view(bvid)
    if progress:
        progress("正在在线提取（字幕/简介）...")
    text = ""
    if info.get("cid"):
        text = bilibili_subtitles(bvid, info["cid"])
    desc_recipe = ""
    if not text:
        desc_recipe = clean_text(info.get("desc", ""))
        if looks_like_recipe(desc_recipe):
            text = desc_recipe
    if not text and load_config().get("allow_temp_download"):
        if progress:
            progress("没有在线文字，临时下载转写（用完自动删除）...")
        text = temp_transcribe("https://www.bilibili.com/video/%s" % bvid, progress=progress)
    return {"title": info["title"], "author": info["author"], "url": url,
            "desc": info.get("desc", ""), "transcript": text, "source": "bilibili"}


# ---------------------------------------------------------------- 临时下载转写（不留文件）

def _ffmpeg_location():
    try:
        import imageio_ffmpeg
        return os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return None


def download_audio(url, out_dir, cookie=""):
    """用 yt-dlp 下载音频到临时目录，返回文件路径"""
    out_tpl = os.path.join(out_dir, "audio.%(ext)s")
    cmd = [sys.executable, "-m", "yt_dlp", "-f", "ba/b", "-o", out_tpl,
           "--no-playlist", "--no-warnings", "--no-check-certificate"]
    ff = _ffmpeg_location()
    if ff:
        cmd += ["--ffmpeg-location", ff]
    if cookie:
        cmd += ["--add-header", "Cookie: %s" % cookie]
    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, timeout=900)
    files = [f for f in os.listdir(out_dir) if f.startswith("audio.")]
    if files:
        return os.path.join(out_dir, files[0])
    # 音频流不可用，下载完整视频再抽音频
    cmd2 = [sys.executable, "-m", "yt_dlp", "-f", "bv*+ba/b", "-o", out_tpl,
            "--no-playlist", "--no-warnings", "--no-check-certificate"]
    if ff:
        cmd2 += ["--ffmpeg-location", ff]
    if cookie:
        cmd2 += ["--add-header", "Cookie: %s" % cookie]
    cmd2.append(url)
    proc = subprocess.run(cmd2, capture_output=True, timeout=900)
    files = [f for f in os.listdir(out_dir) if f.startswith("audio.")]
    if not files:
        raise RuntimeError(proc.stderr.decode("utf-8", "ignore")[-400:])
    return os.path.join(out_dir, files[0])


_WHISPER_MODEL = None
_WHISPER_LOCK = threading.Lock()


def get_whisper_model(model_dir):
    global _WHISPER_MODEL
    with _WHISPER_LOCK:
        if _WHISPER_MODEL is None:
            from faster_whisper import WhisperModel
            model_source = (model_dir or "small").strip()
            try:
                _WHISPER_MODEL = WhisperModel(model_source, device="cpu",
                                              compute_type="int8", cpu_threads=4)
            except Exception as exc:
                raise RuntimeError(
                    "无法准备本地语音模型。请检查网络，或在 config.json 的 "
                    "whisper_model_dir 中填写已下载的模型目录。"
                ) from exc
    return _WHISPER_MODEL


def transcribe(audio_path, model_dir, progress=None):
    model = get_whisper_model(model_dir)
    if progress:
        progress("正在转写语音（约1-3分钟）...")
    segments, _ = model.transcribe(audio_path, language="zh", beam_size=5,
                                   vad_filter=True, condition_on_previous_text=True)
    parts = []
    for seg in segments:
        parts.append(seg.text.strip())
        if progress:
            progress("转写中... %s" % seg.text.strip()[-30:])
    return "".join(parts)


def temp_transcribe(url, cookie="", progress=None):
    """临时下载 -> 转写 -> 自动删除临时文件，只返回文字"""
    tmp = tempfile.mkdtemp(prefix="cook_")
    try:
        audio = download_audio(url, tmp, cookie)
        if os.environ.get("CLOUD_MODE") == "1":
            return transcribe_remote(audio, progress)
        return transcribe(audio, load_config().get("whisper_model_dir", ""), progress)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def transcribe_remote(audio_path, progress=None):
    """云端模式：用 OpenAI 兼容语音识别接口转写（需要 API Key）"""
    cfg = load_config()
    # 转写服务与文本整理服务可以不同。例如 DeepSeek 可用于整理文本，
    # 而 gpt-4o-transcribe 需要使用提供音频转写的 OpenAI 兼容端点。
    key = (cfg.get("stt_api_key") or cfg.get("openai_api_key") or "").strip()
    if not key:
        raise RuntimeError(
            "云端模式转写需要支持音频转写的 API Key：请在环境变量或 config.json 中配置。")
    if progress:
        progress("正在用云端语音识别转写...")
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url=cfg.get("stt_base_url") or None)
    with open(audio_path, "rb") as f:
        resp = client.audio.transcriptions.create(
            model=cfg.get("stt_model", "gpt-4o-transcribe"),
            file=f,
            language="zh",
        )
    return getattr(resp, "text", "") or ""


# ---------------------------------------------------------------- 抖音提取

def douyin_video_id(url):
    m = re.search(r"/(?:video|shipin)/(\d+)", url)
    return m.group(1) if m else None


def fetch_page(url, ua=UA_SPIDER):
    headers = {"User-Agent": ua}
    cookie = load_config().get("douyin_cookie", "")
    if cookie and "douyin.com" in url:
        headers["Cookie"] = cookie
    with http_client() as c:
        r = c.get(url, headers=headers)
        return r.text


def extract_douyin(url, progress=None):
    """抖音：抓页面，尽量拿 AI 文稿；拿不到就返回标题+简介"""
    vid = douyin_video_id(url)
    if not vid:
        raise RuntimeError("无法识别抖音链接")
    video_url = "https://www.douyin.com/video/%s" % vid
    html = fetch_page(video_url)
    title_m = re.search(r"<title[^>]*>([^<]+)</title>", html)
    desc_m = re.search(r'name="description" content="([^"]*)"', html)
    title = clean_html(title_m.group(1)) if title_m else ""
    desc = clean_html(desc_m.group(1)) if desc_m else ""
    result = {
        "title": title.replace(" - 抖音", ""),
        "author": "",
        "date": "",
        "likes": "",
        "url": video_url,
        "desc": desc,
        "transcript": "",
        "source": "douyin",
    }
    # 从简介解析作者 / 发布日期 / 点赞数
    m_stat = re.search(r"[-\u2014\u2013]\s*([^-—–]{1,30}?)于(\d{8})发布在抖音，已经收获了([^，]+?)个喜欢", desc)
    if m_stat:
        result["author"] = m_stat.group(1).strip()
        d = m_stat.group(2)
        result["date"] = "%s-%s-%s" % (d[:4], d[4:6], d[6:8])
        result["likes"] = m_stat.group(3).strip()
    # 尝试相关视频页拿 AI 文稿
    try:
        shipin_html = fetch_page("https://www.douyin.com/shipin/%s" % vid)
        ais = (re.findall(r'data-e2e="ai-text">(.*?)</p>', shipin_html, re.S)
               or re.findall(r'"ai_text"\s*:\s*"([^"]+)"', shipin_html, re.S)
               or re.findall(r'data-e2e="ai-text">(.*?)</span>', shipin_html, re.S))
        if ais:
            result["transcript"] = clean_html(ais[0])
    except Exception:
        pass
    if not result["transcript"]:
        # 视频页里也可能带 AI 文稿
        ais = re.findall(r'data-e2e="ai-text">(.*?)</p>', html, re.S)
        if ais:
            result["transcript"] = clean_html(ais[0])
    # 没有 AI 文稿，但简介里本身就写着菜谱（部分视频把做法写在简介里）
    if not result["transcript"]:
        desc_recipe = strip_douyin_stats(desc)
        if looks_like_recipe(desc_recipe):
            result["transcript"] = clean_text(desc_recipe)
    # 抖音只走在线文字（AI文稿/简介），不下载不转写；拿不到就返回空，由前端给视频链接
    # 尝试从视频页的脚本数据里找作者
    author_m = re.search(r'"nickname":"([^"]+)"', html)
    if author_m:
        result["author"] = author_m.group(1)
    return result


def extract_url(url, progress=None):
    """识别链接（支持短链接/分享文案）后自动选择抖音/B站提取"""
    p = parse_video_input(url)
    if not p.get("ok"):
        raise RuntimeError(p.get("error", "链接识别失败"))
    if p["source"] == "douyin":
        return extract_douyin(p["url"], progress)
    return extract_bilibili(p["url"], progress)


# ---------------------------------------------------------------- 整理模板

INGREDIENTS = [
    # 主料：肉类
    ("五花肉", "主料"), ("前腿肉", "主料"), ("前甲肉", "主料"), ("梅花肉", "主料"),
    ("里脊肉", "主料"), ("里脊", "主料"), ("瘦肉", "主料"), ("猪肉", "主料"),
    ("牛肉", "主料"), ("羊肉", "主料"), ("鸡肉", "主料"), ("鸭肉", "主料"),
    ("排骨", "主料"), ("肉末", "主料"), ("肉沫", "主料"), ("肉片", "主料"),
    ("肉丝", "主料"), ("腊肉", "主料"), ("香肠", "主料"), ("火腿肠", "主料"),
    ("火腿", "主料"), ("培根", "主料"), ("肥肉", "主料"), ("肥膘", "主料"),
    ("虾仁", "主料"), ("虾", "主料"), ("鱿鱼", "主料"), ("花甲", "主料"),
    ("蟹", "主料"), ("鱼", "主料"), ("带鱼", "主料"), ("黄鱼", "主料"),
    # 主料：蛋
    ("鸡蛋", "主料"), ("鸭蛋", "主料"), ("皮蛋", "主料"), ("鹌鹑蛋", "主料"),
    # 主食
    ("米饭", "主食"), ("大米", "主食"), ("面条", "主食"), ("粉丝", "主食"),
    ("粉条", "主食"), ("年糕", "主食"), ("馒头", "主食"), ("饺子", "主食"),
    ("馄饨", "主食"),
    # 配料：蔬菜
    ("螺丝椒", "配料"), ("青椒", "配料"), ("辣椒", "配料"), ("小米辣", "配料"),
    ("小米椒", "配料"), ("尖椒", "配料"), ("杭椒", "配料"), ("二荆条", "配料"),
    ("泡椒", "配料"), ("红椒", "配料"), ("彩椒", "配料"), ("土豆", "配料"),
    ("番茄", "配料"), ("西红柿", "配料"), ("茄子", "配料"), ("豆角", "配料"),
    ("四季豆", "配料"), ("荷兰豆", "配料"), ("西兰花", "配料"), ("花菜", "配料"),
    ("菜花", "配料"), ("白菜", "配料"), ("娃娃菜", "配料"), ("包菜", "配料"),
    ("卷心菜", "配料"), ("生菜", "配料"), ("油麦菜", "配料"), ("菠菜", "配料"),
    ("空心菜", "配料"), ("茼蒿", "配料"), ("芹菜", "配料"), ("韭菜", "配料"),
    ("蒜苔", "配料"), ("蒜薹", "配料"), ("蒜苗", "配料"), ("大蒜叶", "配料"),
    ("洋葱", "配料"), ("大葱", "配料"), ("小葱", "配料"), ("香葱", "配料"),
    ("葱", "配料"), ("生姜", "配料"), ("姜", "配料"), ("蒜子", "配料"),
    ("大蒜", "配料"), ("蒜头", "配料"), ("蒜末", "配料"), ("蒜", "配料"),
    ("胡萝卜", "配料"), ("白萝卜", "配料"), ("萝卜", "配料"), ("黄瓜", "配料"),
    ("冬瓜", "配料"), ("南瓜", "配料"), ("丝瓜", "配料"), ("苦瓜", "配料"),
    ("西葫芦", "配料"), ("玉米", "配料"), ("豌豆", "配料"), ("毛豆", "配料"),
    ("黄豆", "配料"), ("豆芽", "配料"),
    # 配料：菌菇
    ("香菇", "配料"), ("蘑菇", "配料"), ("杏鲍菇", "配料"), ("金针菇", "配料"),
    ("木耳", "配料"), ("银耳", "配料"), ("春笋", "配料"), ("冬笋", "配料"),
    ("笋", "配料"), ("莴笋", "配料"),
    # 配料：豆制品
    ("豆腐", "配料"), ("豆干", "配料"), ("豆腐干", "配料"), ("腐竹", "配料"),
    ("豆皮", "配料"), ("千张", "配料"), ("豆豉", "配料"), ("黄豆酱", "配料"),
    # 调料
    ("盐", "调料"), ("生抽", "调料"), ("老抽", "调料"), ("酱油", "调料"),
    ("蒸鱼豉油", "调料"), ("蚝油", "调料"), ("料酒", "调料"), ("黄酒", "调料"),
    ("糯米酒", "调料"), ("白酒", "调料"), ("醋", "调料"), ("陈醋", "调料"),
    ("香醋", "调料"), ("白糖", "调料"), ("冰糖", "调料"), ("味精", "调料"),
    ("鸡精", "调料"), ("鸡粉", "调料"), ("胡椒粉", "调料"), ("白胡椒粉", "调料"),
    ("黑胡椒", "调料"), ("十三香", "调料"), ("五香粉", "调料"), ("孜然", "调料"),
    ("辣椒面", "调料"), ("辣椒粉", "调料"), ("豆瓣酱", "调料"), ("甜面酱", "调料"),
    ("番茄酱", "调料"), ("蒜蓉辣酱", "调料"), ("豆豉酱", "调料"), ("芝麻油", "调料"),
    ("香油", "调料"), ("食用油", "调料"), ("菜籽油", "调料"), ("花生油", "调料"),
    ("猪油", "调料"), ("玉米淀粉", "调料"), ("淀粉", "调料"), ("生粉", "调料"),
    ("面粉", "调料"), ("芝麻", "调料"), ("花椒", "调料"), ("八角", "调料"),
    ("桂皮", "调料"), ("香叶", "调料"), ("干辣椒", "调料"), ("水淀粉", "调料"),
    ("高汤", "调料"), ("清水", "调料"),
]

_CN_NUM = "一二两三四五六七八九十半"
_UNIT = "个颗根把勺克斤两块瓣段片条碗份粒滴片包盒只瓶袋"

# 数字/量词，尽量把「三个螺丝椒」「五花肉300克」「两勺盐」都抓出来
_AMOUNT_NUM = r"(?:[0-9]+|[一二两三四五六七八九十半]+)"
_AMOUNT_UNIT = r"(?:个|颗|根|把|勺|汤匙|茶匙|克|斤|两|块|瓣|段|条|碗|份|粒|滴|片|包|盒|只|瓶|袋)"


def extract_ingredients(text):
    """从文字里找出食材，尽量带数量"""
    found = []
    spans = []  # 已匹配的区间，防止 葱/大葱、蒜/大蒜 重复
    for name, cat in sorted(INGREDIENTS, key=lambda x: -len(x[0])):
        m = re.search(re.escape(name), text)
        if not m:
            continue
        start, end = m.start(), m.end()
        if any(s <= start < e or s < end <= e for s, e, *_ in spans):
            continue
        amount = ""
        # 名字后面跟数量：五花肉300克 / 螺丝椒三个
        am = re.search(re.escape(name) + r"[的]?[\s]?(?:约|大概|差不多)?("
                       + _AMOUNT_NUM + r")(?:到" + _AMOUNT_NUM + r")?\s*("
                       + _AMOUNT_UNIT + r")", text)
        if not am:
            # 数量在名字前面：三个鸡蛋 / 300克五花肉 / 三个这种大小的螺丝椒
            am = re.search(r"(?:约|大概)?("
                           + _AMOUNT_NUM + r")(?:到" + _AMOUNT_NUM + r")?\s*("
                           + _AMOUNT_UNIT + r")"
                           + r"(?:这种大小的|左右|大小|新鲜|嫩|老|大|小|的|个)?\s*"
                           + re.escape(name),
                           text)
        if am:
            amount = "%s%s" % (am.group(1), am.group(2))
        if not amount:
            # 无数字的少量表达：少许 / 适量 / 一点点 / 一点
            sm = re.search(r"(少许|适量|一点点|一点)\s*[的]?\s*" + re.escape(name), text)
            if sm:
                amount = sm.group(1)
        spans.append((start, end, name))
        found.append({"name": name, "amount": amount, "cat": cat})
    # 去掉冗余表述：具体部位肉出现时，去掉泛指的肉；具体辣椒/葱/蒜同理
    names = [it["name"] for it in found]
    if any(n in names for n in ("前腿肉", "前甲肉", "五花肉", "梅花肉", "里脊", "里脊肉",
                                "排骨", "腊肉", "香肠", "火腿肠", "火腿", "培根",
                                "牛肉", "羊肉", "鸡肉", "鸭肉", "虾仁", "虾", "鱼")):
        drop = {"瘦肉", "肥肉", "肥膘", "肉片", "肉丝", "肉末", "肉沫", "猪肉", "肉"}
        found = [it for it in found if it["name"] not in drop]
    if any(n in names for n in ("螺丝椒", "杭椒", "尖椒", "二荆条", "彩椒", "青椒", "小米辣")):
        found = [it for it in found if it["name"] != "辣椒"]
    if any(n in names for n in ("大葱", "小葱", "香葱")):
        found = [it for it in found if it["name"] != "葱"]
    if any(n in names for n in ("蒜子", "大蒜", "蒜头")):
        found = [it for it in found if it["name"] not in ("蒜", "蒜末")]
    # 归组，保持出现顺序
    groups = {"主料": [], "配料": [], "调料": [], "主食": []}
    for it in found:
        cat = it["cat"]
        groups.setdefault(cat, []).append(it)
    # 「吃三碗米饭」这类口播不算食材
    if re.search(r"吃[一二两三四五六七八九十\d]+碗米饭", text):
        groups["主食"] = [it for it in groups.get("主食", []) if it["name"] != "米饭"]
    return groups


# 强步骤词：一般出现在一句话开头，表示新一步
_STRONG_START = (
    "首先|第一步|接下来|下一步|然后|接着|最后|"
    "先把|再把|再下|再放|再倒|再少|再起|再入|"
    "起锅|热锅|锅烧|烧热|把锅|锅热|油热|"
    "下锅|下入|倒入|加入|放入|放进|倒进|下油|倒油|放油|"
    "盛出|捞出|出锅|开火|关火|大火|小火|转大火|转小火|"
    "翻炒|炒香|炒至|炒到|回锅|"
    "准备|配料|做法|处理"
)
_STEP_STARTER = re.compile(_STRONG_START)
_INTRO_OUTRO = re.compile(
    r"收藏好|学会了吗|学会了吧|毫无保留|天花板|分享给|快去|关注|点赞|评论|转发|"
    r"三碗米饭|这一口|爽晕|记得收藏|干饭|香迷糊|别忘|快试试|给我点|"
    r"今天把这个|毫无保留的分享|你学会了吗"
)
_FILLER_HEAD = re.compile(
    r"^(?:然后|接着|再|接下来|下一步|首先|先把|我们先把|我们给|我们再把|我们再来)?[，,：:]*"
)


def _is_new_step(chunk):
    """判断一个小句是否是新步骤的开头"""
    chunk = chunk.strip("，。！？； \n")
    if not chunk:
        return False
    if _STEP_STARTER.match(chunk):
        return True
    # 强词出现在前 10 个字内也算（如「这个肥肉呢，我们是直接下锅炒的」）
    head = chunk[:10]
    return bool(re.search(_STRONG_START, head))


def split_steps(text):
    """把口播文字切成步骤，尽量接近人工模板的分步"""
    text = (text or "").strip()
    if not text:
        return []
    # 情况1：文字里已经有序号步骤
    lines = [l.strip() for l in re.split(r"[\n\r]+", text) if l.strip()]
    numbered = [l for l in lines if re.match(r"^\s*(?:步骤)?\s*[0-9一二三四五六七八九十]+[\.、．:]", l)]
    if len(numbered) >= 2:
        steps = [re.sub(r"^\s*(?:步骤)?\s*[0-9一二三四五六七八九十]+[\.、．:]\s*", "", l)
                 for l in numbered]
        return [s for s in steps if len(s) >= 4][:18]

    # 情况2：有标点，按小句分组
    if re.search(r"[。！？；]", text):
        chunks = [c.strip() for c in re.split(r"[。！？；，,\n\r]+", text) if len(c.strip()) >= 3]
        steps = []  # 每项 (文本, 是否新步骤)
        for ch in chunks:
            if _INTRO_OUTRO.search(ch) and len(ch) < 45:
                continue  # 营销开头/结尾直接丢掉
            if _is_new_step(ch):
                steps.append([ch, True])
            elif steps:
                steps[-1][0] += ch
            else:
                steps.append([ch, False])
        # 短的新步骤标题并入下一步（向前合并），而不是向后吞内容
        merged = []
        i = 0
        while i < len(steps):
            cur, is_new = steps[i]
            if is_new and len(cur) < 30 and i + 1 < len(steps):
                steps[i + 1][0] = cur + steps[i + 1][0]
                i += 1
                continue
            merged.append(cur)
            i += 1
        steps = merged
    else:
        # 情况3：没有标点（whisper 常见），按强步骤词切
        matches = list(re.finditer(_STRONG_START, text))
        if len(matches) < 2:
            return [text] if len(text) >= 8 else []
        cuts = [0]
        for m in matches:
            if m.start() - cuts[-1] > 18:
                cuts.append(m.start())
        cuts.append(len(text))
        steps = []
        for i in range(len(cuts) - 1):
            s = text[cuts[i]:cuts[i + 1]].strip("，。！？； \n")
            if s and not (_INTRO_OUTRO.search(s) and len(s) < 45):
                steps.append(s)

    # 去掉营销废话、开头连接词
    cleaned = []
    for s in steps:
        s = _FILLER_HEAD.sub("", s)
        s = s.strip("，。！？； \n")
        if not s:
            continue
        if _INTRO_OUTRO.search(s) and len(s) < 45:
            continue
        cleaned.append(s)
    # 尾部悬挂短语清理（如「这个肥肉呢」挂在上一句尾）
    cleaned = [re.sub(r"(?:这个|那个)[^，。！？]{0,4}呢$", "", s).strip("，。！？； ") or s
               for s in cleaned]
    # 同标题的相邻小步骤合并（备菜1+备菜2、煸辣椒前半+后半）
    final = []
    titles_now = [_step_title(s) for s in cleaned]
    for s, t in zip(cleaned, titles_now):
        if (final and final[-1][1] == t and len(final[-1][0]) + len(s) < 220):
            final[-1][0] += s
        else:
            final.append([s, t])
    final = [s for s, _ in final]
    # 仍然太碎的合并一次
    merged2 = []
    for s in final:
        if merged2 and len(s) < 26 and len(merged2[-1]) + len(s) < 200:
            merged2[-1] += s
        else:
            merged2.append(s)
    return [s for s in merged2 if len(s) >= 8][:18]


def _step_title(s):
    """给步骤起个短标题（如：处理肉 / 煎鸡蛋 / 煸辣椒）"""
    for kw, label in (
        ("准备", "备菜"),
        ("配料", "备菜"),
        ("剁碎", "备菜"),
        ("打入", "备菜"),
        ("满个味", "腌制"),
        ("码味", "腌制"),
        ("上浆", "腌制"),
        ("腌", "腌制"),
        ("前甲肉", "处理肉"),
        ("前腿肉", "处理肉"),
        ("肉皮", "处理肉"),
        ("肥肉", "煸肥肉"),
        ("肥膘", "煸肥肉"),
        ("五花肉", "煸五花肉"),
        ("瘦肉", "滑肉"),
        ("肉丝", "滑肉"),
        ("肉片", "滑肉"),
        ("牛肉", "滑肉"),
        ("青椒", "合炒"),
        ("回锅", "合炒"),
        ("翻炒", "合炒"),
        ("辣椒", "煸辣椒"),
        ("鸡蛋", "煎鸡蛋"),
        ("出锅", "合炒"),
        ("切", "处理肉"),
        ("洗", "处理肉"),
        ("刮", "处理肉"),
    ):
        if kw in s:
            return label
    m = re.match(r"([煎炒煸蒸煮炸腌切洗调制炖烧拌卤焖汆焯滑溜])(\S{0,5})", s)
    if m:
        return m.group(1) + m.group(2)
    return s[:6]


def extract_tips(text):
    tips = []
    _TIP_KEY = re.compile(
        r"一定要|千万|记住|注意|不要|不用|千万别|容易|才能|才会|更香|更嫩|更脆|更鲜|"
        r"更入味|关键|窍门|秘诀|小贴士|技巧|切记|最好|别忘|小心|火候|口感|重点|讲究|"
        r"比较吃盐|水汽|锅气|必须先|要先|最重要"
    )
    _STEP_HEAD = re.compile(r"^(首先|接下来|下一步|然后|接着|再|先把|我们先把|"
                            r"我们选择|下饭菜|这道菜|最后把|最后|起锅|热锅|下锅|下入|倒入|加入|放入|"
                            r"这个肥肉|这个瘦肉|这个辣椒)")
    # 有标点：按句子 -> 按小句抽关键句
    sentences = [s.strip() for s in re.split(r"[。！？；\n]+", text or "") if s.strip()]
    for sent in sentences:
        if _INTRO_OUTRO.search(sent):
            continue
        clauses = [c.strip() for c in re.split(r"[，,]+", sent) if c.strip()]
        hit = [c for c in clauses if _TIP_KEY.search(c) and not _STEP_HEAD.match(c)]
        if not hit:
            continue
        t = "，".join(hit)
        t = re.sub(r"^(?:然后|接着|再|接下来|下一步|首先)[，,]?", "", t)
        t = t.strip("，。！？ ")
        if re.match(r"^(这样|那样|这个|那个|总之)", t):
            continue
        if 8 <= len(t) <= 90 and t not in tips:
            tips.append(t)
        if len(tips) >= 6:
            break
    # 没有标点：围绕关键词截一段
    if not tips:
        for m in _TIP_KEY.finditer(text or ""):
            s = max(0, m.start() - 16)
            e = min(len(text), m.end() + 30)
            t = text[s:e].strip("，。！？ \n")
            if len(t) >= 8 and not _INTRO_OUTRO.search(t) and t not in tips:
                tips.append(t)
            if len(tips) >= 6:
                break
    # 去重：按前 12 个字去重
    uniq, seen = [], set()
    for t in tips:
        key = t[:12]
        if key not in seen:
            seen.add(key)
            uniq.append(t)
    return uniq


def organize(text, title="", desc=""):
    """把提取到的文字整理成食材+步骤+技巧"""
    text = clean_text(text)
    full = text
    if desc:
        full = text + "。" + clean_text(desc)
    groups = extract_ingredients(full)
    steps = split_steps(text or clean_text(desc))
    tips = extract_tips(full)
    titles = [_step_title(s) for s in steps]
    return {
        "ingredients": groups,
        "steps": steps,
        "step_titles": titles,
        "tips": tips,
        "raw_text": text,
    }


# ---------------------------------------------------------------- 可选 LLM 整理

def organize_with_llm(text, title="", desc=""):
    cfg = load_config()
    key = cfg.get("openai_api_key", "").strip()
    if not key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=cfg.get("openai_base_url") or None)
        prompt = (
            "你是专业菜谱整理助手。下面是一段做菜视频的口播文字（可能夹杂口语废话）。\n"
            "请整理成 JSON，格式："
            '{"ingredients":[{"name":"食材名","amount":"数量(没有就空)","cat":"主料/配料/调料"}],'
            '"steps":["第1步...","第2步..."],"tips":["关键技巧..."]}\n'
            "要求：步骤完整、顺序正确、去掉废话；食材归类准确；只输出 JSON。\n\n"
            "标题：" + (title or "") + "\n简介：" + (desc or "") + "\n口播文字：\n" + text
        )
        resp = client.chat.completions.create(
            model=cfg.get("llm_model", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = resp.choices[0].message.content.strip()
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
        data = json.loads(content)
        groups = {"主料": [], "配料": [], "调料": [], "主食": []}
        for it in data.get("ingredients", []):
            cat = it.get("cat", "配料")
            groups.setdefault(cat, []).append({"name": it.get("name", ""), "amount": it.get("amount", ""), "cat": cat})
        return {
            "ingredients": groups,
            "steps": data.get("steps", []),
            "tips": data.get("tips", []),
            "raw_text": text,
            "by_llm": True,
        }
    except Exception:
        return None


# ---------------------------------------------------------------- 模板输出

def render_markdown(meta, organized):
    lines = []
    lines.append("# %s" % (meta.get("title") or "做菜教程"))
    lines.append("")
    lines.append("## 视频")
    lines.append("")
    lines.append(meta.get("title", ""))
    lines.append("")
    lines.append(meta.get("url", ""))
    lines.append("")
    if meta.get("source") == "douyin":
        lines.append("复制此链接，打开Dou音搜索，直接观看视频！")
        lines.append("")
    meta_parts = []
    if meta.get("author"):
        meta_parts.append("作者：%s" % meta["author"])
    if meta.get("date"):
        meta_parts.append("发布：%s" % meta["date"])
    if meta.get("likes"):
        meta_parts.append("点赞：%s" % meta["likes"])
    if not meta_parts and meta.get("source"):
        meta_parts.append("来源：%s" % meta["source"])
    if meta_parts:
        lines.append(" ｜ ".join(meta_parts))
        lines.append("")
    lines.append("---")
    lines.append("")
    groups = organized.get("ingredients", {})
    cat_names = [("主料", "主料"), ("配料", "配料"), ("调料", "调料"), ("主食", "主食")]
    has = {k: v for k, v in groups.items() if v}
    if has:
        lines.append("## 食材清单")
        lines.append("")
        for cat, _ in cat_names:
            if groups.get(cat):
                lines.append("**%s**" % cat)
                for it in groups[cat]:
                    amount = (" %s" % it["amount"]) if it.get("amount") else ""
                    lines.append("- %s%s" % (it["name"], amount))
                lines.append("")
    steps = organized.get("steps", [])
    if steps:
        lines.append("## 做法步骤")
        lines.append("")
        titles = organized.get("step_titles") or []
        for i, s in enumerate(steps, 1):
            if isinstance(s, dict):
                why = s.get("why", [])
                s = s.get("text", "")
            else:
                why = []
            t = titles[i - 1] if i - 1 < len(titles) else ""
            if t:
                lines.append("%d. **%s**：%s" % (i, t, s))
            else:
                lines.append("%d. %s" % (i, s))
            for w in why[:2]:
                lines.append("   - 为什么：%s" % w)
        lines.append("")
    tips = organized.get("tips", [])
    if tips:
        lines.append("## 关键技巧")
        lines.append("")
        for t in tips:
            lines.append("- %s" % t)
        lines.append("")
    raw = organized.get("raw_text", "")
    if raw:
        lines.append("---")
        lines.append("")
        lines.append("## 视频文字原文")
        lines.append("")
        lines.append(raw)
        lines.append("")
    return "\n".join(lines)
