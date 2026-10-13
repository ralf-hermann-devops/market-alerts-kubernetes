FROM python:3.14.7-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip setuptools \
    && python -m pip install --no-cache-dir -r requirements.txt
COPY exporter.py .
RUN useradd -u 10001 app && chown -R app /app
USER app
CMD ["python", "exporter.py"]
