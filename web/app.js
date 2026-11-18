/* Clipfarm dashboard — vanilla JS, no build step. All data via /api/*. */
"use strict";

// ---------------------------------------------------------------- helpers
const $ = (s, el = document) => el.querySelector(s);
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));  // text is never parsed as HTML
  }
  return el;
}
const fmt = (n) => n === null || n === undefined ? "—" :
  n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "K" : String(Math.round(n));
const money = (n) => n === null || n === undefined ? "—" : "$" + Number(n).toFixed(2);
const ago = (iso) => {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  return s < 90 ? "just now" : s < 5400 ? Math.round(s / 60) + "m ago" : s < 172800 ? Math.round(s / 3600) + "h ago" : Math.round(s / 86400) + "d ago";
};
const mmss = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST", headers: { "X-Clipfarm": "1", "Content-Type": typeof body === "string" ? "text/plain" : "application/json" },
    body: typeof body === "string" ? body : JSON.stringify(body),
  };
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}
let toastTimer;
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (err ? " err" : ""); t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), 4200);
}
async function act(fn, ok) {
  try { const r = await fn(); if (ok) toast(ok); await refresh(); return r; }
  catch (e) { toast(e.message, true); }
}
const runJob = (type, params) => act(() => api("/api/jobs", { type, params }), `Started ${type}`);

const STATUS = {
  rendered: ["warn", "needs review"], approved: ["good", "ready to post"], posted: ["info", "posted"],
  rejected: ["neutral", "rejected"], failed: ["bad", "failed"], rendering: ["accent", "rendering"],
  new: ["neutral", "new"], queued: ["accent", "queued"], processing: ["accent", "processing"],
  processed: ["good", "processed"], skipped: ["neutral", "skipped"], needs_rights: ["warn", "needs your call"],
};
const chip = (s) => { const [c, label] = STATUS[s] || ["neutral", s || "?"]; return h("span", { class: `chip ${c}` }, label); };
const RIGHTS = { campaign: "good", permission: "good", own: "good", official: "info", unverified: "warn", blocked: "bad" };
const rightsChip = (r) => h("span", { class: `chip ${RIGHTS[r] || "neutral"}`, title: "rights level" }, r || "unverified");

// ---------------------------------------------------------------- state
const S = { tab: "today", state: null, libFilter: "approved", scoutFilter: "needs_rights,new,queued", sort: { key: "views", dir: -1 } };

async function refresh() {
  try { S.state = await api("/api/state"); } catch (e) { toast("Server unreachable: " + e.message, true); return; }
  renderChrome();
  await renderTab();
}

function renderChrome() {
  const st = S.state;
  $("#handle").textContent = "@" + (st.handle || "clipfarm");
  const p = st.plan;
  $("#phase-pill").textContent = `${(p.phase || "").replace("_", " ")} · ${p.target}/day`;
  $("#brain-pill").replaceChildren(h("span", { class: "dot" + (st.brain ? " on" : "") }), st.brain ? "Claude brain" : "heuristics");
  const running = st.jobs_running || [];
  $("#jobs-pill").replaceChildren(h("span", { class: "dot" + (running.length ? " busy" : "") }), running.length ? running.join(", ") : "idle");
  $("#autopilot-toggle").checked = !!(st.autopilot && st.autopilot.enabled);
  const rc = st.clip_counts.rendered || 0, nr = st.candidates.needs_rights || 0;
  $("#review-count").hidden = !rc; $("#review-count").textContent = rc;
  $("#scout-count").hidden = !nr; $("#scout-count").textContent = nr;
}

// ---------------------------------------------------------------- tabs
const TABS = { today: viewToday, review: viewReview, library: viewLibrary, scout: viewScout, analytics: viewAnalytics, sources: viewSources, activity: viewActivity };
async function renderTab() {
  const view = $("#view");
  const focused = document.activeElement;
  if (focused && view.contains(focused) && ["INPUT", "TEXTAREA", "SELECT"].includes(focused.tagName)) return; // don't clobber typing
  const playing = [...view.querySelectorAll("video")].some((v) => !v.paused);
  if (playing) return;
  const node = await TABS[S.tab]();
  view.replaceChildren(node);
}
function setTab(t) {
  S.tab = t; location.hash = t;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === t));
  renderTab();
}

