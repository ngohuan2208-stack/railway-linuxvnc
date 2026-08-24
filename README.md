# Linux Desktop on Railway

A lightweight Linux desktop environment accessible via web browser, running on Railway.

## Features

- XFCE4 desktop environment
- VNC + noVNC for browser-based access
- Terminal, File Manager (Thunar), and basic applications
- Pre-installed: bash, git, curl, wget, nano, python3, Node.js/npm
- Persistent volume at `/home` for file storage
- Simple password authentication via environment variable
- Optimized for low RAM and CPU usage

## Deploy to Railway

### Prerequisites

- [Railway account](https://railway.app)
- [Railway CLI](https://docs.railway.app/reference/cli) (optional)

### Steps

1. **Fork or clone this repository**

2. **Create a new Railway project**
   - Go to [railway.app](https://railway.app)
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Select this repository

3. **Set environment variables**
   - In Railway dashboard, go to your service → Variables
   - Add `VNC_PASSWORD` with your desired desktop password (default: `linuxdesktop`)

4. **Add persistent volume**
   - In Railway dashboard, go to your service → Volumes
   - Add a volume mounted at `/home`

5. **Generate a domain**
   - In Railway dashboard, go to your service → Settings → Networking
   - Click "Generate Domain" to get a public URL

6. **Access your desktop**
   - Open the generated domain in your browser
   - Enter the VNC password when prompted
   - You'll see the XFCE4 desktop

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | Port for noVNC web interface (auto-set by Railway) |
| `VNC_PASSWORD` | `linuxdesktop` | Password for VNC/desktop access |

## Usage

- **Terminal**: Right-click desktop → Applications → Terminal Emulator
- **File Manager**: Right-click desktop → Applications → File Manager
- **Applications**: Right-click desktop → Applications menu

## Local Development

```bash
docker build -t linux-desktop .
docker run -p 8080:8080 -e VNC_PASSWORD=mypassword linux-desktop
```

Then open `http://localhost:8080/vnc.html` in your browser.

## Architecture

- **Base**: Debian Bookworm Slim
- **Desktop**: XFCE4 (lightweight)
- **VNC Server**: TigerVNC (Xvnc)
- **Web Client**: noVNC + websockify
- **Process Manager**: supervisord

## Resource Usage

- RAM: ~200-400MB idle
- CPU: Minimal when idle
- Disk: ~800MB (base image)
