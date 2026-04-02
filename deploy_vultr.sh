#!/bin/bash
# ============================================================
# TradingAgent - Vultr VPS Deployment Script
# Server: 65.20.83.74 | Mumbai | Ubuntu 22.04
# Run this from your Mac Terminal: bash deploy_vultr.sh
# ============================================================

SERVER_IP="65.20.83.74"
SERVER_USER="root"
APP_DIR="/opt/trading-agent"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "=================================================="
echo " TradingAgent Vultr Deployment"
echo " Target: $SERVER_USER@$SERVER_IP"
echo "=================================================="
echo ""
echo "You'll be asked for the server password a couple of times."
echo "Password: bD?2\$2#TY-v*sx@9"
echo ""

# Step 1: Add server to known hosts
echo "[1/5] Adding server to known hosts..."
ssh-keyscan -H $SERVER_IP >> ~/.ssh/known_hosts 2>/dev/null

# Step 2: Set up server environment
echo "[2/5] Setting up server environment (Python, pip, git)..."
ssh $SERVER_USER@$SERVER_IP << 'REMOTE_SETUP'
set -e
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv git curl -qq
pip3 install gunicorn -q
mkdir -p /opt/trading-agent
echo "✅ Server environment ready"
REMOTE_SETUP

# Step 3: Copy project files (excluding .git, __pycache__, test files, node_modules)
echo "[3/5] Uploading TradingAgent files..."
rsync -avz --progress \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='server.pid' \
  --exclude='server.log' \
  --exclude='*.log' \
  --exclude='node_modules' \
  --exclude='venv' \
  --exclude='.env' \
  "$PROJECT_DIR/" $SERVER_USER@$SERVER_IP:$APP_DIR/

# Step 4: Upload .env separately
echo "[4/5] Uploading environment variables..."
scp "$PROJECT_DIR/.env" $SERVER_USER@$SERVER_IP:$APP_DIR/.env

# Step 5: Install dependencies and set up systemd service
echo "[5/5] Installing dependencies and creating service..."
ssh $SERVER_USER@$SERVER_IP << REMOTE_DEPLOY
set -e
cd $APP_DIR

# Install Python dependencies
pip3 install -r requirements.txt -q
echo "✅ Dependencies installed"

# Create systemd service for auto-start
cat > /etc/systemd/system/trading-agent.service << 'SERVICE'
[Unit]
Description=TradingAgent Flask App
After=network.target

[Service]
User=root
WorkingDirectory=/opt/trading-agent
EnvironmentFile=/opt/trading-agent/.env
ExecStart=/usr/local/bin/gunicorn server:app --bind 0.0.0.0:80 --workers 1 --timeout 120
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

# Enable and start the service
systemctl daemon-reload
systemctl enable trading-agent
systemctl restart trading-agent
sleep 2
systemctl status trading-agent --no-pager

echo ""
echo "✅ TradingAgent is LIVE at http://$SERVER_IP:80"
REMOTE_DEPLOY

echo ""
echo "=================================================="
echo " ✅ DEPLOYMENT COMPLETE!"
echo ""
echo " Dashboard: http://$SERVER_IP:80"
echo " Static IP (whitelist in Dhan): $SERVER_IP"
echo " TradingView Webhook URL: http://$SERVER_IP:80/webhook"
echo "=================================================="
