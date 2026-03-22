from playwright.sync_api import sync_playwright
try:
    from playwright_stealth import stealth_sync
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False
from colorama import Fore, Style
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread, Lock
from config import HEADLESS, DEBUG, MAX_THREADS
import json
import time
import os
import re
import sys
import socket
import queue

# ========================= KONFIGURASI =========================
PORT = 5000        # Satu port saja, pakai path /t1, /t2, dst
MAX_RETRY = 5
OTP_TIMEOUT = 120  # detik menunggu OTP

# ================================================================

info = f"{Fore.CYAN}[INFO]{Style.RESET_ALL}"
success = f"{Fore.GREEN}[OK]{Style.RESET_ALL}"
failed = f"{Fore.RED}[FAIL]{Style.RESET_ALL}"
warning = f"{Fore.YELLOW}[WARN]{Style.RESET_ALL}"

# Dictionary untuk menyimpan OTP berdasarkan thread_id
# Format: { thread_id (int): { "timestamp": "...", "otp": "..." } }
otp_storage = {}
otp_lock = Lock()
print_lock = Lock()

# Webhook URL publik (diisi saat ngrok start)
public_url = ""

# Detect OS
IS_LINUX = sys.platform.startswith('linux')

# ========================= DASHBOARD =========================
# Status per thread: { thread_id: "status message" }
thread_status = {}
num_dashboard_threads = 0
dashboard_initialized = False

def init_dashboard(num_threads):
    """Inisialisasi dashboard dengan jumlah thread."""
    global num_dashboard_threads, dashboard_initialized
    num_dashboard_threads = num_threads
    dashboard_initialized = True

    if DEBUG:
        # Mode debug: skip dashboard, pakai plain log
        with print_lock:
            print(f"\n[DEBUG MODE] Dashboard disabled, plain log aktif.")
            print(f"[DEBUG MODE] Threads: {num_threads}")
            sys.stdout.flush()
        return

    with print_lock:
        # Print header + baris kosong per thread
        print(f"\n{'='*60}")
        print(f"  THREAD STATUS DASHBOARD")
        print(f"{'='*60}")
        for i in range(1, num_threads + 1):
            thread_status[i] = "Menunggu..."
            print(f"  T{i}: Menunggu...")
        print(f"{'='*60}")
        sys.stdout.flush()

def update_status(thread_id, msg):
    """Update status satu thread. DEBUG=True: plain log, DEBUG=False: dashboard."""
    if DEBUG:
        # Mode debug: plain print, semua log jelas
        with print_lock:
            print(f"  T{thread_id}: {msg}")
            sys.stdout.flush()
        return

    if not dashboard_initialized:
        with print_lock:
            print(f"  T{thread_id}: {msg}")
            sys.stdout.flush()
        return
    
    # Bersihkan ANSI color codes untuk panjang display
    thread_status[thread_id] = msg
    
    with print_lock:
        # Hitung berapa baris naik: footer(1) + sisa thread di bawah
        lines_up = (num_dashboard_threads - thread_id) + 1  # +1 untuk footer ===
        
        # Move cursor up, clear line, print, move back down
        sys.stdout.write(f"\033[{lines_up}A")  # naik
        sys.stdout.write(f"\033[2K")  # clear line
        # Truncate pesan jika terlalu panjang
        display_msg = msg[:56]
        sys.stdout.write(f"  T{thread_id}: {display_msg}\n")
        # Turun kembali ke posisi semula
        if lines_up > 1:
            sys.stdout.write(f"\033[{lines_up - 1}B")
        sys.stdout.flush()

def safe_print(msg):
    """Legacy safe_print - tetap ada untuk backward compatibility."""
    with print_lock:
        print(msg)
        sys.stdout.flush()

# ========================= OTP UTILS =========================

