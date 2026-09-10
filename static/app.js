const view = document.getElementById("view");
const state = { current: null, pendingJob: null };
let pollTimer = null;

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function asJson(resp) {
  const text = await resp.text();
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error("服务返回了异常内容，请重启「启动做菜助手.bat」后重试");
  }
}

async function getJson(url) {
  return fetch(url).then(asJson);
}

async function postJson(url, body) {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  }).then(asJson);
}

function lockToken() {
  return sessionStorage.getItem("cook_lock_token") || "";
}

async function lockedGet(url) {
  return fetch(url, { headers: { "X-Lock-Token": lockToken() } }).then(asJson);
}

async function lockedPost(url, body) {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Lock-Token": lockToken() },
    body: JSON.stringify(body || {}),
  }).then(asJson);
}

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), 2600);
}

function statusHTML(msg, type) {
  return `<div class="status ${type}">${esc(msg)}</div>`;
}

// ---------------- 路由 ----------------

function parseHash() {
  const h = location.hash.replace(/^#\/?/, "") || "search";
  const [name, query] = h.split("?");
  return { name, params: new URLSearchParams(query || "") };
}

async function route() {
  const { name, params } = parseHash();
  document.querySelectorAll(".tab-item").forEach((a) =>
    a.classList.toggle("active", a.dataset.nav === name));
  view.innerHTML = "";
  view.scrollTop = 0;
  window.scrollTo(0, 0);
  try {
    if (name === "recipes") return renderRecipes();
    if (name === "settings") return renderSettings();
    if (name === "detail") return renderDetail(params);
    return renderSearch();
  } catch (e) {
    view.innerHTML = statusHTML("出错了：" + e.message, "error");
  }
}

window.addEventListener("hashchange", route);

// ---------------- 搜索 ----------------

async function renderSearch() {
  view.innerHTML = `
    <h1 class="page-title anim-in">找一道菜</h1>
    <p class="lead">输入菜名，自动从抖音和 B 站找做法视频并提取文字。</p>
    <div class="search-box anim-in" style="--i:1">
      <input id="keyword" type="text" placeholder="例如：农家一碗香 / 鱼香肉丝">
      <button id="btn-search" class="btn primary">搜索</button>
    </div>
    <div id="search-status"></div>
    <details class="paste-box anim-in" style="--i:2">
      <summary>或者直接粘贴抖音 / B 站视频链接</summary>
      <div class="field"><input id="paste-url" type="text" placeholder="https://v.douyin.com/... 或 B 站链接"></div>
      <button id="btn-paste" class="btn">提取链接</button>
    </details>
    <div id="results"></div>`;

  $bind("btn-search", "click", () => doSearch($val("keyword")));
  $bind("keyword", "keydown", (e) => { if (e.key === "Enter") doSearch($val("keyword")); });
  $bind("btn-paste", "click", () => {
    const u = $val("paste-url");
    if (u) startExtract(u);
  });
  $bind("paste-url", "keydown", (e) => { if (e.key === "Enter") startExtract($val("paste-url")); });
  const box = document.getElementById("search-status");
  if (state.pendingJob) {
    box.innerHTML = statusHTML("正在提取中...（可以先去别的页面，完成后会自动跳到结果）", "busy");
  } else if (state.current && !state.current.saved) {
    box.innerHTML = `<div class="status info">已生成一份菜谱，<a href="#/detail">点这里查看</a></div>`;
  }
}

async function doSearch(kw) {
  if (!kw) return toast("请输入菜名");
  const box = document.getElementById("search-status");
  document.getElementById("results").innerHTML = "";
  box.innerHTML = statusHTML("正在搜索「" + kw + "」（抖音 + B 站，约 10～20 秒）...", "busy");
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 120000);
  try {
    const r = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keyword: kw }),
      signal: ctrl.signal,
    }).then(asJson);
    if (!r.ok) {
      box.innerHTML = statusHTML(r.error || "搜索失败", "error");
      return;
    }
    box.innerHTML = "";
    if (!r.items || !r.items.length) {
      document.getElementById("results").innerHTML =
        `<div class="empty">没有搜到相关视频，换个关键词，或粘贴视频链接试试。</div>`;
      return;
    }
    renderResults(r.items);
  } catch (e) {
    box.innerHTML = statusHTML(
      e.name === "AbortError"
        ? "搜索超时了（网络太慢），请重试"
        : "连不上本地服务：请确认黑色窗口开着，重新双击启动脚本后刷新",
      "error");
    document.getElementById("server-banner").classList.remove("hidden");
  } finally {
    clearTimeout(timer);
  }
}

