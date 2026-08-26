# CHANGELOG

## 2026-08-26 (2) — Hotfix: PORT=5901 làm httpserver crash-loop vĩnh viễn

### Bug đã sửa

1. **ROOT CAUSE deploy FAILED — `PORT=5901` trùng port Xvnc**
   - Biến `PORT` trong container nhận giá trị `5901` (đặt tay/conflict khi cấu hình TCP Proxy cho VNC) → HTTP server bind trùng port Xvnc → `OSError 98 address already in use` → exit 1 ~200ms, lặp vô hạn → `/health` không bao giờ trả lời → Railway healthcheck fail hết `healthcheckTimeout` (300s) × retries = deploy treo ~7 phút.
   - Fix 2 lớp: `start.sh` ép `PORT` về 8080 nếu trùng `5901`/`${CODE_SERVER_PORT}` (kèm WARN vào boot log); `http-server.py` tự chặn ở `main()` với thông báo CRITICAL rõ ràng thay vì EADDRINUSE khó hiểu.

## 2026-08-26 (1) — Chống crash-loop httpserver (fail ở build thay vì runtime)

1. Dockerfile thêm smoke test `import aiohttp, psutil` ngay sau layer apt — thiếu dependency giờ làm BUILD FAIL ngay, không còn image hỏng lên Railway crash-loop.
2. start.sh preflight kiểm tra deps trước khi raise supervisord (fail loud kèm hướng dẫn redeploy không cache).
3. `_env_int()` cho mọi biến env số — biến rỗng/rác không còn làm process chết lúc import.
4. Error middleware + traceback đầy đủ ra stderr trước khi exit 1.
5. Lazy-init OptimizerJob/TaskJob; bỏ dead code (`tcp_ready`, `handle_static` trùng lặp); bỏ package chết (`python3-requests`, `xdotool`); bỏ tab log `websocket` chết.
6. Tối ưu build/cache: gộp COPY, `index.html` xuống cuối layer; `.dockerignore` sạch (+`.git`); `access_log=None`; desktop startretries 200→50.

## 2026-08-25 (6) — VNC Client: ket noi bang app VNC that (IP + mat khau)

### Thêm mới

1. **Nút "VNC Client (IP + Pass)"** — modal hiện địa chỉ + mật khẩu để kết nối bằng app VNC thật (RealVNC Viewer, TigerVNC, RVNC...), độ trễ thấp hơn noVNC.
   - API mới `/api/vnc/client`: trả `public_mode`, `tcp_proxy`, `address`, IP nội bộ container, port, mật khẩu (theo đúng chính sách `/api/session` — chỉ lộ khi là mật khẩu mặc định).
   - Biến mới: **`VNC_PUBLIC=1`** → Xvnc bind `0.0.0.0:5901` (trước chỉ nghe localhost); **`VNC_TCP_PROXY=host:port`** → địa chỉ Railway TCP Proxy hiển thị sẵn để copy.
   - Modal có hướng dẫn 4 bước tạo TCP Proxy trên Railway + nút Copy cho từng dòng; cảnh báo đỏ khi bật public mà không có mật khẩu.
   - Fix thứ tự chuẩn hóa `VNC_PUBLIC` trong start.sh (normalize trước khi export cho process con).

## 2026-08-25 (5) — Hotfix: job failed, AI CLI, buff HDH

### Bug đã sửa

1. **ROOT CAUSE "job failed" — sai đường dẫn script** (buff HDH + cài VS Code fail 100%)
   - Dockerfile copy `scripts/os-profile.sh` giữ nguyên tên có `.sh`, nhưng http-server gọi `/usr/local/bin/os-profile` (không `.sh`) → `spawn failed` ngay lập tức. Tương tự với `install-vscode`.
   - Fix: http-server giờ resolve động qua `_script_path()` (thử cả bản không `.sh` và có `.sh`), kiểm tra file tồn tại trước khi spawn và trả lỗi RÕ RÀNG về UI thay vì "spawn failed" chung chung; Dockerfile thêm alias không `.sh` (như `optimize-system`) để chạy tay `os-profile dev`, `install-vscode` được.

2. **AI exec chạy sai HOME (/root)**
   - `bash -l` kế thừa env của root → đọc `/root/.bash_profile` (permission denied) và `$HOME` sai cho mọi lệnh AI.
   - Fix: truyền thẳng `HOME=/home/user, USER=user, LOGNAME=user` vào env con TRƯỚC khi bash đọc profile + `cd /home/user` chặn profile lạ đổi thư mục.

3. **AI exec chạy quyền root tạo file root-owned trong /home/user**
   - Giờ chạy bằng quyền `user` (preexec setuid/gid) — file do AI tạo ra owner đúng; cần root thì `sudo` (NOPASSWD sẵn trong container).
   - Timeout giờ kill CẢ PROCESS GROUP (`killpg` + `start_new_session`) — không còn lệnh con (`sleep`, build...) sống sót ngầm sau khi hủy.

