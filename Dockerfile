FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir -e .

ENV PORT=8080
EXPOSE 8080

CMD ["python", "-m", "radar.telegram.webhook", "--host", "0.0.0.0", "--port", "8080"]