function renderResults(items) {
  const box = document.getElementById("results");
  box.innerHTML = `<h2 class="section">搜索结果</h2>`;
  items.forEach((it, idx) => {
    const badge = it.source === "douyin"
      ? `<span class="badge douyin">抖音</span>`
      : `<span class="badge bili">B站</span>`;
    const item = document.createElement("div");
    item.className = "result-item anim-in";
    item.style.setProperty("--i", idx);
    item.innerHTML = `
      <div class="rank">${String(idx + 1).padStart(2, "0")}</div>
      <div class="info">
        <div class="title"><a href="${esc(it.url)}" target="_blank">${esc(it.title)}</a></div>
        <div class="meta">${badge}${esc(it.author || "未知作者")}${it.play ? " · " + esc(it.play) : ""}${it.duration ? " · " + esc(it.duration) : ""}</div>
      </div>
      <button class="btn" data-url="${esc(it.url)}">生成模板</button>`;
    item.querySelector("button").addEventListener("click", () => startExtract(it.url));
    box.appendChild(item);
  });
}

// ---------------- 提取 ----------------

function startExtract(url) {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  state.pendingJob = null;
  state.current = null;
  document.getElementById("results").innerHTML = "";
  const box = document.getElementById("search-status");
  if (!box) return;
  box.innerHTML = statusHTML("开始提取...", "busy");
  postJson("/api/job/extract", { url })
    .then((d) => {
      if (!d.ok) throw new Error(d.error || "任务创建失败");
      state.pendingJob = d.job_id;
      pollJob(d.job_id);
    })
    .catch((e) => fail(e.message));
}

function pollJob(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const r = await getJson("/api/job/" + jobId);
      if (r.status === "running") {
        const box = document.getElementById("search-status");
        if (box) box.innerHTML = statusHTML(r.stage || "处理中...", "busy");
        return;
      }
      clearInterval(pollTimer); pollTimer = null;
      state.pendingJob = null;
      if (r.status === "error") {
        state.current = null;
        return fail(r.error || "处理失败");
      }
      if (r.status === "done") return finishExtract(r.result);
    } catch (e) {
      clearInterval(pollTimer); pollTimer = null;
      state.pendingJob = null;
      fail("任务出错：" + e.message);
    }
  }, 900);
}

function fail(msg) {
  const box = document.getElementById("search-status");
  if (box) box.innerHTML = statusHTML(msg, "error");
}

async function finishExtract(result) {
  const box = document.getElementById("search-status");
  if (box) box.innerHTML = statusHTML("文字提取完成，正在整理模板...", "busy");
  if (!result.transcript) {
    const msg = result.source === "douyin"
? "这条抖音视频在线没有公开文字，无法自动提取；点「打开视频观看」直接去原视频学习。"
      : "这条 B 站视频没有字幕和简介，且临时下载转写未开启或失败。";
    state.current = null;
    if (box) box.innerHTML = statusHTML(msg, "error");
    else toast(msg);
    return;
  }
  try {
    const r = await postJson("/api/generate", { result });
    if (!r.ok) throw new Error(r.error || "整理失败");
    state.current = {
      meta: r.meta, organized: r.organized, markdown: r.markdown,
      note: r.note, saved: false,
    };
    toast("提取完成，已生成菜谱");
    if (parseHash().name === "detail") route();
    else location.hash = "#/detail";
  } catch (e) {
    if (box) box.innerHTML = statusHTML("整理出错：" + e.message, "error");
    else toast("整理出错：" + e.message);
  }
}

// ---------------- 我的菜谱 ----------------

