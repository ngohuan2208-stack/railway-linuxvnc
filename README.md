# Linux Desktop trên Railway

Desktop Linux nhẹ, chạy trên trình duyệt web với đầy đủ công cụ.

## Cài đặt công cụ

### Desktop & Office
- **XFCE4** — Desktop nhẹ (~80MB RAM idle)
- **Thunar** — Quản lý tập tin
- **Mousepad** — Soạn thảo văn bản
- **Xarchiver** — Nén/giải nén (zip, 7z, tar)
- **xfce4-screenshooter** — Chụp màn hình
- **Htop** — Theo dõi tài nguyên hệ thống

### Trình duyệt
- **Firefox ESR** — Trình duyệt đầy đủ tính năng

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
6. Mở domain → nhập VNC password

## Biến môi trường

| Biến | Mặc định | Mô tả |
|------|-----------|-------|
| `PORT` | `8080` | Cổng web noVNC |
| `VNC_PASSWORD` | `linuxdesktop` | Mật khẩu desktop |
| `RESOLUTION` | `1600x900` | Độ phân giải |
| `VNC_DEPTH` | `24` | Số bit màu (16=ít RAM hơn, 24=nét hơn) |
| `TZ` | _(trống)_ | Múi giờ (VD: `Asia/Ho_Chi_Minh`) |
| `AUTO_BACKUP` | `1` | Tự động backup định kỳ |
| `BACKUP_INTERVAL_MIN` | `30` | Phút giữa các lần backup |
| `AUTO_BACKUP_ON_EXIT` | `1` | Backup khi tắt máy |

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
- **IDLE RAM**: ~150-250MB (không có trình duyệt)

## Phát triển cục bộ

```bash
docker build -t linux-desktop .
docker run -p 8080:8080 -e VNC_PASSWORD=mypassword linux-desktop
```

Mở `http://localhost:8080/vnc.html` trên trình duyệt.

## Kiến trúc

- **Base**: Debian Bookworm Slim
- **Desktop**: XFCE4 (tùy chỉnh nhẹ)
- **VNC Server**: TigerVNC (Xvnc localhost)
- **Web Client**: noVNC + websockify + heartbeat
- **Process Manager**: supervisord
- **Backup**: tar + symlink, tự động mỗi 30 phút
