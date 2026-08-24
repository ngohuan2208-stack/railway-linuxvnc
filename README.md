# Linux Desktop trên Railway

Desktop Linux nhẹ, tùy chỉnh cao, chạy trên trình duyệt web.

## Tính năng chính

- **XFCE4** + Dock trong suốt (Arc-Dark theme)
- **noVNC** + sidebar theo dõi FPS/RAM/CPU real-time
- **Bàn phím ảo** Onboard
- **VS Code** (code-server) port 8443
- **YouTube** playback (Chromium + codecs)
- **Auto-sleep** tiết kiệm RAM khi idle
- **Tor proxy** chống IP block
- **Wallpaper** gradient tùy chỉnh

## Ứng dụng có sẵn

| Ứng dụng | Mục đích |
|----------|----------|
| Firefox ESR | Trình duyệt web |
| Chromium | Trình duyệt nhanh, YouTube |
| VS Code | Code editor (web) |
| VLC | Xem video, nghe nhạc |
| GIMP | Chỉnh sửa ảnh |
| LibreOffice | Office (Writer, Calc, Impress) |
| Thunar | Quản lý tập tin |
| xfce4-terminal | Terminal emulator |
| Mousepad | Soạn thảo văn bản |
| htop | Theo dõi hệ thống |
| xfce4-taskmanager | Quản lý tiến trình |

## Triển khai

1. Fork repo
2. Deploy trên Railway
3. Set env vars (xem bên dưới)
4. Thêm Volume mount tại `/home`
5. Generate domain
6. Mở domain

## Biến môi trường

| Biến | Mặc định | Mô tả |
|------|-----------|-------|
| `PORT` | `8080` | Cổng web |
| `RESOLUTION` | `1600x900` | Độ phân giải |
| `VNC_DEPTH` | `24` | Bit màu (16=ít RAM) |
| `VNC_FPS` | `30` | FPS khung hình VNC |
| `TZ` | _(trống)_ | Múi giờ |
| `IDLE_TIMEOUT` | `300` | Giây trước khi sleep |
| `ENABLE_PROXY` | `0` | Bật Tor proxy (1=bật) |
| `AUTO_BACKUP` | `1` | Tự động backup |

## FPS & Hiển thị

Sidebar hiển thị:
- **FPS** — Tốc độ khung hình real-time
- **CPU/RAM/Disk** — Usage với bar indicator
- **Network** — WiFi, Sent/Recv bytes
- **System** — Uptime, Idle time, Sleep status

## YouTube & Video

### Chromium (khuyến nghị)
```bash
# Chromium đã cấu hình sẵn cho YouTube
chromium-browser --no-sandbox https://youtube.com
```

### Firefox
```bash
firefox-esr https://youtube.com
```

### VLC
```bash
vlc /path/to/video.mp4
```

Codecs đã cài: ffmpeg, gstreamer1.0 (base, good, bad, ugly), libav

## Tor Proxy (Chống IP Block)

### Bật proxy
```bash
start-proxy
```

### Dùng Tor
```bash
proxychains4 firefox-esr              # Firefox qua Tor
proxychains4 chromium-browser --no-sandbox  # Chromium qua Tor
proxychains4 curl -s https://httpbin.org/ip  # Test IP
```

### Tắt proxy
```bash
stop-proxy
```

### Kiểm tra Tor
```bash
curl --proxy socks5://127.0.0.1:9050 https://check.torproject.org
```

## Đổi ảnh nền

```bash
# Wallpaper đã tạo sẵn
ls ~/.wallpapers/

# Đổi qua terminal
DISPLAY=:1 xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitor0/workspace0/last-image -s /path/to/image.png

# Wallpaper tự động tạo gradient dark
python3 /usr/local/bin/wallpaper-gen.py ~/.wallpapers/mywallpaper.png 1920 1080
```

## Dock trong suốt

Dock (panel) XFCE4 đã cấu hình:
- **Vị trí**: Bottom center
- **Theme**: Arc-Dark, transparency 75%
- **Icons**: Papirus-Dark, 36px
- **Apps**: Firefox, Chromium, Terminal, Files, Tasklist

## Cài app mới

### Dùng apt (terminal)
```bash
sudo apt update && sudo apt install -y <package-name>
```

### Ví dụ
```bash
# Telegram
sudo apt install -y telegram-desktop

# Slack
sudo snap install slack --classic  # (nếu snap available)

# FileZilla
sudo apt install -y filezilla

# Audacity
sudo apt install -y audacity

# Blender
sudo apt install -y blender
```

### App `.deb`
```bash
wget https://example.com/app.deb
sudo dpkg -i app.deb
sudo apt-get install -f  # sửa dependency nếu cần
```

### App `.AppImage`
```bash
chmod +x app.AppImage
./app.AppImage
```

## Tiết kiệm RAM

| Tính năng | Tiết kiệm |
|-----------|-----------|
| VNC_DEPTH=16 | ~50MB |
| XFCE compositor off | ~30MB |
| MALLOC_ARENA_MAX=2 | ~20MB |
| Auto-sleep (idle) | ~100-200MB |
| Drop page cache | ~50-200MB |
| **Tổng tối đa** | **~250-400MB** |

## Kiến trúc

- **Base**: Debian Bookworm Slim
- **Desktop**: XFCE4 + Arc-Dark + Papirus icons
- **VNC**: TigerVNC (Xvnc localhost, configurable FPS)
- **Web**: Python HTTP server (noVNC proxy + stats API)
- **IDE**: code-server (VS Code web)
- **Browser**: Chromium + Firefox ESR (YouTube codecs)
- **Media**: VLC, ffmpeg, gstreamer
- **Office**: LibreOffice Writer/Calc/Impress
- **Image**: GIMP
- **Proxy**: Tor + Privoxy (optional)
- **Idle Monitor**: xprintidle + Python auto-sleep
- **Process Manager**: supervisord