async function renderRecipes() {
  const r = await getJson("/api/recipes");
  const items = r.items || [];
  if (!items.length) {
    view.innerHTML = `
      <h1 class="page-title anim-in">我的菜谱</h1>
      <div class="empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V4H6.5A2.5 2.5 0 0 0 4 6.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/></svg>
        <p>还没有保存菜谱</p>
        <p style="margin-top:6px">去「搜索」找一道菜，生成后点「保存到菜谱」即可。</p>
      </div>`;
    return;
  }
  view.innerHTML = `
    <h1 class="page-title anim-in">我的菜谱</h1>
    <p class="lead">共 ${items.length} 份，存在本网站数据库里。</p>
    <div class="card-grid"></div>`;
  const grid = view.querySelector(".card-grid");
  items.forEach((it, idx) => {
    const card = document.createElement("div");
    card.className = "mini-card anim-in";
    card.style.setProperty("--i", idx);
    card.innerHTML = `
      <div class="mc-top">
        <span class="badge ${it.source === "douyin" ? "douyin" : "bili"}">${it.source === "douyin" ? "抖音" : "B站"}</span>
        <button class="icon-btn del" data-id="${it.id}" title="删除">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/></svg>
        </button>
      </div>`;
    card.insertAdjacentHTML("beforeend",
      `<div class="mc-title">${esc(it.title)}</div>
       <div class="mc-meta">${it.author ? esc(it.author) : "未知作者"}${it.date ? " · " + esc(it.date) : ""}</div>`);
    card.querySelector(".del").addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("删除这份菜谱？")) return;
      await fetch("/api/recipes/" + it.id, { method: "DELETE" }).then(asJson);
      toast("已删除");
      renderRecipes();
    });
    card.addEventListener("click", () => { location.hash = "#/detail?id=" + it.id; });
    grid.appendChild(card);
  });
}

// ---------------- 详情 ----------------

async function renderDetail(params) {
  const id = params.get("id");
  if (id) {
    const r = await getJson("/api/recipes/" + id);
    if (!r.ok) {
      view.innerHTML = statusHTML(r.error || "菜谱不存在", "error");
      return;
    }
    const d = r.recipe;
    state.current = {
      meta: { title: d.title, url: d.video_url, source: d.source, author: d.author, date: d.date, likes: d.likes },
      organized: { ingredients: d.ingredients || {}, steps: d.steps || [], tips: d.tips || [] },
      markdown: d.markdown || "",
      saved: true, id: d.id,
    };
  }
  if (!state.current) {
    view.innerHTML = statusHTML("还没有生成菜谱，先去搜索吧。", "info");
    return;
  }
  renderDetailView(state.current);
}

