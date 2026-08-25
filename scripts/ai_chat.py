#!/usr/bin/env python3
"""AI backend helper shared by the web UI (/api/ai/*) and the `ai` CLI.

Config resolution order (first non-empty wins):
  1. Environment: AI_API_LINK, AI_API_KEY, AI_MODEL, AI_NAME, AI_PROVIDER,
     AI_TEMPERATURE, AI_MAX_TOKENS, AI_SYSTEM_PROMPT
  2. Config file: /home/user/.ai-cli/config.json (written by start.sh from
     the same Railway variables)

Providers:
  - openai (default): any OpenAI-compatible /chat/completions endpoint
    (OpenAI, Groq, OpenRouter, Ollama, vLLM, one-api...)
  - gemini: Google Generative Language API (auto-detected by URL)
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

CONFIG_PATH = "/home/user/.ai-cli/config.json"

DEFAULT_SYSTEM_PROMPT = (
    "Ban la AI CLI chay ngay tren he dieu hanh Linux Desktop "
    "(Debian bookworm, container Railway, user 'user', sudo khong can mat khau). "
    "Nguoi dung se yeu cau viec; hay tra loi NGAN gon bang tieng Viet. "
    "Neu viec can chay lenh shell, dua tung lenh ben duoi trong code block ```bash ... ``` "
    "Moi lenh phai: don gian, an toan, khong tuong tac stdin, khong can xac nhan, "
    "co the dung chuoi && hoac for/awk neu hop ly. KHONG BAO GIO de xuat lenh pha hoai "
    "(xoa he thong, mkfs, dd ghi /dev/*, shutdown, rm -rf /...). "
    "Neu cau hoi chi la tra loi thong tin thi khong can code block."
)


def load_config():
    cfg = {
        "provider": os.environ.get("AI_PROVIDER", ""),
        "api_link": os.environ.get("AI_API_LINK",
                                   os.environ.get("AI_API_URL", "")),
        "api_key": os.environ.get("AI_API_KEY", ""),
        "model": os.environ.get("AI_MODEL", ""),
        "name": os.environ.get("AI_NAME", ""),
        "temperature": os.environ.get("AI_TEMPERATURE", ""),
        "max_tokens": os.environ.get("AI_MAX_TOKENS", ""),
        "system_prompt": os.environ.get("AI_SYSTEM_PROMPT", ""),
    }
    try:
        with open(CONFIG_PATH) as f:
            fc = json.load(f)
        for k in ("provider", "api_link", "api_key", "model", "name",
                  "temperature", "max_tokens", "system_prompt"):
            if not cfg.get(k) and fc.get(k):
                cfg[k] = fc[k]
    except Exception:
        pass
    if not cfg["name"]:
        cfg["name"] = "AI Assistant"
    return cfg


def enabled(cfg=None):
    cfg = cfg or load_config()
    return bool(cfg.get("api_link") and cfg.get("api_key") and
                cfg.get("model"))


def _http_json(url, payload, headers, timeout):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers,
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise RuntimeError("HTTP %s: %s" % (e.code, body)) from None
    except urllib.error.URLError as e:
        raise RuntimeError("Khong ket noi duoc API (%s)" % e.reason) from None


def _chat_openai(cfg, prompt, timeout):
    link = cfg["api_link"].rstrip("/")
    if not link.endswith("/chat/completions"):
        if re.search(r"/v\d+$", link) or link.endswith("/openai"):
            link += "/chat/completions"
        else:
            link += "/v1/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": cfg.get("system_prompt") or
             DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        payload["temperature"] = float(cfg.get("temperature") or 0.2)
    except (TypeError, ValueError):
        payload["temperature"] = 0.2
    try:
        payload["max_tokens"] = int(cfg.get("max_tokens") or 2048)
    except (TypeError, ValueError):
        payload["max_tokens"] = 2048
    data = _http_json(link, payload, {
        "Content-Type": "application/json",
        "Authorization": "Bearer %s" % cfg["api_key"],
    }, timeout)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Phan hoi API khong dung dinh dang OpenAI") from None
    return content or ""


def _chat_gemini(cfg, prompt, timeout):
    link = cfg["api_link"].rstrip("/")
    if "generativelanguage" not in link:
        link = ("https://generativelanguage.googleapis.com/v1beta/models/"
                "%s:generateContent" % cfg["model"])
    sys_text = cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
    payload = {
        "contents": [{"parts": [{"text": sys_text +
                                 "\n\n---\nYeu cau nguoi dung: " + prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
    }
    sep = "&" if "?" in link else "?"
    data = _http_json(link + sep + "key=" + cfg["api_key"], payload,
                      {"Content-Type": "application/json"}, timeout)
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Phan hoi API khong dung dinh dang Gemini") from None


def chat(cfg, prompt, timeout=90):
    provider = (cfg.get("provider") or "").lower()
    if provider == "gemini" or \
            "generativelanguage" in cfg.get("api_link", ""):
        return _chat_gemini(cfg, prompt, timeout)
    return _chat_openai(cfg, prompt, timeout)


_FENCE_RX = re.compile(r"```(?:bash|sh|shell|console|posix)?[ \t]*\r?\n"
                       r"(.*?)```", re.S)


def extract_commands(text):
    """Pull runnable shell lines out of an AI reply.

    Returns list of cleaned command strings (fenced blocks first, then bare
    '$ cmd' style lines if no fences were present).
    """
    cmds = []
    seen = set()

    def add(line):
        line = line.strip()
        while line.startswith("$ ") or line.startswith("> "):
            line = line[2:].strip()
        if not line or line.startswith("#"):
            return
        if line not in seen:
            seen.add(line)
            cmds.append(line)

    for m in _FENCE_RX.finditer(text or ""):
        for line in m.group(1).splitlines():
            s = line.strip()
            while s.startswith("$ ") or s.startswith("> "):
                s = s[2:].strip()
            add(s)

    if not cmds:
        for line in (text or "").splitlines():
            s = line.strip()
            if s.startswith("$ ") and len(s) > 2:
                add(s[2:])
    return cmds


def main():
    args = [a for a in sys.argv[1:]]
    run_mode = False
    if "--run" in args:
        run_mode = True
        args.remove("--run")
    prompt = " ".join(args).strip() or sys.stdin.read().strip()
    if not prompt:
        print('usage: ai "<cau hoi / viec can lam>"   |   ai --run "<viec>"')
        return 2

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from ai_safety import classify_command
    except Exception:
        def classify_command(_):
            return True, ""

    cfg = load_config()
    if not enabled(cfg):
        print("[ai] Chua cau hinh AI.")
        print("     Dat cac bien tren Railway: AI_API_LINK, AI_API_KEY,"
              " AI_MODEL")
        print("     (hoặc ghi %s)" % CONFIG_PATH)
        return 1

    print("[ai] Dang hoi %s (%s)..." % (cfg["name"], cfg["model"]))
    try:
        reply = chat(cfg, prompt)
    except RuntimeError as e:
        print("[ai] Loi: %s" % e)
        return 1

    print("\n%s\n" % reply)
    cmds = extract_commands(reply)
    if not cmds:
        return 0

    if not run_mode:
        print("--- lenh de xuat ---")
        for c in cmds:
            ok, why = classify_command(c)
            mark = "$ " if ok else "x BI CHAN (%s): " % why
            print("  %s%s" % (mark, c))
        print("chay that: ai --run \"<yeu cau>\"")
        return 0

    rc_all = 0
    import subprocess
    for c in cmds:
        ok, why = classify_command(c)
        if not ok:
            print("\n[BI CHAN] %s\n  $ %s" % (why, c))
            rc_all = 126
            continue
        print("\n$ %s" % c)
        try:
            r = subprocess.run(["bash", "-lc", c])
            if r.returncode != 0:
                rc_all = r.returncode
        except KeyboardInterrupt:
            break
    return rc_all


if __name__ == "__main__":
    sys.exit(main())
