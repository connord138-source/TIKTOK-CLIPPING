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
  try { const r = await fn(); if (ok) toast(ok); await refresh(true); return r; }
  catch (e) { toast(e.message, true); }
}
const runJob = (type, params) => act(() => api("/api/jobs", { type, params }), `Started ${type}`);

const STATUS = {
  rendered: ["warn", "needs review"], approved: ["good", "ready to post"], posted: ["info", "posted"],
  drafted: ["accent", "in TikTok drafts"], sending: ["accent", "sending to TikTok"],
  rejected: ["neutral", "rejected"], failed: ["bad", "failed"], rendering: ["accent", "rendering"],
  new: ["neutral", "new"], queued: ["accent", "queued"], processing: ["accent", "processing"],
  processed: ["good", "processed"], skipped: ["neutral", "skipped"], needs_rights: ["warn", "needs your call"],
};
const chip = (s) => { const [c, label] = STATUS[s] || ["neutral", s || "?"]; return h("span", { class: `chip ${c}` }, label); };
const RIGHTS = { campaign: "good", permission: "good", own: "good", official: "info", unverified: "warn", blocked: "bad" };
const rightsChip = (r) => h("span", { class: `chip ${RIGHTS[r] || "neutral"}`, title: "rights level" }, r || "unverified");

// ---------------------------------------------------------------- state
const S = { tab: "today", state: null, libFilter: "approved,drafted", scoutFilter: "needs_rights,new,queued", sort: { key: "views", dir: -1 } };

async function refresh(force = false) {
  try { S.state = await api("/api/state"); } catch (e) { toast("Server unreachable: " + e.message, true); return; }
  renderChrome();
  await renderTab(force);
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
const TABS = { today: viewToday, review: viewReview, library: viewLibrary, scout: viewScout, analytics: viewAnalytics, sources: viewSources, activity: viewActivity, connections: viewConnections };
async function renderTab(force = false) {
  const view = $("#view");
  if (!force) {  // background refresh: never wipe typing, edits not yet saved, or a playing video
    const focused = document.activeElement;
    if (focused && view.contains(focused) && ["INPUT", "TEXTAREA", "SELECT"].includes(focused.tagName)) return;
    if (view.querySelector("[data-dirty]")) return;
    if ([...view.querySelectorAll("video")].some((v) => !v.paused)) return;
  }
  const node = await TABS[S.tab]();
  view.replaceChildren(node);
}
function setTab(t) {
  S.tab = t; location.hash = t;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === t));
  renderTab(true);
}

