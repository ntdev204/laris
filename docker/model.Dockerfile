# The model service (P2): Python code and the `model` extra only. Weights, tokenizer and checkpoints are mounted
# read-only at run time; with none configured the service runs the scripted placeholder backend.
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src src
RUN pip install --no-cache-dir --prefix=/install ".[model]"

FROM python:3.12-slim
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin laris
COPY --from=build /install /usr/local
# The command line imports the research tooling, which reads `configs/` next to `src/`: keep that layout.
WORKDIR /app
COPY src src
COPY configs configs
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 8001
ENTRYPOINT ["python", "-m", "cli.model", "serve"]
CMD ["--host", "0.0.0.0", "--port", "8001"]
