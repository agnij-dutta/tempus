FROM node:22-bookworm-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates python3 python3-pip python3-venv \
      build-essential lsb-release \
    && rm -rf /var/lib/apt/lists/*

# Pinned wend-agent toolchain versions.
ARG CLAUDE_CODE_VERSION=2.1.168
ARG CLOUDFLARED_VERSION=2026.5.2

RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

RUN curl -fsSL -o /usr/local/bin/cloudflared \
      "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-amd64" \
    && chmod +x /usr/local/bin/cloudflared

RUN useradd -m -u 1000 wend && mkdir -p /workspace /app && chown -R wend:wend /workspace /app

COPY --chown=wend:wend entrypoint.py /app/entrypoint.py
COPY --chown=wend:wend requirements.txt /app/requirements.txt
RUN pip3 install --break-system-packages --no-cache-dir -r /app/requirements.txt

USER wend
WORKDIR /workspace
EXPOSE 8080

CMD ["python3", "/app/entrypoint.py"]
