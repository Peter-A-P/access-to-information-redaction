/* The live dashboard: /dashboard.json every five seconds, drawn the way the overview's
   charts are, with SVG built by the DOM API and every colour a class in style.css.

   The counts are the server's, across every visitor, and say nothing about anyone: how
   many of each kind of action, never the text acted on. */

"use strict";

const SVG = "http://www.w3.org/2000/svg";
const EVERY = 5000;

function el(name, attrs, text) {
  const node = document.createElementNS(SVG, name);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
  if (text !== undefined) node.textContent = text;
  return node;
}

function html(name, cls, text) {
  const node = document.createElement(name);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

const fmt = (n) => Number(n).toLocaleString();
const set = (id, text) => { const n = document.getElementById(id); if (n) n.textContent = text; };

const OUTCOMES = [
  ["withhold", "o-withhold", "Withheld"],
  ["escalate", "o-escalate", "Escalated"],
  ["release", "o-release", "Released"],
  ["add", "o-add", "Selected by hand"],
];

/* The categories by a name short enough for a chart label; the overview uses the same. */
const SHORT = {
  "The requester's own personal information": "The requester's own",
  "An official of a public body acting in that capacity": "Officials, in capacity",
  "Already publicly available": "Already public",
  "An individual dead more than twenty years": "Dead over twenty years",
  "Not personal information": "Not personal",
  "Third-party personal information": "Third parties",
};
const shortName = (name) => SHORT[name] || (name.length > 30 ? `${name.slice(0, 28)}...` : name);

function legend(hostId, items) {
  const host = document.getElementById(hostId);
  if (!host || host.childElementCount) return;
  for (const [, cls, label] of items) {
    const item = html("span", "legend-item");
    item.append(html("span", `swatch solid ${cls}`), document.createTextNode(label));
    host.append(item);
  }
}

function tiles(d) {
  set("t-visitors", fmt(d.visitors));
  set("t-live", fmt(d.live));
  set("t-decisions", fmt(d.decisions_total));
  set("t-pages", fmt(d.pages_completed));
  set("t-pdfs", d.pdfs.built ? `${fmt(d.pdfs.clean)} of ${fmt(d.pdfs.built)}` : "0");
  set("t-pdfs-caption", d.pdfs.built
    ? `released PDFs clean when leak-tested, over ${fmt(d.pdfs.boxes)} boxes; a PDF that fails is never sent`
    : "released PDFs so far; each is leak-tested before it is sent, and one that fails is never sent");
  set("t-spread", fmt(d.spread));
}

/* Decisions per minute over the last hour, stacked by outcome. */
function minutes(d) {
  const host = document.getElementById("minute-chart");
  const W = 720, H = 220, L = 40, R = 12, T = 12, B = 30;
  const rows = d.minutes;
  const totals = rows.map((m) => OUTCOMES.reduce((a, [k]) => a + (m[k] || 0), 0));
  const max = Math.max(4, ...totals);
  const bw = (W - L - R) / rows.length;
  const y = (v) => T + (H - T - B) * (1 - v / max);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Decisions per minute over the last hour" });
  const step = max > 40 ? 20 : max > 16 ? 10 : max > 8 ? 4 : 2;
  for (let t = 0; t <= max; t += step) {
    svg.append(el("line", { x1: L, x2: W - R, y1: y(t), y2: y(t), class: "gridline" }));
    svg.append(el("text", { x: L - 6, y: y(t) + 4, "text-anchor": "end", class: "tick" }, String(t)));
  }
  rows.forEach((m, i) => {
    let at = 0;
    for (const [k, cls] of OUTCOMES) {
      const v = m[k] || 0;
      if (!v) continue;
      const r = el("rect", { x: L + i * bw + 1, y: y(at + v), width: Math.max(1, bw - 2), height: y(at) - y(at + v), class: `bar ${cls}` });
      r.append(el("title", {}, `${new Date(m.t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}: ${v} ${k}`));
      svg.append(r);
      at += v;
    }
  });
  for (const i of [0, 15, 30, 45, rows.length - 1]) {
    if (!rows[i]) continue;
    const label = i === rows.length - 1 ? "now" : `${rows.length - 1 - i} min ago`;
    svg.append(el("text", { x: L + i * bw + bw / 2, y: H - 10, "text-anchor": "middle", class: "tick" }, label));
  }
  if (totals.every((t) => t === 0)) {
    svg.append(el("text", { x: (L + W - R) / 2, y: (T + H - B) / 2, "text-anchor": "middle", class: "empty-label halo" },
      "No decisions in the last hour. Review a record and they appear here."));
  }
  host.replaceChildren(svg);
  legend("minute-legend", OUTCOMES);
}

/* Agreement by category: of the proposals in each category that visitors decided, the share
   decided the way the tool proposed. */
function agreement(d) {
  const host = document.getElementById("agree-chart");
  const rows = Object.entries(d.by_code).filter(([, v]) => v.decided > 0 && v.direction !== "escalate");
  const W = 720, L = 260, R = 70, T = 6, barH = 18, gap = 12;
  const H = T + Math.max(1, rows.length) * (barH + gap) + 34;
  const x = (v) => L + (W - L - R) * (v / 100);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Share of decided proposals where visitors agreed with the tool, by category" });
  for (const t of [0, 25, 50, 75, 100]) {
    svg.append(el("line", { x1: x(t), x2: x(t), y1: T, y2: H - 34, class: "gridline" }));
    svg.append(el("text", { x: x(t), y: H - 18, "text-anchor": "middle", class: "tick" }, `${t}%`));
  }
  if (!rows.length) {
    svg.append(el("text", { x: (L + W - R) / 2, y: T + 22, "text-anchor": "middle", class: "empty-label halo" },
      "Nothing decided yet."));
  }
  rows.sort((a, b) => b[1].decided - a[1].decided).forEach(([code, v], i) => {
    const y0 = T + i * (barH + gap) + gap / 2;
    const share = (100 * v.agreed) / v.decided;
    svg.append(el("text", { x: L - 10, y: y0 + barH - 4, "text-anchor": "end", class: "row-label" }, `${code} ${shortName(v.name)}`));
    svg.append(el("rect", { x: L, y: y0, width: Math.max(1.5, x(share) - L), height: barH, rx: 2,
      class: `bar ${v.direction === "withhold" ? "o-withhold" : "o-release"}` }));
    svg.append(el("text", { x: x(share) + 6, y: y0 + barH - 4, class: "bar-value" }, `${share.toFixed(0)}% of ${fmt(v.decided)}`));
  });
  host.replaceChildren(svg);

  const body = document.querySelector("#agree-table tbody");
  body.replaceChildren();
  const WORDS = { withhold: "To withhold", release: "To release", escalate: "To withhold and escalate" };
  for (const [kind, v] of Object.entries(d.agreement)) {
    const tr = html("tr");
    tr.append(html("th", "", WORDS[kind] || kind));
    tr.firstChild.scope = "row";
    for (const n of [v.decided, v.withhold, v.release, v.escalate]) tr.append(html("td", "num", fmt(n)));
    body.append(tr);
  }
}

/* The released pages, counted apart: see the section's lead. */
function released(d) {
  const r = d.released;
  if (!r) return;
  set("r-decisions", fmt(r.decisions_total));
  set("r-withheld", fmt(r.decisions.withhold + r.decisions.escalate + r.decisions.add));
  set("r-pages", fmt(r.pages_completed));
  set("r-scans", fmt(d.pdfs.scans || 0));
  const body = document.querySelector("#released-table tbody");
  body.replaceChildren();
  const WORDS = { withhold: "To withhold", release: "To release", escalate: "To withhold and escalate" };
  for (const [kind, v] of Object.entries(r.agreement)) {
    const tr = html("tr");
    tr.append(html("th", "", WORDS[kind] || kind));
    tr.firstChild.scope = "row";
    for (const n of [v.decided, v.withhold, v.release, v.escalate]) tr.append(html("td", "num", fmt(n)));
    body.append(tr);
  }
  const t = r.tool;
  if (t && t.records) {
    set("released-tool", `On these ${t.records} records the tool proposed ${fmt(t.spans)} spans: ` +
      `${fmt(t.withhold)} to withhold, ${fmt(t.escalate)} to withhold and escalate, ` +
      `${fmt(t.release)} to release, and ${fmt(t.not_personal)} not personal information. ` +
      "Every one of them is text LAC released.");
  }
}

function tool(d) {
  const host = document.getElementById("tool-tiles");
  if (!host || host.childElementCount) return;
  const t = d.tool;
  const items = [
    [fmt(t.spans), `spans proposed on ${t.records} records`, ""],
    [fmt(t.withhold), "proposed to withhold: a third party", ""],
    [fmt(t.escalate), "withheld and escalated: the record does not say", ""],
    [fmt(t.release), "proposed to release: the requester, officials, the public", ""],
    [fmt(t.not_personal), "not personal information at all", ""],
  ];
  for (const [figure, caption, cls] of items) {
    const s = html("div", `stat ${cls}`);
    s.append(html("span", "figure", figure), html("span", "caption", caption));
    host.append(s);
  }
}

let failures = 0;

async function tick() {
  const status = document.getElementById("status");
  try {
    const r = await fetch("/dashboard.json", { credentials: "same-origin", cache: "no-store" });
    if (!r.ok) throw new Error(String(r.status));
    const d = await r.json();
    failures = 0;
    document.getElementById("failure").hidden = true;
    tiles(d);
    minutes(d);
    agreement(d);
    released(d);
    tool(d);
    const since = new Date(d.since).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
    status.replaceChildren(html("span", "pulse"), document.createTextNode(
      ` Live: counting since ${since}, last updated at ${new Date(d.now).toLocaleTimeString()}`));
  } catch (err) {
    failures += 1;
    if (failures > 1) {
      const box = document.getElementById("failure");
      box.textContent = "The server is not answering just now; the counts shown are the last ones it sent.";
      box.hidden = false;
    }
  }
}

tick();
setInterval(() => { if (!document.hidden) tick(); }, EVERY);
