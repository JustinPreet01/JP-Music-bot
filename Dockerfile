# Python ka official image use kar rahe hain
FROM python:3.10-slim

# System updates aur FFmpeg install karna
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libffi-dev \
    libnacl-dev \
    python3-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Working directory set karna
WORKDIR /app

# Requirements copy karke install karna
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baaki saara code copy karna
COPY . .

# Bot ko start karna
CMD ["python", "bot.py"]