// ---------------------------------------------------------------- Today
async function viewToday() {
  const st = S.state, p = st.plan, k = st.kpis;
  const clips = await api("/api/clips?status=approved,posted");
  const byId = Object.fromEntries(clips.map((c) => [c.id, c]));
  const pct = Math.min(100, Math.round((p.posted_today / Math.max(p.target, 1)) * 100));

  const tiles = h("div", { class: "grid kpis" },
    kpi("Posted today", `${p.posted_today}/${p.target}`, `${p.phase.replace("_", " ")} phase`, pct),
    kpi("Ready to post", p.ready, `${p.in_review} awaiting review`),
    kpi("Total views", fmt(k.views), `${k.posted} posts · avg ${fmt(k.avg_views)}`),
    kpi("Followers", fmt(k.followers), k.last_metrics_at ? `metrics ${ago(k.last_metrics_at)}` : "pull metrics →"),
    kpi("Est. campaign earnings", money(k.earnings), "after platform fee"),
  );

  const slotBoard = h("div", { class: "slots" }, p.slots.map((s) => {
    const c = s.clip_id && byId[s.clip_id];
    const label = { posted: ["info", "posted"], missed: ["neutral", "missed"], assigned: ["good", s.due ? "post now" : "assigned"], empty: ["warn", "empty"] }[s.state];
    return h("div", { class: "slot" + (s.due && s.state === "assigned" ? " due" : "") },
      h("div", { class: "row" }, h("span", { class: "time" }, s.time), h("span", { class: `chip ${label[0]}` }, label[1])),
      c && c.thumb ? h("img", { src: "/" + c.thumb, alt: c.hook || "" }) : null,
      c ? h("div", { class: "muted", style: { fontSize: "12px", marginTop: "6px" } }, c.hook) : null,
      c && s.state === "assigned" ? h("div", { class: "row", style: { marginTop: "8px" } },
        h("a", { class: "btn sm", href: "/" + c.file, download: `${c.id}.mp4` }, "Download"),
        h("button", { class: "btn sm", onclick: () => copy(c.caption) }, "Copy caption"),
        h("button", { class: "btn sm primary", onclick: () => markPosted(c) }, "Posted")) : null);
  }));

  const perf = p.performance;
  const prod = h("div", { class: "card" },
    h("h2", {}, "Production", h("small", {}, "keeps the queue ~1 day ahead")),
    h("p", {}, p.renders_needed > 0
      ? `Need ~${p.renders_needed} more renders to cover ${p.open_slots} open slot(s) today + tomorrow's buffer (approval rate ${Math.round(p.approval_rate * 100)}%).`
      : `Queue is covered: ${p.ready} ready, ${p.in_review} in review for ${p.open_slots} open slot(s).`),
    h("div", { class: "row" },
      h("button", { class: "btn primary", onclick: () => runJob("produce") }, "Produce now"),
      h("button", { class: "btn", onclick: () => runJob("scout") }, "Scout now"),
      st.candidates.needs_rights ? h("button", { class: "btn", onclick: () => { S.scoutFilter = "needs_rights"; setTab("scout"); } },
        `${st.candidates.needs_rights} source(s) need your call`) : null));

  const advice = h("div", { class: "card" },
    h("h2", {}, "Cadence advisor"),
    h("p", {}, perf.reason),
    h("div", { class: "row muted" },
      `3-day median ${fmt(perf.median_recent_3d)} · prior ${fmt(perf.median_prior)} · suggested change: `,
      h("strong", {}, perf.delta > 0 ? "+1/day" : perf.delta < 0 ? "−1/day" : "hold")),
    perf.breakouts.length ? h("div", { class: "callout good", style: { marginTop: "10px" } },
      "Breakouts: ", perf.breakouts.map((b) => `${b.id} “${b.hook}” (${fmt(b.views)}, ${b.channel})`).join(" · ")) : null,
    h("p", { class: "muted", style: { fontSize: "12px" } },
      st.config.cadence.auto_adjust.apply ? "Auto-apply is ON: the advisor changes today's target." : "Auto-apply is OFF (Autopilot tab) — suggestions only."));

  return h("div", { class: "grid" }, tiles,
    h("div", { class: "card" }, h("h2", {}, `Today's slots`, h("small", {}, `${p.date} · ${p.timezone}`)), slotBoard),
    h("div", { class: "grid two" }, prod, advice));
}
function kpi(label, value, sub, pct) {
  return h("div", { class: "card kpi" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value),
    h("div", { class: "sub" }, sub), pct !== undefined ? h("div", { class: "progress" }, h("span", { style: { width: pct + "%" } })) : null);
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text || ""); toast("Caption copied"); } catch { toast("Copy failed — select the text manually", true); }
}
function markPosted(c) {
  const url = prompt("Paste the TikTok video URL (optional — metrics will auto-link it otherwise):", "");
  if (url === null) return;
  act(() => api(`/api/clips/${c.id}`, { action: "posted", tiktok_url: url.trim() }), `${c.id} marked posted`);
}

