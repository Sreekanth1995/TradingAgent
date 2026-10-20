#!/bin/bash
# ============================================================
# TradingAgent - Vultr VPS Deployment Script
# Server: 65.20.83.74 | Mumbai | Ubuntu 22.04
# Run this from your Mac Terminal: bash deploy_vultr.sh
# ============================================================

SERVER_IP="65.20.83.74"
SERVER_USER="root"
APP_DIR="/opt/trading-agent"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

VERSION_FILE="$PROJECT_DIR/VERSION"
if [ -f "$VERSION_FILE" ]; then
    CURRENT_VERSION=$(tr -d '[:space:]' < "$VERSION_FILE")
else
    CURRENT_VERSION=$(git describe --tags --exact-match 2>/dev/null || git describe --tags 2>/dev/null || echo "v2.0.0")
fi
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

echo ""
echo "=================================================="
echo " TradingAgent Vultr Deployment"
echo " Target: $SERVER_USER@$SERVER_IP"
echo " Release: $CURRENT_VERSION ($GIT_COMMIT on $GIT_BRANCH)"
echo "=================================================="
echo ""
echo "You'll be asked for your server SSH password or key."
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
  --exclude='.claude' \
  --exclude='graphify-out' \
  --exclude='.planning' \
  --exclude='.env' \
  --exclude='trade_history.json' \
  --exclude='levels.json' \
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

# Clean up obsolete .git folder if present from older syncs
rm -rf $APP_DIR/.git

# Record release metadata on server
cat > $APP_DIR/RELEASE_INFO << RELEASE_META_INNER
Version: $CURRENT_VERSION
Commit: $GIT_COMMIT
Branch: $GIT_BRANCH
DeployedAt: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
RELEASE_META_INNER

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
echo "✅ TradingAgent ($CURRENT_VERSION) is LIVE at http://$SERVER_IP:80"
REMOTE_DEPLOY

echo ""
echo "=================================================="
echo " ✅ DEPLOYMENT COMPLETE!"
echo ""
echo " Release: $CURRENT_VERSION ($GIT_COMMIT)"
echo " Dashboard: http://$SERVER_IP:80"
echo " Health Check: http://$SERVER_IP:80/health"
echo " Version API: http://$SERVER_IP:80/version"
echo " Static IP (whitelist in Dhan): $SERVER_IP"
echo " TradingView Webhook URL: http://$SERVER_IP:80/webhook"
echo "=================================================="
