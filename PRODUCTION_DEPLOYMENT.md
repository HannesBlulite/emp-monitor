# EMP Monitor Production Deployment

This is the right operating model for this project:

- One central Linux server or DigitalOcean droplet hosts the Django dashboard and API.
- Staff laptops run only the Windows agent.
- The person who monitors staff uses only a browser and never touches Python or server setup.

## Recommended Topology

- DigitalOcean droplet: Ubuntu 24.04
- Reverse proxy: Nginx
- App server: Gunicorn
- Database: PostgreSQL
- TLS: Let's Encrypt
- Optional private networking: ZeroTier if you do not want to expose the dashboard publicly

## What The Monitoring Person Does

The monitoring person only needs:

- the dashboard URL
- a username
- a password

They do not install Python, run scripts, or log into the server.

## High-Level Flow

1. Deploy the Django server to the droplet.
2. Secure it with HTTPS.
3. Create employees and tokens in the dashboard.
4. Install the agent on each staff desktop.
5. Staff machines upload screenshots and activity to the droplet.
6. Managers monitor through the browser.

## 1. Create The Droplet

Use a small Ubuntu droplet to start, for example:

- 2 vCPU
- 2 GB RAM
- 50 GB SSD

Attach a domain if you have one. If not, you can test using the droplet IP first.

## 2. Prepare Ubuntu

SSH into the droplet and run:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx postgresql postgresql-contrib libpq-dev
sudo mkdir -p /opt/emp-monitor
sudo chown -R www-data:www-data /opt/emp-monitor
```

## 3. Copy The Project To The Droplet

Place the project at:

```text
/opt/emp-monitor
```

Suggested structure:

```text
/opt/emp-monitor
  /server
  /agent
  /deploy
  /venv
  .env
```

## 4. Create The Python Environment

```bash
cd /opt/emp-monitor
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r server/requirements.txt
```

Use `server/requirements.txt` on Linux. The root requirements file still includes Windows agent packages such as `pywin32`, which will fail on the droplet.

## 5. Create PostgreSQL Database

```bash
sudo -u postgres psql
```

Then inside PostgreSQL:

```sql
CREATE DATABASE empmonitor;
CREATE USER empmonitor WITH PASSWORD 'replace-with-a-strong-db-password';
GRANT ALL PRIVILEGES ON DATABASE empmonitor TO empmonitor;
\q
```

## 6. Configure Environment Variables

Copy [deploy/production.env.example](deploy/production.env.example) to `/opt/emp-monitor/.env` and set real values.

If you want the secrets generated for you on your Windows machine first, run:

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\generate-production-env.ps1"
```

That script creates a ready-to-use env file with a random Django secret key and PostgreSQL password.

For this live deployment, a local draft file has also been prepared at [.env.ddcemp.local](.env.ddcemp.local) and a runbook at [DEPLOYMENT_NOTES.local.md](DEPLOYMENT_NOTES.local.md).

Minimum required values:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG=False`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- PostgreSQL connection values
- screenshot and activity retention values

## 7. Run Migrations And Collect Static Files

```bash
cd /opt/emp-monitor/server
source /opt/emp-monitor/venv/bin/activate
export $(grep -v '^#' /opt/emp-monitor/.env | xargs)
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
python manage.py check
python manage.py prune_monitoring_data --dry-run
```

## 8. Install Gunicorn Service

Copy [deploy/empmonitor.service](deploy/empmonitor.service) to:

```text
/etc/systemd/system/empmonitor.service
```

Then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable empmonitor
sudo systemctl start empmonitor
sudo systemctl status empmonitor
```

## 8.1 Install Daily Retention Cleanup

Copy these files:

- [deploy/empmonitor-retention.service](deploy/empmonitor-retention.service)
- [deploy/empmonitor-retention.timer](deploy/empmonitor-retention.timer)

To:

```text
/etc/systemd/system/empmonitor-retention.service
/etc/systemd/system/empmonitor-retention.timer
```

Then enable the timer:

```bash
sudo systemctl daemon-reload
sudo systemctl enable empmonitor-retention.timer
sudo systemctl start empmonitor-retention.timer
sudo systemctl list-timers | grep empmonitor-retention
```

This will prune old screenshots and activity data automatically every day.

## 9. Configure Nginx

Copy [deploy/nginx-empmonitor.conf](deploy/nginx-empmonitor.conf) to:

```text
/etc/nginx/sites-available/empmonitor
```

Then enable it:

```bash
sudo ln -s /etc/nginx/sites-available/empmonitor /etc/nginx/sites-enabled/empmonitor
sudo nginx -t
sudo systemctl reload nginx
```

## 10. Add HTTPS

If using a domain:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

Do not leave the production server on plain HTTP if staff desktops are uploading real screenshots.

## Retention Defaults

The production env template includes these defaults:

- screenshots kept for 30 days
- activity logs kept for 90 days

You can change them in `/opt/emp-monitor/.env` without changing code.

## 11. Point Agents To Production

Each staff PC should use:

```json
{
    "server_url": "https://your-domain.com",
    "agent_token": "PER_MACHINE_TOKEN"
}
```

Each machine should have its own token created from the dashboard settings page.

## 12. Operational Recommendation

For this project, the easiest real-world model is:

- You or a technical admin deploy the server once.
- The monitoring person uses only the web dashboard.
- Staff PC agent installation should be turned into a single installer or scripted package.

That is the part worth automating next.

## What Still Needs Hardening

This production pack is enough to stand the server up, but these should be addressed next:

- split server and agent requirements
- add proper production Django settings for secure cookies and proxy SSL headers
- move agent token storage out of plain JSON if you want stronger endpoint security
- create a one-click Windows installer for the agent
- define screenshot retention and backup policy

The production settings and retention cleanup are now in place, but the Windows installer still needs to be built.

## Recommended Next Step

Use the droplet for the dashboard first. After that, automate the Windows agent install so remote desktops can be enrolled with one script or installer.