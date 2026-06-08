FROM node:22-bookworm-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates python3 python3-pip python3-venv \
      build-essential lsb-release \
    && rm -rf /var/lib/apt/lists/*

# Pinned wend-agent toolchain versions.
ARG CLAUDE_CODE_VERSION=2.1.168
ARG CLOUDFLARED_VERSION=2026.5.2

RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

RUN set -eux; \
    mkdir -p --mode=0755 /usr/share/keyrings; \
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
      | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null; \
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" \
      > /etc/apt/sources.list.d/cloudflared.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends cloudflared; \
    rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1001 wend && mkdir -p /workspace /app && chown -R wend:wend /workspace /app

COPY --chown=wend:wend entrypoint.py /app/entrypoint.py
COPY --chown=wend:wend requirements.txt /app/requirements.txt
RUN pip3 install --break-system-packages --no-cache-dir -r /app/requirements.txt

USER wend
WORKDIR /workspace
EXPOSE 8080

CMD ["python3", "/app/entrypoint.py"]