// ---------------------------------------------------------------- Review
async function viewReview() {
  const clips = await api("/api/clips?status=rendered,rendering");
  const head = h("div", { class: "section-head" }, h("h1", {}, "Review queue"),
    h("span", { class: "muted" }, "Approve what you'd post; rejections teach the approval rate the planner uses."));
  if (!clips.length) return h("div", {}, head, h("div", { class: "empty" }, "Nothing to review. ", h("button", { class: "btn sm", onclick: () => runJob("produce") }, "Produce clips")));
  return h("div", {}, head, h("div", { class: "grid clips" }, clips.map(clipCard)));
}
function clipCard(c) {
  const hook = h("input", { type: "text", value: c.hook || "", "aria-label": "Hook" });
  const cap = h("textarea", { "aria-label": "Caption" }, c.caption || "");
  const qc = c.qc || {};
  const src = c.source_url ? (c.platform === "youtube" ? `${c.source_url}&t=${Math.floor(c.start || 0)}s` : c.source_url) : null;
  const save = (rerender) => act(() => api(`/api/clips/${c.id}`, { action: "edit", hook: hook.value, caption: cap.value, rerender }),
    rerender ? "Saved — re-rendering with new hook" : "Saved");
  if (c.status === "rendering") return h("div", { class: "card clip" }, h("div", { class: "row" }, h("strong", {}, c.id), chip("rendering")), h("div", { class: "muted" }, "Rendering…"));
  return h("div", { class: "card clip" },
    h("div", { class: "row" }, h("strong", {}, c.id), chip(c.status), rightsChip(c.rights), h("span", { class: "spacer" }),
      h("span", { class: "muted", title: "Predicted strength (Claude or heuristic)" }, `score ${c.score ?? "—"}`)),
    c.file ? h("video", { src: "/" + c.file, controls: true, preload: "metadata", poster: c.thumb ? "/" + c.thumb : null, playsinline: true }) : null,
    h("div", { class: "meta" }, h("span", {}, c.channel || "?"), h("span", {}, `${mmss(c.start || 0)}–${mmss(c.end || 0)} (${c.duration}s)`),
      h("span", {}, c.picked_by === "brain" ? "picked by Claude" : "heuristic pick"), src ? h("a", { href: src, target: "_blank", rel: "noopener" }, "source ↗") : null),
    c.reason ? h("div", { class: "why" }, c.reason) : null,
    qc.issues && qc.issues.length ? h("div", { class: "issues" }, "QC: " + qc.issues.join(" · ")) : null,
    h("label", { class: "muted" }, "On-screen hook", hook),
    h("label", { class: "muted" }, "Caption", cap),
    h("div", { class: "actions" },
      h("button", { class: "btn good", onclick: () => act(() => api(`/api/clips/${c.id}`, { action: "edit", hook: hook.value, caption: cap.value }).then(() => api(`/api/clips/${c.id}`, { action: "approve" })), `${c.id} approved`) }, "Approve"),
      h("button", { class: "btn danger", onclick: () => { const r = prompt("Reject reason (optional):", "weak moment"); if (r !== null) act(() => api(`/api/clips/${c.id}`, { action: "reject", reason: r }), `${c.id} rejected`); } }, "Reject"),
      h("button", { class: "btn", onclick: () => save(false) }, "Save text"),
      h("button", { class: "btn", title: "Burn the edited hook into the video", onclick: () => save(true) }, "Re-render"),
      c.grid ? h("a", { class: "btn", href: "/" + c.grid, target: "_blank", rel: "noopener", title: "6-frame contact sheet" }, "Frames") : null));
}

// ---------------------------------------------------------------- Library
async function viewLibrary() {
  const clips = await api("/api/clips?status=" + S.libFilter);
  const filters = [["approved", "Ready to post"], ["posted", "Posted"], ["rejected", "Rejected"], ["failed", "Failed"], ["approved,posted,rejected,failed,rendered", "All"]];
  const head = h("div", { class: "section-head" }, h("h1", {}, "Clip library"), h("span", { class: "spacer" }),
    filters.map(([v, l]) => h("button", { class: "btn sm" + (S.libFilter === v ? " primary" : ""), onclick: () => { S.libFilter = v; renderTab(); } }, l)));
  if (!clips.length) return h("div", {}, head, h("div", { class: "empty" }, "No clips here yet."));
  return h("div", {}, head, h("div", { class: "grid clips" }, clips.map((c) => {
    const m = c.metrics || {};
    return h("div", { class: "card clip" },
      h("div", { class: "row" }, h("strong", {}, c.id), chip(c.status), rightsChip(c.rights)),
      c.file ? h("video", { src: "/" + c.file, controls: true, preload: "none", poster: c.thumb ? "/" + c.thumb : null, playsinline: true }) : null,
      h("div", { class: "hook" }, c.hook || ""),
      c.status === "failed" ? h("div", { class: "issues" }, c.error || "") : null,
      h("div", { class: "caption-box" }, c.caption || ""),
      c.status === "posted" ? h("div", { class: "meta" }, `${fmt(m.views)} views · ${fmt(m.likes)} likes · ${fmt(m.comments)} comments · ${fmt(m.shares)} shares`,
        c.est_earnings != null ? ` · ${money(c.est_earnings)}` : "", c.tiktok_url ? h("a", { href: c.tiktok_url, target: "_blank", rel: "noopener" }, "TikTok ↗") : null) : null,
      h("div", { class: "actions" },
        c.file ? h("a", { class: "btn", href: "/" + c.file, download: `${c.id}.mp4` }, "Download") : null,
        h("button", { class: "btn", onclick: () => copy(c.caption) }, "Copy caption"),
        c.status === "approved" ? h("button", { class: "btn primary", onclick: () => markPosted(c) }, "Mark posted") : null,
        ["approved", "rejected"].includes(c.status) ? h("button", { class: "btn", onclick: () => act(() => api(`/api/clips/${c.id}`, { action: "unreview" }), "Back to review") }, "Back to review") : null));
  })));
}

