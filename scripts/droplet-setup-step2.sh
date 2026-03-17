#!/usr/bin/env bash
set -euo pipefail

echo "=== Step 2: Superuser + Gunicorn + Nginx + Retention ==="

# --- 1. Temporarily disable SSL redirect until certbot runs ---
cd /opt/emp-monitor
sed -i 's/^DJANGO_SECURE_SSL_REDIRECT=True/DJANGO_SECURE_SSL_REDIRECT=False/' .env
sed -i 's/^DJANGO_SESSION_COOKIE_SECURE=True/DJANGO_SESSION_COOKIE_SECURE=False/' .env
sed -i 's/^DJANGO_CSRF_COOKIE_SECURE=True/DJANGO_CSRF_COOKIE_SECURE=False/' .env
# Add http origin while we don't have HTTPS yet
sed -i 's|^DJANGO_CSRF_TRUSTED_ORIGINS=.*|DJANGO_CSRF_TRUSTED_ORIGINS=http://ddcemp.co.za,http://206.189.24.243,https://ddcemp.co.za|' .env

echo "[OK] SSL settings temporarily disabled for initial setup"

# --- 2. Create Django superuser ---
cd /opt/emp-monitor/server
set -a
source /opt/emp-monitor/.env
set +a

export DJANGO_SUPERUSER_USERNAME=admin
export DJANGO_SUPERUSER_EMAIL=admin@ddcemp.co.za
export DJANGO_SUPERUSER_PASSWORD=EmpMon2026!Secure
/opt/emp-monitor/venv/bin/python manage.py createsuperuser --noinput 2>/dev/null && echo "[OK] Superuser 'admin' created" || echo "[SKIP] Superuser already exists"

# --- 3. Fix ownership so www-data can run the app ---
chown -R www-data:www-data /opt/emp-monitor
echo "[OK] Ownership set to www-data"

# --- 4. Install Gunicorn systemd service ---
cp /tmp/deploy/empmonitor.service /etc/systemd/system/empmonitor.service
systemctl daemon-reload
systemctl enable empmonitor
systemctl start empmonitor
sleep 2
systemctl is-active empmonitor && echo "[OK] Gunicorn service running" || { echo "[FAIL] Gunicorn service"; journalctl -u empmonitor --no-pager -n 20; exit 1; }

# --- 5. Install Nginx site ---
cp /tmp/deploy/nginx-empmonitor.conf /etc/nginx/sites-available/empmonitor
ln -sf /etc/nginx/sites-available/empmonitor /etc/nginx/sites-enabled/empmonitor
rm -f /etc/nginx/sites-enabled/default
nginx -t && echo "[OK] Nginx config valid" || { echo "[FAIL] Nginx config invalid"; exit 1; }
systemctl reload nginx
echo "[OK] Nginx reloaded"

# --- 6. Install retention cleanup timer ---
cp /tmp/deploy/empmonitor-retention.service /etc/systemd/system/empmonitor-retention.service
cp /tmp/deploy/empmonitor-retention.timer /etc/systemd/system/empmonitor-retention.timer
systemctl daemon-reload
systemctl enable empmonitor-retention.timer
systemctl start empmonitor-retention.timer
echo "[OK] Retention timer enabled (daily 02:30)"

# --- 7. Open firewall ---
ufw allow 'Nginx Full' >/dev/null 2>&1 || true
ufw allow OpenSSH >/dev/null 2>&1 || true
echo y | ufw enable 2>/dev/null || true
echo "[OK] Firewall configured"

# --- 8. Quick smoke test ---
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/admin/login/)
if [ "$HTTP_CODE" = "200" ]; then
    echo "[OK] Django admin login page returns 200"
else
    echo "[WARN] Admin login returned HTTP $HTTP_CODE (may need DNS/domain)"
fi

echo ""
echo "=== Setup complete ==="
echo "Dashboard: http://206.189.24.243"
echo "Admin:     http://206.189.24.243/admin/"
echo "Username:  admin"
echo "Password:  EmpMon2026!Secure"
echo ""
echo "Next: Point ddcemp.co.za A record to 206.189.24.243, then run certbot"
