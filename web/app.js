/* The overview's drawings, and the letter's reasons. No framework and no charting library,
   like the other project pages on peterparker.ca: SVG built with the DOM API, every colour a
   class in style.css, every piece of text set with textContent.

   Two requests to this server: data/site.json, written by `sever site` from the results
   files, and /dashboard.json, the live count of visitors' decisions. If the second fails the
   page says nothing about it; the line under the buttons is the only thing it feeds. */

"use strict";

const SVG = "http://www.w3.org/2000/svg";

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

function fail(message) {
  const box = document.getElementById("failure");
  if (!box) return;
  box.textContent = message;
  box.hidden = false;
}

async function getJson(path) {
  const r = await fetch(path, { credentials: "same-origin", cache: "no-cache" });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

const pct = (v) => `${v.toFixed(1)}%`;

function legend(hostId, items) {
  const host = document.getElementById(hostId);
  if (!host) return;
  host.replaceChildren();
  for (const [cls, label] of items) {
    const item = html("span", "legend-item");
    item.append(html("span", `swatch solid ${cls}`), document.createTextNode(label));
    host.append(item);
  }
}

/* An x axis along the bottom of a plot: gridlines, ticks and a title. */
function xAxis(svg, x, ticks, top, bottom, title, fmt) {
  for (const t of ticks) {
    svg.append(el("line", { x1: x(t), x2: x(t), y1: top, y2: bottom, class: "gridline" }));
    svg.append(el("text", { x: x(t), y: bottom + 16, "text-anchor": "middle", class: "tick" }, fmt(t)));
  }
  if (title) {
    svg.append(el("text", { x: (x(ticks[0]) + x(ticks[ticks.length - 1])) / 2, y: bottom + 34,
      "text-anchor": "middle", class: "axis-title" }, title));
  }
}

/* ------------------------------------------------------------------ the trade-off */

const SYSTEM_LABELS = {
  full: "The tool: rules, then Jev",
  rules: "The rules alone",
  model_only: "Jev alone, no rules",
  sentence: "Rules, no context",
  blunt: "Blunt privacy tool",
};

function drawTradeoff(systems) {
  const host = document.getElementById("tradeoff-chart");
  if (!host) return;
  const W = 720, H = 380, L = 56, R = 24, T = 18, B = 52;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": "Leak rate against over-redaction for five configurations" });
  const maxLeak = Math.max(...systems.map((s) => s.leak[2])) * 1.15;
  const x = (v) => L + (W - L - R) * (v / 100);
  const y = (v) => T + (H - T - B) * (1 - v / maxLeak);
  xAxis(svg, x, [0, 20, 40, 60, 80, 100], T, H - B, "Over-redaction: must be released, withheld", (t) => `${t}%`);
  const step = maxLeak > 12 ? 5 : 2;
  for (let t = 0; t <= maxLeak; t += step) {
    svg.append(el("line", { x1: L, x2: W - R, y1: y(t), y2: y(t), class: "gridline" }));
    svg.append(el("text", { x: L - 8, y: y(t) + 4, "text-anchor": "end", class: "tick" }, `${t}%`));
  }
  svg.append(el("text", { x: 14, y: (T + H - B) / 2, "text-anchor": "middle", class: "axis-title",
    transform: `rotate(-90 14 ${(T + H - B) / 2})` }, "Leak rate"));
  /* The corner nobody can reach without reading the record: low on both. */
  svg.append(el("rect", { x: x(0), y: y(maxLeak * 0.22), width: x(18) - x(0),
    height: y(0) - y(maxLeak * 0.22), class: "good-zone" }));
  svg.append(el("text", { x: x(1), y: y(0) - 8, class: "zone-label" }, "Better on both"));
  for (const s of systems) {
    const cls = `sys-${s.key}`;
    const g = el("g", { class: `system ${cls}`, tabindex: 0,
      "aria-label": `${SYSTEM_LABELS[s.key]}: leak ${pct(s.leak[0])}, over-redaction ${pct(s.over[0])}` });
    g.append(el("line", { x1: x(s.over[1]), x2: x(s.over[2]), y1: y(s.leak[0]), y2: y(s.leak[0]), class: "whisker" }));
    g.append(el("line", { x1: x(s.over[0]), x2: x(s.over[0]), y1: y(s.leak[1]), y2: y(s.leak[2]), class: "whisker" }));
    g.append(el("circle", { cx: x(s.over[0]), cy: y(s.leak[0]), r: s.key === "full" ? 7 : 5.5, class: "pt" }));
    /* The tool sits at the left edge, so its label goes to the right; the model alone sits
       close to it, so its label goes above. */
    const left = s.over[0] > 70;
    const dy = s.key === "model_only" ? -28 : -9;
    const tx = x(s.over[0]) + (left ? -12 : 12);
    g.append(el("text", { x: tx, y: y(s.leak[0]) + dy, "text-anchor": left ? "end" : "start",
      class: "pt-label halo" }, SYSTEM_LABELS[s.key]));
    g.append(el("text", { x: tx, y: y(s.leak[0]) + dy + 16, "text-anchor": left ? "end" : "start",
      class: "pt-sub halo" }, `${pct(s.leak[0])} leak, ${pct(s.over[0])} over`));
    svg.append(g);
  }
  host.replaceChildren(svg);
}

/* ------------------------------------------------------------------ bars with intervals */

/* Horizontal bars, one row per entry and one bar per series, each with its interval.
   rows: [{label, sub, values: {series: [v, lo, hi]}}]; series: [[key, cls, label]]. */
function hbars(hostId, rows, series, opts) {
  const host = document.getElementById(hostId);
  if (!host) return;
  const W = 720, L = opts.left || 190, R = 64, T = 8;
  const barH = 13, gap = 5, rowGap = 16;
  const rowH = series.length * (barH + gap) - gap;
  const H = T + rows.length * (rowH + rowGap) + 40;
  const max = opts.max || 100;
  const x = (v) => L + (W - L - R) * (Math.min(v, max) / max);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.label });
  const bottom = H - 40;
  xAxis(svg, x, opts.ticks || [0, 25, 50, 75, 100], T, bottom, opts.title, (t) => `${t}%`);
  rows.forEach((r, i) => {
    const top = T + i * (rowH + rowGap) + rowGap / 2;
    svg.append(el("text", { x: L - 12, y: top + rowH / 2 + (r.sub ? -2 : 4), "text-anchor": "end",
      class: "row-label" }, r.label));
    if (r.sub) {
      svg.append(el("text", { x: L - 12, y: top + rowH / 2 + 12, "text-anchor": "end",
        class: "row-note" }, r.sub));
    }
    series.forEach(([key, cls], j) => {
      const v = r.values[key];
      if (!v) return;
      const y0 = top + j * (barH + gap);
      svg.append(el("rect", { x: L, y: y0, width: Math.max(1.5, x(v[0]) - L), height: barH,
        rx: 2, class: `bar ${cls}` }));
      if (v.length > 2 && v[1] !== v[2]) {
        svg.append(el("line", { x1: x(v[1]), x2: x(v[2]), y1: y0 + barH / 2, y2: y0 + barH / 2,
          class: "whisker" }));
        for (const end of [v[1], v[2]]) {
          svg.append(el("line", { x1: x(end), x2: x(end), y1: y0 + 3, y2: y0 + barH - 3, class: "whisker" }));
        }
      }
      const tip = v.length > 2 ? v[2] : v[0];
      svg.append(el("text", { x: x(tip) + 6, y: y0 + barH - 2, class: "bar-value" },
        opts.fmt ? opts.fmt(v[0]) : pct(v[0])));
    });
  });
  host.replaceChildren(svg);
}

