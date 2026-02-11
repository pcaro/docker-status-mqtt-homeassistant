FROM ghcr.io/astral-sh/uv:python3.12-alpine

# Set working directory
WORKDIR /app

# Copy all files
COPY . .

# Install dependencies (package needs to be installed for uv to work)
RUN uv sync

# Note: Running as root for Docker socket access
# In production, consider using Docker socket proxy or adjusting permissions

# Health check - comprehensive service validation
HEALTHCHECK --interval=60s --timeout=30s --start-period=10s --retries=3 \
    CMD uv run healthcheck.py

# Run the application
ENV WEB_PORT=8080
EXPOSE 8080
CMD ["uv", "run", "main.py"]