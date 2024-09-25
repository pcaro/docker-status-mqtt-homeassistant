FROM ghcr.io/astral-sh/uv:python3.12-alpine

ADD . /app

WORKDIR /app
RUN uv sync --frozen

CMD ["uv", "run", "main.py"]