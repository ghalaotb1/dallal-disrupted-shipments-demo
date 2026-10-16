# Dallal backend. Build from the REPOSITORY ROOT:   docker build -f backend/Dockerfile -t dallal-backend .
# Runs from the source tree (paths in dallal/config.py are relative to it). No datasets, no secrets, no raw data in the image:
# only code, the committed calibrated model artifacts and the committed experiment reports.
FROM python:3.12-slim
# Secure by default: staging mode refuses to start without DALLAL_API_KEY, forces simulated actions and sandbox WhatsApp unless explicitly configured otherwise.
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PORT=8000 DALLAL_ENV=staging DALLAL_DB=/data/dallal.sqlite DALLAL_BACKUP_DIR=/data/backups DALLAL_AUTOSTART=1
WORKDIR /app/backend
COPY backend/pyproject.toml ./pyproject.toml
RUN pip install "pydantic>=2.7" "pyyaml>=6" "requests>=2.31" "numpy>=1.26" "pandas>=2.2" "pyarrow>=16" "scikit-learn>=1.5" "joblib>=1.3" "scipy>=1.11" "fastapi>=0.110" "uvicorn>=0.29"
COPY backend/dallal ./dallal
COPY backend/artifacts ./artifacts
COPY backend/registry ./registry
COPY docs/ml /app/docs/ml
COPY docs/experiments /app/docs/experiments
RUN mkdir -p /data && useradd -m dallal && chown -R dallal /data
USER dallal
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://localhost:%s/v1/health'%os.environ.get('PORT','8000'))"
CMD ["sh", "-c", "python -m uvicorn dallal.api.app:app --host 0.0.0.0 --port ${PORT}"]
