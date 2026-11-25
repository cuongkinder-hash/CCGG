"""
Cầu nối Thanh Thanh  —  cho app "Sổ Kênh & Mail" nói chuyện bằng GÓI THÁNG Claude
qua Claude Code đã đăng nhập trên máy này (không cần khóa API).

Chạy:  python cau_noi.py        (hoặc bấm đúp Bat-Thanh-Thanh.bat)
Mặc định lắng nghe http://127.0.0.1:8787 — CHỈ máy này truy cập được.

An toàn:
- Chỉ nhận yêu cầu từ trang của bạn (danh sách ALLOWED_ORIGINS bên dưới).
- Claude chạy ở chế độ không có công cụ (--tools "") và --safe-mode: không đọc/ghi file, không chạy lệnh.
- Không lưu phiên hội thoại của Claude Code (--no-session-persistence); cửa sổ chỉ ghi thời gian + độ dài, không ghi nội dung.
"""
import glob, json, os, shutil, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = "127.0.0.1", 8787
ALLOWED_ORIGINS = {
    "https://cuongkinder-hash.github.io",   # trang thật trên GitHub Pages
    "http://127.0.0.1:8080", "http://localhost:8080",  # bản xem thử trên máy
}
# thêm trang khác (cách nhau bởi dấu phẩy) qua biến môi trường BRIDGE_EXTRA_ORIGINS nếu cần
ALLOWED_ORIGINS |= {o.strip().rstrip("/") for o in os.environ.get("BRIDGE_EXTRA_ORIGINS", "").split(",") if o.strip()}
MODEL_ALIAS = {"claude-opus-5-5": "opus", "claude-sonnet-5-5": "sonnet", "claude-haiku-5-5": "haiku"}
TIMEOUT = 240          # giây cho một câu trả lời
MAX_PARALLEL = 2       # tối đa 2 câu xử lý cùng lúc
WORKDIR = os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "ThanhThanhBridge", "work")
os.makedirs(WORKDIR, exist_ok=True)
SLOTS = threading.Semaphore(MAX_PARALLEL)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def find_claude():
    """Tìm claude.exe: biến CLAUDE_EXE → PATH → bản đi kèm tiện ích VS Code/Cursor/Antigravity… (mới nhất)."""
    env = os.environ.get("CLAUDE_EXE")
    if env and os.path.isfile(env):
        return env
    w = shutil.which("claude")
    if w:
        return w
    home = os.path.expanduser("~")
    pats = [os.path.join(home, ".local", "bin", "claude.exe")]
    for ide in (".vscode", ".vscode-insiders", ".cursor", ".windsurf", ".antigravity-ide", ".antigravity"):
        pats.append(os.path.join(home, ide, "extensions", "anthropic.claude-code-*", "resources", "native-binary", "claude.exe"))
    hits = [p for pat in pats for p in glob.glob(pat) if os.path.isfile(p)]
    return max(hits, key=os.path.getmtime) if hits else None


def flatten(messages):
    """Claude Code -p nhận một lời nhắn → gộp lịch sử hội thoại thành văn bản."""
    msgs = [m for m in messages if str(m.get("content", "")).strip()]
    if not msgs:
        return ""
    if len(msgs) == 1:
        return str(msgs[0]["content"])
    hist = []
    for m in msgs[:-1]:
        who = "SẾP" if m.get("role") == "user" else "THANH THANH (bạn, câu trả lời JSON trước đó)"
        hist.append(f"[{who}]:\n{m['content']}")
    return ("LỊCH SỬ HỘI THOẠI HÔM NAY (để hiểu ngữ cảnh, KHÔNG lặp lại thao tác đã làm):\n\n" + "\n\n".join(hist)
            + "\n\n==========\nTIN NHẮN MỚI CỦA SẾP (trả lời tin này):\n" + str(msgs[-1]["content"]))


