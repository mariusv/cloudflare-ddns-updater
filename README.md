# Cloudflare DDNS Updater

A lightweight Dynamic DNS (DDNS) updater for Cloudflare DNS records. This service automatically updates your DNS A and AAAA records when your public IP address changes, perfect for home servers, VPNs, and other services behind dynamic IPs.

Whether you need to keep one subdomain updated or manage multiple domains with different subdomains, this service handles it all from a single configuration.

## Features

- Lightweight Python-based updater
- IPv4 (A records) and IPv6 (AAAA records) support
- Supports single or multiple domains in one service
- Root domain (@) and subdomain support
- Secure systemd service with hardening options
- Configurable update intervals (default: 5 minutes)
- Smart updates - only updates when IP actually changes
- Dry-run mode for testing configuration
- Automatic retry with exponential backoff
- Comprehensive logging to systemd journal
- Easy installation via Debian package or Docker
- Automatic startup on boot
- Optional Cloudflare proxy support per domain

## Installation

### Option 1: Debian Package (Recommended for servers)

1. Download the latest `.deb` package from [Releases](https://github.com/mariusv/cloudflare-ddns-updater/releases)
2. Install the package:
   ```bash
   sudo dpkg -i cloudflare-ddns-updater_*.deb
   sudo apt-get install -f  # Install any missing dependencies
   ```

### Option 2: Docker Container

```bash
# Pull the image
docker pull ghcr.io/mariusv/cloudflare-ddns-updater:latest

# Run with your config
docker run -v /path/to/config.json:/etc/cloudflare-ddns/config.json:ro ghcr.io/mariusv/cloudflare-ddns-updater

# Or use docker-compose (see docker-compose.example.yml)
wget https://raw.githubusercontent.com/mariusv/cloudflare-ddns-updater/main/docker-compose.example.yml
# Edit docker-compose.example.yml and add your config.json
docker-compose -f docker-compose.example.yml up -d
```

### Option 3: From Source

```bash
git clone https://github.com/mariusv/cloudflare-ddns-updater.git
cd cloudflare-ddns-updater
sudo make install
```

## Configuration

The service can manage DNS records for a single domain or multiple domains from one configuration file.

### Setting Up Your Configuration

1. Copy the example configuration:
   ```bash
   sudo cp /usr/share/doc/cloudflare-ddns-updater/config.example.json /etc/cloudflare-ddns/config.json
   ```

2. Edit the configuration file:
   ```bash
   sudo nano /etc/cloudflare-ddns/config.json
   ```

3. Configure your domain(s):

   **For a single domain:**
   ```json
   {
       "api_token": "YOUR_CLOUDFLARE_API_TOKEN",
       "zone_id": "YOUR_CLOUDFLARE_ZONE_ID",
       "domain": "example.com",
       "subdomains": [
           "@",
           "vpn",
           "home",
           "server"
       ],
       "ttl": 120,
       "proxied": false,
       "ipv6": false
   }
   ```

   **For multiple domains:**
   ```json
   {
       "api_token": "YOUR_CLOUDFLARE_API_TOKEN",
       "domains": [
           {
               "domain": "example.com",
               "zone_id": "ZONE_ID_FOR_EXAMPLE_COM",
               "subdomains": ["@", "vpn", "home", "server"],
               "ttl": 120,
               "proxied": false,
               "ipv6": true
           },
           {
               "domain": "another-domain.org",
               "zone_id": "ZONE_ID_FOR_ANOTHER_DOMAIN",
               "subdomains": ["mail", "ftp", "backup"],
               "ttl": 300,
               "proxied": true,
               "ipv6": false
           }
       ]
   }
   ```

### Configuration Options

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `api_token` | Yes | - | Cloudflare API token with DNS edit permissions |
| `zone_id` | Yes | - | Zone ID for your domain (found in Cloudflare dashboard) |
| `domain` | Yes | - | Your domain name |
| `subdomains` | Yes | - | List of subdomains to update (use `@` for root domain) |
| `ttl` | No | Current | Time-to-live in seconds (minimum 120 for free plans) |
| `proxied` | No | Current | Whether to proxy traffic through Cloudflare |
| `ipv6` | No | false | Enable IPv6 (AAAA record) updates |

### Getting Cloudflare Credentials

1. **API Token**:
   - Go to [Cloudflare Dashboard](https://dash.cloudflare.com/profile/api-tokens)
   - Create a new token with "Zone:DNS:Edit" permissions
   - Scope it to your specific zone

2. **Zone ID**:
   - Go to your domain's overview page in Cloudflare
   - Find the Zone ID in the right sidebar

## Usage

### Enable and Start the Service

```bash
# Enable the timer to start on boot
sudo systemctl enable cloudflare-ddns.timer

# Start the timer
sudo systemctl start cloudflare-ddns.timer

# Check timer status
sudo systemctl status cloudflare-ddns.timer
```

### Manual Run

```bash
# Run the updater manually
sudo systemctl start cloudflare-ddns.service

# Check logs
sudo journalctl -u cloudflare-ddns -f
```

### Dry-Run Mode

Test your configuration without making any changes:

```bash
# Test with default config
cloudflare-ddns --dry-run

# Test with custom config
cloudflare-ddns --config /path/to/config.json --dry-run
```

### Command Line Options

```
Usage: cloudflare-ddns [OPTIONS]

Options:
  -c, --config PATH   Path to configuration file (default: /etc/cloudflare-ddns/config.json)
  --dry-run           Show what would be updated without making changes
```

### Service Management

```bash
# Stop the timer
sudo systemctl stop cloudflare-ddns.timer

# Disable automatic startup
sudo systemctl disable cloudflare-ddns.timer

# View next scheduled run
sudo systemctl list-timers cloudflare-ddns.timer
```

## How It Works

1. The service runs every 5 minutes (configurable)
2. It fetches your current public IPv4 (and IPv6 if enabled) from multiple providers
3. For each configured subdomain:
   - Queries Cloudflare for the current DNS record
   - Compares the DNS IP with your actual public IP
   - Updates only if they differ
4. Failed requests are automatically retried with exponential backoff
5. Caches the last known IP to minimize API calls
6. Logs all actions to systemd journal

## Troubleshooting

### View Logs
```bash
sudo journalctl -u cloudflare-ddns -f
```

### Common Issues

1. **"Configuration error: Missing required field"**: Check your config.json has all required fields
2. **"DNS record not found"**: Ensure the A/AAAA record exists in Cloudflare before running the updater
3. **"Invalid API token"**: Check your API token has the correct permissions
4. **"Failed to get public IP"**: Network connectivity issue or all IP services are down
5. **"IPv6 enabled but could not detect IPv6 address"**: Your network doesn't have IPv6 connectivity

## Security

The service runs with minimal privileges:
- No access to home directories
- Read-only system access (except for cache directory)
- Restricted system calls
- Private /tmp directory

## License

MIT License - see [LICENSE](LICENSE) file for details

## Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss what you would like to change.