def extract_otp(text: str) -> str:
    patterns = [
        r'(\d{6})\s+adalah\s+kode',
        r'kode\s*(?:verifikasi|otp|pemulihan|sandi)\s*[:.]?\s*(\d{4,6})',
        r'(\d{6})',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        global otp_storage
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8", errors="replace")
        try:
            data = json.loads(body)
        except Exception:
            data = {"raw": body}

        # Tentukan thread_id dari path: /t1, /t2, dst
        path = self.path.strip("/")
        thread_id = 0
        m = re.match(r't(\d+)', path)
        if m:
            thread_id = int(m.group(1))

        title = data.get("title", "") or ""
        text = data.get("text", "") or ""
        big_text = data.get("big_text", "") or ""
        package = data.get("package_name", "") or data.get("package", "") or ""
        app_name = data.get("app_name", "") or ""
        rule_name = data.get("rule_name", "") or ""

        full_text = big_text if big_text else text
        combined = f"{title} {text} {big_text} {app_name}".lower()
        is_gopay = any(kw in combined for kw in ["gopay", "gojek", "go-pay", "kode verifikasi", "kode pemulihan"])

        if is_gopay:
            otp = extract_otp(full_text) or extract_otp(title)

            otp_data = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "title": title,
                "text": full_text,
                "otp": otp,
                "package": package,
                "app_name": app_name,
                "thread_id": thread_id,
            }

            with otp_lock:
                otp_storage[thread_id] = otp_data

            try:
                filename = f"gopay_otp_t{thread_id}.json"
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump([otp_data], f, indent=2, ensure_ascii=False)
            except Exception:
                pass

            #safe_print(info + f"[Thread-{thread_id}] OTP diterima: {otp} | dari {app_name}")
        else:
            safe_print(info + f"[Thread-{thread_id}] no otp")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())

    def do_GET(self):
        path = self.path.strip("/")
        m = re.match(r't(\d+)', path)
        thread_id = int(m.group(1)) if m else 0
        last_otp = otp_storage.get(thread_id, {})

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "running", "thread": thread_id, "last_otp": last_otp}).encode())

    def log_message(self, *args):
        pass


