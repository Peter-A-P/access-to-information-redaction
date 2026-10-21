# The public demonstration: `sever demo`, behind the shared host's Caddy. Built from a
# checkout; see docs/deploy.md. The proposals are the rules then Jev 1.14, whose answers are
# replayed from results/model-answers-demo.jsonl: nothing in the image calls a model and the
# image holds no credential.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# The spaCy model is a 382 MB download, and on 2026-10-21 it outlasted uv's 30-second
# default and failed the build. Five minutes is a slow link, not a hung one.
ENV UV_HTTP_TIMEOUT=300
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY sever ./sever
# The versions in uv.lock, the ones CI tests, without the development group.
RUN uv sync --frozen --extra detect --no-dev \
 && uv pip install --python .venv/bin/python \
    "en_core_web_lg @ https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl"

# The website, built here from the committed results so the image serves exactly what the
# repository measured (sever/site.py). The tests and the results are read for their figures;
# the build fails if any figure cannot be read, which fails the image.
COPY web ./web
COPY results ./results
COPY gate ./gate
COPY tests ./tests
RUN .venv/bin/sever site --out /app/site

# The released pages (PLAN.md 12.46): excerpts of published LAC packages, built on the
# laptop by `sever demo-records` and gitignored, so a checkout without them builds an image
# without them. Loading them here fails the build instead of the first visitor.
COPY data/demo ./data/demo
RUN .venv/bin/python -c "from sever.review.demo import demo_model, released_items; print(len(released_items(model=demo_model())), 'released records')"

# The checkout's own permissions come across with COPY, and a private checkout is often
# owner-only, which the unprivileged user below could not read.
RUN chmod -R a+rX /app
RUN useradd --system --uid 10007 --home /nonexistent sever
USER sever
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD [".venv/bin/sever", "demo", "--host", "0.0.0.0", "--port", "8000", "--site", "/app/site"]
