FROM continuumio/miniconda3:latest AS builder

WORKDIR /tmp

COPY environment.yaml /tmp/env.yaml

RUN conda install -n base -c conda-forge mamba -y

RUN mamba env create -f /tmp/env.yaml && \
    mamba clean --all -y && \
    find /opt/conda/envs/timon_v0.1.0 -type f -name '*.a' -delete && \
    find /opt/conda/envs/timon_v0.1.0 -type f -name '*.pyc' -delete && \
    find /opt/conda/envs/timon_v0.1.0 -type f -name '*.js.map' -delete && \
    find /opt/conda/envs/timon_v0.1.0 -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/conda/envs/timon_v0.1.0 -type d -name 'tests' -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/conda/envs/timon_v0.1.0 -type d -name 'test' -exec rm -rf {} + 2>/dev/null || true && \
    rm -rf /opt/conda/pkgs && \
    rm -rf /opt/conda/envs/timon_v0.1.0/share/man && \
    rm -rf /opt/conda/envs/timon_v0.1.0/share/doc

FROM debian:bookworm-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    procps \
    ca-certificates \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/conda/envs/timon_v0.1.0 /opt/conda/envs/timon_v0.1.0

ENV PATH="/opt/conda/envs/timon_v0.1.0/bin:$PATH" \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

WORKDIR /app

COPY timon /app/timon

ENV PATH="/opt/conda/envs/timon_v0.1.0/bin:$PATH"

CMD ["python3", "./timon/run.py"]