def wait_for_new_otp(old_timestamp, timeout=OTP_TIMEOUT, thread_id=0):
    """Tunggu OTP baru yang timestamp-nya berbeda dari old_timestamp untuk thread tertentu."""
    global otp_storage
    start = time.time()
    filename = f"gopay_otp_t{thread_id}.json"

    while time.time() - start < timeout:
        with otp_lock:
            data_mem = otp_storage.get(thread_id, {})

        current_ts = data_mem.get("timestamp", "")
        if current_ts and current_ts != old_timestamp and data_mem.get("otp"):
            return data_mem["otp"]

        try:
            if os.path.exists(filename):
                with open(filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and data:
                        entry = data[-1]
                        ts = entry.get("timestamp", "")
                        if ts and ts != old_timestamp and entry.get("otp"):
                            with otp_lock:
                                otp_storage[thread_id] = entry
                            return entry["otp"]
        except Exception:
            pass

        time.sleep(2)

    return None


def start_ngrok(port):
    """Start ngrok tunnel dan return public URL"""
    try:
        from pyngrok import ngrok
        tunnel = ngrok.connect(port, "http")
        return tunnel.public_url
    except ImportError:
        safe_print(failed + "pyngrok belum terinstall. Jalankan: pip install pyngrok")
        return None
    except Exception as e:
        safe_print(failed + f"Ngrok error: {e}")
        safe_print(warning + "Pastikan authtoken sudah di-set: ngrok config add-authtoken YOUR_TOKEN")
        return None


# ========================= PROCESS ACCOUNT =========================

def process_account(email, password, phone, pin, thread_id=0, webhook_url=""):
    global otp_storage
    update_status(thread_id, f"{info} Login {email}")

    try:
        with open("button.json", "r", encoding="utf-8") as f:
            button_labels = json.load(f)
    except FileNotFoundError:
        button_labels = {}

    playwright = None
    browser = None
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            headless=HEADLESS,
            args=[
                '--disable-web-security',
                '--disable-features=site-per-process',
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-software-rasterizer',
                '--disable-extensions',
                '--disable-background-networking',
                '--disable-default-apps',
                '--disable-sync',
                '--disable-translate',
                '--metrics-recording-only',
                '--no-first-run',
                '--incognito',
                '--lang=id-ID',
                '--blink-settings=imagesEnabled=false',
            ]
        )
        context = browser.new_context(
            locale='id-ID',
            viewport={'width': 1280, 'height': 720},
            extra_http_headers={'Accept-Language': 'id-ID'},
            bypass_csp=True,
        )
        page = context.new_page()
        if HAS_STEALTH:
            stealth_sync(page)

        try:
            update_status(thread_id, f"{info} Buka Google Play...")
            page.set_extra_http_headers({"Accept-Language": "id-ID"})
            page.goto("https://play.google.com/store/paymentmethods?hl=id", timeout=300000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)

            # Input email - pakai selector dari code lama yang working
            update_status(thread_id, f"{info} Input email...")
            try:
                page.get_by_label(re.compile(r"Email atau nomor telepon|Email or phone", re.IGNORECASE)).fill(email)
            except:
                page.wait_for_selector('input[type="email"]', timeout=30000)
                page.locator('input[type="email"]').fill(email)

            update_status(thread_id, f"{info} Email diisi, klik Berikutnya...")
            try:
                page.get_by_role("button", name=re.compile(r"Berikutnya|Next", re.IGNORECASE)).click(timeout=4000)
            except:
                page.keyboard.press("Enter")
            time.sleep(3)

            # Input password - pakai selector dari code lama
            update_status(thread_id, f"{info} Input password...")
            page.wait_for_selector('input[type="password"]', timeout=10000)
            try:
                page.get_by_label(re.compile(r"Masukkan sandi|Enter your password", re.IGNORECASE)).fill(password)
            except:
                page.locator('input[type="password"]').fill(password)
            
            update_status(thread_id, f"{info} Password diisi, klik Berikutnya...")
            try:
                page.get_by_role("button", name=re.compile(r"Berikutnya|Next", re.IGNORECASE)).click(timeout=4000)
            except:
                page.keyboard.press("Enter")
            time.sleep(3)

            # "Saya mengerti" / "I understand" - halaman workspace terms of service
            time.sleep(2)
            try:
                page.get_by_role("button", name=re.compile(r"Saya mengerti|I understand", re.IGNORECASE)).click(timeout=8000)
                update_status(thread_id, f"{success} Klik 'Saya mengerti'")
            except:
                try:
                    page.locator('button:has-text("Saya mengerti"), button:has-text("I understand"), input[value="Saya mengerti"], input[value="I understand"]').first.click(timeout=5000)
                    update_status(thread_id, f"{success} Klik confirm via CSS")
                except:
                    update_status(thread_id, f"{warning} Tombol confirm tidak ada, lanjut...")

            # Halaman passkey "Login lebih cepat" → klik "Lain kali" / "Not now"
            try:
                page.wait_for_url("**/passkeyenrollment**", timeout=8000)
                time.sleep(2)
                page.get_by_text(re.compile(r"Lain kali|Not now|Skip", re.IGNORECASE)).click(timeout=5000)
            except:
                pass

            # Tunggu sampai di halaman paymentmethods
            try:
                page.wait_for_url("https://play.google.com/store/paymentmethods?hl=id", timeout=15000)
            except:
                pass
            
            page.wait_for_load_state("domcontentloaded", timeout=60000)
            time.sleep(3)

            # Klik Tambahkan GoPay / Add GoPay - bilingual
            update_status(thread_id, f"{info} Klik Tambahkan GoPay...")
            try:
                page.get_by_role("button", name=re.compile(r"Tambahkan GoPay|Add GoPay", re.IGNORECASE)).click(timeout=10000)
                update_status(thread_id, f"{success} Klik GoPay via role button")
            except:
                # Fallback JS click - bilingual
                try:
                    result = page.evaluate('''() => {
                        const labels = ['Tambahkan GoPay', 'Add GoPay'];
                        const elements = document.querySelectorAll('*');
                        for (const label of labels) {
                            for (const el of elements) {
                                if (el.textContent.trim() === label && el.offsetParent !== null) {
                                    el.click();
                                    return 'clicked: ' + el.tagName + '.' + el.className;
                                }
                            }
                        }
                        for (const el of elements) {
                            if (el.childElementCount === 0 && el.textContent.trim().includes('GoPay') && el.offsetParent !== null) {
                                el.click();
                                return 'partial: ' + el.tagName + '.' + el.className;
                            }
                        }
                        return 'not_found';
                    }''')
                    if 'not_found' not in result:
                        update_status(thread_id, f"{success} Klik GoPay via JS: {result[:50]}")
                    else:
                        page.screenshot(path=f"debug_gopay_btn_t{thread_id}.png")
                        raise Exception("Tombol GoPay tidak ditemukan")
                except Exception as e:
                    if "tidak ditemukan" in str(e):
                        raise
                    page.screenshot(path=f"debug_gopay_btn_t{thread_id}.png")
                    raise Exception(f"Tombol GoPay gagal diklik: {e}")

            # Tunggu iframe hnyNZeIframe muncul - pakai selector dari code lama
            update_status(thread_id, f"{info} Tunggu iframe payment...")
            time.sleep(3)
            
            # Tunggu iframe muncul dengan retry
            iframe_found = False
            for attempt in range(10):  # max 20 detik
                try:
                    iframe_loc = page.locator('iframe[name="hnyNZeIframe"]')
                    if iframe_loc.count() > 0:
                        iframe_found = True
                        break
                except:
                    pass
                time.sleep(2)
                if attempt % 2 == 1:
                    update_status(thread_id, f"{info} Tunggu iframe... ({(attempt+1)*2}s)")
            
            if not iframe_found:
                # Debug screenshot
                page.screenshot(path=f"debug_lanjutkan_t{thread_id}.png")
                for idx, frame in enumerate(page.frames):
                    update_status(thread_id, f"{info} Frame[{idx}]: {frame.url[:60]}")
                raise Exception("iframe hnyNZeIframe tidak muncul")
            
            # Klik Lanjutkan / Continue di iframe - bilingual
            update_status(thread_id, f"{info} Klik Lanjutkan di iframe...")
            with page.expect_popup() as page1_info:
                iframe_frame = page.locator('iframe[name="hnyNZeIframe"]').content_frame
                iframe_frame.get_by_role("button", name=re.compile(r"Lanjutkan|Continue|Proceed", re.IGNORECASE)).click(timeout=10000)
            update_status(thread_id, f"{success} Klik Lanjutkan/Continue berhasil")
            time.sleep(5)
            page1 = page1_info.value
            page1.wait_for_load_state("load", timeout=30000)
            try:
                page1.wait_for_url("**/app/authorize**", timeout=30000)
            except:
                pass
            page1.wait_for_load_state("load", timeout=30000)

            update_status(thread_id, f"{info} Cari form GoPay...")
            gopay_frame = None

            for idx, frame in enumerate(page1.frames):
                try:
                    loc = frame.locator('#phone-number-input')
                    if loc.count() > 0:
                        gopay_frame = frame
                        break
                except:
                    continue

            if gopay_frame is None:
                update_status(thread_id, f"{failed} Form GoPay tidak ditemukan!")
                return False

            # Step 1: Input nomor HP
            update_status(thread_id, f"{info} Input HP {phone}...")
            phone_el = gopay_frame.locator('#phone-number-input')
            phone_el.click(timeout=5000)
            phone_el.fill("")  # clear dulu
            phone_el.press_sequentially(phone, delay=50)
            time.sleep(1)
            
            gopay_frame.locator('button#submit[value="phone-number"]:not([disabled])').click(timeout=10000)

            # Step 2: Tunggu dan input OTP
            with otp_lock:
                old_otp_data = otp_storage.get(thread_id, {})
            old_otp_ts = old_otp_data.get("timestamp", "")
            
            update_status(thread_id, f"{info} Menunggu OTP...")
            time.sleep(5)
            
            otp_code = wait_for_new_otp(old_otp_ts, thread_id=thread_id)

            if otp_code:
                update_status(thread_id, f"{success} OTP: {otp_code} - Input...")
                otp_input = gopay_frame.locator('#firstInput')
                otp_input.wait_for(state="visible", timeout=10000)
                otp_input.click()
                otp_input.press_sequentially(otp_code, delay=50)
            else:
                update_status(thread_id, f"{failed} OTP timeout!")
                return False

            time.sleep(1)
            gopay_frame.locator('button[value="validate-otp"]').click(timeout=10000)
            time.sleep(2)

            # Step 3: Input PIN
            update_status(thread_id, f"{info} Input PIN...")
            pin_input = gopay_frame.locator('input[type="password"].pin')
            pin_input.wait_for(state="visible", timeout=10000)
            pin_input.click()
            pin_input.press_sequentially(pin, delay=50)
            time.sleep(1)
            gopay_frame.locator('button[value="validate-pin"]').click(timeout=10000)
            time.sleep(1)

            frame = page.frame(name="hnyNZeIframe")
            if frame:
                try:
                    name_field = frame.get_by_label(re.compile(r"Nama|Name", re.IGNORECASE))
                    name_field.click(timeout=5000)
                    name_field.press("Enter")
                except:
                    pass

                time.sleep(3)
                page.get_by_role("link", name=re.compile(r"Edit metode pembayaran|Edit payment method", re.IGNORECASE)).click()
                time.sleep(1)
                update_status(thread_id, f"{success} GoPay linked: {email}")
            else:
                update_status(thread_id, f"{info} Manual mode - {email}")
                input(f"[Thread-{thread_id}] Tekan ENTER jika sudah selesai manual...")

            with open("gsuitexGoPay.txt", "a") as f:
                f.write(f"{email}|{password}\n")

            return True

        except Exception as e:
            update_status(thread_id, f"{failed} Error: {str(e)[:40]}")
            return False

    except Exception as e:
        safe_print(failed + f"[Thread-{thread_id}] Error membuat browser: {e}")
        return False
    finally:
        try:
            if browser:
                browser.close()
        except:
            pass
        try:
            if playwright:
                playwright.stop()
        except:
            pass


