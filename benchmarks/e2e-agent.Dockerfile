FROM node:22-bookworm

ARG CLAUDE_CODE_VERSION=2.1.276

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates git python3 python3-venv ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"

WORKDIR /tmp/token-saver
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY integrations ./integrations
RUN mkdir -p benchmarks \
    && cp /dev/null benchmarks/placeholder.json \
    && python3 -m venv /opt/token-saver-venv \
    && /opt/token-saver-venv/bin/pip install --no-cache-dir . \
    && rm -rf /tmp/token-saver \
    && find /opt/token-saver-venv -type d -path '*/share/token-saver/benchmarks' \
       -prune -exec rm -rf {} +

ENV PATH="/opt/token-saver-venv/bin:${PATH}" \
    DISABLE_AUTOUPDATER=1

WORKDIR /workspace
