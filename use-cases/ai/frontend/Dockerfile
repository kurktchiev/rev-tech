FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Mirror the workspace structure uv expects
COPY pyproject.toml ./
COPY frontend/pyproject.toml ./frontend/

# Now uv can resolve the workspace and find 'frontend'
RUN uv sync --no-install-project --package frontend

# Copy the actual source
COPY frontend/ ./frontend/
COPY frontend/public /app/public
RUN uv sync --package frontend


CMD ["sh", "-c", "export CHAINLIT_AUTH_SECRET=None && uv run --package frontend chainlit run frontend/main.py --host 0.0.0.0 --port 8000"]
