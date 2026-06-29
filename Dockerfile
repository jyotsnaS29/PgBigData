FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install deps first (better layer caching), then the package.
COPY pyproject.toml ./
COPY src ./src
COPY sql ./sql
COPY dashboard ./dashboard
COPY assistant ./assistant
RUN pip install -e ".[dashboard,server]"

EXPOSE 8501

# Default: serve the dashboard. Ingestion is run as a one-off override:
#   docker compose run --rm dashboard python -m pgbigdata.cli ingest-acs ...
CMD ["streamlit", "run", "dashboard/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]
