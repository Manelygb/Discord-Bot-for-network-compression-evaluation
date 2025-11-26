FROM python:3.10-slim

# Avoid Python writing .pyc files; ensure stdout/stderr are unbuffered
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# (If you need build tools for some dependencies — e.g. packages with C extensions)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Copy dependencies list & install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create a non-root user and switch to it (good practice for security)
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

# Default command — adjust to your entrypoint (e.g. bot or evaluation script)
CMD ["python3"]
