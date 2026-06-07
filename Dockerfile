FROM python:3.11-slim-bookworm

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        poppler-utils \
        gcc \
        libjpeg62-turbo-dev \
        libtiff5 \
        libopenjp2-7 \
        liblcms2-2 \
        libwebpdemux2 \
        libwebp-dev \
        libimagequant0 \
        libgphoto2-6 \
        ca-certificates \
        curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./server/
COPY client/ ./client/

RUN mkdir -p uploads

EXPOSE 8080

ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=server/app.py

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8080", "--timeout", "120", "server.app:app"]
