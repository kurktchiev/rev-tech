FROM python:3.13-slim-bookworm

# Install tsh for agent discovery via Teleport App Access
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    curl -L https://goteleport.com/static/install.sh | bash -s -- 18.6.4 && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    tsh version

# Install uv for fast package management
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy workspace root (needed for uv workspace resolution), agents, and orchestrator
COPY pyproject.toml ./
COPY agents/pyproject.toml agents/
COPY agents/__init__.py agents/
COPY agents/teleport/ agents/teleport/
COPY orchestrator/ orchestrator/

# Install both packages
RUN uv pip install --system ./agents ./orchestrator

EXPOSE 9000

CMD ["python", "-m", "orchestrator.main"]
