# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
COPY app ./app
RUN pip install --upgrade pip && \
    pip wheel --no-deps --wheel-dir /wheels . && \
    pip wheel --wheel-dir /wheels ".[web]"


FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="pl-winner" \
      org.opencontainers.image.description="Premier League predictor + FPL recommender" \
      org.opencontainers.image.source="https://github.com/t-rhex/pl-winner" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PL_WINNER_DATA_DIR=/data \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# tini gives clean signal forwarding so Ctrl-C works as expected
RUN apt-get update && \
    apt-get install -y --no-install-recommends tini curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install /wheels/*.whl && rm -rf /wheels

# Bring in the streamlit app file at runtime (the wheel doesn't include app/)
COPY app /app/app
COPY README.md /app/

# Cache & DB live in /data so they survive container restarts when mounted
RUN mkdir -p /data && chmod 0777 /data
VOLUME ["/data"]

EXPOSE 8501

# Healthcheck pings the Streamlit health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "streamlit", "run", "/app/app/streamlit_app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", \
     "--browser.gatherUsageStats=false"]
