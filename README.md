# Linux Desktop trên Railway

Desktop Linux nhẹ (XFCE + noVNC), chạy ổn định 24/7, tự phục hồi, tối ưu RAM cho Railway.

## Tính năng chính

- **Desktop Linux** — LXQt (mặc định, nhẹ) hoặc XFCE, chọn bằng biến `DESKTOP`
- **Đa thiết bị cùng lúc** — mở domain trên PC/laptop/điện thoại: tất cả xem và điều khiển chung một desktop (shared session, không giới hạn số thiết bị)
- **noVNC** + sidebar theo dõi CPU/RAM/Disk/Network/Uptime real-time
- **24/7 mode** — desktop KHÔNG tự sleep/suspend khi idle
- **Tự phục hồi** — watchdog tự restart Xvnc / Desktop / HTTP / code-server khi chết (có backoff, chống restart-loop)
- **/health** — health check chi tiết từng component (VNC, Desktop, WebSocket, HTTP, Code Server, AI CLI)
- **System Optimizer** — dọn dẹp an toàn ngay trên web UI, có dry-run, xem log realtime
- **Buff hệ điều hành** — wizard chọn profile tối ưu: Lite Siêu Nhẹ / Developer / Media & Design / Driver & Phần cứng / BUFF TAT CA (bỏ qua = giữ mặc định LXQt nhẹ - đẹp - ổn định)
- **Cài VS Code PC** — 1 nút: tự tải .deb từ microsoft.com và cài, tiến độ hiển thị trong web Terminal
- **AI CLI** — trợ lý AI có toàn quyền chạy lệnh trong desktop (web UI + lệnh `ai` trong terminal), tự động chặn lệnh phá hoại (rm -rf /, mkfs, shutdown...)
- **Guide** — hướng dẫn sử dụng đầy đủ trong web UI (nút góc trái dưới)
- **Logs viewer** — xem log hệ thống/VNC/Desktop/WebSocket/Optimizer trực tiếp
- **VS Code web** (code-server) lazy-start, tự phục hồi
- **Hình nền** — 6 gradient preset + upload ảnh riêng
- **Chất lượng ảnh màn hình** — chọn Đẹp / Cân bằng / Mượt / Tiết kiệm băng thông ngay trên sidebar
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
| `DESKTOP` | `lxqt` | Desktop environment: `lxqt` (nhẹ ~100MB ít RAM hơn) hoặc `xfce` |
| `RESOLUTION` | `1600x900` | Độ phân giải desktop |
| `VNC_DEPTH` | `24` | Bit màu (16 = ít RAM hơn) |
| `VNC_FPS` | `30` | Giới hạn FPS của Xvnc (1–60) |
| `VNC_PASSWORD` | `railwaylinux` | Mật khẩu VNC (noVNC sẽ hỏi khi kết nối). Đặt `none` để tắt xác thực (VNC chỉ nghe localhost) |
| `VNC_PUBLIC` | `0` | `1` = Xvnc nghe 0.0.0.0 — cho phép app VNC thật (RealVNC/TigerVNC/RVNC) kết nối qua TCP Proxy |
| `VNC_TCP_PROXY` | _(trống)_ | Địa chỉ Railway TCP Proxy của port 5901 (vd `abc.proxy.rlwy.net:12345`) — hiện trong nút **VNC Client** |
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
| `AI_API_LINK` | _(trống)_ | Link API AI (OpenAI-compatible, vd `https://api.openai.com/v1`, hoặc Gemini) |
| `AI_API_KEY` | _(trống)_ | API key của dịch vụ AI |
| `AI_MODEL` | _(trống)_ | Tên model (vd `gpt-4o-mini`, `gemini-1.5-flash`) |
| `AI_NAME` | `AI Assistant` | Tên hiển thị của AI |
| `AI_PROVIDER` | `openai` | `openai` hoặc `gemini` (thường tự nhận diện theo link) |
| `AI_EXEC_TIMEOUT` | `240` | Timeout (giây) tối đa cho 1 lệnh AI chạy |

