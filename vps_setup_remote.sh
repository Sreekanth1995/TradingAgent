#!/bin/bash
# Remote setup script - runs ON the VPS
set -e

APP_DIR="/opt/trading-agent"
cd $APP_DIR

echo "=== [1/4] Setting up Python virtual environment ==="
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q

echo "=== [2/4] Installing dependencies ==="
pip install -r requirements.txt -q
echo "✅ Dependencies installed"

echo "=== [3/4] Creating systemd service ==="
cat > /etc/systemd/system/trading-agent.service << 'SERVICE'
[Unit]
Description=TradingAgent Flask App
After=network.target

[Service]
User=root
WorkingDirectory=/opt/trading-agent
EnvironmentFile=/opt/trading-agent/.env
ExecStart=/opt/trading-agent/venv/bin/gunicorn server:app --bind 0.0.0.0:80 --workers 1 --timeout 120
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable trading-agent
systemctl start trading-agent
sleep 2
systemctl status trading-agent --no-pager

echo "=== [4/4] Configuring firewall ==="
ufw allow 80/tcp
ufw allow OpenSSH
ufw --force enable
ufw status

echo ""
echo "✅ VPS setup complete! TradingAgent is running on port 80"
