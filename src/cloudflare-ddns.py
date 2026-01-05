#!/usr/bin/env python3
"""Cloudflare DDNS Updater - Updates DNS records with current public IP."""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

IPV4_SERVICES = [
    ("https://api.ipify.org?format=json", "json", "ip"),
    ("https://ipinfo.io/json", "json", "ip"),
    ("https://api.ip.sb/ip", "text", None),
    ("https://checkip.amazonaws.com", "text", None),
]

IPV6_SERVICES = [
    ("https://api6.ipify.org?format=json", "json", "ip"),
    ("https://v6.ident.me", "text", None),
    ("https://api6.my-ip.io/ip", "text", None),
]

MAX_RETRIES = 3
RETRY_BACKOFF = 2


class ConfigError(Exception):
    pass


def retry_request(func):
    def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except requests.exceptions.RequestException as e:
                last_exception = e
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_BACKOFF ** attempt
                    logger.warning(f"Request failed, retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
        raise last_exception
    return wrapper


class CloudflareDDNS:
    def __init__(self, config_file: str, dry_run: bool = False):
        self.config_file = Path(config_file)
        self.dry_run = dry_run
        self.config = self._load_config()
        self._validate_config()
        self.api_base = "https://api.cloudflare.com/client/v4"
        self.headers = {
            "Authorization": f"Bearer {self.config['api_token']}",
            "Content-Type": "application/json"
        }

    def _load_config(self) -> Dict:
        if not self.config_file.exists():
            raise ConfigError(f"Configuration file not found: {self.config_file}")

        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"Invalid JSON in config file: {e}")

        if 'domain' in config:
            logger.info("Converting single-domain to multi-domain format")
            config = {
                'api_token': config.get('api_token'),
                'domains': [{
                    'domain': config.get('domain'),
                    'zone_id': config.get('zone_id'),
                    'subdomains': config.get('subdomains', []),
                    'ttl': config.get('ttl'),
                    'proxied': config.get('proxied'),
                    'ipv6': config.get('ipv6', False),
                }]
            }

        return config

    def _validate_config(self) -> None:
        if not self.config.get('api_token'):
            raise ConfigError("Missing required field: api_token")

        domains = self.config.get('domains', [])
        if not domains:
            raise ConfigError("No domains configured")

        for i, domain_config in enumerate(domains):
            prefix = f"domains[{i}]"
            if not domain_config.get('domain'):
                raise ConfigError(f"Missing required field: {prefix}.domain")
            if not domain_config.get('zone_id'):
                raise ConfigError(f"Missing required field: {prefix}.zone_id")
            if not domain_config.get('subdomains'):
                raise ConfigError(f"Missing required field: {prefix}.subdomains")

    def _get_ip(self, services: List[Tuple], ip_type: str) -> Optional[str]:
        for url, response_type, json_key in services:
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    if response_type == "json":
                        ip = response.json()[json_key]
                    else:
                        ip = response.text.strip()
                    logger.debug(f"Got {ip_type} from {url}: {ip}")
                    return ip
            except Exception as e:
                logger.debug(f"Failed to get {ip_type} from {url}: {e}")
                continue
        return None

    def get_public_ip(self) -> Optional[str]:
        ip = self._get_ip(IPV4_SERVICES, "IPv4")
        if not ip:
            logger.error("Failed to get public IPv4 from all services")
        return ip

    def get_public_ipv6(self) -> Optional[str]:
        return self._get_ip(IPV6_SERVICES, "IPv6")

    @retry_request
    def get_dns_record(self, zone_id: str, record_name: str, record_type: str = "A") -> Optional[Tuple[str, str, bool, int]]:
        url = f"{self.api_base}/zones/{zone_id}/dns_records"
        params = {"name": record_name, "type": record_type}

        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()

        data = response.json()
        if data["success"] and data["result"]:
            record = data["result"][0]
            return record["id"], record["content"], record["proxied"], record["ttl"]

        logger.debug(f"DNS record not found: {record_name} ({record_type})")
        return None

    @retry_request
    def update_dns_record(self, zone_id: str, record_name: str, record_id: str,
                          ip: str, ttl: int, proxied: bool, record_type: str = "A") -> bool:
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would update {record_name} ({record_type}) to {ip}")
            return True

        url = f"{self.api_base}/zones/{zone_id}/dns_records/{record_id}"
        data = {
            "type": record_type,
            "name": record_name,
            "content": ip,
            "ttl": ttl,
            "proxied": proxied
        }

        response = requests.put(url, headers=self.headers, json=data)
        response.raise_for_status()

        result = response.json()
        if result["success"]:
            logger.info(f"Updated {record_name} ({record_type}) to {ip}")
            return True

        logger.error(f"Failed to update {record_name}: {result.get('errors', 'Unknown error')}")
        return False

    def _build_record_name(self, domain: str, subdomain: str) -> str:
        if subdomain in ("@", ""):
            return domain
        return f"{subdomain}.{domain}"

    def _process_record(self, zone_id: str, record_name: str, current_ip: str,
                        ttl: Optional[int], proxied: Optional[bool], record_type: str) -> Tuple[bool, bool]:
        record_info = self.get_dns_record(zone_id, record_name, record_type)

        if not record_info:
            logger.warning(f"Skipping {record_name} ({record_type}) - record not found")
            return False, False

        record_id, current_dns_ip, current_proxied, current_ttl = record_info

        if current_dns_ip == current_ip:
            logger.info(f"{record_name} ({record_type}) already has correct IP")
            return False, False

        logger.info(f"{record_name} ({record_type}) needs update: {current_dns_ip} -> {current_ip}")

        use_proxied = proxied if proxied is not None else current_proxied
        use_ttl = ttl if ttl is not None else current_ttl

        success = self.update_dns_record(zone_id, record_name, record_id, current_ip, use_ttl, use_proxied, record_type)
        return True, success

    def run(self) -> int:
        if self.dry_run:
            logger.info("Running in dry-run mode - no changes will be made")

        current_ipv4 = self.get_public_ip()
        if not current_ipv4:
            logger.error("Cannot proceed without public IPv4")
            return 1

        logger.info(f"Current public IPv4: {current_ipv4}")

        current_ipv6 = None
        if any(d.get('ipv6') for d in self.config['domains']):
            current_ipv6 = self.get_public_ipv6()
            if current_ipv6:
                logger.info(f"Current public IPv6: {current_ipv6}")
            else:
                logger.warning("IPv6 enabled but could not detect IPv6 address")

        total_updates_needed = 0
        total_success = 0

        for domain_config in self.config['domains']:
            domain = domain_config['domain']
            zone_id = domain_config['zone_id']
            subdomains = domain_config['subdomains']
            ttl = domain_config.get('ttl')
            proxied = domain_config.get('proxied')
            ipv6_enabled = domain_config.get('ipv6', False)

            logger.info(f"Processing domain: {domain}")

            for subdomain in subdomains:
                record_name = self._build_record_name(domain, subdomain)

                needed, success = self._process_record(
                    zone_id, record_name, current_ipv4, ttl, proxied, "A"
                )
                if needed:
                    total_updates_needed += 1
                    if success:
                        total_success += 1

                if ipv6_enabled and current_ipv6:
                    needed, success = self._process_record(
                        zone_id, record_name, current_ipv6, ttl, proxied, "AAAA"
                    )
                    if needed:
                        total_updates_needed += 1
                        if success:
                            total_success += 1

                time.sleep(1)

            time.sleep(1)

        self._update_cache(current_ipv4)
        self._log_summary(total_updates_needed, total_success)

        return 0 if total_success == total_updates_needed else 1

    def _update_cache(self, current_ip: str) -> None:
        if self.dry_run:
            return

        cache_file = Path("/var/cache/cloudflare-ddns/last_ip")
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(current_ip)
        except Exception as e:
            logger.warning(f"Failed to update cache file: {e}")

    def _log_summary(self, total_updates_needed: int, total_success: int) -> None:
        if total_updates_needed == 0:
            logger.info("All DNS records are up to date")
        elif total_success == total_updates_needed:
            logger.info(f"Successfully updated all {total_success} DNS records")
        else:
            logger.warning(f"Updated {total_success}/{total_updates_needed} DNS records")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cloudflare DDNS Updater")
    parser.add_argument(
        "-c", "--config",
        default="/etc/cloudflare-ddns/config.json",
        help="Path to configuration file"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        ddns = CloudflareDDNS(args.config, dry_run=args.dry_run)
        return ddns.run()
    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        return 1
    except Exception as e:
        logger.exception(f"Unhandled exception: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
