FROM python:3.14.7-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip setuptools \
    && python -m pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -u 10001 app && chown -R app /app
USER app
CMD ["python", "app/worker.py"]