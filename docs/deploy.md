# The public demonstration

`redaction.peterparker.ca` runs `sever demo`, live since 2026-10-18. At `/` and `/how` is the
project's website, built by `sever site` into the image from the committed results
(`sever/site.py`), and at `/dashboard` a live count of visitors' decisions
(`sever/review/stats.py`); neither sets a cookie. The reviewer's screen is at `/review`: six
invented records and ten short excerpts of records LAC has released (PLAN.md 12.46), one
private session per visitor, forgotten after two hours. The proposals are the tool as it
ships, the rules then Jev 1.14, and Jev's answers for these records are replayed from
`results/model-answers-demo.jsonl` (recorded once by `sever demo-answers`, PLAN.md 12.52), so
no model is called. A visitor who completes a record can download its PDF, built from their
own decisions and leak-tested before it is served. `sever/review/demo.py` says what the
demonstration adds to the reviewer application and why. It adds nothing else.

## How it runs

One container (`deploy/Dockerfile`, `deploy/compose.yaml`) behind a TLS reverse proxy. It
publishes no port of its own: the proxy reaches it over a private Docker network. The
container is read-only, with a 256 MB `/tmp` for the visitors' audit logs and one named
volume for the dashboard's totals (below). It runs as an unprivileged user, drops every
capability, and is limited to one CPU and 2 GB.

The image holds no credential and the demonstration calls nothing outside itself, so a
compromise of it reaches six invented records, nineteen pages LAC has already published, and
the model answers recorded for them, which are probabilities over categories and no text.

The proxy adds HSTS, `nosniff`, `Referrer-Policy: no-referrer`, a 64 KB limit on a request
body, and this content security policy:

```
default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';
img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none';
form-action 'self'
```

The website's own pages need nothing inline. The reviewer screen's hundred lines of script
and its stylesheet are inline, which is why the policy allows inline script and style, and
it allows nothing from another host.

## Running it yourself

The released pages are not committed, so build them first from the packages named in
`data/releases` ([docs/data.md](data.md) has where each came from), then build and start the
container:

```bash
uv run sever demo-records
docker compose -f deploy/compose.yaml up -d --build
```

The compose file joins an external network for the proxy; drop that, or run `sever demo
--insecure-cookie` directly, to try it on one machine.

## The dashboard's totals survive an update

The dashboard's running totals (visitors, decisions, pages, PDFs, agreement) are written by
`sever demo --stats-file /data/stats.json` every half minute and when the container stops,
and read back when it starts (`sever.review.stats.keep`). `/data` is a named volume, so a new
image keeps them. The file holds the numbers `/dashboard.json` already publishes and nothing
else; the last hour's per-minute activity is not kept. A file that cannot be read is renamed
`stats.json.unreadable`, never overwritten. The output of `/dashboard.json` is itself a valid
file, which is how the totals were carried over from the containers that kept them only in
memory (2026-10-21), and how they are restored if the volume is lost.

## Checking it

- `GET /healthz` answers `ok` without creating a session.
- A first visit is a 303 that sets an `HttpOnly`, `Secure`, `SameSite=Lax` cookie.
- Two browsers see each other's decisions nowhere (`tests/test_demo.py` holds this too).
- A released record's PDF has nothing under its boxes. Select the text under one.
