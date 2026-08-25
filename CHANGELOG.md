# CHANGELOG

## 2026-08-25 (2) — LXQt desktop + multi-device

### Thêm mới

1. **Đổi Desktop Environment — biến `DESKTOP`**
   - `DESKTOP=lxqt` (**mặc định mới**, nhẹ hơn): LXQt + Openbox (Arc-Dark) + pcmanfm-qt. Đo thực tế trên cùng image: container **226MB** so với **350MB** của XFCE → **tiết kiệm ~124MB RAM**.
   - `DESKTOP=xfce` — quay lại XFCE4 cổ điển với dock trong suốt như cũ (đã test compat OK).
   - Fix kèm theo: LXQt không tự khởi động WM qua config mặc định → set `window_manager=openbox` đúng key trong `session.conf`; tắt xscreensaver autostart; `xset s off -dpms` trong session.
   - Watchdog / health / optimizer nhận diện session process động theo `DESKTOP` (không còn hardcode `xfce4-session`).

2. **Multi-device dùng đồng thời**
   - Xác minh `-AlwaysShared`: nhiều thiết bị mở cùng domain thấy chung một desktop và cùng điều khiển (shared session kiểu TeamViewer). Test 2 kết nối RFB auth **đồng thời** qua WebSocket bridge → cả hai AUTH OK.
   - Bridge aiohttp async nên số kết nối song song không giới hạn ở tầng app.

3. Build args mới: `INSTALL_LXQT=1` (default) — build slim có thể đặt `0`.

## 2026-08-25 — Stability, 24/7, Watchdog, Optimizer, Guide, Logs

### Bug đã sửa

1. **ROOT CAUSE #1 — Xvnc KHÔNG BAO GIỜ start được (phát hiện khi test thực tế)**
   - Lệnh Xvnc cũ chứa option **`-QualityLevel`** (cùng `-CompressionLevel`, `-MaxCutPending`) — đây là option của TightVNC/TurboVNC, **không tồn tại** trong TigerVNC của Debian bookworm. Kết quả: `Fatal server error: Unrecognized option: -QualityLevel` → Xvnc crash ngay lúc boot → port 5901 không bao giờ mở → **mọi trình duyệt đều thấy "Connecting…" vĩnh viễn rồi "Failed to connect to server"**.
   - Các commit fix cũ chỉ xử lý triệu chứng (retry 60s ở bridge, đổi thứ tự start) mà không thấy lỗi cú pháp lệnh này.
   - Đã thay bằng bộ option TigerVNC hợp lệ (`-FrameRate`, `-CompareFB`, `-ZlibLevel`, `-BlacklistThreshold=0`, `-UseBlacklist=0`) và kiểm chứng bằng RFB handshake thật qua WebSocket.
2. **ROOT CAUSE #2 — idle-monitor tự kill XFCE sau 5 phút idle**
   - `IDLE_TIMEOUT` mặc định `300` khiến `supervisorctl stop desktop` chạy định kỳ. Người dùng quay lại thấy desktop đen/mất kết nối — nguyên nhân "Failed" ngẫu nhiên hằng ngày. Giờ mặc định `0` = **24/7 không bao giờ suspend**; muốn bật lại thì set `IDLE_TIMEOUT>0`.
3. **ROOT CAUSE #3 — supervisor bỏ cuộc vĩnh viễn + không có hồi sinh**
   - `startretries=20/50` cạn sau chuỗi crash nhanh → service FATAL mãi. Thêm resource-watchdog revival: unhealthy → restart với backoff 30s→600s, tối đa 6 lần/giờ/service, log `[VNC] unhealthy/restarting/ready`.
4. **code-server bind nhầm port công khai (phát hiện khi test)**
   - code-server ưu tiên biến môi trường `PORT` hơn cả flag `--bind-addr`. Trên Railway `PORT=8080` → code-server crash `EADDRINUSE: 127.0.0.1:8080` liên tục. Đã tạo wrapper `run-code-server.sh` unset `PORT` trước khi exec.
5. **Xvnc blacklist khóa cả người dùng thật (phát hiện khi test)**
   - Các kết nối chưa hoàn tất auth (health probe cũ, noVNC auto-reconnect với mật khẩu sai) cộng dồn vào blacklist của Xvnc → server trả "Too many security failures" cho MỌI client kể cả khi nhập đúng mật khẩu. Đã tắt blacklist (`-BlacklistThreshold=0 -UseBlacklist=0`) và chuyển health-check sang đọc `/proc/net/tcp` (LISTEN check) — không còn connection rác nào chạm vào Xvnc.
