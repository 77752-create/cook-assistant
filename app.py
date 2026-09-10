# -*- coding: utf-8 -*-
"""做菜助手 - 本地 Web 服务（菜谱存数据库，支持手机局域网访问）"""
import json
import hashlib
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
import uuid
import webbrowser
from contextlib import contextmanager

from flask import Flask, jsonify, request, send_from_directory

import core
import knowledge

app = Flask(__name__, static_folder="static", static_url_path="/static")

JOBS = {}
JOBS_LOCK = threading.Lock()
LOCK_TOKENS = {}
LOCK_TOKENS_LOCK = threading.Lock()
LOCK_SALT = "cook-assistant-pin-v1"
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "做菜助手.log")
DB_PATH = os.environ.get("COOK_DB") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "recipes.db")
SENSITIVE_CONFIG_KEYS = {"openai_api_key", "douyin_cookie", "stt_api_key"}


def _safe_config(cfg):
    """Never send credentials to a browser, even after settings are unlocked."""
    safe = {k: v for k, v in cfg.items() if k not in SENSITIVE_CONFIG_KEYS}
    safe["openai_key_configured"] = bool(cfg.get("openai_api_key", "").strip())
    return safe


@app.before_request
def require_app_password():
    """Optional whole-site guard for a personal public deployment."""
    # Health checks reveal no application or network details.
    if request.path == "/health":
        return None
    password = os.environ.get("APP_PASSWORD", "")
    if not password:
        return None
    auth = request.authorization
    if auth and auth.username == "cook" and secrets.compare_digest(auth.password or "", password):
        return None
    return ("需要访问密码。", 401, {"WWW-Authenticate": 'Basic realm="Cook Assistant"'})


