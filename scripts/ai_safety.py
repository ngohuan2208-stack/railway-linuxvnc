#!/usr/bin/env python3
"""Safety filter for AI-generated / user-triggered shell commands.

classify_command(cmd) -> (ok: bool, reason: str)
 - ok=True  : command is allowed to run
 - ok=False : command matches a destructive pattern, reason explains why

This is a deterministic guardrail (NOT a sandbox). It blocks classic
system-destroying commands while letting normal work (apt install, git,
python, file ops inside /home/user...) pass through untouched.

Protected infrastructure:
  supervisord, Xvnc, dbus, http-server, watchdog, idle-monitor,
  /start.sh, /etc/supervisor, core scripts in /usr/local/bin, web UI.
"""
import re

ROOT_TARGETS = {
    "/", "/*", "/etc", "/usr", "/var", "/boot", "/bin", "/sbin",
    "/lib", "/lib32", "/lib64", "/opt", "/srv", "/run",
    "/dev", "/proc", "/sys", "/home",
    "~", "~/", "~/*", "$HOME", "$HOME/", "$HOME/*",
    "/home/user", "/home/user/",
}

_RECURSIVE_VERBS = ("rm", "chmod", "chown", "shred")

_DISK_TOOLS = {
    "mkfs", "mke2fs", "mkfs.ext2", "mkfs.ext3", "mkfs.ext4", "mkfs.vfat",
    "mkfs.ntfs", "mkfs.xfs", "mkfs.btrfs", "mkswap",
    "fdisk", "sfdisk", "cfdisk", "gdisk", "sgdisk", "parted",
    "wipefs", "blkdiscard", "blockdev", "cryptsetup",
}

_CORE_PROCS = ("supervisord", "xvnc", "dbus-daemon", "dbus-launch",
               "http-server", "resource-watchdog", "idle-monitor",
               "run-xvnc", "run-desktop")

_CORE_PATHS = re.compile(
    r"(/start\.sh"
    r"|/etc/supervisor"
    r"|supervisord\.conf"
    r"|/srv/index\.html"
    r"|/usr/local/bin/(http-server|resource-watchdog|idle-monitor"
    r"|run-xvnc|run-desktop|optimize-system|backup-data|restore-data"
    r"|ai-safety|ai-chat)\b)"
)

_WRITE_VERBS = re.compile(
    r"(^|[;&|\s])(>|>>|tee\s|cp\s|mv\s|rm\s|ln\s|sed\s+-i\s|truncate\s"
    r"|dd\s|chmod\s|chown\s|install\s)"
)

_DENY_RES = [
    # fork bomb: :(){ :|:& };: and friends
    (re.compile(r":\s*\(\s*\)\s*\{[^}]*\|[^}]*&[^}]*\}\s*;?"), "fork bomb"),
    # power off / reboot from inside (lifecycle belongs to Railway)
    (re.compile(r"\b(shutdown|poweroff|halt|reboot)\b"),
     "tat/khoi dong lai he thong"),
    (re.compile(r"\binit\s+[06]\b"), "init 0/6"),
    (re.compile(r"\bsystemctl\s+(poweroff|reboot|halt|suspend)\b"),
     "systemctl power management"),
    # raw block device writes
    (re.compile(r"\bdd\b[^;&|]*\bof=/dev/"), "dd ghi thang vao thiet bi /dev/*"),
    (re.compile(r">\s*/dev/(sd|hd|nvme|vd|mmcblk)"), "ghi de thiet bi luu tru"),
    (re.compile(r"\bmv\s+/\*\s+/dev/null\b"), "mv /* /dev/null"),
    # find / -delete or find / -exec rm
    (re.compile(r"\bfind\s+/\s+[^;&|]*(-delete|-exec\s+rm\b)"),
     "find / xoa de quy"),
    # credential / sudo tampering
    (re.compile(r"[;&|\s](>|>>|tee\s+|chmod\s+|chown\s+|sed\s+-i\s)"
                r"[^;\n]*/etc/(shadow|passwd|sudoers)\b"),
     "sua tep xac thuc/sudoers"),
    # removing core desktop/VNC packages
    (re.compile(r"\bapt(-get)?\s+(remove|purge)\b[^;\n]*"
                r"(tigervnc|xvnc|novnc|xfce4-session|lxqt-core|openbox|"
                r"xorg|supervisor|dbus)\b"),
     "go bo component cot loi cua desktop/VNC"),
]


def _segments(cmd):
    return [s for s in re.split(r";|\|\||&&|\|", cmd) if s.strip()]


def _tokens(seg):
    out = []
    for t in re.findall(r'"[^"]*"|\'[^\']*\'|\S+', seg):
        out.append(t.strip("\"'"))
    return out


def _rooted(targets):
    for t in targets:
        if t in ROOT_TARGETS:
            return True
        n = t.rstrip("*").rstrip("/")
        if t.endswith("*") and n in ROOT_TARGETS:
            return True
    return False


def classify_command(cmd):
    """Return (ok, reason). ok=False means the command MUST NOT run."""
    if not cmd or not cmd.strip():
        return False, "lenh rong"
    if len(cmd) > 4000:
        return False, "lenh qua dai"

    for rx, reason in _DENY_RES:
        if rx.search(cmd):
            return False, reason

    for seg in _segments(cmd):
        toks = _tokens(seg)
        for i, t in enumerate(toks):
            base = t.split("/")[-1] if "/" in t else t

            if base in _DISK_TOOLS:
                return False, "cong cu chia/dinh dang dia (%s)" % base

            if base == "supervisorctl":
                rest = toks[i + 1:i + 2]
                if not rest or rest[0] != "status":
                    return False, "supervisorctl chi cho phep 'status'"

            if base in ("kill", "pkill", "killall"):
                joined = " ".join(toks[i + 1:]).lower()
                for p in _CORE_PROCS:
                    if p in joined:
                        return False, "kill tien trinh he thong (%s)" % p

            if base in _RECURSIVE_VERBS:
                flags = []
                j = i + 1
                while j < len(toks) and toks[j].startswith("-"):
                    flags.append(toks[j])
                    j += 1
                targets = toks[j:]
                recursive = any(re.search(r"[rR]", f.lstrip("-"))
                                for f in flags if len(f) > 1)
                if base == "rm" and recursive and _rooted(targets):
                    return False, "rm -rf tren thu muc he thong/home"
                if base in ("chmod", "chown") and "-R" in flags and \
                        _rooted(targets):
                    return False, base + " -R de quy tren thu muc goc/home"
                if base == "shred":
                    return False, "shred xoa khong phuc hoi"

            if base == "dd":
                for x in toks[i + 1:]:
                    if x.startswith("of=/dev/"):
                        return False, "dd ghi vao thiet bi"

        if _CORE_PATHS.search(seg) and _WRITE_VERBS.search(seg):
            return False, "sua/xoa tep he thong cua platform"

    return True, ""


if __name__ == "__main__":
    import sys
    lines = sys.argv[1:] or sys.stdin.readlines()
    for line in lines:
        line = line.rstrip("\n")
        ok, why = classify_command(line)
        tag = "ALLOW" if ok else "DENY "
        suffix = "" if ok else "   <- %s" % why
        print("%s   %s%s" % (tag, line, suffix))
