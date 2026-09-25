FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV PORT=8080
CMD ["sh", "-c", "exec uvicorn l4flow.app:app --host 0.0.0.0 --port \${PORT}"]
