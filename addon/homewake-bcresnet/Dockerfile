FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY homewake /app/homewake
COPY models /app/models
COPY scripts /app/scripts
COPY addon/homewake-bcresnet/run.sh /usr/local/bin/run.sh

RUN pip install --no-cache-dir . && chmod +x /usr/local/bin/run.sh

EXPOSE 10700

ENTRYPOINT ["/usr/local/bin/run.sh"]
