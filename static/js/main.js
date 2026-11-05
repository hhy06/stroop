"use strict";

const $ = (sel) => document.querySelector(sel);
const PENDING_KEY = "stroop_pending_v1";

const state = {
  config: null,
  sessionId: null,
  seed: null,
  blockOrder: [],
  trials: [],
  practice: [],
  colorKeys: [],
  pending: [],
  vocabItems: [],
  vocabAnswers: [],
  vocabIndex: 0,
  hz: null,
  returnScreen: "setup",
};

function showToast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.remove("hidden");
}
function hideToast() { $("#toast").classList.add("hidden"); }
function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail; } catch (e) { /* 非 JSON 错误响应 */ }
    throw new Error(typeof detail === "string" && detail ? detail : `请求失败 (${res.status})`);
  }
  return res.json();
}

function guard(fn) {
  return async (...args) => {
    try { await fn(...args); }
    catch (err) { console.error(err); showToast(err.message || String(err)); }
  };
}

function showScreen(name) {
  document.querySelectorAll(".screen").forEach((el) => el.classList.add("hidden"));
  const target = $(`#screen-${name}`);
  if (target) target.classList.remove("hidden");
  window.scrollTo(0, 0);
}
function currentScreen() {
  const el = document.querySelector(".screen:not(.hidden)");
  return el ? el.id.replace("screen-", "") : "setup";
}

function setProgress(ratio) {
  $("#progress-fill").style.width = `${Math.max(0, Math.min(1, ratio)) * 100}%`;
}

function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

function estimateHz() {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    setTimeout(() => finish(null), 1600);
    const stamps = [];
    function step(ts) {
      if (done) return;
      stamps.push(ts);
      if (stamps.length < 40) { requestAnimationFrame(step); return; }
      const diffs = [];
      for (let i = 1; i < stamps.length; i++) diffs.push(stamps[i] - stamps[i - 1]);
      diffs.sort((a, b) => a - b);
      const med = diffs[Math.floor(diffs.length / 2)];
      finish(med > 0 ? Math.round(10000 / med) / 10 : null);
    }
    requestAnimationFrame(step);
  });
}

function renderRatings() {
  const wrap = $("#rating-list");
  wrap.innerHTML = "";
  const labels = ["1 完全不懂", "2", "3 一般", "4", "5 非常熟练"];
  for (const lang of state.config.language_keys) {
    const meta = state.config.languages[lang];
    const row = document.createElement("div");
    row.className = "rating-row";
    const name = document.createElement("div");
    name.textContent = meta.name;
    const scales = document.createElement("div");
    scales.className = "rating-scales";
    for (let v = 1; v <= 5; v++) {
      const lab = document.createElement("label");
      const input = document.createElement("input");
      input.type = "radio";
      input.name = `rating-${lang}`;
      input.value = String(v);
      input.checked = v === 1;
      const span = document.createElement("span");
      span.textContent = labels[v - 1];
      lab.append(input, span);
      scales.appendChild(lab);
    }
    row.append(name, scales);
    wrap.appendChild(row);
  }
}

function colorChips(container, withKey) {
  container.innerHTML = "";
  state.colorKeys.forEach((key, i) => {
    const el = withKey ? document.createElement("button") : document.createElement("div");
    el.className = withKey ? "response-btn" : "mapping-chip";
    el.dataset.color = key;
    el.style.background = state.config.colors[key].hex;
    if (withKey) {
      el.type = "button";
      el.innerHTML = `<span class="key">${i + 1}</span>${escapeHtml(state.config.colors[key].label)}`;
    } else {
      el.style.color = "#fff";
      el.textContent = `${i + 1}  ${state.config.colors[key].label}`;
    }
    container.appendChild(el);
  });
}

function persistPending() {
  try {
    localStorage.setItem(PENDING_KEY, JSON.stringify({ session_id: state.sessionId, trials: state.pending }));
  } catch (e) { console.warn("本地暂存失败", e); }
}

async function flushPending() {
  if (!state.pending.length || !state.sessionId) return;
  const payload = { trials: state.pending };
  await api(`/api/session/${state.sessionId}/trials`, { method: "POST", body: JSON.stringify(payload) });
  state.pending = [];
  try { localStorage.removeItem(PENDING_KEY); } catch (e) { /* 忽略 */ }
}

