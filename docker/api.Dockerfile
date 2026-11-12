# Server API (protocol P1): `laris-server`. Slim, non-root, no GPU, no weights, no policy.
# Policy (.laris/, LARIS.md) is mounted read-only at run time; secrets arrive as Docker secrets.
#   docker build -f docker/api.Dockerfile -t laris-api .
FROM python:3.12-slim AS build
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip wheel --no-cache-dir --wheel-dir /wheels ".[server]"

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin laris \
    && mkdir -p /app /data && chown laris:laris /app /data
COPY --from=build /wheels /wheels
RUN pip install --no-index --find-links /wheels "laris[server]" && rm -rf /wheels
WORKDIR /app
COPY --chown=laris:laris configs ./configs
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=20s --retries=4 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
ENTRYPOINT ["laris-server"]
CMD ["model", "serve", "--host", "0.0.0.0", "--port", "8000"]