function drawCategories(data) {
  const names = data.code_names || {};
  const rows = Object.entries(data.per_code).map(([code, v]) => ({
    label: `${code} ${names[code] ? shortName(names[code]) : ""}`.trim(), values: { over: v },
  }));
  for (const [code, v] of Object.entries(data.per_code_leak)) {
    rows.push({ label: `${code} ${shortName(names[code] || "")}`.trim(), sub: "leak rate", values: { leak: v } });
  }
  hbars("category-chart", rows, [["over", "b-over"], ["leak", "b-leak"]], {
    left: 250, label: "Over-redaction by category, and the leak rate for third parties",
    title: "Withheld though it must be released (leak rate for R1)",
  });
}

function shortName(name) {
  const SHORT = {
    "The requester's own personal information": "The requester's own",
    "An official of a public body acting in that capacity": "Officials, in capacity",
    "Already publicly available": "Already public",
    "An individual dead more than twenty years": "Dead over twenty years",
    "Not personal information": "Not personal",
    "Third-party personal information": "Third parties",
  };
  return SHORT[name] || name;
}

/* ------------------------------------------------------------------ the leaks */

function drawLeaks(systems) {
  const host = document.getElementById("leak-chart");
  if (!host) return;
  const parts = [
    ["never_found", "seg-never", "Never found"],
    ["mislabelled", "seg-mislabel", "Found, called a place or an organisation"],
    ["box_short", "seg-short", "Box too short"],
    ["decision", "seg-decision", "The decision was wrong"],
  ];
  const order = ["full", "rules", "model_only", "sentence", "blunt"];
  const rows = order.map((k) => systems.find((s) => s.key === k)).filter(Boolean);
  const W = 720, L = 190, R = 50, T = 8, barH = 22, rowGap = 14;
  const H = T + rows.length * (barH + rowGap) + 34;
  const max = Math.max(...rows.map((s) => parts.reduce((a, [k]) => a + s.decomposition[k], 0)));
  const x = (v) => L + (W - L - R) * (v / max);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Leaks by cause, per configuration" });
  const nice = max > 200 ? 50 : max > 80 ? 20 : 10;
  const ticks = [];
  for (let t = 0; t <= max; t += nice) ticks.push(t);
  xAxis(svg, x, ticks, T, H - 34, "", (t) => String(t));
  rows.forEach((s, i) => {
    const y0 = T + i * (barH + rowGap) + rowGap / 2;
    svg.append(el("text", { x: L - 12, y: y0 + barH / 2 + 4, "text-anchor": "end", class: "row-label" }, SYSTEM_LABELS[s.key]));
    let at = 0;
    for (const [k, cls] of parts) {
      const v = s.decomposition[k];
      if (v > 0) {
        const r = el("rect", { x: x(at), y: y0, width: Math.max(1, x(at + v) - x(at)), height: barH, class: `bar ${cls}` });
        r.append(el("title", {}, `${parts.find((p) => p[0] === k)[2]}: ${v}`));
        svg.append(r);
        if (x(at + v) - x(at) > 22) {
          svg.append(el("text", { x: (x(at) + x(at + v)) / 2, y: y0 + barH / 2 + 4, "text-anchor": "middle", class: "seg-label" }, String(v)));
        }
      }
      at += v;
    }
    svg.append(el("text", { x: x(at) + 6, y: y0 + barH / 2 + 4, class: "bar-value" }, String(at)));
  });
  host.replaceChildren(svg);
  legend("leak-legend", parts.map(([, cls, label]) => [cls, label]));
}