function renderDetailView(d) {
  const meta = d.meta || {};
  const o = d.organized || {};
  const cats = [["主料", "主料"], ["配料", "配料"], ["调料", "调料"], ["主食", "主食"]];
  let html = `
    <div class="back-row"><a href="#/search">← 返回搜索</a></div>
    <div class="video-box">
      <div class="v-title">${esc(meta.title || "未命名菜谱")}</div>
      <div class="v-meta">
        ${meta.source === "douyin" ? "抖音" : "B站"}${meta.author ? " · " + esc(meta.author) : ""}${meta.date ? " · 发布 " + esc(meta.date) : ""}${meta.likes ? " · 点赞 " + esc(meta.likes) : ""}${d.note ? " · " + esc(d.note) : ""}
      </div>
      ${meta.url ? `<a class="v-url" href="${esc(meta.url)}" target="_blank">${esc(meta.url)}</a>` : ""}
    </div>
    <div class="btn-row">
      <button id="btn-open" class="btn accent">打开视频观看</button>
      <button id="btn-copy" class="btn">复制模板</button>
      <button id="btn-save" class="btn primary">${d.saved ? "已保存" : "保存到菜谱"}</button>
    </div>`;

  const hasIng = Object.values(o.ingredients || {}).some((x) => x && x.length);
  if (hasIng) {
    html += `<div class="card"><h3>食材清单</h3>`;
    cats.forEach(([key, label]) => {
      const list = (o.ingredients || {})[key] || [];
      if (!list.length) return;
      html += `<div class="ing-group"><h4>${label}</h4><ul class="ing-list">` +
        list.map((it) => `
          <li>
            ${esc(it.name)}${it.amount ? " " + esc(it.amount) : ""}
            ${it.why && it.why.length ? `<div class="ing-why">${esc(it.why[0])}</div>` : ""}
          </li>`).join("") + `</ul></div>`;
    });
    html += `</div>`;
  }

  const steps = o.steps || [];
  if (steps.length) {
    html += `<div class="card"><h3>做法步骤</h3><ol class="step-list">`;
    steps.forEach((s) => {
      const text = typeof s === "string" ? s : (s.text || "");
      const why = typeof s === "string" ? [] : (s.why || []);
      html += `<li class="step-item"><span class="step-text">${esc(text)}</span>` +
        why.map((w) => `<div class="step-why"><b>为什么</b>：${esc(w)}</div>`).join("") +
        `</li>`;
    });
    html += `</ol></div>`;
  }

  const tips = o.tips || [];
  if (tips.length) {
    html += `<div class="card"><h3>关键技巧</h3><ul class="tips-list">` +
      tips.map((t) => `<li>${esc(typeof t === "string" ? t : (t.text || ""))}</li>`).join("") +
      `</ul></div>`;
  }

  if (o.raw_text) {
    html += `<details class="raw"><summary>查看视频文字原文</summary><pre>${esc(o.raw_text)}</pre></details>`;
  }
  view.innerHTML = html;

  $bind("btn-open", "click", () => meta.url && window.open(meta.url, "_blank"));
  $bind("btn-copy", "click", copyMarkdown);
  const saveBtn = document.getElementById("btn-save");
  if (!d.saved) {
    saveBtn.addEventListener("click", async () => {
      const r = await postJson("/api/recipes", {
        title: meta.title, url: meta.url, source: meta.source, author: meta.author,
        date: meta.date, likes: meta.likes, markdown: d.markdown, organized: o,
      });
      if (r.ok) {
        state.current.saved = true;
        state.current.id = r.id;
        toast("已保存到我的菜谱");
        saveBtn.textContent = "已保存";
      } else {
        toast("保存失败：" + (r.error || ""));
      }
    });
  }
}

async function copyMarkdown() {
  if (!state.current || !state.current.markdown) return toast("没有可复制的内容");
  try {
    await navigator.clipboard.writeText(state.current.markdown);
    toast("模板已复制");
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = state.current.markdown;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
    toast("模板已复制");
  }
}

// ---------------- 设置 ----------------

