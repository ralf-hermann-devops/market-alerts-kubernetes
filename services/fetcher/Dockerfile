FROM python:3.14.7-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -u 10001 app && chown -R app /app
USER app
CMD ["python", "-m", "app.scheduler"]