4. **Modal mật khẩu VNC kẹt khi bỏ qua**: đóng modal (Esc/nút Bỏ qua/backdrop) mà chưa nhập pass → iframe vẫn load, noVNC sẽ tự hỏi sau. Đổi chất lượng ảnh trước lúc kết nối cũng không còn reload oan iframe.

5. **Profile Lite "giả"**: trước chỉ in "không có gói nào" — giờ dọn thật: apt cache/lists, thumbnails, /tmp cũ, drop page cache + báo số MB giải phóng.

6. **Cài VS Code im lặng ~1 phút khi download**: giờ log tiến độ mỗi 5 giây ("...đã tải NMB").

7. **Config AI JSON vỡ nếu key chứa ký tự đặc biệt**: start.sh ghi config qua `python3 json.dump` thay vì heredoc bash.

### Ghi chú test

| Test | Kết quả |
|------|---------|
| `_script_path` resolve đúng cả 2 layout (alias + .sh) | PASS |
| POST /api/tasks/run/vscode → script-missing báo lỗi rõ ràng | PASS |
| AI chat gọi OpenAI thật: key sai → 502 + msg sạch (key bị mask) | PASS |
| ai_exec: whoami=user, HOME=/home/user, pwd=/home/user, file owner=user | PASS |
| sudo NOPASSWD từ user context | PASS |
| timeout 3s → rc=124 sau đúng ~3s, pgrep xác nhận KHÔNG leak tiến trình | PASS |

## 2026-08-25 (4) — Mật khẩu VNC, ảnh màn hình, Buff HDH, VS Code PC, AI CLI

### Thêm mới

1. **Bảng nhập mật khẩu VNC riêng (web UI)**
   - Khi admin đặt `VNC_PASSWORD` custom, trang hiện modal nhập mật khẩu đẹp (không còn popup xấu của noVNC); mật khẩu giữ trong bộ nhớ trình duyệt, đổi chất lượng ảnh/kết nối lại không phải nhập lần 2.

2. **Chọn chất lượng ảnh màn hình** (sidebar → Hinh Anh)
   - Đẹp / Cân bằng / Mượt (choi game) / Tiết kiệm băng thông — đổi tức thì bằng cách reload iframe noVNC với `quality`/`compression` tương ứng; lưu localStorage.

3. **Wizard "Buff hệ điều hành"** (`/api/os/profiles`, `/api/tasks/run/os?profile=`)
   - Hiện lần đầu mở trang; **bấm Bỏ qua = mặc định LXQt siêu nhẹ, đẹp, ổn định**.
   - 5 profile: `lite` (dọn sâu + tinh chỉnh), `dev` (gcc/cmake/jq/ripgrep/fzf/tmux/sqlite3/strace...), `media` (Inkscape/Krita/Audacity/mpv/HandBrake), `drivers` (FUSE/gvfs/NTFS/exFAT/USB-PCI/SMART/lm-sensors), `ultra` (= dev + media + drivers).
   - Chạy qua script `os-profile` mới, log realtime ra **web Terminal** (SSE + buffer replay khi mở lại), kết quả JSON tổng hợp. Cài từng gói, lỗi gói nào bỏ qua gói đó không chết cả luồng. Marker `.config/os-profiles/<id>.done` ghi vết.

4. **Web Terminal dùng chung** (`/api/tasks/status|run|stream`)
   - Modal terminal xem tiến độ mọi job backend (buff HDH, cài VS Code). Đóng modal không làm chết job; mở lại thấy toàn bộ log từ đầu.

5. **Nút Cài VS Code bản PC** (`install-vscode`)
   - Tự tải .deb stable từ microsoft.com (~100MB) → apt install → tạo icon Desktop, tự kiểm tra kiến trúc amd64 trước. Toàn bộ output stream vào web Terminal.

