FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Create output directory
RUN mkdir -p /app/output

# Create data directory for API
RUN mkdir -p /app/data

# Default command (can be overridden in docker-compose)
CMD ["python", "-m", "src.main"]