async function renderSettings() {
  const lockSt = await getJson("/api/lock/status");
  if (lockSt.pin_set && !lockToken()) {
    view.innerHTML = `
      <h1 class="page-title anim-in">设置</h1>
      <div class="card anim-in" style="--i:1">
        <h3>设置已加锁</h3>
        <p class="lead">输入访问密码后才能查看和修改设置。</p>
        <div class="field"><input id="pin-input" type="password" placeholder="访问密码"></div>
        <button id="btn-unlock" class="btn primary block">解锁</button>
        <div id="pin-status"></div>
      </div>`;
    const doUnlock = async () => {
      const r = await postJson("/api/lock/verify", { pin: $val("pin-input") });
      if (r.ok && r.token) {
        sessionStorage.setItem("cook_lock_token", r.token);
        toast("已解锁");
        renderSettings();
      } else {
        document.getElementById("pin-status").innerHTML =
          statusHTML(r.error || "密码不对", "error");
      }
    };
    $bind("btn-unlock", "click", doUnlock);
    $bind("pin-input", "keydown", (e) => { if (e.key === "Enter") doUnlock(); });
    return;
  }

  view.innerHTML = `
    <h1 class="page-title anim-in">设置</h1>

    <div class="set-group anim-in" style="--i:1">
      <div class="set-label">手机访问</div>
      <div class="set-card">
        <div class="set-row">
          <div><div class="sr-title">本机（电脑上打开）</div><div class="sr-desc">http://127.0.0.1:8765</div></div>
          <a href="http://127.0.0.1:8765" target="_blank">打开</a>
        </div>
        <div id="lan-rows"></div>
      </div>
    </div>

    <div class="set-group anim-in" style="--i:2">
      <div class="set-label">抖音提取</div>
      <div class="set-card">
        <label class="set-row" for="cfg-temp">
          <div><div class="sr-title">允许临时下载转写</div><div class="sr-desc">B 站无字幕时自动转写，用完删除</div></div>
          <input id="cfg-temp" type="checkbox">
        </label>
        <label class="set-row" for="cfg-mc">
          <div><div class="sr-title">优先抖音官方搜索</div><div class="sr-desc">需先扫码激活登录态</div></div>
          <input id="cfg-mc" type="checkbox">
        </label>
      </div>
    </div>

    <div class="set-group anim-in" style="--i:3">
      <div class="set-label">AI 菜谱整理（可选）</div>
      <div class="set-card">
        <div class="set-row">
          <div>
            <div class="sr-title">文本 AI Key</div>
            <div id="cfg-key-state" class="sr-desc">不填写也能使用本地规则整理</div>
          </div>
        </div>
        <div class="field">
          <input id="cfg-ai-key" type="password" autocomplete="new-password" spellcheck="false"
            placeholder="粘贴 API Key；留空不会覆盖已保存的 Key">
        </div>
        <div class="field">
          <input id="cfg-ai-base" type="url" autocomplete="off" spellcheck="false"
            placeholder="Base URL（OpenAI 官方接口可留空）">
        </div>
        <div class="field">
          <input id="cfg-ai-model" type="text" autocomplete="off"
            placeholder="模型名称，例如 gpt-4o-mini">
        </div>
        <div class="btn-row">
          <button id="btn-clear-ai-key" class="btn">清除已保存的 Key</button>
        </div>
        <div id="ai-key-status"></div>
      </div>
    </div>

    <div class="set-group anim-in" style="--i:4">
      <div class="set-label">访问密码</div>
      <div class="set-card">
        <div class="set-row">
          <div><div class="sr-title">防误改</div><div class="sr-desc">${lockSt.pin_set ? "已开启：打开设置需输入密码" : "未设置"}</div></div>
        </div>
        <div class="field"><input id="cfg-pin" type="password" placeholder="新密码（至少 4 位，留空保存则清除）"></div>
        <button id="btn-setpin" class="btn">保存密码</button>
        <div id="pin-status2"></div>
      </div>
    </div>

    <div class="set-group anim-in" style="--i:5">
      <div class="set-label">菜谱数据</div>
      <div class="set-card">
        <div class="btn-row"><button id="btn-backup" class="btn">备份菜谱（下载）</button></div>
        <div class="field"><textarea id="restore-text" rows="3" placeholder="把备份的 JSON 粘贴到这里再点恢复"></textarea></div>
        <button id="btn-restore" class="btn">恢复菜谱</button>
        <div id="data-status"></div>
      </div>
    </div>

    <div class="set-group anim-in" style="--i:6">
      <div class="set-label">安装到手机桌面</div>
      <div class="set-card">
        <div class="set-row"><div><div class="sr-title">iPhone</div><div class="sr-desc">Safari 分享按钮 → 添加到主屏幕</div></div></div>
        <div class="set-row"><div><div class="sr-title">Android</div><div class="sr-desc">Chrome 菜单 → 安装应用</div></div></div>
      </div>
    </div>

    <button id="btn-savecfg" class="btn primary block">保存设置</button>
    <div id="cfg-status"></div>`;

  const c = await lockedGet("/api/config");
  if (c.ok) {
    document.getElementById("cfg-temp").checked = c.config.allow_temp_download !== false;
    document.getElementById("cfg-mc").checked = c.config.use_mediacrawler === true;
    document.getElementById("cfg-ai-base").value = c.config.openai_base_url || "";
    document.getElementById("cfg-ai-model").value = c.config.llm_model || "";
    document.getElementById("cfg-key-state").textContent = c.config.openai_key_configured
      ? "已配置。为保护安全，已保存的 Key 不会显示在页面上。"
      : "未配置。留空也能使用本地规则整理。";
  }
  const info = await getJson("/api/info");
  const lanBox = document.getElementById("lan-rows");
  if (info.ok) {
    lanBox.innerHTML = (info.lan_urls || []).map((u) => `
      <div class="set-row">
        <div><div class="sr-title">手机（同一 WiFi）</div><div class="sr-desc">用手机浏览器打开</div></div>
        <a href="${esc(u)}" target="_blank">${esc(u.replace(/^https?:\/\//, ""))}</a>
      </div>`).join("") +
      `<div class="set-row"><div class="sr-desc">打不开时：Windows 防火墙放行 Python</div></div>`;
  }
  $bind("btn-setpin", "click", async () => {
    const r = await lockedPost("/api/config", { settings_pin: $val("cfg-pin") });
    const box = document.getElementById("pin-status2");
    box.innerHTML = statusHTML(r.ok ? "访问密码已更新" : (r.error || "保存失败"), r.ok ? "info" : "error");
    setTimeout(() => { box.innerHTML = ""; }, 3000);
  });
  $bind("btn-clear-ai-key", "click", async () => {
    if (!window.confirm("确定清除已保存的文本 AI Key 吗？之后会改用本地规则整理。")) return;
    const r = await lockedPost("/api/config", { openai_api_key: "" });
    const box = document.getElementById("ai-key-status");
    box.innerHTML = statusHTML(r.ok ? "AI Key 已清除" : (r.error || "清除失败"), r.ok ? "info" : "error");
    if (r.ok) document.getElementById("cfg-key-state").textContent = "未配置。留空也能使用本地规则整理。";
  });
  $bind("btn-backup", "click", async () => {
    const r = await getJson("/api/recipes/export");
    if (!r.ok || !r.recipes) return toast("备份失败");
    const blob = new Blob([JSON.stringify({ recipes: r.recipes }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "菜谱备份-" + new Date().toISOString().slice(0, 10) + ".json";
    a.click();
    URL.revokeObjectURL(a.href);
    toast("已下载备份文件");
  });
  $bind("btn-restore", "click", async () => {
    const raw = $val("restore-text");
    let data;
    try {
      data = JSON.parse(raw);
    } catch (e) {
      document.getElementById("data-status").innerHTML = statusHTML("JSON 格式不对，请检查", "error");
      return;
    }
    const recipes = data.recipes || (Array.isArray(data) ? data : []);
    const r = await postJson("/api/recipes/import", { recipes });
    const box = document.getElementById("data-status");
    box.innerHTML = statusHTML(r.ok ? ("已导入 " + (r.imported || 0) + " 份菜谱") : (r.error || "导入失败"), r.ok ? "info" : "error");
    setTimeout(() => { box.innerHTML = ""; }, 4000);
  });
  $bind("btn-savecfg", "click", saveConfig);
}

async function saveConfig() {
  const body = {
    allow_temp_download: document.getElementById("cfg-temp").checked,
    use_mediacrawler: document.getElementById("cfg-mc").checked,
    openai_base_url: $val("cfg-ai-base"),
    llm_model: $val("cfg-ai-model"),
  };
  const apiKey = $val("cfg-ai-key");
  if (apiKey) body.openai_api_key = apiKey;
  const r = await lockedPost("/api/config", body);
  const box = document.getElementById("cfg-status");
  box.innerHTML = statusHTML(r.ok ? "设置已保存" : "保存失败", r.ok ? "info" : "error");
  if (r.ok && apiKey) {
    document.getElementById("cfg-ai-key").value = "";
    document.getElementById("cfg-key-state").textContent = "已配置。为保护安全，已保存的 Key 不会显示在页面上。";
  }
  setTimeout(() => { box.innerHTML = ""; }, 2600);
}

// ---------------- 工具 ----------------

function $val(id) {
  const el = document.getElementById(id);
  return el ? el.value.trim() : "";
}

function $set(id, v) {
  const el = document.getElementById(id);
  if (el) el.value = v || "";
}

function $bind(id, evt, fn) {
  const el = document.getElementById(id);
  if (el) el.addEventListener(evt, fn);
}

// 启动
async function boot() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/static/sw.js").catch(() => {});
  }
  try {
    const ctrl = new AbortController();
    setTimeout(() => ctrl.abort(), 5000);
    await fetch("/api/lock/status", { signal: ctrl.signal });
  } catch (e) {
    document.getElementById("server-banner").classList.remove("hidden");
  }
  route();
}

boot();