6. **Path traversal trong static serving**: `/novnc/../../etc/passwd` đọc được file ngoài root. Đã thay bằng `safe_join()` (realtime realpath check) — test xác nhận 404 với mọi biến thể encoded.
7. **FPS bịa số**: API cũ trả giá trị env làm FPS thật. Giờ trả `null` → UI hiển thị `N/A`.
8. **Nút Terminal/Firefox/Chromium hỏng ngầm**: postMessage vào iframe noVNC không được xử lý / chỉ mở Google Search. Thay bằng `/api/apps/{name}` whitelist launcher chạy thật trên desktop.
9. **WebSocket bridge rò rỉ lỗi nội bộ**: exception string gửi thẳng ra browser qua close frame. Giờ chỉ mã + message chung chung.
10. **Healthcheck "ok" giả**: `/health` luôn 200 dù VNC chết. Giờ JSON chi tiết từng component; 503 khi VNC FAILED sau boot-grace (Railway tự restart container như phương án cuối).
11. **dbus system bus chết im lặng**: thiếu package `dbus` (chỉ có `dbus-x11`) → `/usr/share/dbus-1/system.conf` không tồn tại → `dbus-daemon --system` crash loop. Đã thêm package.
12. **pulseaudio FATAL noise** khi audio off: exit trước `startsecs=1` → FATAL. Đổi `startsecs=0`.

### Optimization đã thêm

- Docker image: gộp layer, xoá `/usr/share/doc`, `/usr/share/man`, apt lists/cache, `apt autoremove`; bỏ `gdown` pip (không dùng).
- Optional build args: `INSTALL_GIMP / INSTALL_LIBREOFFICE / INSTALL_VLC / INSTALL_TOR / INSTALL_NODE / INSTALL_CODESERVER` (mặc định 1 = giữ nguyên tính năng hiện tại).
- XFCE: tắt compositor/shadow, power-manager không sleep/dpms/lock, screensaver off — desktop luôn hiển thị 24/7.
- `chown -R /home/user` cũ (chậm với volume lớn) → chỉ chown các thư mục cần thiết.
- Wallpaper chỉ copy nếu chưa tồn tại (volume mount không bị ghi đè mỗi boot).
- Chromium/Firefox Preferences/user.js chỉ tạo khi chưa có (giữ cài đặt người dùng).

### Feature mới

- **`/health` JSON chi tiết**: `{status, vnc, desktop, websocket, code_server, components{...}, uptime_seconds}`. Trạng thái: `healthy | degraded | starting | unhealthy`. Trả HTTP 503 khi VNC chết sau boot-grace (Railway sẽ restart container như phương án cuối).
- **Watchdog revival**: Xvnc/XFCE/HTTP chết → tự `supervisorctl restart` với backoff 30s→600s, log `[VNC] unhealthy / restarting / ready`.
- **System Optimizer** (web UI): cảnh báo → dry-run option → 9 bước → SSE realtime log → kết quả RAM/Disk/Services/Time. Script `optimize-system --dry-run` chạy tay được. Log: `/var/log/optimizer.log`.
- **Guide panel**: nút "Hướng dẫn" góc trái dưới màn hình — 7 mục (Bắt đầu/Cài ứng dụng/Developer/Storage/Tối ưu/Troubleshooting/Railway), nút Copy cho từng command.
- **Logs viewer**: whitelist 9 log (system/boot/vnc/xfce/websocket/watchdog/optimizer/code-server/backup), Refresh/Clear/Auto-refresh. Không đọc được file ngoài whitelist (chặn path traversal).
- **Connection status UI**: Starting / Waiting for VNC / Connecting / Connected / Reconnecting / Failed + nút Reconnect now; đọc trạng thái thật từ noVNC (same-origin) + `/health`.
- **Services panel** trong sidebar: VNC/XFCE/WebSocket/HTTP/Code Server với READY/STARTING/STOPPED/WARNING/FAILED (dữ liệu thật từ backend).
- **Uptime thực**: backend trả `uptime_seconds`, UI đếm mượt giữa các lần poll.
- **App launcher API** (`/api/apps/{terminal|firefox|chromium|files}`): chỉ chạy command whitelist, không nhận lệnh tuỳ ý.
- **VS Code lazy-start cải tiến**: start → poll port → mở tab khi sẵn sàng; code-server tự restart nếu chết sau khi đã bật (`autorestart=true`, `autostart=false`).

