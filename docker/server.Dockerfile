# laris-server: a static, non-root image. It holds the binary, CA certificates and an empty state directory;
# the policy (.laris) and every secret arrive at run time (mounted read-only / Docker secrets).
ARG RUST_VERSION=1.100.0

FROM rust:${RUST_VERSION}-bookworm AS build
RUN apt-get update && apt-get install -y --no-install-recommends musl-tools ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && rustup target add x86_64-unknown-linux-musl
WORKDIR /src
COPY Cargo.toml Cargo.lock rust-toolchain.toml deny.toml ./
COPY .cargo .cargo
COPY vendor vendor
COPY crates crates
COPY xtask xtask
RUN cargo build --release --locked --offline --target x86_64-unknown-linux-musl -p laris-server \
    && install -d -m 0700 /state \
    && cp target/x86_64-unknown-linux-musl/release/laris-server /laris-server

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build /laris-server /usr/local/bin/laris-server
COPY --from=build --chown=65532:65532 /state /state
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/laris-server"]