// ---------------------------------------------------------------- Scout
async function viewScout() {
  const st = S.state;
  const cands = await api(`/api/candidates?status=${S.scoutFilter}&limit=150`);
  const src = await api("/api/sources");
  const filters = [["needs_rights", "Needs your call"], ["needs_rights,new,queued", "Open"], ["processed", "Processed"], ["skipped,failed", "Skipped/failed"]];
  const head = h("div", { class: "section-head" }, h("h1", {}, "Scout"),
    h("span", { class: "muted" }, `${st.candidates.total} sources tracked`), h("span", { class: "spacer" }),
    filters.map(([v, l]) => h("button", { class: "btn sm" + (S.scoutFilter === v ? " primary" : ""), onclick: () => { S.scoutFilter = v; renderTab(); } }, l)),
    h("button", { class: "btn sm", onclick: () => runJob("scout") }, "Scout now"));

  const campaigns = src.campaigns || [];
  const url = h("input", { type: "url", placeholder: "YouTube / Twitch / direct video URL", style: { flex: "1", minWidth: "240px" } });
  const start = h("input", { type: "number", placeholder: "start s", style: { width: "90px" } });
  const end = h("input", { type: "number", placeholder: "end s", style: { width: "90px" } });
  const rsel = h("select", { "aria-label": "Rights for this link" }, [["unverified", "no permission yet (my call)"], ["campaign", "campaign"], ["permission", "permission"], ["own", "my own footage"], ["official", "official"]].map(([v, l]) => h("option", { value: v }, l)));
  const csel = h("select", {}, h("option", { value: "" }, "no campaign"), campaigns.map((c) => h("option", { value: c.id }, c.name)));
  const manual = h("div", { class: "card" }, h("h2", {}, "Clip a link you found", h("small", {}, "paste any YouTube or Twitch video, a campaign source link, or a file path")),
    h("div", { class: "row" }, url, start, end, rsel, csel,
      h("button", { class: "btn primary", onclick: () => {
        if (!url.value) return toast("Paste a URL", true);
        runJob("clip_url", { url: url.value, start: start.value ? +start.value : null, end: end.value ? +end.value : null, rights: rsel.value, campaign_id: csel.value || null });
      } }, "Clip it")),
    h("p", { class: "muted", style: { fontSize: "12px", marginBottom: 0 } }, "Leave start/end blank and the farm finds the best 1–2 moments itself. Clips land in Review; a link you paste is clipped whatever its rights label, so that call is yours."));

  const trend = st.trend_queries.length ? h("div", { class: "callout good" }, "Claude trend queries in rotation: ", st.trend_queries.join(" · "),
    " ", h("button", { class: "btn sm", onclick: () => runJob("trends") }, "Refresh")) : null;

  const policy = h("div", { class: "callout" },
    h("strong", {}, "Rights gate: "), `auto-clipped levels = ${(src.policy.auto_render || []).join(", ")}. `,
    "Unverified sources wait here. Join a creator's clipping program (Whop/Content Rewards) or get permission, then “Trust channel” so all their uploads flow automatically. Re-uploading creators without a program risks DMCA strikes and TikTok’s unoriginal-content suppression.");

  const table = !cands.length ? h("div", { class: "empty" }, "No candidates in this view.") : h("div", { class: "card table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["", "Source", "Channel", "Views", "Velocity/h", "Age", "Score", "Rights", "Status", ""].map((t, i) => h("th", { class: [3, 4, 5, 6].includes(i) ? "num" : "" }, t)))),
    h("tbody", {}, cands.map((c) => {
      const sel = h("select", { "aria-label": "rights", onchange: (e) => act(() => api(`/api/candidates/${encodeURIComponent(c.id)}`, { rights: e.target.value }), "Rights updated") },
        ["unverified", "campaign", "permission", "own", "official", "blocked"].map((r) => h("option", { value: r, selected: r === c.rights }, r)));
      return h("tr", {},
        h("td", {}, c.thumbnail ? h("img", { class: "thumb", src: c.thumbnail, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }) : null),
        h("td", {}, h("a", { class: "title", href: c.url, target: "_blank", rel: "noopener", title: c.title }, c.title || c.url),
          h("span", { class: "muted", style: { fontSize: "12px" } }, `${c.platform}${c.duration ? " · " + mmss(c.duration) : ""}${c.query ? " · q: " + c.query : ""}`)),
        h("td", {}, c.channel || "—"),
        h("td", { class: "num" }, fmt(c.views)), h("td", { class: "num" }, fmt(c.velocity)),
        h("td", { class: "num" }, c.age_hours != null ? `${Math.round(c.age_hours)}h` : "—"),
        h("td", { class: "num" }, c.score ?? "—"),
        h("td", {}, sel), h("td", {}, chip(c.status)),
        h("td", {}, h("div", { class: "row", style: { flexWrap: "nowrap" } },
          h("button", { class: "btn sm primary", onclick: () => act(() => api(`/api/candidates/${encodeURIComponent(c.id)}`, { action: "queue" }).then(() => api("/api/jobs", { type: "produce", params: { max_renders: 2 } })), "Queued — producing") }, "Clip"),
          c.channel ? h("button", { class: "btn sm", title: "Mark this channel as clipping-program/permission: all its uploads auto-clip", onclick: () => act(() => api(`/api/candidates/${encodeURIComponent(c.id)}`, { rights: "permission", apply_channel: true }), `${c.channel} trusted`) }, "Trust channel") : null,
          h("button", { class: "btn sm", onclick: () => act(() => api(`/api/candidates/${encodeURIComponent(c.id)}`, { action: "skip" })) }, "Skip"))));
    }))));
  return h("div", { class: "grid" }, head, policy, trend, manual, table);
}