### Environment variables mới

| Biến | Mặc định | Ý nghĩa |
|------|----------|---------|
| `IDLE_TIMEOUT` | `0` (trước là `300`) | 0 = 24/7 không suspend. Đặt >0 để bật lại tính năng cũ |
| `BOOT_GRACE_SEC` | `240` | Thời gian boot-grace trước khi health báo FAILED |
| `VNC_CONNECT_WINDOW` | `120` | Bridge chờ Xvnc bao lâu trước khi từ chối WS |
| `CODE_START_TIMEOUT` | `30` | Timeout chờ code-server lên port |
| `VNC_PASSWORD` | `railwaylinux` | Mật khẩu VNC mặc định (theo yêu cầu). Đặt giá trị khác để đổi; `none` = tắt xác thực. Phiên bản cũ mặc định `linuxdesktop` hardcode — đã bỏ |

Không phá biến cũ: mọi biến cũ vẫn hoạt động đúng ý nghĩa.

### Deploy Railway

1. Fork/push repo này
2. Railway New Project → Deploy from GitHub
3. Volume mount `/home` (khuyến nghị)
4. Generate Domain → mở URL

### Troubleshoot "Connecting…"

1. Container mới boot: chờ 15–30s, trang tự chuyển Connected
2. Bấm **Reconnect now**
3. Kiểm tra `<domain>/health` — xem `status` và `components.vnc`
4. Xem tab **Logs → boot/vnc** trong web UI
5. Railway → Deployments → Restart nếu kéo dài > 2 phút

### Sử dụng System Optimizer

Sidebar → **Toi uu** → đọc cảnh báo → (tuỳ chọn Dry run) → **Chay toi uu hoa** → xem progress `[1/9]…[9/9]` → kết quả hiện RAM saved / Disk cleaned / Services / Time.

### Kết quả test thực tế (Docker, image build từ repo này)

| # | Test | Kết quả |
|---|------|---------|
| 1 | Docker build | PASS (image ~1.45GB) |
| 2 | Boot flow + boot log `[BOOT]/[VNC]/[XFCE]/[WS]/[SYSTEM]` | PASS (~16s đến Desktop READY) |
| 3 | HTTP 200, index served | PASS |
| 4 | `/health` JSON chi tiết từng component | PASS |
| 5 | Port 5901 LISTEN, Xvnc chạy user=user | PASS |
| 6 | WebSocket bridge → RFB banner qua `/websockify` | PASS |
| 7 | VNC auth challenge-response (DES) đúng mật khẩu `railwaylinux` | PASS |
| 8 | Sai mật khẩu → không auth được; custom password không leak qua API | PASS |
| 9 | Kill Xvnc → watchdog restart → health `starting`→`ready` → RFB OK lại | PASS (~28s) |
| 10 | Kill XFCE (`pkill -9 xfce4-session`) → tự hồi sinh | PASS |
| 11 | Kill HTTP server → watchdog revive | PASS |
| 12 | Optimizer dry-run + real run qua CLI và HTTP API (SSE stream) | PASS (9/9 steps) |
| 13 | Optimizer không xóa user data (sentinel: Documents/Projects/.ssh/git config) | PASS |
| 14 | Path traversal (novnc static, catch-all, log names) | PASS (404 hết) |
| 15 | Logs viewer whitelist 9 file | PASS |
| 16 | code-server lazy-start qua API → ready 1.5s → proxy `/code/` 200 | PASS |
| 17 | FPS hiển thị N/A (không fake), uptime real từ backend | PASS |

Chưa test được trong môi trường này: noVNC render pixel trên trình duyệt thật (cần màn hình), Railway deploy thật (volume mount + PORT injection của platform), Tor/proxy end-to-end.

### File đã thay đổi / mới

- Sửa: `Dockerfile`, `start.sh`, `supervisord.conf`, `http-server.py`, `index.html`, `resource-watchdog.py`, `idle-monitor.py`, `railway.json`, `README.md`
- Mới: `scripts/optimize.sh`, `scripts/run-code-server.sh`, `.dockerignore`, `CHANGELOG.md`
