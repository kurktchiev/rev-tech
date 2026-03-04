FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy workspace root and agents package
COPY pyproject.toml ./
COPY agents/ agents/

# Install dependencies
RUN uv sync --no-dev

EXPOSE 9003

CMD ["uv", "run", "python", "-m", "agents.general_agent.main"]