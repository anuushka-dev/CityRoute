FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements-prod.txt .

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements-prod.txt

# CityRoute application
COPY app ./app

# Large Kanpur routing graph used by CityRoute
COPY data/graphs/kanpur.graphml ./data/graphs/kanpur.graphml

# Run as an unprivileged user instead of root.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Render supplies PORT at runtime.
# /health is the CityRoute health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
url='http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'); \
sys.exit(0 if urllib.request.urlopen(url, timeout=4).status == 200 else 1)" || exit 1

# Each worker loads its own copy of the large Kanpur graph.
# Default to one worker for the Render deployment.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-1}"]