def run_claude(exe, system, messages, schema, model, effort):
    prompt = flatten(messages)
    if not prompt:
        raise ValueError("Tin nhắn trống")
    fd, sysfile = tempfile.mkstemp(suffix=".txt", dir=WORKDIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(system or "")
        cmd = [exe, "-p", "--output-format", "json", "--tools", "", "--safe-mode",
               "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands",
               "--system-prompt-file", sysfile, "--model", MODEL_ALIAS.get(model, model or "sonnet")]
        if effort in ("low", "medium", "high", "xhigh", "max"):
            cmd += ["--effort", effort]
        if schema:
            cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
        p = subprocess.run(cmd, input=prompt.encode("utf-8"), capture_output=True, timeout=TIMEOUT, cwd=WORKDIR,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        try:
            os.remove(sysfile)
        except OSError:
            pass
    out = p.stdout.decode("utf-8", "replace").strip()
    try:
        j = json.loads(out)
    except Exception:
        err = (p.stderr.decode("utf-8", "replace") or out)[-600:]
        raise RuntimeError("Claude Code lỗi: " + err.strip())
    if j.get("is_error") or j.get("subtype") != "success":
        msg = j.get("result") or j.get("subtype") or "lỗi không rõ"
        raise RuntimeError(f"Claude Code báo lỗi: {msg}")
    if schema:
        data = j.get("structured_output")
        if data is None:  # dự phòng: tự đọc JSON trong result
            data = json.loads(j.get("result", ""))
        return data
    return j.get("result", "")


class Handler(BaseHTTPRequestHandler):
    server_version = "ThanhThanhBridge/1.0"

    def log_message(self, *a):  # tắt log mặc định (có thể lộ đường dẫn)
        pass

    def _origin_ok(self):
        o = self.headers.get("Origin")
        return o is None or o in ALLOWED_ORIGINS

    def _cors(self):
        o = self.headers.get("Origin")
        if o in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", o)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        if not self._origin_ok():
            self.send_response(403); self.end_headers(); return
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        if not self._origin_ok():
            return self._json(403, {"ok": False, "error": "Trang này không được phép dùng cầu nối"})
        if self.path.startswith("/health"):
            return self._json(200, {"ok": bool(EXE), "app": "thanh-thanh-bridge", "version": VERSION, "claude": bool(EXE)})
        self._json(404, {"ok": False})

    def do_POST(self):
        if not self._origin_ok():
            return self._json(403, {"ok": False, "error": "Trang này không được phép dùng cầu nối"})
        if not self.path.startswith("/chat"):
            return self._json(404, {"ok": False})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > 8_000_000:
                return self._json(413, {"ok": False, "error": "Dữ liệu quá lớn"})
            req = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return self._json(400, {"ok": False, "error": "Yêu cầu không hợp lệ"})
        if not EXE:
            return self._json(500, {"ok": False, "error": "Không tìm thấy Claude Code (claude.exe) trên máy"})
        if not SLOTS.acquire(timeout=60):
            return self._json(429, {"ok": False, "error": "Đang bận, thử lại sau ít giây"})
        t = time.time()
        try:
            data = run_claude(EXE, req.get("system", ""), req.get("messages", []), req.get("schema"), req.get("model"), req.get("effort"))
            print(f"[{time.strftime('%H:%M:%S')}] ✓ trả lời sau {time.time()-t:.1f}s (lời nhắn {sum(len(str(m.get('content',''))) for m in req.get('messages',[]))} ký tự)", flush=True)
            self._json(200, {"ok": True, "data": data})
        except subprocess.TimeoutExpired:
            print(f"[{time.strftime('%H:%M:%S')}] ✗ quá thời gian", flush=True)
            self._json(504, {"ok": False, "error": f"Claude Code trả lời quá {TIMEOUT} giây"})
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ✗ {e}", flush=True)
            self._json(502, {"ok": False, "error": str(e)})
        finally:
            SLOTS.release()


EXE = find_claude()
VERSION = ""
if EXE:
    try:
        VERSION = subprocess.run([EXE, "--version"], capture_output=True, timeout=30).stdout.decode("utf-8", "replace").strip()
    except Exception:
        VERSION = "?"

if __name__ == "__main__":
    print("🌸 Cầu nối Thanh Thanh")
    print(f"   Claude Code: {VERSION or 'KHÔNG TÌM THẤY'}")
    if not EXE:
        print("   → Cài Claude Code hoặc đặt biến môi trường CLAUDE_EXE trỏ tới claude.exe")
    print(f"   Đang chạy tại http://{HOST}:{PORT}  — để cửa sổ này mở trong lúc dùng Thanh Thanh. Đóng cửa sổ = tắt.")
    print("   Trang được phép: " + ", ".join(sorted(ALLOWED_ORIGINS)))
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except OSError as e:
        print(f"Không mở được cổng {PORT}: {e}  (có thể cầu nối đang chạy ở cửa sổ khác)")
        input("Nhấn Enter để đóng…")
