# Dockerfile

# --- Stage 1: Build Stage ---
# Use a bigger base image for installing dependencies
FROM python:3.12-slim as builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install Python dependencies
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# --- Stage 2: Final/Runtime Stage ---
# Use a smaller base image for security and size
FROM python:3.12-slim

# Copy dependencies from the builder stage
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

# Copy application code
WORKDIR /app
COPY . /app

# Expose the port used by your FastAPI/Uvicorn server (e.g., 8085)
EXPOSE 8085

# Run the application using Uvicorn
# Adjust 'api.server:app' if your main file path is different
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8085"]