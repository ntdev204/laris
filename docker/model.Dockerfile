# Model service (protocol P2): `laris-model`. Inference only, CUDA base, no training extras.
# Weights are a read-only volume at /models; nothing is baked in.
#   docker build -f docker/model.Dockerfile -t laris-model .
ARG CUDA_IMAGE=nvidia/cuda:12.4.1-runtime-ubuntu22.04
ARG LARIS_EXTRAS=model,gpu,tokenizer
FROM ${CUDA_IMAGE} AS build
ARG LARIS_EXTRAS
RUN apt-get update && apt-get install -y --no-install-recommends python3.10 python3-pip \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install --no-cache-dir --upgrade pip  # Ubuntu's pip cannot read pyproject.toml
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip wheel --no-cache-dir --wheel-dir /wheels ".[${LARIS_EXTRAS}]"

FROM ${CUDA_IMAGE}
ARG LARIS_EXTRAS
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends python3.10 python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin laris \
    && mkdir -p /app /models && chown laris:laris /app
COPY --from=build /wheels /wheels
RUN python3 -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-index --find-links /wheels "laris[${LARIS_EXTRAS}]" && rm -rf /wheels
WORKDIR /app
COPY --chown=laris:laris configs ./configs
USER 10001
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=4s --start-period=60s --retries=4 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)"
ENTRYPOINT ["laris-model"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8001"]