/* ------------------------------------------------------------------ the reviewers */

function drawReviewers(data) {
  const host = document.getElementById("reviewer-chart");
  if (!host) return;
  const rows = data.reviewers;
  const W = 720, L = 130, R = 40, T = 10, rowH = 40;
  const H = T + rows.length * rowH + 40;
  const max = Math.ceil(Math.max(...rows.map((r) => r.unaided)) + 0.5);
  const x = (v) => L + (W - L - R) * (v / max);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Minutes per page by reviewer, by hand and with proposals" });
  const ticks = [];
  for (let t = 0; t <= max; t += 0.5) ticks.push(t);
  xAxis(svg, x, ticks, T, H - 40, "Minutes per page", (t) => (Number.isInteger(t) ? String(t) : t.toFixed(1)));
  rows.forEach((r, i) => {
    const y = T + i * rowH + rowH / 2;
    svg.append(el("text", { x: L - 14, y: y + 4, "text-anchor": "end", class: "row-label" }, r.name));
    svg.append(el("line", { x1: x(r.with), x2: x(r.unaided), y1: y, y2: y, class: "dumbbell" }));
    svg.append(el("circle", { cx: x(r.unaided), cy: y, r: 7, class: "dot-unaided" }));
    svg.append(el("circle", { cx: x(r.with), cy: y, r: 7, class: "dot-with" }));
    svg.append(el("text", { x: x(r.unaided) + 12, y: y + 4, class: "bar-value" }, `${r.unaided.toFixed(1)}`));
    svg.append(el("text", { x: x(r.with) - 12, y: y + 4, "text-anchor": "end", class: "bar-value" }, `${r.with.toFixed(1)}`));
  });
  host.replaceChildren(svg);
  legend("reviewer-legend", [["sw-with", "With the tool's proposals"], ["sw-unaided", "By hand"]]);
}

