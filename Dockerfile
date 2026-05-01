FROM python:3.14-slim

RUN groupadd --gid 1000 bot && \
    useradd --uid 1000 --gid bot --create-home bot

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

USER bot

CMD ["python", "-m", "bot.main"]