// ---------------------------------------------------------------- Analytics
async function viewAnalytics() {
  const a = await api("/api/analytics");
  const st = S.state;
  const head = h("div", { class: "section-head" }, h("h1", {}, "TikTok analytics"),
    h("span", { class: "muted" }, st.kpis.last_metrics_at ? `last pull ${ago(st.kpis.last_metrics_at)} via ${st.kpis.metrics_source}` : "no metrics pulled yet"),
    h("span", { class: "spacer" }),
    h("button", { class: "btn primary", onclick: () => runJob("metrics") }, "Pull metrics now"),
    h("label", { class: "btn", title: "TikTok Studio export (CSV)" }, "Import CSV",
      h("input", { type: "file", accept: ".csv,text/csv", hidden: true, onchange: async (e) => {
        const f = e.target.files[0]; if (!f) return;
        act(async () => api("/api/import-csv", await f.text()), "CSV imported");
      } })),
    st.tiktok_api.configured ? h("a", { class: "btn", href: "/auth/tiktok" }, st.tiktok_api.connected ? "Reconnect TikTok API" : "Connect TikTok API") : null);

  const daily = a.daily;
  const acct = (a.account || []).filter((x) => x.total_views != null);
  const charts = h("div", { class: "grid two" },
    h("div", { class: "card" }, h("h3", {}, "Views by posting day", h("small", {}, "views on clips posted that day, last 30d")),
      barChart(daily.map((d) => ({ x: d.date.slice(5), y: d.views, tip: `${d.posts} posts` })), fmt)),
    h("div", { class: "card" }, h("h3", {}, "Posts per day", h("small", {}, "last 30 days")),
      barChart(daily.map((d) => ({ x: d.date.slice(5), y: d.posts })), (v) => String(v))),
    h("div", { class: "card" }, h("h3", {}, "Account total views", h("small", {}, "from each metrics pull")),
      acct.length >= 2 ? lineChart(acct.map((x) => ({ x: new Date(x.ts), y: x.total_views }))) : h("div", { class: "empty" }, "Needs 2+ metrics pulls.")),
    h("div", { class: "card" }, h("h3", {}, "Views by source creator"),
      a.by_channel.length ? hbars(a.by_channel.slice(0, 10).map((r) => ({ label: r.channel, value: r.views, sub: `${r.posts} posts` }))) : h("div", { class: "empty" }, "No posted clips yet.")));

  const cols = [["thumb", ""], ["hook", "Clip"], ["channel", "Creator"], ["posted_at", "Posted"], ["views", "Views", 1], ["likes", "Likes", 1], ["comments", "Comm.", 1], ["shares", "Shares", 1], ["est_earnings", "Earned", 1]];
  const rows = [...a.clips].sort((x, y) => ((x[S.sort.key] ?? -1) > (y[S.sort.key] ?? -1) ? 1 : -1) * S.sort.dir);
  const table = h("div", { class: "card table-wrap" }, h("h3", {}, "Per-clip performance"),
    rows.length ? h("table", {},
      h("thead", {}, h("tr", {}, cols.map(([k, l, num]) => h("th", { class: (num ? "num " : "") + (k !== "thumb" ? "sortable" : ""),
        onclick: () => { if (k === "thumb") return; S.sort = { key: k, dir: S.sort.key === k ? -S.sort.dir : -1 }; renderTab(); } }, l + (S.sort.key === k ? (S.sort.dir < 0 ? " ↓" : " ↑") : ""))))),
      h("tbody", {}, rows.map((r) => h("tr", {},
        h("td", {}, r.thumb ? h("img", { class: "thumb v", src: "/" + r.thumb, alt: "" }) : null),
        h("td", {}, r.tiktok_url ? h("a", { class: "title", href: r.tiktok_url, target: "_blank", rel: "noopener" }, r.hook || r.id) : h("span", { class: "title" }, r.hook || r.id)),
        h("td", {}, r.channel || "—"), h("td", {}, ago(r.posted_at)),
        h("td", { class: "num" }, fmt(r.views)), h("td", { class: "num" }, fmt(r.likes)), h("td", { class: "num" }, fmt(r.comments)),
        h("td", { class: "num" }, fmt(r.shares)), h("td", { class: "num" }, money(r.est_earnings)))))) : h("div", { class: "empty" }, "Mark clips as posted, then pull metrics."));
  return h("div", { class: "grid" }, head, charts, table);
}

