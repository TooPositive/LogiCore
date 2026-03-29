# Build stage
FROM rust:1.83-slim AS builder

WORKDIR /app

# Cache dependencies — copy manifests first
COPY Cargo.toml Cargo.lock* ./
RUN mkdir src && echo "fn main() {}" > src/main.rs && cargo build --release && rm -rf src

# Build actual source
COPY src src
RUN touch src/main.rs && cargo build --release

# Runtime stage — minimal image
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/target/release/logicore-simulator /usr/local/bin/logicore-simulator

EXPOSE 8081

CMD ["logicore-simulator"]
