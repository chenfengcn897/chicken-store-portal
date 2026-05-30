#!/bin/bash
# Deploy script for chicken-store-portal

# Create systemd service
cat > /tmp/csp.service << 'SVCEOF'
[Unit]
Description=Chicken Store Data Portal
After=network.target docker.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/chicken-store-portal
ExecStart=/home/ubuntu/chicken-store-portal/venv/bin/python app.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SVCEOF

sudo cp /tmp/csp.service /etc/systemd/system/chicken-store-portal.service
sudo systemctl daemon-reload
sudo systemctl enable chicken-store-portal
sudo systemctl restart chicken-store-portal

# Check if nginx portal location exists
if ! grep -q "location /portal/" /etc/nginx/sites-enabled/default 2>/dev/null; then
    # Add portal location to nginx
    sudo sed -i '/location \/ {/i \    location /portal/ {\n        proxy_pass http://127.0.0.1:5006/;\n        proxy_set_header Host $host;\n        proxy_set_header X-Real-IP $remote_addr;\n        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n    }\n' /etc/nginx/sites-enabled/default
    sudo nginx -t && sudo systemctl reload nginx
fi

sleep 2
sudo systemctl status chicken-store-portal --no-pager
echo "---"
curl -s -o /dev/null -w "%{http_code}" http://localhost:5006/