// --- charts: single-series SVG with hover tooltips (values also in the table/tiles) ---
function barChart(data, f) {
  const W = 560, H = 200, L = 44, B = 22, T = 8;
  const max = Math.max(1, ...data.map((d) => d.y));
  const bw = (W - L) / data.length;
  const wrap = h("div", { class: "chart" });
  const tip = h("div", { class: "tooltip", hidden: true });
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "bar chart" });
  [0, 0.5, 1].forEach((t) => {
    const y = T + (H - B - T) * (1 - t);
    svg.append(svgEl("line", { class: "grid-line", x1: L, x2: W, y1: y, y2: y }));
    svg.append(svgText(f(max * t), L - 6, y + 4, "end"));
  });
  data.forEach((d, i) => {
    const bh = ((H - B - T) * d.y) / max;
    const x = L + i * bw + 1, w = Math.max(bw - 2, 1), y = H - B - bh;
    const r = Math.min(4, w / 2, bh);
    const path = bh > 0 ? `M${x},${H - B} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${H - B} Z` : "";
    const bar = svgEl("path", { class: "bar", d: path });
    const hit = svgEl("rect", { x: L + i * bw, y: T, width: bw, height: H - B - T, fill: "transparent", tabindex: 0 });
    const show = () => { bar.classList.add("hot"); tip.hidden = false; tip.replaceChildren(h("strong", {}, f(d.y)), `${d.x}${d.tip ? " · " + d.tip : ""}`);
      tip.style.left = `${((L + i * bw + bw / 2) / W) * 100}%`; tip.style.top = "0"; tip.style.transform = "translate(-50%, -100%)"; };
    const hide = () => { bar.classList.remove("hot"); tip.hidden = true; };
    hit.addEventListener("pointerenter", show); hit.addEventListener("focus", show);
    hit.addEventListener("pointerleave", hide); hit.addEventListener("blur", hide);
    svg.append(bar, hit);
    if (i % Math.ceil(data.length / 6) === 0) svg.append(svgText(d.x, L + i * bw + bw / 2, H - 6, "middle"));
  });
  wrap.append(svg, tip);
  return wrap;
}
function lineChart(data) {
  const W = 560, H = 200, L = 48, B = 22, T = 10;
  const xs = data.map((d) => d.x.getTime()), x0 = Math.min(...xs), x1 = Math.max(...xs);
  const ymin = Math.min(...data.map((d) => d.y)), ymax = Math.max(...data.map((d) => d.y));
  const yr = Math.max(1, ymax - ymin);
  const X = (t) => L + ((W - L) * (t - x0)) / Math.max(1, x1 - x0);
  const Y = (v) => T + (H - B - T) * (1 - (v - ymin) / yr);
  const wrap = h("div", { class: "chart" });
  const tip = h("div", { class: "tooltip", hidden: true });
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "line chart" });
  [0, 0.5, 1].forEach((t) => { const y = T + (H - B - T) * (1 - t);
    svg.append(svgEl("line", { class: "grid-line", x1: L, x2: W, y1: y, y2: y }), svgText(fmt(ymin + yr * t), L - 6, y + 4, "end")); });
  const pts = data.map((d) => `${X(d.x.getTime())},${Y(d.y)}`);
  svg.append(svgEl("path", { class: "area", d: `M${X(x0)},${H - B} L${pts.join(" L")} L${X(x1)},${H - B} Z` }));
  svg.append(svgEl("path", { class: "line", d: "M" + pts.join(" L") }));
  svg.append(svgText(data[0].x.toLocaleDateString(), L, H - 6, "start"), svgText(data[data.length - 1].x.toLocaleDateString(), W, H - 6, "end"));
  const cross = svgEl("line", { class: "cross", y1: T, y2: H - B, visibility: "hidden" });
  const dot = svgEl("circle", { class: "marker", r: 5, visibility: "hidden" });
  svg.append(cross, dot);
  svg.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect(); const px = ((e.clientX - r.left) / r.width) * W;
    let best = 0; data.forEach((d, i) => { if (Math.abs(X(d.x.getTime()) - px) < Math.abs(X(data[best].x.getTime()) - px)) best = i; });
    const d = data[best], cx = X(d.x.getTime()), cy = Y(d.y);
    cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", cx); dot.setAttribute("cy", cy); dot.setAttribute("visibility", "visible");
    tip.hidden = false; tip.replaceChildren(h("strong", {}, fmt(d.y)), d.x.toLocaleString());
    tip.style.left = `${(cx / W) * 100}%`; tip.style.top = "0"; tip.style.transform = "translate(-50%, -100%)";
  });
  svg.addEventListener("pointerleave", () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); });
  wrap.append(svg, tip);
  return wrap;
}
function hbars(rows) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return h("div", { class: "hbars" }, rows.map((r) => h("div", { class: "hrow", title: `${r.label}: ${r.value} views · ${r.sub}` },
    h("span", { class: "title" }, r.label), h("div", { class: "htrack" }, h("div", { class: "hfill", style: { width: `${(r.value / max) * 100}%` } })),
    h("span", { class: "hval" }, fmt(r.value)))));
}
const NS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs) { const el = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); return el; }
function svgText(t, x, y, anchor) { const el = svgEl("text", { x, y, "text-anchor": anchor, class: "axis-label" }); el.textContent = t; return el; }

