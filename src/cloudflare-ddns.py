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
                return json.load(f)
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
        
    def get_dns_record(self, subdomain: str) -> Optional[Tuple[str, str]]:
        """Get DNS record ID and current IP for a subdomain"""
        url = f"{self.api_base}/zones/{self.config['zone_id']}/dns_records"
        params = {
            "name": f"{subdomain}.{self.config['domain']}",
            "type": "A"
        }
        
        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            if data["success"] and data["result"]:
                record = data["result"][0]
                return record["id"], record["content"]
            else:
                logger.error(f"DNS record not found for {subdomain}.{self.config['domain']}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.exception(f"Failed to get DNS record for {subdomain}: {e}")
            return None
            
    def update_dns_record(self, subdomain: str, record_id: str, ip: str) -> bool:
        """Update DNS A record for subdomain"""
        url = f"{self.api_base}/zones/{self.config['zone_id']}/dns_records/{record_id}"
        data = {
            "type": "A",
            "name": f"{subdomain}.{self.config['domain']}",
            "content": ip,
            "ttl": self.config.get("ttl", 120),
            "proxied": self.config.get("proxied", False)
        }
        
        try:
            response = requests.put(url, headers=self.headers, json=data)
            response.raise_for_status()
            
            result = response.json()
            if result["success"]:
                logger.info(f"Successfully updated {subdomain}.{self.config['domain']} to {ip}")
                return True
            else:
                logger.error(f"Failed to update {subdomain}: {result.get('errors', 'Unknown error')}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.exception(f"Failed to update DNS record for {subdomain}: {e}")
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
        
        # Process each subdomain
        updates_needed = []
        subdomains = self.config["subdomains"]
        
        for i, subdomain in enumerate(subdomains):
            record_info = self.get_dns_record(subdomain)
            
            if not record_info:
                logger.warning(f"Skipping {subdomain} - record not found")
                continue
                
            record_id, current_dns_ip = record_info
            
            # Check if update is needed by comparing with actual DNS value
            if current_dns_ip == current_ip:
                logger.info(f"{subdomain}.{self.config['domain']} already has correct IP ({current_ip})")
            else:
                logger.info(f"{subdomain}.{self.config['domain']} needs update: {current_dns_ip} -> {current_ip}")
                updates_needed.append((subdomain, record_id))
            
            # Rate limiting between API calls (except for the last one)
            if i < len(subdomains) - 1:
                time.sleep(1)
        
        # Perform updates if needed
        if not updates_needed:
            logger.info("All DNS records are already up to date")
            # Still update cache file even if no DNS updates were needed
            if current_ip != last_cached_ip:
                try:
                    cache_file.write_text(current_ip)
                except Exception as e:
                    logger.warning(f"Failed to update cache file: {e}")
            return
        
        # Update records that need it
        success_count = 0
        total_updates = len(updates_needed)
        
        for i, (subdomain, record_id) in enumerate(updates_needed):
            if self.update_dns_record(subdomain, record_id, current_ip):
                success_count += 1
            
            # Rate limiting between update calls (except for the last one)
            if i < total_updates - 1:
                time.sleep(1)
        
        # Update cache file if any updates succeeded
        if success_count > 0:
            try:
                cache_file.write_text(current_ip)
            except Exception as e:
                logger.warning(f"Failed to update cache file: {e}")
        
        # Report results
        if success_count == total_updates:
            logger.info(f"Successfully updated all {success_count} DNS records")
        else:
            logger.warning(f"Updated {success_count}/{total_updates} DNS records")
            

if __name__ == "__main__":
    try:
        ddns = CloudflareDDNS()
        ddns.run()
    except Exception as e:
        logger.exception(f"Unhandled exception: {e}")
        sys.exit(1)