6. **AI CLI — trợ lý AI toàn quyền chạy lệnh, có "vành đai" an toàn**
   - Biến Railway: `AI_API_LINK`, `AI_API_KEY`, `AI_MODEL` (+ tuỳ chọn `AI_NAME`, `AI_PROVIDER=openai|gemini`, `AI_TEMPERATURE`, `AI_MAX_TOKENS`, `AI_SYSTEM_PROMPT`, `AI_EXEC_TIMEOUT`). Hỗ trợ mọi API OpenAI-compatible + Gemini.
   - **Ghi thẳng vào hệ điều hành**: boot ghi config vào `~/.ai-cli/config.json`; CLI `ai` (kèm bộ lọc) nằm sẵn trong `/usr/local/bin` — trong desktop terminal chạy `ai "viec"` hoặc `ai --run "viec"`.
   - Web UI: nút **AI CLI** — chat, xem lệnh AI đề xuất (lệnh nguy hiểm hiện nhãn đỏ), bật "Tu chay lenh" để tự thực thi tuần tự, output hiển thị inline.
   - API: `/api/ai/status|chat|exec`. `/api/ai/exec` CHỈ chạy lệnh đã qua bộ lọc an toàn (`ai_safety.py`): chặn rm -rf trên /~/$HOME & thư mục hệ thống, mkfs/fdisk/parted/dd-of=/dev/*, fork bomb, shutdown/reboot/init 0/6, supervisorctl stop/shutdown, kill service nền (Xvnc/dbus/watchdog...), sửa /etc/shadow|passwd|sudoers, gỡ packages VNC/desktop cốt lõi, đụng file platform (/start.sh, supervisord.conf...). Timeout từng lệnh 240s, cắt output 256KB.
   - `/health` thêm component `ai_cli` (ready/stopped).

### Ghi chú test

| Test | Kết quả |
|------|---------|
| Bộ lọc an toàn: 17 lệnh thật (rm -rf /, mkfs, dd, fork bomb, shutdown, pkill Xvnc, sed /start.sh...) | PASS (chặn đúng 11, cho 6 lệnh lành) |
| `ai` CLI gọi API OpenAI thật (401 key giả → báo lỗi sạch) | PASS |
| extract_commands: code block ```bash``` + dòng `$ cmd` | PASS |
| TaskJob stream + parse TASK_RESULT_JSON | PASS |
| http-server import + 48 routes + ai_status/os_profiles handler | PASS |
| os-profile lite chạy thật end-to-end | PASS (TASK_RESULT_JSON ok) |
| bash -n / py_compile / node --check toàn bộ file mới+sửa | PASS |

Chưa test được local: render wizard/modal trên trình duyệt thật (cần màn hình), apt install các profile dev/media/drivers (cần mạng + băng thông), Gemini thực tế.

## 2026-08-25 (3) — Web cho mọi thiết bị, hình nền, tắt máy, persistence

### Bug nghiêm trọng đã sửa

1. **Zombie VNC connections chặn đa thiết bị (root cause "2 thiết bị không dùng được cùng lúc")**
   - Khi client WebSocket chết đột ngột (TV sleep, mất mạng, đóng tab cứng), task đọc từ VNC trong bridge **treo vô hạn** vì VNC im lặng khi idle → kết nối không bao giờ được dọn. TigerVNC xử lý handshake gần như tuần tự → 1 zombie chặn TẤT CẢ thiết bị kết nối sau đó.
   - Fix: teardown `FIRST_COMPLETED` (một bên chết → cancel bên kia ngay) + idle timeout 30s (`VNC_IDLE_TIMEOUT`) + WS heartbeat 15s. Test: auth OK → giết kết nối đột ngột → thiết bị kế tiếp auth OK **0.0s**; 3 thiết bị song song đều pass; không còn ESTABLISHED leak.

### Thêm mới

2. **Web UI chạy trên mọi thiết bị kể cả Tivi LG**
   - Toàn bộ JS viết lại chuẩn ES5: bỏ async/await / arrow functions / NodeList.forEach (các construct khiến trình duyệt WebKit cũ **fail parse toàn bộ script** → trang trắng).
   - Fallback XHR khi không có fetch; fallback polling khi không có EventSource (SSE).
   - Auto-recovery: kẹt reconnecting/failed >30s → tự reload iframe một lần; `visibilitychange` → kiểm tra + reconnect khi tab thức dậy (mobile/TV suspend hay giết socket ngầm).

3. **Hình nền** (`/api/wallpaper/*`)
   - 6 gradient preset ("sinh động"): midnight, aurora, sunset, ocean, neon, forest — pre-built trong image, áp dụng tức thì.
   - Upload ảnh riêng (PNG/JPG/WebP/GIF, tối đa 8MB, validate magic bytes — file giả mạo bị chặn).
   - Áp dụng đúng theo DE: xfconf-query (XFCE) hoặc pcmanfm-qt config + restart desktop layer (LXQt). Marker `.wallpapers/CURRENT` ghi vết.

4. **Tắt máy / Restart Desktop** (`/api/system/{action}`, yêu cầu `?confirm=really`)
   - Reboot: backup dữ liệu → `supervisorctl shutdown` → container exit sạch (exit 0) → Railway policy ALWAYS tự boot lại (~30s). Đã test vòng đời đầy đủ: shutdown sạch → start lại → healthy → dữ liệu nguyên vẹn.
   - Restart-desktop: chỉ khởi động lại session desktop.

5. **Persistence hoàn chỉnh (write_once)**
   - 18 file cấu hình trong `/home/user` (theme, panel, wallpaper, gtk, openbox, lxqt, code-server...) chỉ ghi khi CHƯA tồn tại → tùy biến của người dùng (hình nền, giao diện...) sống qua mọi lần restart/reboot/redeploy có volume.
   - Đã test: marker file + wallpaper custom + config đều nguyên vẹn qua docker restart.

### Ghi chú test

| Test | Kết quả |
|------|---------|
| Auth RFB qua WS sau reboot | PASS |
| Thiết bị 2 auth ngay khi thiết bị 1 chết đột ngột | PASS (0.0s) |
| 3 thiết bị auth song song | PASS |
| Không sót kết nối ESTABLISHED sau các phiên | PASS |
| Upload ảnh hợp lệ / chặn file giả mạo | PASS |
| Preset neon apply → config + CURRENT marker | PASS |
| Reboot: backup → exit 0 → start lại healthy + data nguyên | PASS |

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
