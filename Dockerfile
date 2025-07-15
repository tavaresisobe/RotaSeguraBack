FROM python:3.11.4-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    gcc libffi-dev curl build-essential

RUN curl -sSL https://install.python-poetry.org | python3 - --version 1.8.4 \
    && ln -s /root/.local/bin/poetry /usr/local/bin/poetry

COPY pyproject.toml poetry.lock /app/

RUN poetry config virtualenvs.create false

RUN poetry install --no-cache --only main

COPY . /app

RUN chmod +x start.sh

FROM python:3.11.4-slim-bookworm AS final

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

RUN mkdir -p /app/logs

EXPOSE 8000

CMD ["sh", "start.sh"]