/* ------------------------------------------------------------------ the releases and scans */

function drawReleases(sets) {
  const rows = sets.map((s) => ({
    label: s.label, sub: `${s.packages} packages, ${s.pages} pages, ${s.kind}`,
    values: { before: [s.before[0]], now: s.now },
  }));
  hbars("release-chart", rows, [["before", "b-before"], ["now", "b-now"]], {
    left: 290, label: "Share of released spans the tool would withhold, per set",
    title: "Of what a person released, withheld by the tool",
  });
  legend("release-legend", [["b-before", "Before 2026-10-17"], ["b-now", "The tool as it ships"]]);
}

function drawScans(profiles) {
  const rows = profiles.map((p) => ({
    label: p.name.charAt(0).toUpperCase() + p.name.slice(1),
    sub: p.name === "native" ? "the original file" : `${p.cer} of characters misread`,
    values: { leak: p.leak, over: p.over },
  }));
  hbars("scan-chart", rows, [["leak", "b-leak"], ["over", "b-over"]], {
    left: 210, label: "Leak rate and over-redaction by input", title: "",
  });
  legend("scan-legend", [["b-leak", "Leak rate"], ["b-over", "Over-redaction"]]);
}

/* ------------------------------------------------------------------ the letter */

function wireLetter() {
  const letter = document.getElementById("letter");
  const box = document.getElementById("why");
  if (!letter || !box) return;
  const title = box.querySelector(".why-title");
  const text = box.querySelector(".why-text");
  const show = (mark) => {
    const note = mark.dataset.note || "";
    const cut = note.indexOf(". ");
    title.textContent = `"${mark.textContent}"`;
    text.textContent = note;
    box.className = `why-box ${[...mark.classList].find((c) => c.startsWith("x-")) || ""}`;
    if (cut > 0) {
      text.replaceChildren(html("strong", "", note.slice(0, cut + 1)), document.createTextNode(note.slice(cut + 1)));
    }
  };
  for (const mark of letter.querySelectorAll("mark")) {
    mark.removeAttribute("title");
    mark.addEventListener("mouseenter", () => show(mark));
    mark.addEventListener("focus", () => show(mark));
    mark.addEventListener("click", () => show(mark));
  }
}

/* ------------------------------------------------------------------ the live line */

async function liveLine() {
  const line = document.getElementById("live");
  if (!line) return;
  try {
    const d = await getJson("/dashboard.json");
    const n = d.decisions_total;
    const since = new Date(d.since).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
    line.replaceChildren(html("span", "pulse"), document.createTextNode(
      n === 0
        ? ` Live since ${since}: no decisions yet. Be the first.`
        : ` Live since ${since}: ${n.toLocaleString()} decision${n === 1 ? "" : "s"} by ${d.visitors.toLocaleString()} visitor${d.visitors === 1 ? "" : "s"}, and ${d.pdfs.clean} of ${d.pdfs.built} released PDF${d.pdfs.built === 1 ? "" : "s"} clean.`));
  } catch (err) {
    line.textContent = "";
  }
}

async function main() {
  wireLetter();
  liveLine();
  let data;
  try {
    data = await getJson("/data/site.json");
  } catch (err) {
    fail(`The charts could not load their data (${err.message}). Every number is still in the text.`);
    return;
  }
  const draw = [
    () => drawTradeoff(data.systems),
    () => drawCategories(data),
    () => drawLeaks(data.systems),
    () => drawReviewers(data),
    () => drawReleases(data.releases),
    () => drawScans(data.scans),
  ];
  for (const d of draw) {
    try { d(); } catch (err) { fail(`A chart failed to draw: ${err.message}`); }
  }
}

main();

/* The clip plays by itself, muted, unless the reader has asked for less motion; then it
   waits with its controls showing. */
(function () {
  const clip = document.querySelector(".clip video");
  if (!clip || !window.matchMedia) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    clip.removeAttribute("autoplay");
    clip.pause();
    clip.controls = true;
  }
})();