async function recoverPending() {
  try {
    const raw = localStorage.getItem(PENDING_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    if (!data.session_id || !Array.isArray(data.trials) || !data.trials.length) {
      localStorage.removeItem(PENDING_KEY);
      return;
    }
    await api(`/api/session/${data.session_id}/trials`, { method: "POST", body: JSON.stringify({ trials: data.trials }) });
    localStorage.removeItem(PENDING_KEY);
  } catch (e) { console.warn("历史暂存数据未能回传", e); }
}

async function startSession() {
  const btn = $("#btn-start");
  btn.disabled = true;
  showToast("正在准备试次…");
  const selfRating = {};
  for (const lang of state.config.language_keys) {
    const input = document.querySelector(`input[name="rating-${lang}"]:checked`);
    selfRating[lang] = Number(input ? input.value : 1);
  }
  state.hz = await estimateHz();
  const data = await api("/api/session", {
    method: "POST",
    body: JSON.stringify({ self_rating: selfRating, user_agent: navigator.userAgent, screen_hz: state.hz }),
  });
  state.sessionId = data.session_id;
  state.seed = data.seed;
  state.config = data.config;
  state.blockOrder = data.block_order;
  state.trials = data.trials;
  state.practice = data.practice;
  state.colorKeys = data.config.color_keys;
  state.pending = [];
  $("#session-tag").textContent = `编号 ${data.session_id.slice(0, 6)}`;
  $("#formal-count").textContent = String(state.trials.length);
  $("#formal-blocks").textContent = String(state.blockOrder.length);
  colorChips($("#response-bar"), true);
  colorChips($("#mapping-preview"), false);
  hideToast();
  showScreen("instructions");
}

function waitForClick(sel) {
  return new Promise((resolve) => {
    const el = $(sel);
    const handler = () => { el.removeEventListener("click", handler); resolve(); };
    el.addEventListener("click", handler);
  });
}

function runOneTrial(trial, isPractice) {
  const T = state.config.timing;
  return new Promise((resolve) => {
    const ac = new AbortController();
    const fixation = $("#fixation");
    const stimulus = $("#stimulus");
    const feedback = $("#feedback");
    let t0 = null;
    let t1 = null;
    let responded = false;
    let blurred = false;
    let finished = false;
    let timeoutId = null;
    let fixationId = null;
    let rafId = null;

    feedback.className = "feedback hidden";
    feedback.textContent = "";
    stimulus.textContent = trial.word;
    stimulus.style.color = state.config.colors[trial.ink_color].hex;
    stimulus.className = "stimulus hidden";
    fixation.classList.remove("hidden");

    const onVisibility = () => { if (document.hidden) blurred = true; };
    const onBlur = () => { blurred = true; };
    document.addEventListener("visibilitychange", onVisibility, { signal: ac.signal });
    window.addEventListener("blur", onBlur, { signal: ac.signal });

    const onKey = (e) => {
      const map = { "1": 0, "2": 1, "3": 2, "4": 3, d: 0, f: 1, j: 2, k: 3 };
      const idx = map[e.key.toLowerCase()];
      if (idx === undefined || idx >= state.colorKeys.length) return;
      e.preventDefault();
      respond(state.colorKeys[idx], e);
    };
    const onPointer = (e) => {
      const btn = e.target.closest("[data-color]");
      if (!btn) return;
      e.preventDefault();
      respond(btn.dataset.color, e);
    };
    window.addEventListener("keydown", onKey, { signal: ac.signal });
    $("#response-bar").addEventListener("pointerdown", onPointer, { signal: ac.signal });

    function respond(color, event) {
      if (responded) return;
      responded = true;
      const now = performance.now();
      let stamp = event && typeof event.timeStamp === "number" ? event.timeStamp : now;
      if (!Number.isFinite(stamp) || Math.abs(stamp - now) > 1000) stamp = now;
      t1 = stamp;
      finish(color, false);
    }

    function finish(color, timedOut) {
      if (finished) return;
      finished = true;
      ac.abort();
      clearTimeout(timeoutId);
      clearTimeout(fixationId);
      if (rafId !== null) cancelAnimationFrame(rafId);

      const rt = t0 !== null && t1 !== null ? Math.max(0, t1 - t0) : null;
      const anticipated = t0 === null;
      const correct = !timedOut && color === trial.correct_color;
      stimulus.classList.add("hidden");
      fixation.classList.add("hidden");
      if (isPractice) {
        feedback.textContent = timedOut ? "超时" : correct ? "正确" : "不对，看颜色";
        feedback.className = `feedback ${correct ? "ok" : "no"}`;
      }
      const result = {
        trial_id: trial.trial_id,
        response_color: timedOut ? null : color,
        rt_ms: rt,
        timeout: timedOut,
        anticipated,
        blurred,
        client_meta: {
          dpr: window.devicePixelRatio || 1,
          hz: state.hz,
          w: window.innerWidth,
          h: window.innerHeight,
        },
      };
      const delay = isPractice && !timedOut ? T.feedback_ms : T.iti_ms;
      setTimeout(() => {
        feedback.className = "feedback hidden";
        resolve(result);
      }, delay);
    }

    const wait = T.fixation_ms + (Math.random() * 2 - 1) * T.fixation_jitter_ms;
    fixationId = setTimeout(() => {
      fixation.classList.add("hidden");
      rafId = requestAnimationFrame((ts) => {
        t0 = ts;
        if (!responded) {
          stimulus.classList.remove("hidden");
          timeoutId = setTimeout(() => finish(null, true), T.response_deadline_ms);
        }
      });
    }, wait);
  });
}

async function runTrials(list, isPractice, withBreaks) {
  for (let i = 0; i < list.length; i++) {
    const trial = list[i];
    if (withBreaks && i > 0 && trial.block !== list[i - 1].block) {
      showScreen("break");
      $("#break-progress").textContent = `${i} / ${list.length}`;
      await waitForClick("#btn-continue");
      showScreen("trial");
    }
    setProgress((i + 1) / list.length);
    const result = await runOneTrial(trial, isPractice);
    if (!isPractice) {
      state.pending.push(result);
      persistPending();
      const isBlockEnd = i === list.length - 1 || list[i + 1].block !== trial.block;
      if (isBlockEnd) {
        try { await flushPending(); }
        catch (e) { console.warn("本段回传失败，已本地暂存", e); }
      }
    }
  }
  setProgress(1);
}

async function runPractice() {
  showScreen("trial");
  setProgress(0);
  await runTrials(state.practice, true, false);
  showScreen("ready");
}

async function runFormal() {
  showScreen("trial");
  setProgress(0);
  await runTrials(state.trials, false, true);
  try { await flushPending(); } catch (e) { console.warn(e); }
  startVocab();
}

function startVocab() {
  state.vocabItems = shuffle(state.config.vocab_items.slice());
  state.vocabAnswers = [];
  state.vocabIndex = 0;
  $("#vocab-total").textContent = String(state.vocabItems.length);
  const opts = $("#vocab-options");
  opts.innerHTML = "";
  const options = state.colorKeys.map((key) => ({ answer: key, label: state.config.colors[key].label }));
  options.push({ answer: "unknown", label: "不认识" });
  for (const opt of options) {
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.answer = opt.answer;
    b.textContent = opt.label;
    b.addEventListener("click", () => answerVocab(opt.answer));
    opts.appendChild(b);
  }
  showScreen("vocab");
  renderVocab();
}

function renderVocab() {
  const item = state.vocabItems[state.vocabIndex];
  $("#vocab-word").textContent = item.word;
  $("#vocab-lang").textContent = item.language_name;
  $("#vocab-fill").style.width = `${(state.vocabIndex / state.vocabItems.length) * 100}%`;
}

async function answerVocab(answer) {
  const item = state.vocabItems[state.vocabIndex];
  state.vocabAnswers.push({ language: item.language, word: item.word, answer });
  state.vocabIndex += 1;
  if (state.vocabIndex >= state.vocabItems.length) {
    await finishVocab();
    return;
  }
  renderVocab();
}

async function finishVocab() {
  showToast("正在生成结果…");
  await api(`/api/session/${state.sessionId}/vocab`, {
    method: "POST", body: JSON.stringify({ answers: state.vocabAnswers }),
  });
  const summary = await api(`/api/session/${state.sessionId}/summary`);
  renderSummary(summary);
  hideToast();
  showScreen("summary");
}

function renderSummary(s) {
  $("#summary-meta").textContent =
    `匿名编号 ${s.session_id.slice(0, 6)} · 已记录 ${s.n_submitted}/${s.n_expected} 题 · 序列种子 ${s.seed} · ${s.created_at}`;

  const cards = [];
  for (const [lang, info] of Object.entries(s.by_language)) {
    const name = state.config.languages[lang] ? state.config.languages[lang].name : lang;
    const value = info.interference_ms === null ? "—" : `${info.interference_ms > 0 ? "+" : ""}${info.interference_ms} ms`;
    const vocab = info.vocab ? `${info.vocab.correct}/${info.vocab.total}` : "未完成";
    cards.push(
      `<div class="interference-card"><div class="lang">${escapeHtml(name)}</div>` +
      `<div class="value">${escapeHtml(value)}</div>` +
      `<div class="note">自评 ${info.self_rating ?? "—"}/5 · 译词 ${escapeHtml(vocab)} 正确</div></div>`
    );
  }
  const rows = s.cells.map((c) => {
    const name = state.config.languages[c.language] ? state.config.languages[c.language].name : c.language;
    const condName = { congruent: "一致", incongruent: "不一致", neutral: "中性" }[c.condition] || c.condition;
    return `<tr><td>${escapeHtml(name)}</td><td>${condName}</td>` +
      `<td class="num">${c.n_valid}/${c.n_total}</td>` +
      `<td class="num">${c.median_rt_ms === null ? "—" : c.median_rt_ms.toFixed(1)}</td>` +
      `<td class="num">${c.error_rate === null ? "—" : (c.error_rate * 100).toFixed(1) + "%"}</td></tr>`;
  }).join("");
  const interpretations = Object.entries(s.by_language).map(([lang, info]) => {
    const name = state.config.languages[lang] ? state.config.languages[lang].name : lang;
    return `<div class="interpret"><strong>${escapeHtml(name)}：</strong>${escapeHtml(info.interpretation)}</div>`;
  }).join("");

  $("#summary-body").innerHTML =
    `<h3>干扰量（不一致 − 中性）</h3><div class="interference-grid">${cards.join("")}</div>` +
    `<p class="muted">干扰量越接近 0，说明词义越没有自动激活；只看绝对反应时会把「认字慢」误当成干扰。</p>` +
    `<h3>各条件明细</h3><table><thead><tr><th>语言</th><th>条件</th>` +
    `<th class="num">有效/总数</th><th class="num">中位 RT (ms)</th><th class="num">错误率</th></tr></thead>` +
    `<tbody>${rows}</tbody></table>` +
    `<h3>怎么读这组数据</h3>${interpretations}` +
    `<p class="muted">${escapeHtml(s.caveat)}</p>`;
}

async function showOverview() {
  if (currentScreen() !== "overview") state.returnScreen = currentScreen();
  showScreen("overview");
  const data = await api("/api/overview");
  const rows = [];
  for (const s of data.sessions) {
    for (const [lang, info] of Object.entries(s.by_language)) {
      const name = state.config.languages[lang] ? state.config.languages[lang].name : lang;
      const vocab = info.vocab ? `${info.vocab.correct}/${info.vocab.total}` : "—";
      rows.push(
        `<tr><td>${escapeHtml(s.session_id.slice(0, 6))}</td><td>${escapeHtml(s.created_at.slice(0, 16))}</td>` +
        `<td>${escapeHtml(name)}</td><td class="num">${info.self_rating ?? "—"}</td>` +
        `<td class="num">${escapeHtml(vocab)}</td>` +
        `<td class="num">${info.interference_ms === null ? "—" : info.interference_ms}</td></tr>`
      );
    }
  }
  $("#overview-body").innerHTML =
    `<p class="muted">共 ${data.n_sessions} 个会话</p>` +
    `<table><thead><tr><th>编号</th><th>时间 (UTC)</th><th>语言</th>` +
    `<th class="num">自评</th><th class="num">译词</th><th class="num">干扰量 (ms)</th></tr></thead>` +
    `<tbody>${rows.join("") || '<tr><td colspan="6">暂无数据</td></tr>'}</tbody></table>`;
}

function refreshStartButton() {
  $("#btn-start").disabled = !($("#check-colorvision").checked && $("#check-consent").checked);
}

async function init() {
  try {
    state.config = await api("/api/config");
    state.colorKeys = state.config.color_keys;
    renderRatings();
    colorChips($("#mapping-preview"), false);
  } catch (e) {
    showToast(`配置加载失败：${e.message}`);
    return;
  }
  $("#check-colorvision").addEventListener("change", refreshStartButton);
  $("#check-consent").addEventListener("change", refreshStartButton);
  $("#btn-start").addEventListener("click", guard(startSession));
  $("#btn-practice").addEventListener("click", guard(runPractice));
  $("#btn-formal").addEventListener("click", guard(runFormal));
  $("#btn-restart").addEventListener("click", () => location.reload());
  $("#btn-overview").addEventListener("click", guard(showOverview));
  $("#btn-overview-refresh").addEventListener("click", guard(showOverview));
  $("#btn-overview-back").addEventListener("click", () => showScreen(state.returnScreen));
  refreshStartButton();
  recoverPending();
}

init();
