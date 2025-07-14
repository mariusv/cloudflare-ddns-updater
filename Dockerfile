FROM debian:bookworm-slim

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y python3 python3-requests && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy application files
COPY src/cloudflare-ddns.py /usr/bin/cloudflare-ddns
RUN chmod +x /usr/bin/cloudflare-ddns

# Create directories
RUN mkdir -p /etc/cloudflare-ddns /var/cache/cloudflare-ddns

# Create entrypoint script
RUN echo '#!/bin/bash\n\
if [ ! -f /etc/cloudflare-ddns/config.json ]; then\n\
  echo "Error: /etc/cloudflare-ddns/config.json not found"\n\
  echo "Mount your config file to /etc/cloudflare-ddns/config.json"\n\
  echo "Example: docker run -v \$PWD/config.json:/etc/cloudflare-ddns/config.json ghcr.io/mariusv/cloudflare-ddns-updater"\n\
  exit 1\n\
fi\n\
exec /usr/bin/cloudflare-ddns "$@"' > /usr/local/bin/docker-entrypoint.sh && \
    chmod +x /usr/local/bin/docker-entrypoint.sh

# Set up volumes
VOLUME ["/etc/cloudflare-ddns", "/var/cache/cloudflare-ddns"]

# Set entrypoint
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Add labels
LABEL org.opencontainers.image.source="https://github.com/mariusv/cloudflare-ddns-updater"
LABEL org.opencontainers.image.description="Lightweight Dynamic DNS updater for Cloudflare"
LABEL org.opencontainers.image.licenses="MIT"