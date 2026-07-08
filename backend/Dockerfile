FROM python:3.12-slim

WORKDIR /app

# Install uv (fast Python package manager)
RUN pip install --no-cache-dir uv

# Copy dependency manifest and install dependencies only (cache layer)
COPY backend/pyproject.toml backend/.python-version ./
RUN uv sync --no-dev --no-install-project

# Copy application source
COPY backend/app/ app/

# Copy frontend static files (served by FastAPI)
COPY frontend/ frontend/

EXPOSE 8000

CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
