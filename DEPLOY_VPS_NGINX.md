# Deploy On Ubuntu VPS With Nginx

This guide runs your existing Streamlit app at your domain with:

- `systemd` for process management
- `nginx` as reverse proxy
- Let's Encrypt TLS certificate

It keeps the app behavior the same as local development.

## Recommended VPS size

For this Whisper + Streamlit workload:

- Minimum: `2 vCPU / 2 GB RAM`
- Better: `2-4 vCPU / 4 GB RAM`

`2 GB` can work for short videos, but `4 GB` is more stable.

## 0. Domain choice

This guide uses `YOURDOMAIN` directly.

If you use a subdomain instead, avoid underscores.

## 1. Point DNS to your VPS

At your DNS provider:

1. Create an `A` record:
   - Host/name: `@`
     (or leave blank, depending on provider)
   - Value: your VPS public IPv4
2. (Optional) Add `AAAA` record for IPv6 if your VPS has it.
3. Wait for DNS propagation.

Verify from your machine:

```bash
dig +short YOURDOMAIN
```

## 2. Prepare VPS packages

SSH to server and run:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg nginx certbot python3-certbot-nginx
```

## 3. Create app directory and user ownership

```bash
sudo mkdir -p /opt/ai-video-analyzer
sudo chown -R $USER:$USER /opt/ai-video-analyzer
```

Copy your project files into `/opt/ai-video-analyzer`  
(via `git clone`, `rsync`, or SFTP).

## 4. Install app dependencies

```bash
cd /opt/ai-video-analyzer
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

## 5. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```text
LLM_PROVIDER=auto
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-2.5-flash
GROQ_API_KEY=your_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
WHISPER_MODEL=base
DATA_DIR=/opt/ai-video-analyzer/data
MAX_TRANSCRIPT_CHARS=120000
```

Lock permissions:

```bash
chmod 600 .env
```

Do **not** commit `.env` to git. Keep it only on the server.

## 6. Set filesystem permissions for runtime user

Choose your app runtime user:

- `www-data` (default in template), or
- your SSH user (for example `YOUR_USERNAME`).

Example below uses `YOUR_USERNAME`:

```bash
sudo mkdir -p /opt/ai-video-analyzer/data
sudo chown -R YOUR_USERNAME:YOUR_USERNAME /opt/ai-video-analyzer/data
sudo chown YOUR_USERNAME:YOUR_USERNAME /opt/ai-video-analyzer/.env
```

## 7. Install systemd service

Copy service file from this repo:

```bash
sudo cp deploy/systemd/ai-video-analyzer.service /etc/systemd/system/ai-video-analyzer.service
sudo sed -i 's/^User=.*/User=YOUR_USERNAME/; s/^Group=.*/Group=YOUR_USERNAME/' /etc/systemd/system/ai-video-analyzer.service
```

Reload and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ai-video-analyzer
```

Check status/logs:

```bash
sudo systemctl status ai-video-analyzer --no-pager
sudo journalctl -u ai-video-analyzer -n 100 --no-pager
```

## 8. Configure Nginx reverse proxy

Copy nginx site config:

```bash
sudo cp deploy/nginx/ai-video-analyzer.conf /etc/nginx/sites-available/ai-video-analyzer.conf
sudo ln -s /etc/nginx/sites-available/ai-video-analyzer.conf /etc/nginx/sites-enabled/ai-video-analyzer.conf
```

Optional: remove default site:

```bash
sudo rm -f /etc/nginx/sites-enabled/default
```

Before testing nginx, make sure the nginx config uses your bare domain in `server_name`, for example:

```nginx
server_name YOURDOMAIN;
```

Test and reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 9. Open firewall

If UFW is enabled:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

## 10. Issue HTTPS certificate

```bash
sudo certbot --nginx -d YOURDOMAIN
```

Choose redirect to HTTPS when prompted.

Test renewal:

```bash
sudo certbot renew --dry-run
```

If you also want `www.YOURDOMAIN`, configure DNS and nginx for it, then issue the certificate like this instead:

```bash
sudo certbot --nginx -d YOURDOMAIN -d www.YOURDOMAIN
```

## 11. Verify end-to-end

1. Visit `https://YOURDOMAIN`
2. Upload a short test video.
3. Confirm:
   - transcription works
   - Gemini output appears
   - JSON files are saved in `/opt/ai-video-analyzer/data/results`

## Updating app code later

After you push/update code on the server:

```bash
cd /opt/ai-video-analyzer
source .venv/bin/activate
python3 -m pip install -r requirements.txt
sudo systemctl restart ai-video-analyzer
```

## Repository recommendations (GitHub or Bitbucket)

Keep deployment simple with one repository and one branch for production:

1. Create repo with:
   - `main` as stable branch
   - optional `dev` branch for experiments
2. Add remote and push:

```bash
git init
git add .
git commit -m "Initial AI Video Analyzer MVP"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

3. On VPS, use Git clone for easy updates:

```bash
cd /opt
git clone <your-repo-url> ai-video-analyzer
```

4. Future update flow:
   - Push to `main`
   - On VPS: `git pull`, reinstall requirements, restart service

Use private repos if you keep `.env` only on server (recommended).

## Optional protection for private use

If this is private/personal use, add Basic Auth in nginx to avoid strangers consuming your Gemini quota.

1. Create password file:

```bash
sudo apt install -y apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd YOUR_USERNAME
```

2. Add to the `server` block in `/etc/nginx/sites-available/ai-video-analyzer.conf`:

```nginx
auth_basic "Restricted";
auth_basic_user_file /etc/nginx/.htpasswd;
```

3. Reload:

```bash
sudo nginx -t && sudo systemctl reload nginx
```
