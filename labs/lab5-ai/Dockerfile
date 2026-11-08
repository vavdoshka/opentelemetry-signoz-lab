# The alert-triggered investigator: Claude Code, kubectl and a small webhook
# server. Built from labs/lab5-ai, so it can copy the workspace.
FROM node:24-trixie-slim

# python3 runs the webhook server. curl fetches kubectl.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Claude Code, pinned to the version this lab was tested with. The npm package
# installs the same native binary as Anthropic's install script.
RUN npm install -g @anthropic-ai/claude-code@2.1.319

# kubectl for the agent's read-only checks. Reads work across the 1.26 to 1.37
# clusters this lab runs on.
ARG KUBECTL_VERSION=v1.32.4
RUN curl -fsSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/$(dpkg --print-architecture)/kubectl" \
 && chmod +x /usr/local/bin/kubectl

# The same workspace you use on your machine: instructions, permissions and
# SigNoz's skills. Only the MCP address differs, so it comes from app/mcp.json.
COPY workspace/AGENTS.md workspace/CLAUDE.md /workspace/
COPY workspace/.claude/settings.json /workspace/.claude/settings.json
COPY workspace/.claude/skills /workspace/.claude/skills
COPY app/mcp.json /etc/investigator/mcp.json
COPY app/investigator.py /app/investigator.py

USER node
ENV HOME=/home/node
CMD ["python3", "/app/investigator.py"]
