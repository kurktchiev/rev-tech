FROM python:3.13-slim-bookworm

# Install uv for fast package management
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy workspace root and frontend package
COPY pyproject.toml ./
COPY frontend/pyproject.toml ./frontend/
COPY frontend/ ./frontend/

# Install dependencies
RUN uv pip install --system ./frontend

# Chainlit expects public/ and .chainlit/ relative to WORKDIR
RUN cp -r frontend/public /app/public && \
    cp -r frontend/.chainlit /app/.chainlit

EXPOSE 8000

# Set via env var at runtime; "None" disables auth (local dev only)
# ENV CHAINLIT_AUTH_SECRET=None

CMD ["chainlit", "run", "frontend/main.py", "--host", "0.0.0.0", "--port", "8000"]