// ---------------------------------------------------------------- Sources
async function viewSources() {
  const src = await api("/api/sources");
  const levels = ["campaign", "permission", "own", "official", "unverified", "blocked"];
  const chTable = h("div", { class: "card table-wrap" }, h("h2", {}, "Creators & channels", h("small", {}, "rights level applies to every upload from the channel")),
    h("table", {}, h("thead", {}, h("tr", {}, ["Platform", "Channel", "Rights", "Campaign", "Watch", "Layout", "Notes"].map((t) => h("th", {}, t)))),
      h("tbody", {}, src.channels.map((ch) => {
        const save = (patch) => act(() => api("/api/sources/channel", { ...ch, ...patch }), "Channel updated");
        return h("tr", {},
          h("td", {}, ch.platform), h("td", {}, ch.name || ch.login || ch.id),
          h("td", {}, h("select", { onchange: (e) => save({ rights: e.target.value }) }, levels.map((l) => h("option", { value: l, selected: l === ch.rights }, l)))),
          h("td", {}, h("select", { onchange: (e) => save({ campaign_id: e.target.value || null }) }, h("option", { value: "" }, "—"),
            (src.campaigns || []).map((c) => h("option", { value: c.id, selected: c.id === ch.campaign_id }, c.name)))),
          h("td", {}, ch.platform === "twitch" ? h("input", { type: "checkbox", checked: !!ch.watch, onchange: (e) => save({ watch: e.target.checked }) }) : "—"),
          h("td", {}, h("select", { onchange: (e) => save({ layout: e.target.value || null }) }, ["", "blurpad", "zoom", "split"].map((l) => h("option", { value: l, selected: (ch.layout || "") === l }, l || "default")))),
          h("td", { class: "muted" }, ch.notes || ""));
      }))));
  const plat = h("select", {}, ["twitch", "youtube", "kick"].map((p) => h("option", { value: p }, p)));
  const ident = h("input", { type: "text", placeholder: "login / channel id / name" });
  const lvl = h("select", {}, levels.map((l) => h("option", { value: l, selected: l === "permission" }, l)));
  const add = h("div", { class: "card" }, h("h3", {}, "Add creator"), h("div", { class: "row" }, plat, ident, lvl,
    h("button", { class: "btn primary", onclick: () => {
      if (!ident.value.trim()) return toast("Enter a channel", true);
      const v = ident.value.trim();
      act(() => api("/api/sources/channel", { platform: plat.value, id: v, login: plat.value === "twitch" ? v.toLowerCase() : null, name: v, rights: lvl.value, watch: plat.value === "twitch" }), "Creator added");
    } }, "Add")));

  const camps = h("div", { class: "card table-wrap" }, h("h2", {}, "Paid clipping campaigns", h("small", {}, "Whop / Content Rewards programs — earnings estimates use these rates")),
    (src.campaigns || []).length ? h("table", {}, h("thead", {}, h("tr", {}, ["Campaign", "Rate /1k", "Max/clip", "Status", "Requirements"].map((t) => h("th", {}, t)))),
      h("tbody", {}, src.campaigns.map((c) => h("tr", {}, h("td", {}, c.source ? h("a", { href: c.source, target: "_blank", rel: "noopener" }, c.name) : c.name),
        h("td", { class: "num" }, money(c.rate_per_1k)), h("td", { class: "num" }, money(c.max_per_clip)), h("td", {}, c.status), h("td", { class: "muted" }, c.requirements || ""))))) : h("div", { class: "empty" }, "No campaigns yet."));
  const cid = h("input", { type: "text", placeholder: "id (e.g. whop-xqc-gta6)" });
  const cname = h("input", { type: "text", placeholder: "name" });
  const crate = h("input", { type: "number", step: "0.01", placeholder: "$ per 1k views" });
  const cmax = h("input", { type: "number", step: "1", placeholder: "max $ per clip" });
  const addCamp = h("div", { class: "card" }, h("h3", {}, "Add campaign"), h("div", { class: "row" }, cid, cname, crate, cmax,
    h("button", { class: "btn primary", onclick: () => {
      if (!cid.value || !crate.value) return toast("id and rate required", true);
      act(() => api("/api/sources/campaign", { id: cid.value.trim(), name: cname.value || cid.value, rate_per_1k: +crate.value, max_per_clip: cmax.value ? +cmax.value : null, status: "active" }), "Campaign saved");
    } }, "Save")));
  return h("div", { class: "grid" }, h("div", { class: "section-head" }, h("h1", {}, "Sources & rights")), chTable, add, h("div", { class: "grid two" }, camps, addCamp));
}

