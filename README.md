# Linux Desktop trên Railway

Desktop Linux nhẹ (XFCE + noVNC), chạy ổn định 24/7, tự phục hồi, tối ưu RAM cho Railway.

## Tính năng chính

- **XFCE4** + Dock trong suốt (Arc-Dark theme)
- **noVNC** + sidebar theo dõi CPU/RAM/Disk/Network/Uptime real-time
- **24/7 mode** — desktop KHÔNG tự sleep/suspend khi idle
- **Tự phục hồi** — watchdog tự restart Xvnc / XFCE / HTTP / code-server khi chết (có backoff, chống restart-loop)
- **/health** — health check chi tiết từng component (VNC, XFCE, WebSocket, HTTP, Code Server)
- **System Optimizer** — dọn dẹp an toàn ngay trên web UI, có dry-run, xem log realtime
- **Guide** — hướng dẫn sử dụng đầy đủ trong web UI (nút góc trái dưới)
- **Logs viewer** — xem log hệ thống/VNC/XFCE/WebSocket/Optimizer trực tiếp
- **VS Code** (code-server) lazy-start, tự phục hồi
- **Bàn phím ảo** Onboard
- **YouTube** playback (Chromium + codecs)
- **Tor proxy** tùy chọn

## Ứng dụng có sẵn

| Ứng dụng | Mục đích |
|----------|----------|
| Firefox ESR | Trình duyệt web |
| Chromium | Trình duyệt nhanh, YouTube |
| VS Code | Code editor (web, lazy-start) |
| VLC | Xem video, nghe nhạc |
| GIMP | Chỉnh sửa ảnh |
| LibreOffice | Office (Writer, Calc, Impress) |
| Thunar | Quản lý tập tin |
| xfce4-terminal | Terminal emulator |
| Mousepad | Soạn thảo văn bản |
| htop | Theo dõi hệ thống |
| xfce4-taskmanager | Quản lý tiến trình |

## Triển khai trên Railway

1. Fork repo
2. Railway > New Project > Deploy from GitHub repo
3. (Khuyến nghị) Thêm Volume mount tại `/home` để giữ dữ liệu
4. Generate Domain
5. Mở domain — chờ 15–30 giay boot đầu tiên, trang sẽ tự chuyển `Connected`

## Biến môi trường

| Biến | Mặc định | Mô tả |
|------|-----------|-------|
| `PORT` | `8080` | Cổng web (Railway tự gán) |
| `RESOLUTION` | `1600x900` | Độ phân giải desktop |
| `VNC_DEPTH` | `24` | Bit màu (16 = ít RAM hơn) |
| `VNC_FPS` | `30` | Giới hạn FPS của Xvnc (1–60) |
| `VNC_PASSWORD` | `railwaylinux` | Mật khẩu VNC (noVNC sẽ hỏi khi kết nối). Đặt `none` để tắt xác thực (VNC chỉ nghe localhost) |
| `TZ` | _(trống)_ | Múi giờ, ví dụ `Asia/Ho_Chi_Minh` |
| `IDLE_TIMEOUT` | `0` | **0 = 24/7 không sleep.** > 0 = giây idle trước khi suspend XFCE (tùy chọn cũ) |
| `ENABLE_PROXY` | `0` | Bật Tor proxy (1=bật) |
| `ENABLE_AUDIO` | `0` | Bật PulseAudio (tốn ~50–80MB RAM) |
| `AUTO_BACKUP` | `1` | Tự động backup định kỳ |
| `BACKUP_INTERVAL_MIN` | `30` | Chu kỳ backup (phút) |
| `MEM_LIMIT_MB` | `1228` | Ngưỡng RAM watchdog can thiệp |
| `CPU_MAX_PCT` | `85` | Ngưỡng CPU watchdog renice |
| `DISK_CLEAN_PCT` | `80` | % disk trước khi auto-clean |
| `WATCHDOG_INTERVAL` | `5` | Chu kỳ kiểm tra watchdog (giây) |
| `BOOT_GRACE_SEC` | `240` | Thời gian "grace" lúc boot trước khi /health báo FAILED |
| `VNC_CONNECT_WINDOW` | `120` | Số giây WebSocket bridge chờ Xvnc trước khi từ chối |
| `CODE_START_TIMEOUT` | `30` | Timeout chờ code-server lên port khi bấm VS Code |

