FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8
ENV SEAFILE_TRANSPORT=streamable-http
ENV SEAFILE_HOST=0.0.0.0
ENV SEAFILE_PORT=8000
ENV SEAFILE_SESSION_PATH=/data/sessions.json

RUN mkdir -p /data && chmod 700 /data

EXPOSE 8000

CMD ["python", "-m", "seafile_mcp.entrypoint"]
