# Multi-stage build
FROM python:3.12-slim AS builder

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN apt-get update && apt-get install -y git

# Runtime stage
FROM python:3.12-slim

# Create non-root user
RUN useradd -m appuser
USER appuser

WORKDIR /app

# Copy from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy app code
COPY . .

# Expose port
EXPOSE 8085

# Healthcheck: use python to avoid installing curl in slim image
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import sys,urllib.request as u;\ntry:\n r=u.urlopen('http://localhost:8085/', timeout=5);\n sys.exit(0 if r.getcode()==200 else 1)\nexcept Exception:\n sys.exit(1)"]

# Run as non-root
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8085"]