### Optional components (build-time)

Image hỗ trợ build slim bằng `--build-arg` (mặc định = 1, giữ nguyên tính năng):

```bash
docker build \
  --build-arg INSTALL_GIMP=0 \
  --build-arg INSTALL_LIBREOFFICE=0 \
  --build-arg INSTALL_VLC=0 \
  --build-arg INSTALL_TOR=0 \
  --build-arg INSTALL_NODE=0 \
  --build-arg INSTALL_CODESERVER=1 \
  -t my-desktop .
```

## FPS & Hiển thị

Sidebar hiển thị:
- **CPU/RAM/Disk** — gauge usage thực tế (đọc cgroup của container)
- **Network** — Sent/Recv bytes
- **Uptime** — uptime thật của container (backend trả về)
- **FPS** — hiển thị `N/A` vì Xvnc không expose số frame thực tế; hệ thống KHÔNG bịa dữ liệu

## YouTube & Video

```bash
# Chromium (khuyến nghị, đã cấu hình sẵn)
chromium --no-sandbox https://youtube.com

# Firefox ESR
firefox-esr https://youtube.com

# VLC
vlc /path/to/video.mp4
```

## Tor Proxy (tùy chọn)

```bash
start-proxy                            # cần ENABLE_PROXY=1
proxychains4 curl -s https://httpbin.org/ip
stop-proxy
```

## System Optimizer

Nút **Toi uu** ở sidebar hoặc Guide:
1. Hiện cảnh báo → chọn Dry run nếu muốn xem trước
2. Chạy 9 bước: kiểm tra CPU/RAM/disk → dọn apt cache → file temp → XFCE → browser cache → kiểm tra service → Railway optimizations
3. Log realtime từng bước, kết quả cuối: RAM saved / Disk cleaned / Services / Time

Chỉ dọn những thứ an toàn. **Không bao giờ đụng** `/home/user/{Desktop,Documents,Downloads,Projects}`, SSH keys, git config, source code.

Chạy tay trong terminal:

```bash
optimize-system --dry-run   # xem trước
optimize-system             # chạy thật (log: /var/log/optimizer.log)
```

## Kiến trúc & Boot flow

```
Container start
→ Environment validation        [BOOT]
→ Filesystem init (/home/user)  [BOOT] Storage OK
→ D-Bus                         [BOOT] D-Bus OK
→ HTTP server (Railway healthcheck trả lời ngay, /health trung thực)
→ Xvnc :1 → wait port 5901      [VNC] Ready
→ XFCE session                  [XFCE] Ready
→ WebSocket bridge sẵn sàng     [WS] ready
→ Watchdog + backup + optional  [SYSTEM] Desktop READY
```

Process manager: supervisord (autorestart) + resource-watchdog (revive có exponential backoff, tối đa 6 lần/giờ/service).

Kết nối trình duyệt:

```
Browser → noVNC → WebSocket /websockify → bridge (localhost) → Xvnc 5901 → XFCE
```

noVNC tự reconnect (`reconnect=true`); UI hiển thị trạng thái Starting / Waiting for VNC / Connecting / Connected / Reconnecting / Failed kèm nút Reconnect.

## Cài app mới

```bash
sudo apt update && sudo apt install -y <package>

# .deb
wget https://example.com/app.deb && sudo dpkg -i app.deb && sudo apt-get install -f

# AppImage
chmod +x app.AppImage && ./app.AppImage
```
