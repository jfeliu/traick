FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY traick/ traick/

RUN pip install --no-cache-dir -e .

# Persistent volume for SQLite will be mounted at /data
RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "traick.main:app", "--host", "0.0.0.0", "--port", "8000"]
