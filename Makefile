.PHONY: install uninstall clean

PREFIX ?= /usr/local
BINDIR = $(PREFIX)/bin
SYSTEMDDIR = /lib/systemd/system
CONFIGDIR = /etc/cloudflare-ddns
CACHEDIR = /var/cache/cloudflare-ddns
DOCDIR = $(PREFIX)/share/doc/cloudflare-ddns-updater

install:
	# Install the main script
	install -D -m 755 src/cloudflare-ddns.py $(DESTDIR)$(BINDIR)/cloudflare-ddns
	
	# Install systemd units
	install -D -m 644 systemd/cloudflare-ddns.service $(DESTDIR)$(SYSTEMDDIR)/cloudflare-ddns.service
	install -D -m 644 systemd/cloudflare-ddns.timer $(DESTDIR)$(SYSTEMDDIR)/cloudflare-ddns.timer
	
	# Install example config
	install -D -m 644 config.example.json $(DESTDIR)$(DOCDIR)/config.example.json
	
	# Create directories
	install -d -m 755 $(DESTDIR)$(CONFIGDIR)
	install -d -m 755 $(DESTDIR)$(CACHEDIR)
	
	# Reload systemd if available
	if [ -d /run/systemd/system ]; then \
		systemctl daemon-reload || true; \
	fi
	
	@echo "Installation complete!"
	@echo "Next steps:"
	@echo "1. Copy example config: sudo cp $(DOCDIR)/config.example.json $(CONFIGDIR)/config.json"
	@echo "2. Edit config: sudo nano $(CONFIGDIR)/config.json"
	@echo "3. Enable service: sudo systemctl enable --now cloudflare-ddns.timer"

uninstall:
	# Stop and disable service
	if [ -d /run/systemd/system ]; then \
		systemctl stop cloudflare-ddns.timer || true; \
		systemctl disable cloudflare-ddns.timer || true; \
	fi
	
	# Remove files
	rm -f $(DESTDIR)$(BINDIR)/cloudflare-ddns
	rm -f $(DESTDIR)$(SYSTEMDDIR)/cloudflare-ddns.service
	rm -f $(DESTDIR)$(SYSTEMDDIR)/cloudflare-ddns.timer
	rm -rf $(DESTDIR)$(DOCDIR)
	
	# Reload systemd
	if [ -d /run/systemd/system ]; then \
		systemctl daemon-reload || true; \
	fi
	
	@echo "Uninstall complete!"
	@echo "Config and cache directories preserved at:"
	@echo "  - $(CONFIGDIR)"
	@echo "  - $(CACHEDIR)"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + || true
	find . -type f -name "*.pyc" -delete || true
	rm -rf build/ dist/ *.egg-info/ || true
	rm -f debian/files debian/*.debhelper debian/*.debhelper.log debian/*.substvars || true
	rm -rf debian/cloudflare-ddns-updater/ || true