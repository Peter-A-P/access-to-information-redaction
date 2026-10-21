"""The website's clip: the tool deciding two pages, then redacting six.

Rendered from the engine's own output, not drawn: the six invented records are built from
the corpus seed, the rules decide what they can, and Jev 1.14's answers are replayed from
`results/model-answers.jsonl`, so every colour in the clip is a proposal `sever report`
scores. Nothing is sent anywhere.

Timing is the measured one. The rules' decisions land together, because they take
microseconds; each of Jev's lands 0.24 seconds after the last, the mean latency of the
7,549 calls in the published run (sever-jev114-210 in project 04's ledger, PLAN.md 12.50).
On a page that is a few seconds of model time, sequentially, which is the conservative way
to show it: the calls are independent and could run at once.

Then the view pulls back to six pages and the export's view of them: only what is
withheld, as a box with the text gone (an escalated span is withheld until a person
releases it, so it is boxed too). The boxes on the four new pages land at the same pace.

    uv sync --extra detect --extra clip
    uv run python tools/clip.py          # writes web/media/jev-clip.mp4 and its .jpg poster

Needs the `clip` extra (Pillow, and imageio-ffmpeg, which carries its own ffmpeg) and a
monospaced TrueType font; Menlo is the default on macOS, `--mono` names another.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from sever.corpus.generate import build
from sever.corpus.personas import PUBLIC_BODY_DOMAIN
from sever.decide.pipeline import DecisionEngine, Proposal, Source
from sever.detect.engine import SeverDetector
from sever.eval.report import config_for
from sever.review.demo import demo_model

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "media" / "jev-clip.mp4"
ANSWERS = ROOT / "results" / "model-answers.jsonl"
FONT = ROOT / "web" / "fonts" / "inter-latin.woff2"
MENLO = Path("/System/Library/Fonts/Menlo.ttc")

# The two pages decided in colour, then the four that join them in the pulled-back view.
# The email chain opens because every span on it is right against its labels; the case
# note, with the clip's only two escalations, is in the grid where only boxes show.
RECORDS = (
    "email_chain-002",
    "hr_memorandum-003",
    "incident_report-004",
    "case_note-000",
    "meeting_minutes-005",
    "correspondence-007",
)
CORPUS_DOCUMENTS = 210

W, H, FPS = 1080, 1350, 30
# Seconds a Jev decision takes: the mean latency of the published run, 244 ms.
STEP = 0.24
RULES_BEAT = 0.45

PAPER = (245, 243, 238)
CARD = (255, 254, 251)
INK = (29, 31, 36)
FAINT = (107, 112, 121)
LINE = (207, 201, 189)
ACCENT = (15, 92, 110)
BOX = (22, 24, 29)
# (tint, strong, text), from web/review.css's proposed marks and the site's x-none.
STYLE = {
    "withhold": ((251, 224, 221), (179, 38, 30), (140, 29, 24)),
    "release": ((220, 239, 227), (30, 122, 76), (23, 96, 59)),
    "escalate": ((253, 238, 201), (176, 120, 0), (110, 74, 0)),
    "none": ((232, 233, 236), (154, 160, 168), (60, 64, 72)),
}
LABEL = {"withhold": "Withhold", "release": "Release", "escalate": "Escalate", "none": "Not personal"}
WITHHELD = frozenset({"withhold", "escalate"})
PRETTY = {
    "case_note": "Case note",
    "hr_memorandum": "HR memorandum",
    "incident_report": "Incident report",
    "email_chain": "Email chain",
    "meeting_minutes": "Meeting minutes",
    "correspondence": "Letter",
}

LH, PADX, PADY, CARD_W = 22, 40, 30, 960
COLS, GAP = 3, 70
TOP, BOTTOM = 158, 1238
Rect = tuple[int, int, int]  # line, first column, column after the last


@dataclass(frozen=True)
class Span:
    kind: str
    by_model: bool
    rects: tuple[Rect, ...]


@dataclass(frozen=True)
class Page:
    doc_id: str
    kind: str
    lines: tuple[str, ...]
    spans: tuple[Span, ...]


def _kind(p: Proposal) -> str:
    if p.code == "K6":
        return "none"
    if p.is_escalation:
        return "escalate"
    return "withhold" if p.withholds else "release"


def pages() -> list[Page]:
    """The records, proposed by the rules and then Jev's replayed answers."""
    model = demo_model(answer_cache=ANSWERS, public_body_domains=(PUBLIC_BODY_DOMAIN,))
    detector = SeverDetector()
    wanted = {item.rendered.document.doc_id: item for item in build(documents=CORPUS_DOCUMENTS)}
    out: list[Page] = []
    for doc_id in RECORDS:
        item = wanted[doc_id]
        doc = item.rendered.document
        props = DecisionEngine(config=config_for(item), detector=detector, model=model).propose(doc)
        text = doc.page(1).text
        lines = text.split("\n")
        starts, c = [], 0
        for ln in lines:
            starts.append(c)
            c += len(ln) + 1
        spans: list[Span] = []
        cursor = 0
        for p in sorted((p for p in props if p.page == 1), key=lambda p: p.detection.offsets.start):
            o = p.detection.offsets
            if o.start < cursor:
                continue
            cursor = o.end
            rects = tuple(
                (i, max(o.start, ls) - ls, min(o.end, ls + len(lines[i])) - ls)
                for i, ls in enumerate(starts)
                if max(o.start, ls) < min(o.end, ls + len(lines[i]))
            )
            spans.append(Span(_kind(p), p.source is Source.MODEL, rects))
        out.append(Page(doc_id, PRETTY[doc_id.rsplit("-", 1)[0]], tuple(lines), tuple(spans)))
    return out


def ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def ease_out(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def mix(a: tuple[int, ...], b: tuple[int, ...], t: float) -> tuple[int, int, int]:
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def schedule(page: Page, t0: float, withheld_only: bool) -> tuple[dict[int, float], float]:
    """When each span lands: the rules' at once, then Jev's one STEP apart."""
    idx = [i for i, s in enumerate(page.spans) if not withheld_only or s.kind in WITHHELD]
    rules = [i for i in idx if not page.spans[i].by_model]
    model = [i for i in idx if page.spans[i].by_model]
    times = dict.fromkeys(rules, t0)
    t = t0 + (RULES_BEAT if rules else 0.0)
    for i in model:
        times[i] = t
        t += STEP
    return times, t


class Clip:
    def __init__(self, records: list[Page], mono: Path) -> None:
        self.pages = records
        self.mono = ImageFont.truetype(str(mono), 16)
        self.cw = self.mono.getlength("M")
        self.f_eyebrow = self._inter(19, "SemiBold")
        self.f_title = self._inter(38, "Bold")
        self.f_sub = self._inter(23, "Medium")
        self.f_count = self._inter(23, "SemiBold")
        self.f_legend = self._inter(21, "Medium")
        self.f_foot = self._inter(16, "Regular")
        self.card_h = max(len(p.lines) for p in records) * LH + 2 * PADY
        self.p1, self.p1_end = schedule(records[0], 0.7, False)
        self.pan0 = self.p1_end + 0.5
        self.pan1 = self.pan0 + 0.6
        self.p2, self.p2_end = schedule(records[1], self.pan1 + 0.35, False)
        self.zoom0 = self.p2_end + 0.5
        self.zoom1 = self.zoom0 + 1.2
        self.grid: dict[int, dict[int, float]] = {}
        g = self.zoom1 + 0.3
        for k in range(2, len(records)):
            self.grid[k], g = schedule(records[k], g, True)
            g += 0.25
        self.end = g + 1.8
        self.slots = [
            ((k % COLS) * (CARD_W + GAP), (k // COLS) * (self.card_h + GAP))
            for k in range(len(records))
        ]
        world_w = COLS * CARD_W + (COLS - 1) * GAP
        world_h = 2 * self.card_h + GAP
        self.gs = min((W - 60) / world_w, (BOTTOM - TOP - 40) / world_h)
        self.gx = (W - world_w * self.gs) / 2
        self.gy = TOP + (BOTTOM - TOP - world_h * self.gs) / 2
        self.cache: dict[Any, Image.Image] = {}

    @staticmethod
    def _inter(size: int, weight: str) -> Any:
        f = ImageFont.truetype(str(FONT), size)
        f.set_variation_by_name(weight)
        return f

    # -- one page ------------------------------------------------------------------------

    def render_page(self, page: Page, pops: dict[int, float], boxes: bool) -> Image.Image:
        im = Image.new("RGB", (CARD_W, self.card_h), CARD)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, CARD_W - 1, self.card_h - 1], outline=LINE, width=2)
        marks: dict[int, list[tuple[int, int, tuple[int, int, int] | None]]] = {}
        for i, age in pops.items():
            s = page.spans[i]
            if boxes:
                w = ease_out(age / 0.14)
                for ln, c0, c1 in s.rects:
                    x0, x1 = PADX + c0 * self.cw - 2, PADX + c1 * self.cw + 2
                    y0 = PADY + ln * LH + 1
                    d.rectangle([x0, y0, x0 + (x1 - x0) * w, y0 + LH - 2], fill=BOX)
                    if w >= 1:  # the text under a finished box is gone, as in the export
                        marks.setdefault(ln, []).append((c0, c1, None))
                continue
            tint, strong, txt = STYLE[s.kind]
            a = ease_out(age / 0.16)
            r = age / 0.35
            for ln, c0, c1 in s.rects:
                x0, x1 = PADX + c0 * self.cw - 3, PADX + c1 * self.cw + 3
                y0 = PADY + ln * LH + 1
                y1 = y0 + LH - 2
                if r < 1:  # the arrival ring, growing and fading
                    g = 2 + 7 * ease_out(r)
                    d.rounded_rectangle(
                        [x0 - g, y0 - g, x1 + g, y1 + g], radius=5,
                        outline=mix(CARD, strong, 1 - r), width=2,
                    )
                d.rounded_rectangle([x0, y0, x1, y1], radius=3, fill=mix(CARD, tint, a))
                d.rectangle([x0, y1 - 1, x1, y1 + 1], fill=mix(CARD, strong, a))
                marks.setdefault(ln, []).append((c0, c1, mix(INK, txt, a)))
        for ln, text in enumerate(page.lines):
            y = PADY + ln * LH + 3
            col = 0
            for c0, c1, fg in sorted(marks.get(ln, []), key=lambda m: m[0]):
                if c0 < col:
                    continue
                if c0 > col:
                    d.text((PADX + col * self.cw, y), text[col:c0], font=self.mono, fill=INK)
                if fg is not None:
                    d.text((PADX + c0 * self.cw, y), text[c0:c1], font=self.mono, fill=fg)
                col = c1
            if col < len(text):
                d.text((PADX + col * self.cw, y), text[col:], font=self.mono, fill=INK)
        return im

    def page_image(self, k: int, t: float) -> Image.Image:
        times = self.p1 if k == 0 else self.p2 if k == 1 else self.grid[k]
        pops = {i: t - ti for i, ti in times.items() if t >= ti}
        settled = all(age > 0.4 for age in pops.values())
        key = (k, tuple(sorted(pops)) if settled else (t,))
        if key not in self.cache:
            self.cache[key] = self.render_page(self.pages[k], pops, k >= 2)
        return self.cache[key]

    def redacted(self, k: int) -> Image.Image:
        key = ("redacted", k)
        if key not in self.cache:
            page = self.pages[k]
            pops = {i: 9.0 for i, s in enumerate(page.spans) if s.kind in WITHHELD}
            self.cache[key] = self.render_page(page, pops, True)
        return self.cache[key]

    # -- the camera ----------------------------------------------------------------------

    def camera(self, t: float) -> tuple[float, float, float]:
        def focus(k: int) -> tuple[float, float, float]:
            return 1.0, (W - CARD_W) / 2 - self.slots[k][0], TOP - self.slots[k][1]

        if t < self.pan0:
            return focus(0)
        if t < self.pan1:
            e = ease((t - self.pan0) / (self.pan1 - self.pan0))
            (s, ax, ay), (_, bx, by) = focus(0), focus(1)
            return s, ax + (bx - ax) * e, ay + (by - ay) * e
        if t < self.zoom0:
            return focus(1)
        e = ease((t - self.zoom0) / (self.zoom1 - self.zoom0))
        s0, tx0, ty0 = focus(1)
        s = math.exp(math.log(s0) + (math.log(self.gs) - math.log(s0)) * e)
        cx, cy = self.slots[1][0] + CARD_W / 2, self.slots[1][1] + self.card_h / 2
        fa = (cx * s0 + tx0, cy * s0 + ty0)
        fb = (cx * self.gs + self.gx, cy * self.gs + self.gy)
        fx, fy = fa[0] + (fb[0] - fa[0]) * e, fa[1] + (fb[1] - fa[1]) * e
        return s, fx - cx * s, fy - cy * s

    # -- the words around it -------------------------------------------------------------

    def legend(self, d: ImageDraw.ImageDraw, kinds: list[str], alpha: float) -> None:
        items = [
            ("Withheld, text removed", BOX, BOX)
            if k == "redacted"
            else (LABEL[k], STYLE[k][0], STYLE[k][1])
            for k in kinds
        ]
        widths = [38 + d.textlength(lbl, font=self.f_legend) for lbl, _, _ in items]
        x = (W - sum(widths) - 34 * (len(items) - 1)) / 2
        for (lbl, fill, edge), w in zip(items, widths, strict=True):
            d.rounded_rectangle(
                [x, 1265, x + 28, 1287], radius=4,
                fill=mix(PAPER, fill, alpha), outline=mix(PAPER, edge, alpha), width=2,
            )
            d.text((x + 38, 1262), lbl, font=self.f_legend, fill=mix(PAPER, INK, alpha))
            x += w + 34

    def overlay(self, frame: Image.Image, t: float) -> None:
        d = ImageDraw.Draw(frame)
        d.rectangle([0, 0, W, TOP - 8], fill=PAPER)
        d.rectangle([0, BOTTOM + 8, W, H], fill=PAPER)
        d.text((60, 34), "ACCESS TO INFORMATION  ·  REDACTION PROPOSALS", font=self.f_eyebrow, fill=ACCENT)
        if t < self.zoom0:
            d.text((60, 62), "Rules first, then Jev at 0.24 s a field", font=self.f_title, fill=INK)
            k = 0 if t < (self.pan0 + self.pan1) / 2 else 1
            times = self.p1 if k == 0 else self.p2
            done = sum(1 for ti in times.values() if t >= ti)
            d.text((60, 112), f"Page {k + 1}  ·  {self.pages[k].kind}", font=self.f_sub, fill=FAINT)
            count = f"{done} / {len(times)} fields"
            self.legend(d, ["withhold", "release", "escalate", "none"], 1.0)
        else:
            d.text((60, 62), "Then every page: withheld spans redacted", font=self.f_title, fill=INK)
            total = sum(len(v) for v in self.grid.values())
            done = sum(1 for v in self.grid.values() for ti in v.values() if t >= ti)
            d.text((60, 112), f"{len(self.pages)} pages", font=self.f_sub, fill=FAINT)
            count = f"{done} / {total} withheld"
            self.legend(d, ["redacted"], ease((t - self.zoom0) / 0.5))
        d.text((W - 60 - d.textlength(count, font=self.f_count), 112), count, font=self.f_count, fill=INK)
        foot = "Invented records. Decisions replayed from Jev 1.14's measured run: 7,549 calls, 0.24 s each."
        d.text(((W - d.textlength(foot, font=self.f_foot)) / 2, 1312), foot, font=self.f_foot, fill=FAINT)

    def frame(self, t: float) -> Image.Image:
        fr = Image.new("RGB", (W, H), PAPER)
        s, tx, ty = self.camera(t)
        for k in range(len(self.pages)):
            vis = (
                ease(t / 0.4) if k == 0
                else (1.0 if t >= self.pan0 else 0.0) if k == 1
                else ease((t - self.zoom0 - 0.3) / 0.6)
            )
            x0, y0 = self.slots[k][0] * s + tx, self.slots[k][1] * s + ty
            w, h = CARD_W * s, self.card_h * s
            if vis <= 0 or x0 > W or y0 > H or x0 + w < 0 or y0 + h < 0:
                continue
            img = self.page_image(k, t)
            if k < 2 and t > self.zoom0:  # the coloured page becomes its export
                m = ease((t - self.zoom0 - 0.2) / 0.6)
                if m > 0:
                    img = Image.blend(img, self.redacted(k), m)
            size = (max(1, round(w)), max(1, round(h)))
            if size != img.size:
                img = img.resize(size, Image.Resampling.LANCZOS)
            shadow = Image.new("RGB", size, (226, 222, 213))
            if vis < 1:
                img = Image.blend(Image.new("RGB", size, PAPER), img, vis)
                shadow = Image.blend(Image.new("RGB", size, PAPER), shadow, vis)
            fr.paste(shadow, (round(x0) + 3, round(y0) + max(4, round(10 * s))))
            fr.paste(img, (round(x0), round(y0)))
        self.overlay(fr, t)
        return fr


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--mono", type=Path, default=MENLO, help="A monospaced TrueType font.")
    args = ap.parse_args()
    if not args.mono.is_file():
        raise SystemExit(f"no font at {args.mono}; pass --mono with a monospaced TrueType font")
    clip = Clip(pages(), args.mono)
    frames = round(clip.end * FPS)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio_ffmpeg.write_frames(
        str(args.out), (W, H), fps=FPS, codec="libx264", quality=None, bitrate=None,
        output_params=["-crf", "18", "-preset", "slow", "-movflags", "+faststart"],
        pix_fmt_out="yuv420p", macro_block_size=2,
    )
    writer.send(None)
    for f in range(frames):
        writer.send(np.asarray(clip.frame(f / FPS)).tobytes())
        if len(clip.cache) > 400:
            clip.cache.clear()
    writer.close()
    # The poster: the first page decided, for a browser that does not autoplay.
    clip.frame(clip.p1_end + 0.4).save(args.out.with_suffix(".jpg"), quality=88)
    print(f"wrote {args.out} ({clip.end:.1f} s, {frames} frames) and its poster")


if __name__ == "__main__":
    main()