// ---------------------------------------------------------------- Autopilot & activity
async function viewActivity() {
  const st = S.state, cfg = st.config;
  const jobs = await api("/api/jobs");
  const num = (path, val, step = 1) => h("input", { type: "number", step, value: val, onchange: (e) => patch(path, +e.target.value) });
  const patch = (path, value) => { const body = {}; let o = body; path.slice(0, -1).forEach((k) => (o = o[k] = {})); o[path[path.length - 1]] = value;
    act(() => api("/api/config", body), "Settings saved"); };
  const ap = cfg.autopilot || {}, cad = cfg.cadence || {};
  const phases = (cad.phases || []).map((p, i) => h("label", {}, `${p.name.replace("_", " ")} ${p.until ? "(→ " + p.until + ")" : "(after)"}`,
    h("input", { type: "number", min: 1, max: 10, value: p.posts_per_day, onchange: (e) => {
      const ph = cad.phases.map((x, j) => (j === i ? { ...x, posts_per_day: +e.target.value } : x)); patch(["cadence", "phases"], ph); } })));
  const settings = h("div", { class: "grid two" },
    h("div", { class: "card" }, h("h2", {}, "Autopilot", h("small", {}, "scheduler inside this server; never posts")),
      h("label", { class: "switch" }, h("input", { type: "checkbox", checked: !!ap.enabled, onchange: (e) => patch(["autopilot", "enabled"], e.target.checked) }), "Enabled"),
      h("div", { class: "form-grid", style: { marginTop: "12px" } },
        h("label", {}, "Scout every (h)", num(["autopilot", "scout_every_hours"], ap.scout_every_hours, 0.5)),
        h("label", {}, "Produce check every (h)", num(["autopilot", "produce_every_hours"], ap.produce_every_hours, 0.5)),
        h("label", {}, "Metrics every (h)", num(["autopilot", "metrics_every_hours"], ap.metrics_every_hours, 1)),
        h("label", {}, "Max renders / run", num(["produce", "max_renders_per_run"], cfg.produce.max_renders_per_run))),
      h("p", { class: "muted", style: { fontSize: "12px" } }, "Produce only runs when the planner says the queue is short, so autopilot can't overproduce.")),
    h("div", { class: "card" }, h("h2", {}, "Cadence", h("small", {}, "posts per day by phase")),
      h("div", { class: "form-grid" }, phases,
        h("label", {}, "Manual ± today", num(["cadence", "manual_offset"], cad.manual_offset || 0)),
        h("label", {}, "Max / creator / day", num(["cadence", "max_per_creator_per_day"], cad.max_per_creator_per_day))),
      h("label", { class: "switch", style: { marginTop: "12px" } }, h("input", { type: "checkbox", checked: !!(cad.auto_adjust || {}).apply,
        onchange: (e) => patch(["cadence", "auto_adjust", "apply"], e.target.checked) }), "Let the advisor adjust today's target (±1)")));

  const jobList = h("div", { class: "card" }, h("h2", {}, "Workflow runs"),
    h("div", { class: "row", style: { marginBottom: "10px" } }, ["scout", "produce", "metrics", "trends", "cycle"].map((t) => h("button", { class: "btn sm", onclick: () => runJob(t) }, `Run ${t}`))),
    jobs.length ? jobs.map((j) => h("details", { open: j.status === "running" || undefined },
      h("summary", {}, h("span", { class: `chip ${j.status === "done" ? "good" : j.status === "failed" ? "bad" : "accent"}` }, j.status), ` ${j.type} · ${ago(j.started_at)}`,
        j.result ? h("span", { class: "muted" }, " · " + JSON.stringify(j.result).slice(0, 140)) : null, j.error ? h("span", { class: "issues" }, " · " + j.error) : null),
      h("pre", { class: "log" }, (j.log || []).join("\n") || "(no log)"))) : h("div", { class: "empty" }, "No runs yet."));
  return h("div", { class: "grid" }, settings, jobList);
}

// ---------------------------------------------------------------- boot
document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
$("#cycle-btn").addEventListener("click", () => runJob("cycle"));
$("#autopilot-toggle").addEventListener("change", (e) => act(() => api("/api/config", { autopilot: { enabled: e.target.checked } }), `Autopilot ${e.target.checked ? "ON" : "OFF"}`));
$("#theme-btn").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("theme", next); } catch { /* storage unavailable */ }
});
try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch { /* ignore */ }
window.addEventListener("hashchange", () => { const t = location.hash.slice(1); if (TABS[t] && t !== S.tab) setTab(t); });
const initial = location.hash.slice(1);
if (TABS[initial]) S.tab = initial;
document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === S.tab));
refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 8000);
