FROM python:3.14.7-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
# 2 stage builds don't make sense here because no build artifacts are produced, 
# and the image size is already small. Instead, we can combine the commands into 
# a single RUN command to reduce the number of layers in the image.
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip setuptools \
    && python -m pip install --no-cache-dir -r requirements.txt
# only copy app scripts and not the tests or other files
COPY app/ ./app/
RUN useradd -u 10001 app && chown -R app /app
USER app
CMD ["python", "-m", "app.scheduler"]