FROM python:3.12-slim

# Mencegah Python menulis file .pyc & memastikan log langsung tampil di stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# libgomp1 wajib ada di Linux container agar LightGBM (anomaly_model.pkl) bisa berjalan
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install dependency Python lebih dulu agar cache Docker layer optimal
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Salin kode FastAPI, artefak model, dan unit test
COPY app ./app
COPY artifacts ./artifacts
COPY tests ./tests
COPY pytest.ini .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
