# The public demonstration

`redaction.peterparker.ca` runs `sever demo`, live since 2026-10-18. At `/` and `/how` is the
project's website, built by `sever site` into the image from the committed results
(`sever/site.py`), and at `/dashboard` a live count of visitors' decisions
(`sever/review/stats.py`); neither sets a cookie. The reviewer's screen is at `/review`: the reviewer's screen over six
invented records and ten short excerpts of records LAC has released (PLAN.md 12.46), one private session per visitor, forgotten after two hours.
The proposals are the tool as it ships, the rules then Jev 1.14, and Jev's answers for these
records are replayed from `results/model-answers-demo.jsonl` (recorded once by `sever
demo-answers`, PLAN.md 12.52), so no model is called. A visitor who completes a record can download its PDF, built from their own
decisions and leak-tested before it is served. `sever/review/demo.py` says what the
demonstration adds to the reviewer application and why. It adds nothing else.

## Where it runs

On the shared OVHcloud VPS that serves project 04 (`docs/deploy.md` in 04's repository),
as one more container behind 04's Caddy. It publishes no port. It joins 04's compose
network so Caddy can reach it by name. The container is read-only, with a 256 MB `/tmp`
for the visitors' audit logs, and one named volume for the dashboard's totals (below). It drops every capability and is limited to one CPU and 2 GB.

The image holds no credential and the demonstration calls nothing outside itself, so a
compromise of it reaches six invented records, nineteen pages LAC has already published, and
the model answers recorded for them, which are probabilities over categories and no text.

## Standing it up

Done 2026-10-18 (PLAN.md 12.44). The host's 04 checkout stays at the tag it runs, with
`deploy/Caddyfile` taken from 04's commit 864fdad (`git checkout 864fdad --
deploy/Caddyfile`), until 04's next tagged deploy carries it. To update the demo, run the
commands below except the Caddy restart, which an update does not need.

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

Then the image. This repository is private and the host holds no GitHub credential, so the
laptop sends the committed source, about 12 MB, and the host builds the image from it:

```bash
# on the laptop, from this repository; the released pages are gitignored, so build them
# first from the packages in data/releases (docs/data.md has where each came from)
uv run sever demo-records
git archive --format=tar --prefix=src/ HEAD > /tmp/sever-src.tar
tar -rf /tmp/sever-src.tar -s ',^,src/,' data/demo/*.pdf    # BSD tar; GNU tar: --transform
gzip -f /tmp/sever-src.tar
scp /tmp/sever-src.tar.gz boundary-vps:/tmp/sever-src.tar.gz
scp deploy/compose.yaml boundary-vps:/tmp/redaction-compose.yaml   # /srv/redaction is root's

# on the host, as ubuntu; the running image is kept as :previous for a rollback
sudo docker tag sever-demo:latest sever-demo:previous
sudo mv /tmp/redaction-compose.yaml /srv/redaction/compose.yaml
rm -rf /tmp/sever-build && mkdir /tmp/sever-build && tar -xzf /tmp/sever-src.tar.gz -C /tmp/sever-build
cd /tmp/sever-build/src && sudo docker build -f deploy/Dockerfile -t sever-demo:latest .
cd /srv/redaction && sudo docker compose up -d --no-build
cd /srv/boundary/repo/deploy && sudo docker compose restart caddy    # first time only
curl -sI https://redaction.peterparker.ca/healthz
rm -rf /tmp/sever-build /tmp/sever-src.tar.gz
```

**Why on the host** (since 2026-10-21, PLAN.md 12.52). The image used to be built on the
laptop and piped over SSH. Built for amd64 on an arm64 laptop it took more than forty
minutes under emulation, against about three natively on the host; and the 1.2 GB upload
over a home connection dropped every few minutes, and the dropped sessions counted as
failures for fail2ban, which banned the laptop's address from SSH for an hour. The source
goes over in one short connection. The build is the same Dockerfile from the same commit.

To roll back: `sudo docker tag sever-demo:previous sever-demo:latest`, then the
`compose up` line again.

## The dashboard's totals survive an update

The dashboard's running totals (visitors, decisions, pages, PDFs, agreement) are written
by `sever demo --stats-file /data/stats.json` every half minute and when the container
stops, and read back when it starts (`sever.review.stats.keep`). `/data` is the named volume
`redaction_stats` (`deploy/compose.yaml`), so a new image keeps them. The file holds the
numbers `/dashboard.json` already publishes and nothing else; the last hour's per-minute
activity is not kept. A file that cannot be read is renamed `stats.json.unreadable`, never
overwritten.

The output of `/dashboard.json` is itself a valid file, which is how the totals were carried
over from the containers that kept them only in memory (2026-10-21), and how to restore them
if the volume is ever lost. Before the `compose up` line:

```bash
curl -s https://redaction.peterparker.ca/dashboard.json > /tmp/stats.json
sudo docker volume create redaction_stats
sudo docker run --rm -v redaction_stats:/data -v /tmp/stats.json:/seed.json:ro \
  --entrypoint cp sever-demo:latest /seed.json /data/stats.json
```

Seeding replaces whatever file the volume held, so it is for an empty or lost volume only.
Compose warns that the volume was not created by it, and uses it.

## Checking it

- `GET /healthz` answers `ok` without creating a session.
- A first visit is a 303 that sets an `HttpOnly`, `Secure`, `SameSite=Lax` cookie.
- Two browsers see each other's decisions nowhere (`tests/test_demo.py` holds this too).
- A released record's PDF has nothing under its boxes. Select the text under one.