// ---------------------------------------------------------------- Today
async function viewToday() {
  const st = S.state, p = st.plan, k = st.kpis;
  const clips = await api("/api/clips?status=approved,drafted,posted");
  const byId = Object.fromEntries(clips.map((c) => [c.id, c]));
  const pct = Math.min(100, Math.round((p.posted_today / Math.max(p.target, 1)) * 100));

  const tiles = h("div", { class: "grid kpis" },
    kpi("Posted today", `${p.posted_today}/${p.target}`, `${p.phase.replace("_", " ")} phase`, pct),
    kpi("Ready to post", p.ready, `${p.in_drafts || 0} in TikTok drafts · ${p.in_review} awaiting review`),
    kpi("Total views", fmt(k.views), `${k.posted} posts · avg ${fmt(k.avg_views)}`),
    kpi("Followers", fmt(k.followers), k.last_metrics_at ? `metrics ${ago(k.last_metrics_at)}` : "pull metrics →"),
    kpi("Est. campaign earnings", money(k.earnings), "after platform fee"),
  );

  const slotBoard = h("div", { class: "slots" }, p.slots.map((s) => {
    const c = s.clip_id && byId[s.clip_id];
    const label = { posted: ["info", "posted"], missed: ["neutral", "missed"], assigned: ["good", s.due ? "post now" : "assigned"], empty: ["warn", "empty"] }[s.state];
    if (s.in_drafts) { label[0] = "accent"; label[1] = s.due ? "post from drafts" : "in TikTok drafts"; }
    return h("div", { class: "slot" + (s.due && s.state === "assigned" ? " due" : "") },
      h("div", { class: "row" }, h("span", { class: "time" }, s.time), h("span", { class: `chip ${label[0]}` }, label[1])),
      c && c.thumb ? h("img", { src: "/" + c.thumb, alt: c.hook || "" }) : null,
      c ? h("div", { class: "muted", style: { fontSize: "12px", marginTop: "6px" } }, c.hook) : null,
      c && s.state === "assigned" ? h("div", { class: "row", style: { marginTop: "8px" } },
        sendBtn(c),
        s.in_drafts ? null : h("a", { class: "btn sm", href: "/" + c.file, download: `${c.id}.mp4` }, "Download"),
        h("button", { class: "btn sm", onclick: () => copy(c.caption) }, "Copy caption"),
        h("button", { class: "btn sm" + (s.in_drafts ? " primary" : ""), onclick: () => markPosted(c) }, "Posted")) : null,
      c ? draftError(c) : null,
      c && s.in_drafts ? h("div", { class: "muted", style: { fontSize: "12px", marginTop: "6px" } }, "In your TikTok inbox. Open TikTok, tap the notification, paste the caption, post.") : null);
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

  return h("div", { class: "grid" }, fullAutoCard(), tiles,
    h("div", { class: "card" }, h("h2", {}, `Today's slots`, h("small", {}, `${p.date} · ${p.timezone}`)), slotBoard,
      h("div", { class: "row", style: { marginTop: "12px" } },
        st.tiktok_api.can_upload
          ? [h("button", { class: "btn", onclick: () => runJob("send_drafts") }, "Send all ready clips to TikTok drafts"),
             h("span", { class: "muted", style: { fontSize: "12px" } }, `TikTok allows ${st.tiktok_api.pending_cap} unposted drafts per 24 hours (${st.tiktok_api.pending_24h} waiting now).`)]
          : h("span", { class: "muted", style: { fontSize: "12px" } }, "Want clips sent straight to your TikTok drafts? Do the one-time setup in ",
              h("a", { href: "#connections" }, "Connections"), "."))),
    h("div", { class: "grid two" }, prod, advice));
}
// "Full auto" = four switches the user owns. Nothing here ever posts: clips stop at TikTok drafts.
function autoFlags() {
  const c = S.state.config;
  return { autopilot: !!(c.autopilot || {}).enabled, any: !!(c.produce || {}).include_unverified,
           approve: !!((c.produce || {}).auto_approve || {}).enabled, send: !!(c.tiktok || {}).auto_send };
}
const setAuto = (on) => api("/api/config", { autopilot: { enabled: on }, produce: { include_unverified: on, auto_approve: { enabled: on } }, tiktok: { auto_send: on } });
function fullAutoCard() {
  const st = S.state, f = autoFlags(), on = f.autopilot && f.any && f.approve && f.send, some = f.autopilot || f.any || f.approve || f.send;
  const notes = [
    st.brain ? null : "No Claude key saved: clips are picked and approved by simple rules, without a visual check. Add the key in Connections.",
    st.tiktok_api.can_upload ? null : "TikTok is not connected: clips will be made and approved but not sent to your drafts. Connect it in Connections.",
  ].filter(Boolean);
  if (on) return h("div", { class: "card" },
    h("h2", {}, "Full auto is on ", h("span", { class: "chip good" }, "running")),
    h("p", {}, "Every 2 hours it looks for trending GTA 6 videos, cuts clips, has Claude check each one, and sends up to 5 a day to your TikTok drafts."),
    h("p", {}, h("strong", {}, "Your part: "), "open TikTok, tap the inbox notification, paste the caption, post."),
    notes.map((n) => h("div", { class: "callout", style: { marginBottom: "8px" } }, n)),
    h("div", { class: "row" },
      h("button", { class: "btn", onclick: () => runJob("cycle") }, "Run a round now"),
      h("button", { class: "btn danger", onclick: () => act(() => setAuto(false), "Full auto is off") }, "Turn off")));
  return h("div", { class: "card" },
    h("h2", {}, "Do it all for me", some ? h("small", {}, "partly on: see Autopilot & activity") : null),
    h("p", {}, "One switch: the farm finds trending GTA 6 videos, cuts clips, has Claude check them, approves the good ones and sends them to your TikTok drafts. You only post them in TikTok."),
    h("div", { class: "row" },
      h("button", { class: "btn primary", onclick: () => {
        const ok = confirm("Turn on full auto?\n\n" +
          "• It clips trending GTA 6 videos from ANY creator, including ones you have no permission from. Copyright complaints and strikes on your TikTok account are your risk.\n" +
          "• Clips are approved by Claude's check, without you watching them first.\n" +
          "• Up to 5 clips a day are sent to your TikTok drafts.\n" +
          "• Nothing is ever posted for you. You post from TikTok.\n\nYou can turn it off at any time.");
        if (ok) act(() => setAuto(true).then(() => api("/api/jobs", { type: "cycle" })), "Full auto is on. First round started.");
      } }, "Turn on full auto")));
}

function sendBtn(c, cls = "btn sm primary") {
  if (c.status !== "approved") return null;
  if (c.sending) return h("button", { class: cls, disabled: true }, "Sending…");
  if (!S.state.tiktok_api.can_upload) return h("button", { class: cls.replace(" primary", ""), title: "One-time setup in the Connections tab", onclick: () => setTab("connections") }, "Connect TikTok to send");
  return h("button", { class: cls, title: "Upload this clip to your TikTok drafts", onclick: () => act(() => api(`/api/clips/${c.id}`, { action: "send_to_drafts" }), `Sending ${c.id} to your TikTok drafts`) }, "Send to TikTok drafts");
}
const draftError = (c) => c.draft_error ? h("div", { class: "issues", style: { marginTop: "6px" } }, "Not sent: " + c.draft_error) : null;

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
    c.review && c.review.reason ? h("div", { class: "why" }, `Claude's check (${c.review.quality}/100): ${c.review.reason}`) : null,
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
  const filters = [["approved,drafted", "Ready to post"], ["posted", "Posted"], ["rejected", "Rejected"], ["failed", "Failed"], ["approved,drafted,posted,rejected,failed,rendered", "All"]];
  const head = h("div", { class: "section-head" }, h("h1", {}, "Clip library"), h("span", { class: "spacer" }),
    filters.map(([v, l]) => h("button", { class: "btn sm" + (S.libFilter === v ? " primary" : ""), onclick: () => { S.libFilter = v; renderTab(true); } }, l)));
  if (!clips.length) return h("div", {}, head, h("div", { class: "empty" }, "No clips here yet."));
  return h("div", {}, head, h("div", { class: "grid clips" }, clips.map((c) => {
    const m = c.metrics || {};
    return h("div", { class: "card clip" },
      h("div", { class: "row" }, h("strong", {}, c.id), chip(c.sending ? "sending" : c.status), rightsChip(c.rights)),
      c.file ? h("video", { src: "/" + c.file, controls: true, preload: "none", poster: c.thumb ? "/" + c.thumb : null, playsinline: true }) : null,
      h("div", { class: "hook" }, c.hook || ""),
      c.status === "failed" ? h("div", { class: "issues" }, c.error || "") : null,
      draftError(c),
      h("div", { class: "caption-box" }, c.caption || ""),
      c.status === "posted" ? h("div", { class: "meta" }, `${fmt(m.views)} views · ${fmt(m.likes)} likes · ${fmt(m.comments)} comments · ${fmt(m.shares)} shares`,
        c.est_earnings != null ? ` · ${money(c.est_earnings)}` : "", c.tiktok_url ? h("a", { href: c.tiktok_url, target: "_blank", rel: "noopener" }, "TikTok ↗") : null) : null,
      h("div", { class: "actions" },
        sendBtn(c, "btn primary"),
        c.file ? h("a", { class: "btn", href: "/" + c.file, download: `${c.id}.mp4` }, "Download") : null,
        h("button", { class: "btn", onclick: () => copy(c.caption) }, "Copy caption"),
        ["approved", "drafted"].includes(c.status) ? h("button", { class: "btn", onclick: () => markPosted(c) }, "Mark posted") : null,
        ["approved", "rejected"].includes(c.status) ? h("button", { class: "btn", onclick: () => act(() => api(`/api/clips/${c.id}`, { action: "unreview" }), "Back to review") }, "Back to review") : null));
  })));
}

// ---------------------------------------------------------------- Scout
async function viewScout() {
  const st = S.state;
  const cands = await api(`/api/candidates?status=${S.scoutFilter}&limit=150`);
  const src = await api("/api/sources");
  const mine = await api("/api/candidates?manual=1&limit=5");
  const filters = [["needs_rights", "Needs your call"], ["needs_rights,new,queued", "Open"], ["processed", "Processed"], ["skipped,failed", "Skipped/failed"]];
  const head = h("div", { class: "section-head" }, h("h1", {}, "Scout"),
    h("span", { class: "muted" }, `${st.candidates.total} sources tracked`), h("span", { class: "spacer" }),
    filters.map(([v, l]) => h("button", { class: "btn sm" + (S.scoutFilter === v ? " primary" : ""), onclick: () => { S.scoutFilter = v; renderTab(true); } }, l)),
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
  const LINK = { queued: "waiting to start", processing: "working on it…", processed: "done", skipped: "no clip made", failed: "failed" };
  const myLinks = mine.length ? h("div", { class: "card" }, h("h3", {}, "Links you pasted"),
    mine.map((c) => h("div", { class: "row", style: { margin: "6px 0" } }, chip(c.status),
      h("a", { class: "title", href: c.url, target: "_blank", rel: "noopener" }, c.title || c.url),
      h("span", { class: "muted", style: { fontSize: "12px" } },
        c.status === "processed" ? `${(c.clip_ids || []).length} clip(s) made: see Review` : (c.notes || LINK[c.status] || ""))))) : null;
  return h("div", { class: "grid" }, head, policy, trend, manual, myLinks, table);
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
    h("button", { class: "btn", onclick: () => setTab("connections") }, st.tiktok_api.connected ? "TikTok connected" : "Connect TikTok"));

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
        onclick: () => { if (k === "thumb") return; S.sort = { key: k, dir: S.sort.key === k ? -S.sort.dir : -1 }; renderTab(true); } }, l + (S.sort.key === k ? (S.sort.dir < 0 ? " ↓" : " ↑") : ""))))),
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
  const f = autoFlags();
  const sw = (label, checked, path, note) => h("div", { style: { margin: "10px 0" } },
    h("label", { class: "switch" }, h("input", { type: "checkbox", checked, onchange: (e) => patch(path, e.target.checked) }), label),
    note ? h("div", { class: "muted", style: { fontSize: "12px", marginLeft: "46px" } }, note) : null);
  const auto = h("div", { class: "card" }, h("h2", {}, "Full auto switches", h("small", {}, "the Today tab's big button flips all four")),
    sw("Find and make clips on a schedule (autopilot)", f.autopilot, ["autopilot", "enabled"]),
    sw("Clip trending videos from any creator", f.any, ["produce", "include_unverified"], "Includes creators you have no permission from. Copyright complaints and strikes are your risk. Off = only campaign, permission and your own footage."),
    sw("Approve clips automatically", f.approve, ["produce", "auto_approve", "enabled"], "Claude looks at frames from each clip and approves or rejects it. Off = everything waits in Review."),
    sw("Send approved clips to my TikTok drafts automatically", f.send, ["tiktok", "auto_send"], "Up to 5 unposted drafts at a time (TikTok's limit). It never posts."));
  return h("div", { class: "grid" }, auto, settings, jobList);
}

