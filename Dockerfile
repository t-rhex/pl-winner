# syntax=docker/dockerfile:1.7
# ----------------------------------------------------------------------------
# Hardened Streamlit deployment for pl-winner.
# - Pinned base image digest (Dependabot keeps it up to date)
# - Multi-stage: build tools never reach runtime
# - Non-root user with minimal capabilities
# - Read-only root filesystem (writable bits explicitly via VOLUMEs)
# ----------------------------------------------------------------------------

# python:3.12-slim — pinned to digest. Bumped by Dependabot.
ARG PYTHON_IMAGE=python:3.12-slim@sha256:6026d9374020066a85690cabdb66f5d06a2dd606e756c7082fccdaaaf6d048dd

FROM ${PYTHON_IMAGE} AS builder

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


FROM ${PYTHON_IMAGE} AS runtime

LABEL org.opencontainers.image.title="pl-winner" \
      org.opencontainers.image.description="Premier League predictor + FPL recommender" \
      org.opencontainers.image.source="https://github.com/t-rhex/pl-winner" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PL_WINNER_DATA_DIR=/data \
    HOME=/home/app \
    XDG_CACHE_HOME=/tmp/cache \
    STREAMLIT_HOME=/tmp/streamlit \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# tini gives clean signal forwarding so SIGTERM works as expected.
# curl is needed for the in-image HEALTHCHECK.
RUN apt-get update && \
    apt-get install -y --no-install-recommends tini=0.19.0-1 curl && \
    rm -rf /var/lib/apt/lists/* && \
    # Create non-root user (UID 10001 = avoids overlap with system users)
    groupadd --system --gid 10001 app && \
    useradd --system --uid 10001 --gid app --home-dir /home/app --create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install /wheels/*.whl && rm -rf /wheels

# Bring in the streamlit app file (the wheel doesn't include app/)
COPY app /app/app
COPY README.md /app/

# /data is the persistent volume mount for caches + the SQLite DB.
# /tmp is needed because Streamlit / matplotlib write there at runtime.
RUN mkdir -p /data /tmp/cache /tmp/streamlit /home/app && \
    chown -R app:app /app /data /tmp/cache /tmp/streamlit /home/app && \
    chmod 0750 /data /home/app

VOLUME ["/data", "/tmp"]

USER app:app

EXPOSE 8501

# Container-level healthcheck (Fly also has its own from fly.toml)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "streamlit", "run", "/app/app/streamlit_app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", \
     "--browser.gatherUsageStats=false"]