def worker(thread_id, gopay_phone, gopay_pin, gsuite_queue, counters, webhook_url):
    """
    Worker function for each thread.
    Sekarang TIDAK perlu start server sendiri, semua pakai 1 server + path routing.
    """
    while True:
        try:
            gsuite_data = gsuite_queue.get(timeout=1)
        except queue.Empty:
            update_status(thread_id, f"{success} Selesai - idle")
            break
        
        email, password = gsuite_data

        berhasil_akun = False
        for attempt in range(1, MAX_RETRY + 1):
            update_status(thread_id, f"{info} {email} (percobaan {attempt}/{MAX_RETRY})")
            
            result = process_account(
                email=email,
                password=password,
                phone=gopay_phone,
                pin=gopay_pin,
                thread_id=thread_id,
                webhook_url=webhook_url
            )
            
            if result:
                with counters['lock']:
                    counters['berhasil'] += 1
                berhasil_akun = True
                break
            else:
                update_status(thread_id, f"{warning} Gagal #{attempt}, retry 5s...")
                time.sleep(5)
        
        if not berhasil_akun:
            with counters['lock']:
                counters['gagal'] += 1
                counters['gagal_akun'].append(f"{email} | {gopay_phone}")
            update_status(thread_id, f"{failed} {email} gagal {MAX_RETRY}x")

        gsuite_queue.task_done()


