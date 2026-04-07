# AURA Backend Dockerfile
# Python FastAPI application

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./backend/
COPY .env .env

# Create data directories
RUN mkdir -p /data/chroma_db /data/documents /data/identity

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV CHROMA_PATH=/data/chroma_db
ENV INGEST_DIR=/data/documents
ENV P2P_KEY_DIR=/data/identity

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
