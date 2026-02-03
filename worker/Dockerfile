# worker/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install cloud CLIs (optional, for extended functionality)
# RUN curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
#     && curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" \
#     && unzip awscliv2.zip \
#     && ./aws/install \
#     && rm -rf awscliv2.zip aws/

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create non-root user
RUN useradd -m -u 1001 worker && \
    chown -R worker:worker /app
USER worker

# Health check (simple process check)
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import redis; r=redis.Redis(host='localhost', port=6379, socket_connect_timeout=1); r.ping()" || exit 1

CMD ["python", "worker.py"]