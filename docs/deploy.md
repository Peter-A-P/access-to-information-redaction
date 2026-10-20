# The public demonstration

`redaction.peterparker.ca` runs `sever demo`, live since 2026-10-18. At `/` and `/how` is the
project's website, built by `sever site` into the image from the committed results
(`sever/site.py`), and at `/dashboard` a live count of visitors' decisions
(`sever/review/stats.py`); neither sets a cookie. The reviewer's screen is at `/review`: the reviewer's screen over six
invented records and ten short excerpts of records LAC has released (PLAN.md 12.46), one private session per visitor, forgotten after two hours, rules only
and no model. A visitor who completes a record can download its PDF, built from their own
decisions and leak-tested before it is served. `sever/review/demo.py` says what the
demonstration adds to the reviewer application and why. It adds nothing else.

## Where it runs

On the shared OVHcloud VPS that serves project 04 (`docs/deploy.md` in 04's repository),
as one more container behind 04's Caddy. It publishes no port. It joins 04's compose
network so Caddy can reach it by name. The container is read-only, with a 256 MB `/tmp`
for the visitors' audit logs. It drops every capability and is limited to one CPU and 2 GB.

The image holds no credential and the demonstration calls nothing outside itself, so a
compromise of it reaches six invented records and nineteen pages LAC has already published.

## Standing it up

Done 2026-10-18 (PLAN.md 12.44). The host's 04 checkout stays at the tag it runs, with
`deploy/Caddyfile` taken from 04's commit 864fdad (`git checkout 864fdad --
deploy/Caddyfile`), until 04's next tagged deploy carries it. To update the demo, repeat the
laptop half of the commands below and `sudo docker compose up -d --no-build` on the host;
Caddy needs no restart for that.

Three things only Peter can do, in this order:

1. **DNS.** In Cloudflare, add an A record `redaction` pointing at the VPS's address,
   **DNS only** (grey cloud), as 04's record is. Caddy fetches the certificate itself.
2. **04's Caddyfile.** Add this block beside the `gateway.peterparker.ca` one. It lives in
   04's repository, so it is 04's change to commit:

   ```
   redaction.peterparker.ca {
   	encode zstd gzip
   	header {
   		Strict-Transport-Security "max-age=31536000"
   		X-Content-Type-Options nosniff
   		Referrer-Policy no-referrer
   		Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
   		-Server
   	}
   	request_body {
   		max_size 64KB
   	}
   	reverse_proxy redaction:8000
   	log {
   		output stdout
   		format json
   	}
   }
   ```

   The reviewer screen's hundred lines of script and its stylesheet are inline. That is
   why the policy allows inline script and style, and allows nothing from another host.
3. **The note in 04's deploy doc** that says the host "runs nothing else" has to change,
   because 04's published load test names this machine. The demonstration is idle almost
   all the time and is capped at one CPU. A load test run after this point should still
   say that it shares the host.

Then, on the host, as `ubuntu`. This repository is private and the host holds no GitHub
credential, so the image is built on the laptop and copied over:

```bash
# on the laptop, from this repository; the released pages are gitignored, so build them
# first from the packages in data/releases (docs/data.md has where each came from)
uv run sever demo-records
docker build --platform linux/amd64 -f deploy/Dockerfile -t sever-demo:latest .
docker save sever-demo:latest | ssh boundary-vps 'sudo docker load'
scp deploy/compose.yaml boundary-vps:/srv/redaction/compose.yaml

# on the host
cd /srv/redaction && sudo docker compose up -d --no-build
cd /srv/boundary/repo/deploy && sudo docker compose restart caddy
curl -sI https://redaction.peterparker.ca/healthz
```

## Checking it

- `GET /healthz` answers `ok` without creating a session.
- A first visit is a 303 that sets an `HttpOnly`, `Secure`, `SameSite=Lax` cookie.
- Two browsers see each other's decisions nowhere (`tests/test_demo.py` holds this too).
- A released record's PDF has nothing under its boxes. Select the text under one.
