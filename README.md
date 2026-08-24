# Linux Desktop trên Railway

Desktop Linux nhẹ, chạy trên trình duyệt web với sidebar theo dõi hệ thống.

## Giao diện

- **Sidebar trái** — CPU, RAM, Disk, WiFi, Network, Uptime
- **Bàn phím ảo** — Florence virtual keyboard, toggle bằng nút
- **VS Code** — code-server (VS Code web), mở tab mới
- **Desktop** — XFCE4 qua noVNC, auto-connect

## Cài đặt công cụ

### Desktop & Office
- **XFCE4** — Desktop nhẹ (~80MB RAM idle)
- **Thunar** — Quản lý tập tin
- **Mousepad** — Soạn thảo văn bản
- **Xarchiver** — Nén/giải nén (zip, 7z, tar)
- **xfce4-screenshooter** — Chụp màn hình
- **Htop** — Theo dõi tài nguyên hệ thống
- **Florence** — Bàn phím ảo

### Trình duyệt
- **Firefox ESR** — Trình duyệt đầy đủ tính năng

### IDE
- **VS Code (code-server)** — Trình biên tập code trên web

### Cloud Drive
- **rclone** — Đồng bộ Google Drive, OneDrive, Dropbox...
- **gdown** — Tải file từ Google Drive công khai

### Dev Tools
- **git, curl, wget, nano** — Cơ bản
- **Python3 + pip** — Python development
- **Node.js 20 + npm** — JavaScript development

## Triển khai lên Railway

1. Fork repo này
2. Tạo project mới trên Railway → Deploy from GitHub
3. Set biến môi trường
4. Thêm Volume mount tại `/home`
5. Generate domain
6. Mở domain → sidebar hiện bên trái

## Biến môi trường

| Biến | Mặc định | Mô tả |
|------|-----------|-------|
| `PORT` | `8080` | Cổng web (HTTP server + noVNC) |
| `VNC_PASSWORD` | `linuxdesktop` | Mật khẩu desktop |
| `RESOLUTION` | `1600x900` | Độ phân giải |
| `VNC_DEPTH` | `24` | Số bit màu (16=ít RAM hơn, 24=nét hơn) |
| `TZ` | _(trống)_ | Múi giờ (VD: `Asia/Ho_Chi_Minh`) |
| `AUTO_BACKUP` | `1` | Tự động backup định kỳ |
| `BACKUP_INTERVAL_MIN` | `30` | Phút giữa các lần backup |
| `AUTO_BACKUP_ON_EXIT` | `1` | Backup khi tắt máy |

## Sidebar Stats

Sidebar hiển thị realtime:
- **CPU**: Usage %, Cores, Frequency, Load average
- **RAM**: Usage %, Used/Total, Swap
- **Disk**: Usage %, Used/Total
- **WiFi**: SSID + signal strength (nếu có)
- **Network**: Sent/Recv total bytes
- **System**: Uptime, Processes, Clock

Cập nhật mỗi 2 giây qua API `/api/stats`.

## Bàn phím ảo

1. Click nút "Bàn phím" trên sidebar
2. Florence hiện ở dưới cùng desktop
3. Gõ phím trên máy → gửi vào VNC desktop
4. Toggle lại để ẩn

## VS Code

- Click nút "VS Code" trên sidebar
- Mở tab mới với code-server
- Access trực tiếp, không cần auth
- Port: 8443

## Cloud Drive

### Cấu hình lần đầu
```bash
drive-setup
```
Làm theo hướng dẫn trên terminal.

### Đồng bộ lên Drive
```bash
drive-push    # Đồng bộ Desktop, Documents, Downloads lên Drive
drive-pull    # Tải từ Drive về máy
drive-mount   # Gắn Google Drive (nếu có FUSE)
```

## Backup & Restore

### Backup tự động
- Chạy mỗi 30 phút (cấu hình `BACKUP_INTERVAL_MIN`)
- Backup khi tắt máy (cấu hình `AUTO_BACKUP_ON_EXIT`)
- Lưu tại `/home/user/.backups/`
- Giữ 5 bản gần nhất

### Backup thủ công
```bash
backup-data
```

### Khôi phục
```bash
restore-data
```

## Tiết kiệm RAM

- **VNC_DEPTH=16** — Giảm 1/3 RAM framebuffer
- **RESOLUTION nhỏ** — Giảm RAM VNC (VD: `1280x720`)
- **XFCE compositor tắt** — Tiết kiệm RAM GPU
- **MALLOC_ARENA_MAX=2** — Giảm bộ nhớ glibc
- **Firefox** — Chỉ dùng RAM khi mở, không chạy nền
- **IDLE RAM**: ~200-300MB (sidebar + desktop)

## Kiến trúc

- **Base**: Debian Bookworm Slim
- **Desktop**: XFCE4 (tùy chỉnh nhẹ)
- **VNC Server**: TigerVNC (Xvnc localhost)
- **Web**: Python HTTP server (noVNC proxy + stats API)
- **IDE**: code-server (VS Code web)
- **Virtual Keyboard**: Florence
- **Process Manager**: supervisord
- **Backup**: tar + symlink, tự động mỗi 30 phút