@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _init_db():
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                video_url TEXT,
                source TEXT,
                author TEXT,
                date TEXT,
                likes TEXT,
                markdown TEXT,
                ingredients TEXT,
                steps TEXT,
                tips TEXT,
                created_at TEXT
            )
        """)


_init_db()


def _run_job(job_id, fn):
    def worker():
        try:
            result = fn()
            with JOBS_LOCK:
                JOBS[job_id]["status"] = "done"
                JOBS[job_id]["result"] = result
        except Exception:
            error_id = uuid.uuid4().hex[:12]
            app.logger.exception("Background job failed id=%s error_id=%s", job_id, error_id)
            with JOBS_LOCK:
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["error"] = "任务失败，请稍后重试"
                JOBS[job_id]["error_id"] = error_id
    t = threading.Thread(target=worker, daemon=True)
    t.start()


def _new_job(fn):
    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "running", "stage": "开始...", "result": None, "error": ""}
    _run_job(job_id, fn)
    return job_id


def _lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


def _log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def _pin_hash(pin):
    return hashlib.sha256((LOCK_SALT + str(pin)).encode()).hexdigest()


def _lock_ok():
    cfg = core.load_config()
    if not cfg.get("settings_pin_hash", ""):
        return True
    tok = request.headers.get("X-Lock-Token", "")
    with LOCK_TOKENS_LOCK:
        exp = LOCK_TOKENS.get(tok)
        if exp and exp > time.time():
            return True
        if tok in LOCK_TOKENS:
            del LOCK_TOKENS[tok]
    return False


@app.route("/api/lock/status", methods=["GET"])
def api_lock_status():
    cfg = core.load_config()
    return jsonify({"ok": True, "pin_set": bool(cfg.get("settings_pin_hash", ""))})


@app.route("/api/lock/verify", methods=["POST"])
def api_lock_verify():
    data = request.get_json(silent=True) or {}
    cfg = core.load_config()
    h = cfg.get("settings_pin_hash", "")
    if not h:
        return jsonify({"ok": True, "token": "", "pin_set": False})
    if _pin_hash(str(data.get("pin", ""))) == h:
        tok = secrets.token_hex(16)
        with LOCK_TOKENS_LOCK:
            LOCK_TOKENS[tok] = time.time() + 86400
        return jsonify({"ok": True, "token": tok, "pin_set": True})
    return jsonify({"ok": False, "error": "密码不对"})


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


@app.route("/api/info", methods=["GET"])
def api_info():
    port = int(os.environ.get("COOK_PORT", "8765"))
    return jsonify({"ok": True,
                    "lan_urls": ["http://%s:%d" % (ip, port) for ip in _lan_ips()],
                    "local_url": "http://127.0.0.1:%d" % port})


@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.get_json(silent=True) or {}
    keyword = (data.get("keyword") or "").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "请输入菜名"})
    return jsonify(core.search(keyword))


@app.route("/api/job/extract", methods=["POST"])
def api_job_extract():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "缺少链接"})

    def fn():
        def progress(msg):
            with JOBS_LOCK:
                JOBS[job_id]["stage"] = msg
        return core.extract_url(url, progress)

    job_id = _new_job(fn)
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/job/<job_id>", methods=["GET"])
def api_job_status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"ok": False, "error": "任务不存在"})
        return jsonify({"ok": True, "status": job["status"], "stage": job["stage"],
                        "error": job.get("error", ""), "error_id": job.get("error_id", ""),
                        "result": job.get("result")})


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json(silent=True) or {}
    result = data.get("result") or {}
    url = data.get("url") or result.get("url") or ""
    title = result.get("title", "")
    author = result.get("author", "")
    source = result.get("source", "")
    date = result.get("date", "")
    likes = result.get("likes", "")
    desc = result.get("desc", "")
    transcript = result.get("transcript", "")
    if not transcript:
        return jsonify({"ok": False, "error": "没有可用的视频文字，无法生成模板"})

    note = ""
    if core.load_config().get("openai_api_key", "").strip():
        organized = core.organize_with_llm(transcript, title, desc)
        if not organized:
            note = "AI整理失败（请检查 config.json 或环境变量），已自动改用本地规则"
    else:
        organized = None
    if not organized:
        organized = core.organize(transcript, title, desc)
    organized = knowledge.attach_reasons(organized)
    meta = {"title": title, "url": url, "author": author, "source": source,
            "date": date, "likes": likes}
    md = core.render_markdown(meta, organized)
    return jsonify({"ok": True, "meta": meta, "organized": organized,
                    "markdown": md, "note": note})


@app.route("/api/recipes", methods=["GET", "POST"])
def api_recipes():
    if request.method == "GET":
        with _db() as conn:
            rows = conn.execute(
                "SELECT id, title, video_url, source, author, date, likes, created_at "
                "FROM recipes ORDER BY id DESC").fetchall()
        return jsonify({"ok": True, "items": [dict(r) for r in rows]})

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip() or "未命名菜谱"
    organized = data.get("organized") or {}
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO recipes (title, video_url, source, author, date, likes, "
            "markdown, ingredients, steps, tips, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (title,
             data.get("url") or "",
             data.get("source") or "",
             data.get("author") or "",
             data.get("date") or "",
             data.get("likes") or "",
             data.get("markdown") or "",
             json.dumps(organized.get("ingredients", {}), ensure_ascii=False),
             json.dumps(organized.get("steps", []), ensure_ascii=False),
             json.dumps(organized.get("tips", []), ensure_ascii=False),
             time.strftime("%Y-%m-%d %H:%M")))
        rid = cur.lastrowid
    return jsonify({"ok": True, "id": rid})


@app.route("/api/recipes/<int:rid>", methods=["GET", "DELETE"])
def api_recipe(rid):
    if request.method == "DELETE":
        with _db() as conn:
            cur = conn.execute("DELETE FROM recipes WHERE id=?", (rid,))
        if cur.rowcount == 0:
            return jsonify({"ok": False, "error": "菜谱不存在"}), 404
        return jsonify({"ok": True})
    with _db() as conn:
        row = conn.execute("SELECT * FROM recipes WHERE id=?", (rid,)).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "菜谱不存在"})
    d = dict(row)
    for k in ("ingredients", "steps", "tips"):
        try:
            d[k] = json.loads(d[k] or "[]")
        except Exception:
            d[k] = {} if k == "ingredients" else []
    return jsonify({"ok": True, "recipe": d})


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        if not _lock_ok():
            return jsonify({"ok": False, "error": "设置已加锁，请先解锁"}), 403
        return jsonify({"ok": True, "config": _safe_config(core.load_config())})
    if not _lock_ok():
        return jsonify({"ok": False, "error": "设置已加锁，请输入访问密码后再修改"}), 403
    data = request.get_json(silent=True) or {}
    cfg = core.load_config()
    if "settings_pin" in data:
        new_pin = str(data.pop("settings_pin", "") or "").strip()
        if new_pin:
            if len(new_pin) < 4:
                return jsonify({"ok": False, "error": "访问密码至少 4 位"})
            cfg["settings_pin_hash"] = _pin_hash(new_pin)
        else:
            cfg["settings_pin_hash"] = ""
    for k in ("openai_api_key", "openai_base_url", "llm_model", "stt_model",
              "douyin_cookie", "allow_temp_download", "use_mediacrawler",
              "whisper_model_dir"):
        if k in data:
            v = data[k]
            cfg[k] = bool(v) if k in ("allow_temp_download", "use_mediacrawler") else (v or "").strip()
    core.save_config(cfg)
    return jsonify({"ok": True, "config": _safe_config(cfg)})


@app.route("/api/recipes/export", methods=["GET"])
def api_export():
    with _db() as conn:
        rows = conn.execute("SELECT * FROM recipes ORDER BY id").fetchall()
    return jsonify({"ok": True, "recipes": [dict(r) for r in rows]})


@app.route("/api/recipes/import", methods=["POST"])
def api_import():
    data = request.get_json(silent=True) or {}
    recipes = data.get("recipes") or []
    n = 0
    with _db() as conn:
        for r in recipes:
            conn.execute(
                "INSERT INTO recipes (title, video_url, source, author, date, likes, "
                "markdown, ingredients, steps, tips, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (r.get("title", ""), r.get("video_url", ""), r.get("source", ""),
                 r.get("author", ""), r.get("date", ""), r.get("likes", ""),
                 r.get("markdown", ""),
                 r.get("ingredients", "{}") if isinstance(r.get("ingredients"), str) else json.dumps(r.get("ingredients", {}), ensure_ascii=False),
                 r.get("steps", "[]") if isinstance(r.get("steps"), str) else json.dumps(r.get("steps", []), ensure_ascii=False),
                 r.get("tips", "[]") if isinstance(r.get("tips"), str) else json.dumps(r.get("tips", []), ensure_ascii=False),
                 r.get("created_at", time.strftime("%Y-%m-%d %H:%M"))))
            n += 1
    return jsonify({"ok": True, "imported": n})


@app.errorhandler(404)
@app.errorhandler(405)
def api_not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "接口不存在或请求方式不对"}), 404
    return e


@app.errorhandler(405)
def api_method_not_allowed(e):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "请求方式不支持"}), 405
    return e


@app.errorhandler(Exception)
def api_error(e):
    if request.path.startswith("/api/"):
        error_id = uuid.uuid4().hex[:12]
        app.logger.exception("Unhandled API error id=%s path=%s", error_id, request.path)
        return jsonify({
            "ok": False,
            "error": "服务暂时不可用，请稍后重试",
            "error_id": error_id,
        }), 500
    raise e


if __name__ == "__main__":
    port = int(os.environ.get("COOK_PORT", "8765"))
    local_url = "http://127.0.0.1:%d" % port
    threading.Timer(1.2, lambda: webbrowser.open(local_url)).start()
    _log("做菜助手启动：%s" % local_url)
    for ip in _lan_ips():
        _log("手机访问：http://%s:%d" % (ip, port))
    print("=" * 56)
    print("做菜助手已启动")
    print("本机访问：" + local_url)
    for ip in _lan_ips():
        print("手机访问（同一WiFi）：http://%s:%d" % (ip, port))
    print("手机打不开时，检查 Windows 防火墙是否放行 Python")
    print("关闭本窗口即可退出服务。")
    print("=" * 56)
    try:
        app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
    except OSError as e:
        if "address already in use" in str(e).lower() or "10048" in str(e):
            _log("端口 %d 已被占用" % port)
            print("端口 %d 已被占用：做菜助手可能已经启动。" % port)
            print("请直接访问：" + local_url)
            input("按回车键关闭本窗口...")
        else:
            raise