# ========================= MAIN =========================

def main():
    global public_url

    print(f"\n{'='*55}")
    print("  GSUITE x GOPAY - AUTO LINK (NGROK + PATH ROUTING)")
    print(f"{'='*55}")
    print(f"  Browser: Chromium (Playwright) | Headless: {HEADLESS}")

    # Validasi file gsuite.txt
    if not os.path.exists("gsuite.txt"):
        print(failed + "File gsuite.txt tidak ditemukan!")
        print(info + "Buat file gsuite.txt dengan format: email|password (satu per baris)")
        sys.exit(1)

    # Validasi file gopay.txt
    if not os.path.exists("gopay.txt"):
        print(failed + "File gopay.txt tidak ditemukan!")
        print(info + "Buat file gopay.txt dengan format: nomor|pin (satu per baris)")
        sys.exit(1)

    # Load akun GSuite
    with open("gsuite.txt", "r", encoding="utf-8") as f:
        gsuite_lines = [line.strip() for line in f if line.strip() and "|" in line]

    # Load akun GoPay
    with open("gopay.txt", "r", encoding="utf-8") as f:
        gopay_lines = [line.strip() for line in f if line.strip() and "|" in line]

    if not gsuite_lines:
        print(failed + "gsuite.txt kosong atau format salah! Format: email|password")
        sys.exit(1)

    if not gopay_lines:
        print(failed + "gopay.txt kosong atau format salah! Format: nomor|pin")
        sys.exit(1)

    num_threads = min(len(gopay_lines), MAX_THREADS)
    
    print(info + f"GSuite Accounts : {len(gsuite_lines)}")
    print(info + f"GoPay Accounts  : {len(gopay_lines)}")
    print(info + f"Threads         : {num_threads}")

    # Start HTTP server (1 server saja)
    server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    print(success + f"OTP Listener aktif di port {PORT}")

    # Start ngrok tunnel
    print(info + "Starting ngrok tunnel...")
    public_url = start_ngrok(PORT)
    
    ip = get_local_ip()

    print(f"\n{'='*55}")
    if public_url:
        print(f"  📡 NGROK AKTIF!")
        print(f"  🌐 Public URL: {public_url}")
    else:
        print(f"  ⚠️  Ngrok gagal, pakai local IP")
        print(f"  🏠 Local URL: http://{ip}:{PORT}")
    print(f"{'─'*55}")
    print(f"  📱 Set Webhook URL di APK Notif Forwarder (per HP):")
    for i in range(num_threads):
        base = public_url if public_url else f"http://{ip}:{PORT}"
        phone = gopay_lines[i].split("|")[0].strip()
        print(f"     HP {i+1} (GoPay {phone}): {base}/t{i+1}")
    print(f"{'='*55}\n")

    input("  Tekan ENTER untuk mulai proses...\n")

    # Setup Queue
    gsuite_queue = queue.Queue()
    for line in gsuite_lines:
        email, password = line.split("|", 1)
        gsuite_queue.put((email.strip(), password.strip()))

    # Shared counters
    counters = {
        'berhasil': 0,
        'gagal': 0,
        'gagal_akun': [],
        'lock': Lock()
    }

    workers = []
    
    # Create threads
    for i in range(num_threads):
        gopay_line = gopay_lines[i]
        phone, pin = gopay_line.split("|", 1)
        
        base = public_url if public_url else f"http://{ip}:{PORT}"
        webhook_url = f"{base}/t{i+1}"
        
        t = Thread(target=worker, args=(i+1, phone.strip(), pin.strip(), gsuite_queue, counters, webhook_url))
        t.start()
        workers.append(t)
        safe_print(info + f"Started Thread-{i+1} with GoPay: {phone.strip()}")

    # Wait for all threads to complete
    try:
        while any(t.is_alive() for t in workers):
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n{failed} FORCE SHUTDOWN DETECTED! Exiting immediately...")
        try:
            from pyngrok import ngrok
            ngrok.kill()
        except:
            pass
        os._exit(1)

    # Summary
    print(f"\n{'='*55}")
    print(f"  SUMMARY")
    print(f"{'='*55}")
    print(f"  Total   : {len(gsuite_lines)}")
    print(f"  Berhasil: {counters['berhasil']}")
    print(f"  Gagal   : {counters['gagal']}")

    if counters['gagal_akun']:
        print(f"\n  Akun yang gagal:")
        for akun in counters['gagal_akun']:
            print(f"    ❌ {akun}")

        with open("gagal.txt", "w", encoding="utf-8") as f:
            for akun in counters['gagal_akun']:
                f.write(akun + "\n")
        print(info + "Akun gagal disimpan ke gagal.txt")

    print(f"{'='*55}\n")

    # Cleanup ngrok
    try:
        from pyngrok import ngrok
        ngrok.kill()
    except:
        pass
    try:
        server.shutdown()
    except:
        pass


if __name__ == "__main__":
    main()