// ---------------------------------------------------------------- Connections
async function viewConnections() {
  const cn = await api("/api/connections");
  const t = cn.tiktok, k = cn.keys;
  const saveKeys = (keys, ok) => act(() => api("/api/connections", { keys }), ok);
  const keyState = (name) => k[name].set ? h("span", { class: "chip good" }, `saved ${k[name].hint || ""}`) : h("span", { class: "chip neutral" }, "not set");
  const secret = (ph) => h("input", { type: "password", placeholder: ph, autocomplete: "off", style: { flex: "1", minWidth: "220px" } });

  // TikTok
  const ck = secret("Client key"), cs = secret("Client secret");
  const uri = h("code", {}, t.redirect_uri);
  const ru = h("input", { type: "text", placeholder: "https://… (only if TikTok refuses the address above)", style: { flex: "1", minWidth: "260px" } });
  const customUri = t.redirect_uri !== t.default_redirect_uri;
  const step = (n, ...kids) => h("li", { style: { margin: "10px 0" } }, ...kids);
  const tiktokCard = h("div", { class: "card" },
    h("h2", {}, "TikTok", h("small", {}, "send clips to your drafts in one click")),
    h("div", { class: "row" },
      t.can_upload ? h("span", { class: "chip good" }, "connected · can send drafts")
        : t.connected ? h("span", { class: "chip warn" }, "connected · no upload permission")
        : h("span", { class: "chip neutral" }, "not connected"),
      t.can_read_stats ? h("span", { class: "chip info" }, "stats permission") : null),
    cn.auth_message ? h("div", { class: "callout" + (cn.auth_message.ok ? " good" : ""), style: { marginTop: "10px" } }, cn.auth_message.text) : null,
    t.connected && !t.can_upload ? h("div", { class: "callout", style: { marginTop: "10px" } },
      "TikTok logged you in but did not grant video.upload. Add the Content Posting API product to your TikTok app, then connect again.") : null,
    h("ol", { style: { paddingLeft: "20px", margin: "12px 0 0" } },
      step(1, "Create a TikTok developer app at ", h("a", { href: "https://developers.tiktok.com/apps", target: "_blank", rel: "noopener" }, "developers.tiktok.com"),
        ". Add the products ", h("strong", {}, "Login Kit"), " and ", h("strong", {}, "Content Posting API"), "."),
      step(2, "In the app's Login Kit settings, add this redirect URI exactly: ", uri, " ",
        h("button", { class: "btn sm", onclick: () => navigator.clipboard.writeText(t.redirect_uri).then(() => toast("Redirect URI copied"), () => toast("Copy failed", true)) }, "Copy"),
        h("div", { class: "row", style: { marginTop: "8px" } },
          h("span", { class: "muted", style: { fontSize: "12px" } }, "Different redirect address:"), ru,
          h("button", { class: "btn sm", onclick: () => {
            const v = ru.value.trim();
            if (!/^https?:\/\/\S+$/.test(v)) return toast("Paste the full address, starting with https://", true);
            act(() => api("/api/config", { tiktok: { redirect_uri: v } }), "Redirect address saved");
          } }, "Save address"),
          customUri ? h("button", { class: "btn sm", onclick: () => act(() => api("/api/config", { tiktok: { redirect_uri: "" } }), "Back to the default address") }, "Use default") : null)),
      step(3, "In the app's Sandbox settings, add your TikTok account as a target user (or submit the app for review)."),
      step(4, "Paste the app's client key and secret: ", keyState("TIKTOK_CLIENT_KEY"),
        h("div", { class: "row", style: { marginTop: "8px" } }, ck, cs,
          h("button", { class: "btn primary", onclick: () => {
            if (!ck.value.trim() || !cs.value.trim()) return toast("Paste both the client key and the client secret", true);
            saveKeys({ TIKTOK_CLIENT_KEY: ck.value, TIKTOK_CLIENT_SECRET: cs.value }, "TikTok app keys saved");
          } }, "Save"))),
      step(5, t.configured ? h("a", { class: "btn primary", href: "/auth/tiktok" }, t.connected ? "Reconnect TikTok" : "Connect TikTok")
          : h("button", { class: "btn", disabled: true }, "Connect TikTok"),
        t.configured ? " Log in with the TikTok account you post from." : " Save the keys first.")),
    h("div", { class: "row", style: { marginTop: "8px" } },
      h("label", { class: "switch" }, h("input", { type: "checkbox", checked: !!(S.state.config.tiktok || {}).request_stats_scopes,
        onchange: (e) => act(() => api("/api/config", { tiktok: { request_stats_scopes: e.target.checked } }), "Saved. Reconnect TikTok to apply.") }),
        "Also ask for stats permissions (follower count in Analytics)"),
      t.connected ? h("button", { class: "btn sm danger", onclick: () => act(() => api("/api/tiktok/disconnect", {}), "TikTok disconnected") }, "Disconnect") : null),
    h("p", { class: "muted", style: { fontSize: "12px", marginBottom: 0 } },
      "Clips only ever go to your TikTok inbox as drafts. You add the caption and post in the TikTok app. TikTok allows 5 unposted drafts per 24 hours."));

  // Claude
  const ak = secret("sk-ant-…");
  const claudeCard = h("div", { class: "card" },
    h("h2", {}, "Claude API key", h("small", {}, "picks the best moments, writes hooks and captions")),
    h("div", { class: "row" }, keyState("ANTHROPIC_API_KEY"), k.ANTHROPIC_API_KEY.source ? h("span", { class: "muted" }, `from ${k.ANTHROPIC_API_KEY.source}`) : null,
      cn.brain ? null : h("span", { class: "muted" }, "Without a key the farm uses simpler rules.")),
    h("div", { class: "row", style: { marginTop: "10px" } }, ak,
      h("button", { class: "btn primary", onclick: () => ak.value.trim() ? saveKeys({ ANTHROPIC_API_KEY: ak.value }, "Claude key saved") : toast("Paste the key first", true) }, "Save"),
      k.ANTHROPIC_API_KEY.source === "dashboard" ? h("button", { class: "btn danger", onclick: () => saveKeys({ ANTHROPIC_API_KEY: "" }, "Claude key removed") }, "Remove") : null),
    h("p", { class: "muted", style: { fontSize: "12px", marginBottom: 0 } }, "Create one at console.anthropic.com → API Keys."));

  // Twitch
  const ti = secret("Client ID"), ts = secret("Client secret");
  const twitchCard = h("div", { class: "card" },
    h("h2", {}, "Twitch keys", h("small", {}, "optional: top GTA 6 clips across all of Twitch")),
    h("div", { class: "row" }, keyState("TWITCH_CLIENT_ID")),
    h("div", { class: "row", style: { marginTop: "10px" } }, ti, ts,
      h("button", { class: "btn primary", onclick: () => (ti.value.trim() && ts.value.trim()) ? saveKeys({ TWITCH_CLIENT_ID: ti.value, TWITCH_CLIENT_SECRET: ts.value }, "Twitch keys saved") : toast("Paste both values", true) }, "Save")),
    h("p", { class: "muted", style: { fontSize: "12px", marginBottom: 0 } }, "Register an app at dev.twitch.tv/console to get them."));

  // Phone page
  const ph = cn.phone;
  let qrImg = null;
  if (ph.enabled && ph.url && typeof qrcode === "function") {
    const qr = qrcode(0, "M"); qr.addData(ph.url); qr.make();
    qrImg = h("img", { src: qr.createDataURL(6, 12), alt: "QR code that opens the captions page on your phone", width: 220, height: 220, style: { borderRadius: "8px", background: "#fff" } });
  }
  const phoneCard = h("div", { class: "card" },
    h("h2", {}, "Captions on your phone", h("small", {}, "TikTok drafts arrive without a caption; this puts it one tap away")),
    h("label", { class: "switch" }, h("input", { type: "checkbox", checked: !!ph.enabled,
      onchange: (e) => act(() => api("/api/config", { phone: { enabled: e.target.checked } }), e.target.checked ? "Phone page is on" : "Phone page is off") }),
      "Let my phone open the captions page"),
    !ph.enabled ? h("p", { class: "muted", style: { fontSize: "13px" } }, "Turn this on, then scan the QR code that appears with your phone's camera.") : null,
    ph.enabled && !ph.listening_on_network ? h("div", { class: "callout", style: { marginTop: "10px" } }, "The farm was started in local-only mode. Stop it (Ctrl+C) and start it again with: python -m clipfarm serve") : null,
    ph.enabled && !ph.lan_ip ? h("div", { class: "callout", style: { marginTop: "10px" } }, "This computer doesn't seem to be on a network, so there is no address for your phone to open.") : null,
    ph.enabled && qrImg ? h("div", { class: "row", style: { marginTop: "12px", alignItems: "flex-start" } }, qrImg,
      h("ol", { style: { margin: 0, paddingLeft: "20px", flex: "1", minWidth: "240px" } },
        h("li", {}, "Connect your phone to the same Wi-Fi as this computer."),
        h("li", {}, "Open the phone's camera and point it at this code. Tap the link that appears."),
        h("li", {}, "Add the page to your home screen so it is one tap away next time."),
        h("li", {}, "If the page won't load: Windows asked whether to allow Python on your network when the farm started. It has to be allowed for private networks."),
        h("li", { class: "muted" }, "Only this captions page is visible to your phone. The rest of the dashboard stays on this computer."))) : null,
    ph.enabled && ph.url ? h("p", { class: "muted", style: { fontSize: "12px", marginBottom: 0 } }, "Or type this into the phone's browser: ", h("code", {}, ph.url)) : null);

  return h("div", { class: "grid" }, h("div", { class: "section-head" }, h("h1", {}, "Connections"),
    h("span", { class: "muted" }, "Keys are stored only on this computer (data/secrets, never committed).")),
    tiktokCard, phoneCard, h("div", { class: "grid two" }, claudeCard, twitchCard));
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
$("#view").addEventListener("input", (e) => { if (e.target.type !== "checkbox" && e.target.type !== "file") e.target.dataset.dirty = "1"; });
refresh(true);
setInterval(() => { if (!document.hidden) refresh(); }, 8000);
