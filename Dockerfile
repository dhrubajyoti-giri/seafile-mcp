FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir .

# Streamable HTTP (multi-user). For local single-user stdio, override the command.
ENV SEAFILE_TRANSPORT=streamable-http
ENV SEAFILE_HOST=0.0.0.0
ENV SEAFILE_PORT=8000

EXPOSE 8000

CMD ["seafile-mcp", "--transport", "streamable-http"]