> Đặt đủ 3 biến `AI_API_LINK`, `AI_API_KEY`, `AI_MODEL` là bật AI CLI. Config được ghi sẵn vào hệ điều hành (`~/.ai-cli/config.json`) — trong terminal desktop gõ `ai "viec can lam"` hoặc `ai --run "viec can lam"` để AI tự làm.

### Optional components (build-time)

Optional components (build args): `INSTALL_LXQT` (default 1), `INSTALL_GIMP`, `INSTALL_LIBREOFFICE`, `INSTALL_VLC`, `INSTALL_TOR`, `INSTALL_NODE`, `INSTALL_CODESERVER` — đặt `0` để build slim.

## Đổi Desktop Environment

```bash
DESKTOP=lxqt   # mặc định - nhẹ, đẹp (Arc-Dark + Papirus + Openbox)
DESKTOP=xfce   # XFCE4 cổ điển với dock trong suốt
```

Đặt biến trên Railway → Variables → redeploy. Cả hai đều dùng chung apps (Firefox, Chromium, VS Code, VLC...).

## Nhiều thiết bị cùng lúc

Desktop chạy dạng **shared session**: mọi thiết bị mở cùng domain sẽ thấy cùng màn hình và cùng điều khiển (con trỏ di chuyển theo thiết bị đang thao tác). Không cần đăng nhập thêm, không giới hạn số kết nối đồng thời.

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

## Kết nối bằng app VNC thật (RealVNC / TigerVNC / RVNC)

Nút **VNC Client (IP + Pass)** trên sidebar hiện địa chỉ + mật khẩu để dán vào app VNC — độ trễ thấp hơn noVNC, nhiều thiết bị cùng xem vẫn OK.

Thiết lập một lần:

1. Railway → Service → Settings → Networking → **+ TCP Proxy**, gắn với cổng nội bộ **5901**
2. Copy địa chỉ proxy Railway cấp (vd `abc.proxy.rlwy.net:12345`)
3. Thêm biến: `VNC_PUBLIC=1` và `VNC_TCP_PROXY=abc.proxy.rlwy.net:12345` → redeploy
4. Mở nút **VNC Client** → copy địa chỉ + mật khẩu vào app

⚠️ Khi `VNC_PUBLIC=1`, hãy luôn đặt `VNC_PASSWORD` mạnh — không bật public mà để trống mật khẩu.

## Buff hệ điều hành

Lần đầu mở trang, wizard hỏi chọn profile (mở lại bất cứ lúc nào bằng nút **Buff HDH**):

| Profile | Nội dung |
|---------|----------|
| **Bỏ qua** | Giữ mặc định LXQt siêu nhẹ — đẹp — ổn định (khuyến nghị RAM nhỏ) |
| **Lite Siêu Nhẹ** | Dọn sâu sau cài + tinh chỉnh hiệu năng, không tải thêm gì |
| **Developer Đầy Đủ** | gcc/cmake, jq, ripgrep, fzf, tmux, sqlite3, strace, python venv... |
| **Media & Design** | Inkscape, Krita, Audacity, mpv, HandBrake |
| **Driver & Phần Cứng** | FUSE + gvfs, NTFS/exFAT, USB/PCI tools, SMART, lm-sensors |
| **BUFF TẤT CẢ** | dev + media + drivers một lượt (~500MB+) |

Tiến độ hiển thị realtime trong web Terminal. Chạy tay được: `os-profile dev`.

## AI CLI

- Web UI: nút **AI CLI** → mô tả việc cần làm → AI trả lời + đưa ra lệnh. Bật "Tự chạy lệnh" để AI tự thực thi.
- Terminal desktop: `ai "cai dat vlc va mo luon"` (xem lệnh) hoặc `ai --run "..."` (chạy luôn).
- **An toàn**: mọi lệnh đi qua bộ lọc — chặn `rm -rf` trên thư mục hệ thống/home, `mkfs`/`fdisk`/`dd` ghi đĩa, fork bomb, shutdown/reboot, `supervisorctl stop/shutdown`, kill service nền, sửa `/etc/shadow|sudoers`, gỡ VNC/desktop packages... Lệnh bị chặn hiện lý do rõ ràng.

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
