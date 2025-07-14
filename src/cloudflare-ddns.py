#!/usr/bin/env python3
"""
Cloudflare DDNS Updater
Updates specified DNS records with current public IP
"""

import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class CloudflareDDNS:
    def __init__(self, config_file: str = "/etc/cloudflare-ddns/config.json"):
        self.config_file = Path(config_file)
        self.config = self._load_config()
        self.api_base = "https://api.cloudflare.com/client/v4"
        self.headers = {
            "Authorization": f"Bearer {self.config['api_token']}",
            "Content-Type": "application/json"
        }
        
    def _load_config(self) -> Dict:
        """Load configuration from JSON file"""
        if not self.config_file.exists():
            logger.error(f"Configuration file not found: {self.config_file}")
            sys.exit(1)
            
        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
                
            # Support both old single-domain and new multi-domain format
            if 'domain' in config:
                # Convert old format to new format internally
                logger.info("Using single-domain configuration format")
                config = {
                    'api_token': config['api_token'],
                    'domains': [{
                        'domain': config['domain'],
                        'zone_id': config['zone_id'],
                        'subdomains': config['subdomains'],
                        'ttl': config.get('ttl'),  # None if not specified
                        'proxied': config.get('proxied')  # None if not specified
                    }]
                }
            else:
                logger.info("Using multi-domain configuration format")
                
            return config
        except json.JSONDecodeError as e:
            logger.exception(f"Invalid JSON in config file: {e}")
            sys.exit(1)
        except Exception as e:
            logger.exception(f"Failed to load config file: {e}")
            sys.exit(1)
            
    def get_public_ip(self) -> Optional[str]:
        """Get current public IP address"""
        ip_services = [
            "https://api.ipify.org?format=json",
            "https://ipinfo.io/json",
            "https://api.ip.sb/ip",
            "https://checkip.amazonaws.com"
        ]
        
        for service in ip_services:
            try:
                response = requests.get(service, timeout=5)
                if response.status_code == 200:
                    if service == "https://api.ipify.org?format=json":
                        return response.json()["ip"]
                    elif service == "https://ipinfo.io/json":
                        return response.json()["ip"]
                    else:
                        return response.text.strip()
            except Exception as e:
                logger.warning(f"Failed to get IP from {service}: {e}")
                continue
                
        logger.error("Failed to get public IP from all services")
        return None
        
    def get_dns_record(self, zone_id: str, domain: str, subdomain: str) -> Optional[Tuple[str, str, bool, int]]:
        """Get DNS record ID, current IP, proxy status, and TTL for a subdomain"""
        url = f"{self.api_base}/zones/{zone_id}/dns_records"
        params = {
            "name": f"{subdomain}.{domain}",
            "type": "A"
        }
        
        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            if data["success"] and data["result"]:
                record = data["result"][0]
                return record["id"], record["content"], record["proxied"], record["ttl"]
            else:
                logger.error(f"DNS record not found for {subdomain}.{domain}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.exception(f"Failed to get DNS record for {subdomain}.{domain}: {e}")
            return None
            
    def update_dns_record(self, zone_id: str, domain: str, subdomain: str, record_id: str, ip: str, ttl: int, proxied: bool) -> bool:
        """Update DNS A record for subdomain"""
        url = f"{self.api_base}/zones/{zone_id}/dns_records/{record_id}"
        data = {
            "type": "A",
            "name": f"{subdomain}.{domain}",
            "content": ip,
            "ttl": ttl,
            "proxied": proxied
        }
        
        try:
            response = requests.put(url, headers=self.headers, json=data)
            response.raise_for_status()
            
            result = response.json()
            if result["success"]:
                logger.info(f"Successfully updated {subdomain}.{domain} to {ip}")
                return True
            else:
                logger.error(f"Failed to update {subdomain}.{domain}: {result.get('errors', 'Unknown error')}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.exception(f"Failed to update DNS record for {subdomain}.{domain}: {e}")
            return False
            
    def run(self):
        """Main execution method"""
        # Get current public IP
        current_ip = self.get_public_ip()
        if not current_ip:
            logger.error("Cannot proceed without public IP")
            sys.exit(1)
            
        logger.info(f"Current public IP: {current_ip}")
        
        # Check if we need to update by comparing with cached IP
        cache_file = Path("/var/cache/cloudflare-ddns/last_ip")
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        
        last_cached_ip = None
        if cache_file.exists():
            try:
                last_cached_ip = cache_file.read_text().strip()
            except Exception as e:
                logger.warning(f"Failed to read cached IP: {e}")
        
        # Process each domain
        total_updates_needed = 0
        total_success = 0
        
        for domain_config in self.config['domains']:
            domain = domain_config['domain']
            zone_id = domain_config['zone_id']
            subdomains = domain_config['subdomains']
            ttl = domain_config.get('ttl')  # None if not specified
            proxied = domain_config.get('proxied')  # None if not specified
            
            logger.info(f"Processing domain: {domain}")
            
            # Process each subdomain
            for i, subdomain in enumerate(subdomains):
                record_info = self.get_dns_record(zone_id, domain, subdomain)
                
                if not record_info:
                    logger.warning(f"Skipping {subdomain}.{domain} - record not found")
                    continue
                    
                record_id, current_dns_ip, current_proxied, current_ttl = record_info
                
                # Check if update is needed
                if current_dns_ip == current_ip:
                    logger.info(f"{subdomain}.{domain} already has correct IP ({current_ip})")
                else:
                    logger.info(f"{subdomain}.{domain} needs update: {current_dns_ip} -> {current_ip}")
                    total_updates_needed += 1
                    
                    # Use existing proxy status and TTL unless explicitly set in config
                    # If proxied is not specified in config (None), keep existing value
                    use_proxied = proxied if proxied is not None else current_proxied
                    use_ttl = ttl if ttl is not None else current_ttl
                    
                    # Log if we're preserving existing settings
                    if proxied is None:
                        logger.debug(f"Preserving existing proxy setting ({current_proxied}) for {subdomain}.{domain}")
                    if ttl is None:
                        logger.debug(f"Preserving existing TTL ({current_ttl}) for {subdomain}.{domain}")
                    
                    if self.update_dns_record(zone_id, domain, subdomain, record_id, current_ip, use_ttl, use_proxied):
                        total_success += 1
                
                # Rate limiting between API calls
                if i < len(subdomains) - 1:
                    time.sleep(1)
            
            # Rate limiting between domains
            time.sleep(1)
        
        # Update cache file if any updates succeeded or IP changed
        if total_success > 0 or (total_updates_needed == 0 and current_ip != last_cached_ip):
            try:
                cache_file.write_text(current_ip)
            except Exception as e:
                logger.warning(f"Failed to update cache file: {e}")
        
        # Report results
        if total_updates_needed == 0:
            logger.info("All DNS records across all domains are already up to date")
        elif total_success == total_updates_needed:
            logger.info(f"Successfully updated all {total_success} DNS records")
        else:
            logger.warning(f"Updated {total_success}/{total_updates_needed} DNS records")
            

if __name__ == "__main__":
    try:
        ddns = CloudflareDDNS()
        ddns.run()
    except Exception as e:
        logger.exception(f"Unhandled exception: {e}")
        sys.exit(1)