FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    git \
    libx11-6 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgl1 \
    cmake \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip "setuptools<81"

RUN pip install --no-cache-dir -r requirements.txt

RUN python -c "import face_recognition_models; print('FACE MODELS INSTALLED:', face_recognition_models.__file__)"

COPY . .

CMD ["python", "app.py"]
