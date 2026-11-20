"""
bot.py — GSUITE x GOPAY TELEGRAM BOT (V2 Update)
Fitur Tambahan:
1. Input Manual via Chat / File .txt otomatis disimpan ke gsuite.txt (agar yang gagal tidak hilang).
2. Akun yang gagal Nempel 3x otomatis dicatat ke gagal_nempel.txt & dikirim ke Telegram selesai proses.
3. Ganti Ngrok Authtoken langsung dari menu Telegram Bot (tanpa edit file manual & bebas error duplicate token).
"""

import os
import re
import sys
import time
import queue
import signal
import concurrent.futures
from threading import Thread, Lock, Event
from http.server import HTTPServer

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

import gopay
from gopay import (
    WebhookHandler,
    get_local_ip,
    PORT,
    MAX_THREADS,
    MAX_RETRY,
    process_account,
    info,
    warning,
    failed as failed_label,
    success as success_label,
)
from main import (
    RESULT_FILE,
    append_result,
    cut_from_gsuite,
    format_duration,
    load_gopay_from_file,
    kill_ngrok_existing,
    yt_process_one,
    load_gagal_pay,
    remove_gagal_pay_from_result,
)
import config

# --- PAKSA KONEKSI TELEGRAM KE IPv4 & ABAIKAN PROXY SISTEM (ANTI ERROR 502) ---
import socket
import urllib3.util.connection as urllib3_cn
urllib3_cn.allowed_gai_family = lambda: socket.AF_INET

from telebot import apihelper
apihelper.SESSION_TIME_TO_LIVE = 60
apihelper.proxy = {}
# ------------------------------------------------------------------------------


def parse_gsuite_data(text: str) -> list:
    """
    Smart Parser GSuite:
    Otomatis mendeteksi dan mengubah format:
    - email pw (pisah spasi atau tab)
    - email:pw (pisah titik dua)
    - email;pw (pisah titik koma)
    - email|pw (pisah pipe)
    Menjadi list tuple (email, password) yang siap disimpan sebagai email|pw.
    """
    results = []
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line or "@" not in line:
            continue
        email, password = "", ""
        if "|" in line:
            parts = line.split("|", 1)
            email, password = parts[0].strip(), parts[1].strip()
        elif ":" in line and not line.startswith("http"):
            parts = line.split(":", 1)
            email, password = parts[0].strip(), parts[1].strip()
        elif ";" in line:
            parts = line.split(";", 1)
            email, password = parts[0].strip(), parts[1].strip()
        else:
            # Pisah berdasarkan spasi / tab pertama (format: email pw)
            parts = line.split(None, 1)
            if len(parts) == 2:
                email, password = parts[0].strip(), parts[1].strip()
        if email and "@" in email and password:
            results.append((email, password))
    return results


def load_gsuite_from_file() -> list:
    """
    Baca gsuite.txt. Jika di dalamnya ada format 'email pw', otomatis
    dinormalisasi menjadi 'email|pw' agar kompatibel dengan seluruh modul.
    """
    if not os.path.exists("gsuite.txt"):
        return []
    with open("gsuite.txt", "r", encoding="utf-8") as f:
        raw_content = f.read()
    parsed = parse_gsuite_data(raw_content)
    # Jika ada baris yang belum memakai '|', tulis ulang agar rapi menjadi email|pw
    raw_lines = [l.strip() for l in raw_content.splitlines() if l.strip()]
    needs_rewrite = any("|" not in l for l in raw_lines)
    if parsed and needs_rewrite:
        with open("gsuite.txt", "w", encoding="utf-8") as f:
            for em, pw in parsed:
                f.write(f"{em}|{pw}\n")
    return parsed


def parse_gopay_data(text: str) -> list:
    """Smart Parser GoPay: mendukung format 'nohp pin', 'nohp:pin', atau 'nohp|pin'."""
    results = []
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        phone, pin = "", ""
        if "|" in line:
            parts = line.split("|", 1)
            phone, pin = parts[0].strip(), parts[1].strip()
        elif ":" in line:
            parts = line.split(":", 1)
            phone, pin = parts[0].strip(), parts[1].strip()
        else:
            parts = line.split(None, 1)
            if len(parts) == 2:
                phone, pin = parts[0].strip(), parts[1].strip()
        if phone and pin:
            results.append(f"{phone}|{pin}")
    return results


BOT_TOKEN = getattr(config, "BOT_TOKEN", "").strip()
ADMIN_IDS = getattr(config, "ADMIN_IDS", [])
GAGAL_NEMPEL_FILE = "gagal_nempel.txt"

if not BOT_TOKEN or BOT_TOKEN == "ISI_BOT_TOKEN_TELEGRAM_DISINI":
    print("[ERROR] BOT_TOKEN belum diisi di config.py!")
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# State global untuk server, proses, dan input user
_server_instance = None
_server_lock = Lock()
_ngrok_url = ""

_job_lock = Lock()
_job_running = False
_stop_event = Event()
_gagal_lock = Lock()

_user_states = {}  # chat_id -> dict(step=..., ...)
_live_thread_status = {}
_status_lock = Lock()

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    """Bersihkan kode warna ANSI dari log terminal untuk ditampilkan di Telegram."""
    return ANSI_ESCAPE_RE.sub("", str(text)).strip()


# Hook fungsi update_status milik gopay.py agar terekam di dashboard Telegram
_original_update_status = gopay.update_status


def _hooked_update_status(thread_id, msg):
    clean_msg = strip_ansi(msg)
    with _status_lock:
        _live_thread_status[thread_id] = clean_msg
    try:
        _original_update_status(thread_id, msg)
    except Exception:
        pass


gopay.update_status = _hooked_update_status


def is_authorized(user_id: int) -> bool:
    """Validasi apakah user diizinkan mengakses bot."""
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


def append_gagal_nempel(email: str, password: str, phone: str = ""):
    """Simpan akun GSuite yang gagal nempel 3x ke gagal_nempel.txt."""
    line = f"{email}|{password}" + (f" (GoPay: {phone})" if phone else "")
    with _gagal_lock:
        with open(GAGAL_NEMPEL_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def save_unique_to_gsuite_file(accounts: list) -> int:
    """Tambahkan daftar (email, password) ke gsuite.txt tanpa duplikat."""
    existing = set()
    if os.path.exists("gsuite.txt"):
        with open("gsuite.txt", "r", encoding="utf-8") as f:
            for line in f:
                if "|" in line:
                    existing.add(line.split("|", 1)[0].strip().lower())
    added = 0
    with open("gsuite.txt", "a", encoding="utf-8") as f:
        for em, pw in accounts:
            if em.lower() not in existing:
                f.write(f"{em}|{pw}\n")
                existing.add(em.lower())
                added += 1
    return added


def update_ngrok_token_everywhere(new_token: str):
    """Simpan token Ngrok baru ke config.py dan tulis ulang ngrok.yml agar bebas error duplicate."""
    new_token = new_token.strip()
    config.NGROK_MANUAL_AUTH = new_token
    gopay.NGROK_MANUAL_AUTH = new_token

    # Update config.py
    if os.path.exists("config.py"):
        with open("config.py", "r", encoding="utf-8") as f:
            content = f.read()
        if "NGROK_MANUAL_AUTH" in content:
            content = re.sub(
                r'NGROK_MANUAL_AUTH\s*=\s*["\'].*?["\']',
                f'NGROK_MANUAL_AUTH = "{new_token}"',
                content,
            )
        else:
            content += f'\nNGROK_MANUAL_AUTH = "{new_token}"\n'
        with open("config.py", "w", encoding="utf-8") as f:
            f.write(content)

    # Hapus ngrok.yml lama jika ada agar tidak bentrok "Authtoken already set"
    default_yml = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ngrok", "ngrok.yml"
    )
    for yml_path in [default_yml, config.NGROK_CONFIG_PATH]:
        if yml_path and os.path.exists(yml_path):
            try:
                os.remove(yml_path)
            except Exception:
                pass

    try:
        from pyngrok import ngrok
        ngrok.set_auth_token(new_token)
    except Exception:
        pass


def start_ngrok_safe(port: int):
    """Start ngrok tunnel dengan penanganan SSL & bypass error duplicate authtoken."""
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context
    try:
        from pyngrok import ngrok
        from pyngrok.conf import PyngrokConfig

        pyngrok_cfg = PyngrokConfig(
            ngrok_path=config.NGROK_EXE_PATH or None,
            config_path=config.NGROK_CONFIG_PATH or None,
            auth_token=config.NGROK_MANUAL_AUTH or None,
        )
        tunnel = ngrok.connect(addr=port, proto="http", pyngrok_config=pyngrok_cfg)
        return tunnel.public_url
    except Exception as e:
        err_str = str(e)
        # Jika masih terkena error Authtoken already set, hapus yml lalu coba connect tanpa set_auth_token
        if "already set" in err_str.lower():
            default_yml = os.path.join(
                os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                "ngrok",
                "ngrok.yml",
            )
            if os.path.exists(default_yml):
                try:
                    os.remove(default_yml)
                except Exception:
                    pass
            try:
                from pyngrok import ngrok
                tunnel = ngrok.connect(addr=port, proto="http")
                return tunnel.public_url
            except Exception as e2:
                print(f"[FAIL] Ngrok retry error: {e2}")
                return None
        print(f"[FAIL] Ngrok error: {e}")
        return None


# Override gopay.start_ngrok agar memakai start_ngrok_safe
gopay.start_ngrok = start_ngrok_safe


def ensure_webhook_server():
    """Pastikan HTTPServer OTP listener berjalan (reusable tanpa error port in use)."""
    global _server_instance
    with _server_lock:
        if _server_instance is None:
            HTTPServer.allow_reuse_address = True
            _server_instance = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
            Thread(target=_server_instance.serve_forever, daemon=True).start()
    return _server_instance


def setup_tunnel():
    """Jalankan OTP listener dan Ngrok tunnel, kembalikan base URL webhook."""
    global _ngrok_url
    ensure_webhook_server()
    kill_ngrok_existing()
    url = start_ngrok_safe(PORT)
    gopay.public_url = url if url else ""
    _ngrok_url = url if url else f"http://{get_local_ip()}:{PORT}"
    return _ngrok_url, bool(url)


def build_main_menu_markup() -> InlineKeyboardMarkup:
    """Buat Inline Keyboard untuk Menu Utama."""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🚀 Mulai (GSuite x GoPay)", callback_data="menu_mulai"),
        InlineKeyboardButton("🎬 Nempel + Pay (YT Prem)", callback_data="menu_nempel_pay"),
    )
    markup.add(
        InlineKeyboardButton("📡 Generate / Set Ngrok", callback_data="menu_ngrok"),
        InlineKeyboardButton("📊 Status Konfigurasi", callback_data="menu_status"),
    )
    markup.add(
        InlineKeyboardButton("📧 Kelola GSuite", callback_data="menu_gsuite"),
        InlineKeyboardButton("📱 Kelola GoPay", callback_data="menu_gopay"),
    )
    markup.add(
        InlineKeyboardButton("📁 Lihat / Download Hasil", callback_data="menu_hasil"),
        InlineKeyboardButton(
            f"🖥️ Headless: {'ON' if config.HEADLESS else 'OFF'}",
            callback_data="toggle_headless",
        ),
    )
    if _job_running:
        markup.add(InlineKeyboardButton("🛑 Stop Proses Berjalan", callback_data="stop_job"))
    return markup


def get_header_text() -> str:
    """Generate teks banner utama untuk pesan Telegram."""
    gsuite_count = len(load_gsuite_from_file())
    gopay_count = len(load_gopay_from_file())
    gagal_nempel_count = 0
    if os.path.exists(GAGAL_NEMPEL_FILE):
        with open(GAGAL_NEMPEL_FILE, "r", encoding="utf-8") as f:
            gagal_nempel_count = sum(1 for line in f if line.strip())
    status_str = "🟢 IDLE" if not _job_running else "🔥 SEDANG PROSES"
    return (
        "🤖 <b>GSUITE x GOPAY — TELEGRAM PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Status Bot   : <b>{status_str}</b>\n"
        f"📧 Antrean GSuite: <b>{gsuite_count} akun</b> (gsuite.txt)\n"
        f"❌ Gagal Nempel : <b>{gagal_nempel_count} akun</b>\n"
        f"📱 GoPay Aktif  : <b>{gopay_count} akun</b>\n"
        f"🧵 Max Thread   : <b>{MAX_THREADS}</b>\n"
        f"🖥️ Headless     : <b>{config.HEADLESS}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Pilih menu di bawah ini:"
    )


def safe_edit_or_send(chat_id, message_id, text, reply_markup=None):
    """Edit pesan jika memungkinkan, atau kirim pesan baru jika gagal."""
    try:
        if message_id:
            return bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
    except Exception:
        pass
    return bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")


# =====================================================================
# HANDLER COMMAND (/start, /menu, /status, /stop)
# =====================================================================
@bot.message_handler(commands=["start", "menu"])
def cmd_start(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔ Anda tidak memiliki akses ke bot ini.")
        return
    _user_states.pop(message.chat.id, None)
    bot.send_message(
        message.chat.id,
        get_header_text(),
        reply_markup=build_main_menu_markup(),
    )


@bot.message_handler(commands=["stop"])
def cmd_stop(message):
    if not is_authorized(message.from_user.id):
        return
    if _job_running:
        _stop_event.set()
        bot.reply_to(
            message,
            "🛑 Sinyal penghentian dikirim! Menunggu proses akun yang sedang berjalan selesai...",
        )
    else:
        bot.reply_to(message, "ℹ️ Tidak ada proses yang sedang berjalan saat ini.")


# =====================================================================
# HANDLER CALLBACK BUTTONS
# =====================================================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    if not is_authorized(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Akses ditolak!", show_alert=True)
        return

    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    data = call.data

    # Kembali ke menu utama
    if data == "back_main":
        _user_states.pop(chat_id, None)
        safe_edit_or_send(chat_id, msg_id, get_header_text(), build_main_menu_markup())
        bot.answer_callback_query(call.id)
        return

    # Toggle Headless Mode
    if data == "toggle_headless":
        config.HEADLESS = not config.HEADLESS
        gopay.HEADLESS = config.HEADLESS
        bot.answer_callback_query(
            call.id, f"Mode Headless diubah ke: {config.HEADLESS}"
        )
        safe_edit_or_send(chat_id, msg_id, get_header_text(), build_main_menu_markup())
        return

    # Stop Job
    if data == "stop_job":
        if _job_running:
            _stop_event.set()
            bot.answer_callback_query(
                call.id, "🛑 Menghentikan antrean...", show_alert=True
            )
        else:
            bot.answer_callback_query(call.id, "Tidak ada proses aktif.")
        safe_edit_or_send(chat_id, msg_id, get_header_text(), build_main_menu_markup())
        return

    # Menu Status Konfigurasi
    if data == "menu_status":
        gsuite_list = load_gsuite_from_file()
        gopay_list = load_gopay_from_file()
        tok_preview = (
            config.NGROK_MANUAL_AUTH[:10] + "..."
            if config.NGROK_MANUAL_AUTH
            else "(Kosong)"
        )
        text = (
            "📊 <b>STATUS KONFIGURASI</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📧 GSuite (gsuite.txt) : <b>{len(gsuite_list)} akun</b>\n"
            f"📱 GoPay (gopay.txt)   : <b>{len(gopay_list)} akun</b>\n"
            f"🧵 Max Threads         : <b>{MAX_THREADS}</b>\n"
            f"🌐 Port OTP Listener   : <b>{PORT}</b>\n"
            f"🔑 Ngrok Token         : <code>{tok_preview}</code>\n"
            f"🖥️ Headless            : <b>{config.HEADLESS}</b>\n"
            f"🐞 Debug               : <b>{config.DEBUG}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        if gsuite_list:
            text += "\n📧 <b>Preview GSuite (Maks 10):</b>\n"
            for idx, (em, _) in enumerate(gsuite_list[:10], 1):
                text += f"  {idx}. <code>{em}</code>\n"
            if len(gsuite_list) > 10:
                text += f"  <i>... dan {len(gsuite_list) - 10} akun lainnya</i>\n"
        if gopay_list:
            text += "\n📱 <b>Data GoPay:</b>\n"
            for idx, (ph, _) in enumerate(gopay_list, 1):
                text += f"  {idx}. <code>{ph}</code>\n"

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔑 Ganti Token Ngrok", callback_data="ngrok_set_token"))
        markup.add(InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_main"))
        safe_edit_or_send(chat_id, msg_id, text, markup)
        bot.answer_callback_query(call.id)
        return

    # =================================================================
    # MENU NGROK & GANTI TOKEN NGROK VIA BOT
    # =================================================================
    if data == "menu_ngrok":
        _user_states.pop(chat_id, None)
        tok_preview = (
            config.NGROK_MANUAL_AUTH[:12] + "..."
            if config.NGROK_MANUAL_AUTH
            else "(Belum diset)"
        )
        text = (
            "📡 <b>MENU NGROK & WEBHOOK</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔑 Token Saat Ini : <code>{tok_preview}</code>\n"
            f"🌐 URL Aktif      : <code>{_ngrok_url or 'Belum dinyalakan'}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🚀 Start / Refresh Ngrok", callback_data="ngrok_start_now"),
            InlineKeyboardButton("🔑 Ganti Token Ngrok", callback_data="ngrok_set_token"),
        )
        markup.add(
            InlineKeyboardButton("🛑 Matikan Ngrok", callback_data="kill_ngrok"),
            InlineKeyboardButton("⬅️ Menu Utama", callback_data="back_main"),
        )
        safe_edit_or_send(chat_id, msg_id, text, markup)
        bot.answer_callback_query(call.id)
        return

    if data == "ngrok_set_token":
        _user_states[chat_id] = {"step": "wait_ngrok_token"}
        text = (
            "🔑 <b>GANTI AUTHTOKEN NGROK</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Token saat ini:\n<code>{config.NGROK_MANUAL_AUTH or '(Kosong)'}</code>\n\n"
            "Silakan kirimkan <b>Authtoken Ngrok baru</b> Anda di chat ini:"
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❌ Batal", callback_data="menu_ngrok"))
        safe_edit_or_send(chat_id, msg_id, text, markup)
        bot.answer_callback_query(call.id)
        return

    if data == "ngrok_start_now":
        gopay_list = load_gopay_from_file()
        if not gopay_list:
            bot.answer_callback_query(
                call.id, "❌ File gopay.txt kosong! Tambahkan GoPay dulu.", show_alert=True
            )
            return
        bot.answer_callback_query(call.id, "⏳ Menyalakan Ngrok tunnel...")
        safe_edit_or_send(chat_id, msg_id, "⏳ <b>Starting OTP Listener & Ngrok Tunnel...</b>")
        base_url, is_ngrok = setup_tunnel()
        num_t = min(len(gopay_list), MAX_THREADS)
        status_ngrok = "📡 <b>NGROK AKTIF!</b>" if is_ngrok else "⚠️ <b>Ngrok gagal, memakai Local IP</b>"
        text = (
            f"{status_ngrok}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 Base URL: <code>{base_url}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📱 <b>Set Webhook URL di APK Notif Forwarder:</b>\n\n"
        )
        for i in range(num_t):
            phone, _ = gopay_list[i]
            text += f"<b>HP {i+1} (GoPay {phone}):</b>\n<code>{base_url}/t{i+1}</code>\n\n"
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🔄 Refresh Ngrok", callback_data="ngrok_start_now"),
            InlineKeyboardButton("🔑 Ganti Token", callback_data="ngrok_set_token"),
        )
        markup.add(
            InlineKeyboardButton("🛑 Matikan Ngrok", callback_data="kill_ngrok"),
            InlineKeyboardButton("⬅️ Menu Utama", callback_data="back_main"),
        )
        safe_edit_or_send(chat_id, msg_id, text, markup)
        return

    if data == "kill_ngrok":
        kill_ngrok_existing()
        bot.answer_callback_query(call.id, "✅ Ngrok dimatikan.")
        safe_edit_or_send(chat_id, msg_id, get_header_text(), build_main_menu_markup())
        return

    # =================================================================
    # KELOLA DATA GSUITE
    # =================================================================
    if data == "menu_gsuite":
        _user_states.pop(chat_id, None)
        gsuite_list = load_gsuite_from_file()
        text = (
            f"📧 <b>KELOLA DATA GSUITE ({len(gsuite_list)} akun)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Catatan: Akun yang gagal saat proses otomatis tetap tersimpan di gsuite.txt agar bisa langsung di-retry.</i>\n\n"
        )
        if gsuite_list:
            for idx, (em, _) in enumerate(gsuite_list[:15], 1):
                text += f"{idx}. <code>{em}</code>\n"
            if len(gsuite_list) > 15:
                text += f"<i>... dan {len(gsuite_list) - 15} akun lainnya</i>\n"
        else:
            text += "<i>(Kosong)</i>\n"

        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("➕ Tambah (Chat / .txt)", callback_data="gsuite_add"),
            InlineKeyboardButton("👁️ Lihat Semua + Pass", callback_data="gsuite_show_all"),
        )
        markup.add(
            InlineKeyboardButton("📥 Download Sisa GSuite", callback_data="gsuite_download"),
            InlineKeyboardButton("🗑️ Hapus Semua GSuite", callback_data="gsuite_clear_confirm"),
        )
        markup.add(InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_main"))
        safe_edit_or_send(chat_id, msg_id, text, markup)
        bot.answer_callback_query(call.id)
        return

    if data == "gsuite_add":
        _user_states[chat_id] = {"step": "wait_gsuite_add"}
        text = (
            "📧 <b>TAMBAH AKUN GSUITE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Kirimkan daftar akun dengan format:\n"
            "<code>email|password</code> (satu per baris)\n\n"
            "📎 <b>Bisa kirim teks banyak baris atau langsung upload file .txt!</b>"
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❌ Batal", callback_data="menu_gsuite"))
        safe_edit_or_send(chat_id, msg_id, text, markup)
        bot.answer_callback_query(call.id)
        return

    if data == "gsuite_show_all":
        gsuite_list = load_gsuite_from_file()
        if not gsuite_list:
            bot.answer_callback_query(call.id, "Data GSuite kosong!", show_alert=True)
            return
        lines = [f"{i}. <code>{em}|{pw}</code>" for i, (em, pw) in enumerate(gsuite_list[:50], 1)]
        if len(gsuite_list) > 50:
            lines.append(f"<i>... dan {len(gsuite_list) - 50} lainnya (gunakan Download)</i>")
        text = "📧 <b>DATA GSUITE LENGKAP:</b>\n\n" + "\n".join(lines)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("⬅️ Kembali", callback_data="menu_gsuite"))
        safe_edit_or_send(chat_id, msg_id, text, markup)
        bot.answer_callback_query(call.id)
        return

    if data == "gsuite_download":
        if os.path.exists("gsuite.txt") and os.path.getsize("gsuite.txt") > 0:
            with open("gsuite.txt", "rb") as f:
                bot.send_document(
                    chat_id,
                    f,
                    caption="📧 File <b>gsuite.txt</b> (Daftar akun belum diproses / gagal nempel)",
                )
            bot.answer_callback_query(call.id)
        else:
            bot.answer_callback_query(call.id, "File gsuite.txt kosong/tidak ada!", show_alert=True)
        return

    if data == "gsuite_clear_confirm":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("✅ Ya, Hapus Semua", callback_data="gsuite_clear_do"),
            InlineKeyboardButton("❌ Batal", callback_data="menu_gsuite"),
        )
        safe_edit_or_send(
            chat_id,
            msg_id,
            "⚠️ <b>Yakin ingin menghapus SEMUA data di gsuite.txt?</b>",
            markup,
        )
        bot.answer_callback_query(call.id)
        return

    if data == "gsuite_clear_do":
        with open("gsuite.txt", "w", encoding="utf-8") as f:
            f.write("")
        bot.answer_callback_query(call.id, "✅ Semua data GSuite dihapus!")
        handle_callback(
            type("CallObj", (), {"from_user": call.from_user, "message": call.message, "data": "menu_gsuite", "id": call.id})
        )
        return

    # =================================================================
    # KELOLA DATA GOPAY
    # =================================================================
    if data == "menu_gopay":
        _user_states.pop(chat_id, None)
        gopay_list = load_gopay_from_file()
        text = (
            f"📱 <b>KELOLA DATA GOPAY ({len(gopay_list)} akun)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        if gopay_list:
            for idx, (ph, pin) in enumerate(gopay_list, 1):
                text += f"{idx}. <code>{ph}</code> | {'*' * len(pin)}\n"
        else:
            text += "<i>(Kosong)</i>\n"

        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("➕ Tambah GoPay", callback_data="gopay_add"),
            InlineKeyboardButton("👁️ Lihat PIN", callback_data="gopay_show_pin"),
        )
        markup.add(
            InlineKeyboardButton("🗑️ Hapus per Nomor", callback_data="gopay_del_menu"),
            InlineKeyboardButton("🗑️ Hapus Semua", callback_data="gopay_clear_confirm"),
        )
        markup.add(InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_main"))
        safe_edit_or_send(chat_id, msg_id, text, markup)
        bot.answer_callback_query(call.id)
        return

    if data == "gopay_add":
        _user_states[chat_id] = {"step": "wait_gopay_add"}
        text = (
            "📱 <b>TAMBAH AKUN GOPAY</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Kirimkan data GoPay baru dengan format:\n"
            "<code>nohp|pin</code> (satu per baris)\n\n"
            "Contoh:\n<code>081234567890|123456</code>"
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❌ Batal", callback_data="menu_gopay"))
        safe_edit_or_send(chat_id, msg_id, text, markup)
        bot.answer_callback_query(call.id)
        return

    if data == "gopay_show_pin":
        gopay_list = load_gopay_from_file()
        if not gopay_list:
            bot.answer_callback_query(call.id, "Data GoPay kosong!", show_alert=True)
            return
        lines = [f"{i}. <code>{ph}|{pin}</code>" for i, (ph, pin) in enumerate(gopay_list, 1)]
        text = "📱 <b>DATA GOPAY LENGKAP (DENGAN PIN):</b>\n\n" + "\n".join(lines)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("⬅️ Kembali", callback_data="menu_gopay"))
        safe_edit_or_send(chat_id, msg_id, text, markup)
        bot.answer_callback_query(call.id)
        return

    if data == "gopay_del_menu":
        gopay_list = load_gopay_from_file()
        if not gopay_list:
            bot.answer_callback_query(call.id, "Tidak ada akun GoPay untuk dihapus!", show_alert=True)
            return
        markup = InlineKeyboardMarkup(row_width=1)
        for idx, (ph, _) in enumerate(gopay_list):
            markup.add(
                InlineKeyboardButton(f"❌ Hapus #{idx+1}: {ph}", callback_data=f"gopay_del_idx:{idx}")
            )
        markup.add(InlineKeyboardButton("⬅️ Kembali", callback_data="menu_gopay"))
        safe_edit_or_send(
            chat_id, msg_id, "📱 <b>Pilih akun GoPay yang ingin dihapus:</b>", markup
        )
        bot.answer_callback_query(call.id)
        return

    if data.startswith("gopay_del_idx:"):
        idx_to_del = int(data.split(":")[1])
        gopay_list = load_gopay_from_file()
        if 0 <= idx_to_del < len(gopay_list):
            removed_ph = gopay_list[idx_to_del][0]
            remaining = [f"{ph}|{pin}" for i, (ph, pin) in enumerate(gopay_list) if i != idx_to_del]
            with open("gopay.txt", "w", encoding="utf-8") as f:
                for line in remaining:
                    f.write(line + "\n")
            bot.answer_callback_query(call.id, f"✅ GoPay {removed_ph} dihapus!")
        handle_callback(
            type("CallObj", (), {"from_user": call.from_user, "message": call.message, "data": "menu_gopay", "id": call.id})
        )
        return

    if data == "gopay_clear_confirm":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("✅ Ya, Hapus Semua", callback_data="gopay_clear_do"),
            InlineKeyboardButton("❌ Batal", callback_data="menu_gopay"),
        )
        safe_edit_or_send(
            chat_id, msg_id, "⚠️ <b>Yakin ingin menghapus SEMUA akun GoPay?</b>", markup
        )
        bot.answer_callback_query(call.id)
        return

    if data == "gopay_clear_do":
        with open("gopay.txt", "w", encoding="utf-8") as f:
            f.write("")
        bot.answer_callback_query(call.id, "✅ Semua data GoPay dihapus!")
        handle_callback(
            type("CallObj", (), {"from_user": call.from_user, "message": call.message, "data": "menu_gopay", "id": call.id})
        )
        return

    # =================================================================
    # LIHAT / DOWNLOAD HASIL & LOG GAGAL
    # =================================================================
    if data == "menu_hasil":
        res_count = 0
        if os.path.exists(RESULT_FILE):
            with open(RESULT_FILE, "r", encoding="utf-8") as f:
                res_count = sum(1 for line in f if line.strip())
        linked_count = 0
        if os.path.exists("gsuitexGoPay.txt"):
            with open("gsuitexGoPay.txt", "r", encoding="utf-8") as f:
                linked_count = sum(1 for line in f if line.strip())
        gagal_nempel_count = 0
        if os.path.exists(GAGAL_NEMPEL_FILE):
            with open(GAGAL_NEMPEL_FILE, "r", encoding="utf-8") as f:
                gagal_nempel_count = sum(1 for line in f if line.strip())
        gagal_pay_count = len(load_gagal_pay())
        sisa_gsuite_count = len(load_gsuite_from_file())

        text = (
            "📁 <b>HASIL PROSES & DATA AKUN</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 <b>RESULT.txt</b>               : {res_count} baris\n"
            f"🔗 <b>gsuitexGoPay.txt (Linked)</b>: {linked_count} akun\n"
            f"❌ <b>gagal_nempel.txt</b>         : {gagal_nempel_count} akun\n"
            f"⚠️ <b>Gagal Pay (Retryable)</b>    : {gagal_pay_count} akun\n"
            f"📧 <b>Sisa di gsuite.txt</b>       : {sisa_gsuite_count} akun\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("👁️ Lihat RESULT.txt", callback_data="view_file:RESULT.txt"),
            InlineKeyboardButton("📥 Unduh RESULT.txt", callback_data="dl_file:RESULT.txt"),
        )
        markup.add(
            InlineKeyboardButton("👁️ Lihat Linked", callback_data="view_file:gsuitexGoPay.txt"),
            InlineKeyboardButton("📥 Unduh Linked", callback_data="dl_file:gsuitexGoPay.txt"),
        )
        markup.add(
            InlineKeyboardButton("👁️ Lihat Gagal Nempel", callback_data=f"view_file:{GAGAL_NEMPEL_FILE}"),
            InlineKeyboardButton("📥 Unduh Gagal Nempel", callback_data=f"dl_file:{GAGAL_NEMPEL_FILE}"),
        )
        markup.add(
            InlineKeyboardButton("🗑️ Reset RESULT.txt", callback_data="clear_file:RESULT.txt"),
            InlineKeyboardButton("🗑️ Reset Gagal Nempel", callback_data=f"clear_file:{GAGAL_NEMPEL_FILE}"),
        )
        markup.add(InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_main"))
        safe_edit_or_send(chat_id, msg_id, text, markup)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("view_file:"):
        fname = data.split(":", 1)[1]
        if not os.path.exists(fname) or os.path.getsize(fname) == 0:
            bot.answer_callback_query(call.id, f"File {fname} masih kosong!", show_alert=True)
            return
        with open(fname, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        preview = "\n".join(f"{i+1}. <code>{l}</code>" for i, l in enumerate(lines[-40:]))
        header = f"📄 <b>Isi {fname} ({len(lines)} baris):</b>\n\n"
        if len(lines) > 40:
            header += "<i>(Menampilkan 40 baris terakhir)</i>\n\n"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("⬅️ Kembali", callback_data="menu_hasil"))
        safe_edit_or_send(chat_id, msg_id, header + preview, markup)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("dl_file:"):
        fname = data.split(":", 1)[1]
        if not os.path.exists(fname) or os.path.getsize(fname) == 0:
            bot.answer_callback_query(call.id, f"File {fname} kosong / belum ada!", show_alert=True)
            return
        with open(fname, "rb") as f:
            bot.send_document(chat_id, f, caption=f"📄 File <b>{fname}</b>")
        bot.answer_callback_query(call.id)
        return

    if data.startswith("clear_file:"):
        fname = data.split(":", 1)[1]
        if os.path.exists(fname):
            with open(fname, "w", encoding="utf-8") as f:
                f.write("")
        bot.answer_callback_query(call.id, f"✅ {fname} berhasil dikosongkan!")
        handle_callback(
            type("CallObj", (), {"from_user": call.from_user, "message": call.message, "data": "menu_hasil", "id": call.id})
        )
        return

    # =================================================================
    # MENU 1: MULAI PROSES (GSUITE x GOPAY)
    # =================================================================
    if data == "menu_mulai":
        if _job_running:
            bot.answer_callback_query(
                call.id, "⚠️ Masih ada proses yang sedang berjalan!", show_alert=True
            )
            return
        sisa_count = len(load_gsuite_from_file())
        text = (
            "🚀 <b>MULAI PROSES (GSUITE x GOPAY)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📂 Antrean di <code>gsuite.txt</code> saat ini: <b>{sisa_count} akun</b>\n\n"
            "Pilih sumber data akun GSuite:"
        )
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton(
                f"📂 Proses dari gsuite.txt ({sisa_count} akun)",
                callback_data="mulai_from_file",
            ),
            InlineKeyboardButton(
                "✍️ Kirim Chat / Upload File .txt Baru", callback_data="mulai_manual"
            ),
            InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_main"),
        )
        safe_edit_or_send(chat_id, msg_id, text, markup)
        bot.answer_callback_query(call.id)
        return

    if data == "mulai_from_file":
        gsuite_data = load_gsuite_from_file()
        gopay_data = load_gopay_from_file()
        if not gsuite_data:
            bot.answer_callback_query(call.id, "❌ File gsuite.txt kosong!", show_alert=True)
            return
        if not gopay_data:
            bot.answer_callback_query(call.id, "❌ File gopay.txt kosong!", show_alert=True)
            return
        bot.answer_callback_query(call.id, "🚀 Memulai proses GSuite x GoPay...")
        start_background_linking(chat_id, gsuite_data, gopay_data)
        return

    if data == "mulai_manual":
        gopay_data = load_gopay_from_file()
        if not gopay_data:
            bot.answer_callback_query(call.id, "❌ File gopay.txt kosong! Isi GoPay dulu.", show_alert=True)
            return
        _user_states[chat_id] = {"step": "wait_mulai_manual"}
        text = (
            "✍️ <b>INPUT GSUITE (CHAT / FILE .TXT)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Silakan <b>paste daftar akun</b> atau <b>upload file .txt</b> dengan format:\n"
            "<code>email|password</code> (satu per baris)\n\n"
            "💡 <i>Semua akun yang Anda kirim akan otomatis dicadangkan ke <code>gsuite.txt</code> terlebih dahulu, sehingga jika ada yang gagal otomatis tersimpan dan siap di-retry!</i>"
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❌ Batal", callback_data="menu_mulai"))
        safe_edit_or_send(chat_id, msg_id, text, markup)
        bot.answer_callback_query(call.id)
        return

    # =================================================================
    # MENU 2: NEMPEL + PAY (GSUITE -> YOUTUBE PREMIUM)
    # =================================================================
    if data == "menu_nempel_pay":
        if _job_running:
            bot.answer_callback_query(
                call.id, "⚠️ Masih ada proses yang sedang berjalan!", show_alert=True
            )
            return
        gagal_pay_list = load_gagal_pay()
        sisa_gsuite = len(load_gsuite_from_file())
        text = (
            "🎬 <b>NEMPEL + PAY (YOUTUBE PREMIUM)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📧 Antrean gsuite.txt : <b>{sisa_gsuite} akun</b>\n"
            f"🔄 Retry Gagal Pay    : <b>{len(gagal_pay_list)} akun</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Pilih mode eksekusi:"
        )
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton(
                f"🎬 Nempel + Pay dari gsuite.txt ({sisa_gsuite} akun)",
                callback_data="nempel_pay_start",
            ),
            InlineKeyboardButton(
                "✍️ Nempel + Pay via Kirim Chat / File .txt",
                callback_data="nempel_pay_manual",
            ),
            InlineKeyboardButton(
                f"🔄 Retry Pay ({len(gagal_pay_list)} akun GAGAL PAY)",
                callback_data="nempel_pay_retry",
            ),
            InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_main"),
        )
        safe_edit_or_send(chat_id, msg_id, text, markup)
        bot.answer_callback_query(call.id)
        return

    if data == "nempel_pay_start":
        gsuite_data = load_gsuite_from_file()
        gopay_data = load_gopay_from_file()
        if not gsuite_data:
            bot.answer_callback_query(call.id, "❌ File gsuite.txt kosong!", show_alert=True)
            return
        if not gopay_data:
            bot.answer_callback_query(call.id, "❌ File gopay.txt kosong!", show_alert=True)
            return
        bot.answer_callback_query(call.id, "🚀 Memulai Pipeline Nempel + Pay...")
        start_background_pipeline(chat_id, gsuite_data, gopay_data)
        return

    if data == "nempel_pay_manual":
        gopay_data = load_gopay_from_file()
        if not gopay_data:
            bot.answer_callback_query(call.id, "❌ File gopay.txt kosong! Isi GoPay dulu.", show_alert=True)
            return
        _user_states[chat_id] = {"step": "wait_nempel_pay_manual"}
        text = (
            "🎬 <b>INPUT NEMPEL + PAY (CHAT / FILE .TXT)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Silakan <b>paste daftar akun</b> atau <b>upload file .txt</b> dengan format:\n"
            "<code>email|password</code> (satu per baris)\n\n"
            "💡 <i>Akun otomatis disimpan ke <code>gsuite.txt</code> sebelum jalan, sehingga jika gagal nempel tidak akan hilang!</i>"
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❌ Batal", callback_data="menu_nempel_pay"))
        safe_edit_or_send(chat_id, msg_id, text, markup)
        bot.answer_callback_query(call.id)
        return

    if data == "nempel_pay_retry":
        gagal_list = load_gagal_pay()
        gopay_data = load_gopay_from_file()
        if not gagal_list:
            bot.answer_callback_query(
                call.id, "Tidak ada akun [GAGAL WAKTU PAY DOANG] di RESULT.txt!", show_alert=True
            )
            return
        num_t = min(len(gopay_data), MAX_THREADS) if gopay_data else 1
        bot.answer_callback_query(call.id, "🔄 Memulai Retry Pay...")
        start_background_retry_pay(chat_id, gagal_list, num_t)
        return


# =====================================================================
# HANDLER INPUT TEKS & FILE DOKUMEN DARI USER
# =====================================================================
@bot.message_handler(content_types=["text", "document"])
def handle_user_input(message):
    if not is_authorized(message.from_user.id):
        return
    chat_id = message.chat.id
    state = _user_states.get(chat_id)
    if not state:
        return

    raw_text = ""
    if message.content_type == "document":
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded = bot.download_file(file_info.file_path)
            raw_text = downloaded.decode("utf-8", errors="replace")
        except Exception as e:
            bot.reply_to(message, f"❌ Gagal membaca file: {e}")
            return
    else:
        raw_text = message.text or ""

    step = state.get("step")

    # Input ganti token Ngrok
    if step == "wait_ngrok_token":
        new_tok = raw_text.strip()
        if not new_tok or len(new_tok) < 10:
            bot.reply_to(message, "❌ Token Ngrok tidak valid!")
            return
        update_ngrok_token_everywhere(new_tok)
        _user_states.pop(chat_id, None)
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🚀 Test Start Ngrok", callback_data="ngrok_start_now"),
            InlineKeyboardButton("⬅️ Menu Ngrok", callback_data="menu_ngrok"),
        )
        bot.reply_to(
            message,
            f"✅ <b>Authtoken Ngrok berhasil diperbarui!</b>\nToken baru: <code>{new_tok[:12]}...</code>",
            reply_markup=markup,
        )
        return

    # Input tambah akun GSuite
    if step == "wait_gsuite_add":
        parsed = parse_gsuite_data(raw_text)
        if not parsed:
            bot.reply_to(
                message,
                "❌ Tidak ada format valid! Pastikan format: <code>email|password</code>",
            )
            return
        added = save_unique_to_gsuite_file(parsed)
        _user_states.pop(chat_id, None)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📧 Kembali ke Menu GSuite", callback_data="menu_gsuite"))
        bot.reply_to(
            message,
            f"✅ Berhasil menerima <b>{len(parsed)} akun</b> (<b>{added} akun baru</b> ditambahkan ke <code>gsuite.txt</code>)!",
            reply_markup=markup,
        )
        return

    # Input tambah akun GoPay (Mendukung nohp|pin atau nohp pin)
    if step == "wait_gopay_add":
        valid_lines = parse_gopay_data(raw_text)
        if not valid_lines:
            bot.reply_to(
                message,
                "❌ Format salah! Gunakan format: <code>nohp|pin</code> (satu per baris)",
            )
            return
        with open("gopay.txt", "a", encoding="utf-8") as f:
            for line in valid_lines:
                f.write(line + "\n")
        _user_states.pop(chat_id, None)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📱 Kembali ke Menu GoPay", callback_data="menu_gopay"))
        bot.reply_to(
            message,
            f"✅ Berhasil menambahkan <b>{len(valid_lines)} akun GoPay</b> ke <code>gopay.txt</code>!",
            reply_markup=markup,
        )
        return

    # Input manual langsung jalan GSuite x GoPay (otomatis backup ke gsuite.txt)
    if step == "wait_mulai_manual":
        parsed = parse_gsuite_data(raw_text)
        if not parsed:
            bot.reply_to(
                message,
                "❌ Format tidak valid! Gunakan: <code>email|password</code>",
            )
            return
        _user_states.pop(chat_id, None)
        added = save_unique_to_gsuite_file(parsed)
        gopay_data = load_gopay_from_file()
        bot.reply_to(
            message,
            f"✅ Memuat <b>{len(parsed)} akun GSuite</b> ({added} baru dicadangkan ke <code>gsuite.txt</code>). Memulai proses...",
        )
        start_background_linking(chat_id, parsed, gopay_data)
        return

    # Input manual langsung jalan Pipeline Nempel + Pay (otomatis backup ke gsuite.txt)
    if step == "wait_nempel_pay_manual":
        parsed = parse_gsuite_data(raw_text)
        if not parsed:
            bot.reply_to(
                message,
                "❌ Format tidak valid! Gunakan: <code>email|password</code>",
            )
            return
        _user_states.pop(chat_id, None)
        added = save_unique_to_gsuite_file(parsed)
        gopay_data = load_gopay_from_file()
        bot.reply_to(
            message,
            f"✅ Memuat <b>{len(parsed)} akun GSuite</b> ({added} baru dicadangkan ke <code>gsuite.txt</code>). Memulai Pipeline Nempel + Pay...",
        )
        start_background_pipeline(chat_id, parsed, gopay_data)
        return


# =====================================================================
# ENGINE EKSEKUSI BACKGROUND & LIVE DASHBOARD TELEGRAM
# =====================================================================
def render_progress_bar(processed: int, total: int) -> str:
    pct = int(processed / total * 100) if total > 0 else 0
    filled = int(pct / 5)
    bar = "█" * filled + "░" * (20 - filled)
    return f"[{bar}] {processed}/{total} ({pct}%)"


def start_background_linking(chat_id: int, gsuite_data: list, gopay_data: list):
    """Jalankan proses GSuite x GoPay di background thread & kirim live update ke Telegram."""
    global _job_running
    with _job_lock:
        if _job_running:
            bot.send_message(chat_id, "⚠️ Proses lain sedang berjalan!")
            return
        _job_running = True
        _stop_event.clear()

    def run_task():
        global _job_running
        start_ts = time.time()
        num_threads = min(len(gopay_data), MAX_THREADS)
        with _status_lock:
            _live_thread_status.clear()
            for idx in range(1, num_threads + 1):
                _live_thread_status[idx] = "Menunggu..."

        status_msg = bot.send_message(
            chat_id, "⏳ <b>Menyiapkan OTP Listener & Ngrok Tunnel...</b>"
        )
        base_url, is_ngrok = setup_tunnel()

        webhook_lines = [
            f"• HP {i+1} (<code>{gopay_data[i][0]}</code>): <code>{base_url}/t{i+1}</code>"
            for i in range(num_threads)
        ]
        webhook_info = "\n".join(webhook_lines)

        q = queue.Queue()
        for item in gsuite_data:
            q.put(item)

        total = len(gsuite_data)
        ctrs = {
            "berhasil": 0,
            "gagal": 0,
            "processed": 0,
            "gagal_list": [],
            "lock": Lock(),
        }

        def worker_fn(t_id, phone, pin, w_url):
            while not _stop_event.is_set():
                try:
                    email, password = q.get(timeout=1)
                except queue.Empty:
                    gopay.update_status(t_id, "[OK] Selesai - idle")
                    break
                ok = False
                for attempt in range(1, MAX_RETRY + 1):
                    if _stop_event.is_set():
                        break
                    gopay.update_status(t_id, f"[INFO] {email} ({attempt}/{MAX_RETRY})")
                    res = process_account(
                        email=email,
                        password=password,
                        phone=phone,
                        pin=pin,
                        thread_id=t_id,
                        webhook_url=w_url,
                    )
                    if res:
                        with ctrs["lock"]:
                            ctrs["berhasil"] += 1
                            ctrs["processed"] += 1
                        cut_from_gsuite(email)
                        append_result(email, password)
                        ok = True
                        break
                    else:
                        gopay.update_status(t_id, f"[WARN] Gagal #{attempt}, retry 5s...")
                        time.sleep(5)
                if not ok:
                    with ctrs["lock"]:
                        ctrs["gagal"] += 1
                        ctrs["processed"] += 1
                        ctrs["gagal_list"].append(f"{email}|{password}")
                    append_gagal_nempel(email, password, phone)
                    gopay.update_status(t_id, f"[FAIL] {email} gagal {MAX_RETRY}x")
                q.task_done()

        threads = []
        for i in range(num_threads):
            ph, pn = gopay_data[i]
            w_url = f"{base_url}/t{i+1}"
            t = Thread(target=worker_fn, args=(i + 1, ph, pn, w_url), daemon=True)
            t.start()
            threads.append(t)

        last_text = ""
        stop_markup = InlineKeyboardMarkup()
        stop_markup.add(InlineKeyboardButton("🛑 Stop Proses", callback_data="stop_job"))

        while any(t.is_alive() for t in threads):
            with ctrs["lock"]:
                proc = ctrs["processed"]
                ok_cnt = ctrs["berhasil"]
                fail_cnt = ctrs["gagal"]
            with _status_lock:
                t_lines = [
                    f"<b>T{idx}:</b> <code>{_live_thread_status.get(idx, '-')[:55]}</code>"
                    for idx in range(1, num_threads + 1)
                ]
            live_text = (
                "🚀 <b>PROSES GSUITE x GOPAY BERJALAN</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📱 <b>Webhook URL:</b>\n{webhook_info}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⏳ <code>{render_progress_bar(proc, total)}</code>\n"
                f"✅ Berhasil: <b>{ok_cnt}</b> | ❌ Gagal: <b>{fail_cnt}</b>\n\n"
                "🧵 <b>Status Thread:</b>\n" + "\n".join(t_lines)
            )
            if live_text != last_text:
                safe_edit_or_send(chat_id, status_msg.message_id, live_text, stop_markup)
                last_text = live_text
            time.sleep(3.5)

        dur_str = format_duration(time.time() - start_ts)
        sisa_gsuite = len(load_gsuite_from_file())
        gagal_preview = ""
        if ctrs["gagal_list"]:
            preview_items = "\n".join(f"• <code>{x}</code>" for x in ctrs["gagal_list"][:10])
            gagal_preview = (
                f"\n❌ <b>Akun Gagal ({len(ctrs['gagal_list'])}):</b>\n{preview_items}\n"
                "<i>(Tetap tersimpan di gsuite.txt & gagal_nempel.txt)</i>\n"
            )

        summary_text = (
            "📊 <b>SUMMARY GSUITE x GOPAY</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📧 Total Diproses : <b>{total}</b>\n"
            f"✅ Berhasil       : <b>{ctrs['berhasil']}</b>\n"
            f"❌ Gagal          : <b>{ctrs['gagal']}</b>\n"
            f"📂 Sisa gsuite.txt: <b>{sisa_gsuite} akun</b>\n"
            f"⏱️ Durasi         : <b>{dur_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
            f"{gagal_preview}"
        )
        _job_running = False
        markup = build_main_menu_markup()
        if ctrs["gagal"] > 0:
            markup.row(
                InlineKeyboardButton(
                    f"🔄 Retry {sisa_gsuite} Akun Gagal di gsuite.txt",
                    callback_data="mulai_from_file",
                )
            )
        safe_edit_or_send(chat_id, status_msg.message_id, summary_text, markup)

        if os.path.exists(RESULT_FILE) and ctrs["berhasil"] > 0:
            with open(RESULT_FILE, "rb") as f:
                bot.send_document(chat_id, f, caption="📄 File <b>RESULT.txt</b> (Akun Berhasil)")

    Thread(target=run_task, daemon=True).start()


def start_background_pipeline(chat_id: int, gsuite_data: list, gopay_data: list):
    """Jalankan pipeline Nempel + Pay secara paralel & kirim live update ke Telegram."""
    global _job_running
    with _job_lock:
        if _job_running:
            bot.send_message(chat_id, "⚠️ Proses lain sedang berjalan!")
            return
        _job_running = True
        _stop_event.clear()

    def run_pipeline():
        global _job_running
        start_ts = time.time()
        num_threads = min(len(gopay_data), MAX_THREADS)
        with _status_lock:
            _live_thread_status.clear()
            for idx in range(1, num_threads + 1):
                _live_thread_status[idx] = "Menunggu..."

        status_msg = bot.send_message(
            chat_id, "⏳ <b>Menyiapkan Pipeline Nempel + Pay & Ngrok...</b>"
        )
        base_url, _ = setup_tunnel()

        webhook_lines = [
            f"• HP {i+1} (<code>{gopay_data[i][0]}</code>): <code>{base_url}/t{i+1}</code>"
            for i in range(num_threads)
        ]
        webhook_info = "\n".join(webhook_lines)

        nempel_q = queue.Queue()
        for item in gsuite_data:
            nempel_q.put(item)
        pay_q = queue.Queue()

        total = len(gsuite_data)
        stats = {
            "nempel_done": 0,
            "nempel_ok": 0,
            "nempel_fail": 0,
            "pay_ok": 0,
            "pay_sudah": 0,
            "pay_fail": 0,
            "gagal_nempel_list": [],
            "lock": Lock(),
        }

        def nempel_worker(t_id, phone, pin, w_url):
            while not _stop_event.is_set():
                try:
                    email, password = nempel_q.get(timeout=1)
                except queue.Empty:
                    gopay.update_status(t_id, "[OK] Nempel selesai - idle")
                    break
                ok = False
                for attempt in range(1, MAX_RETRY + 1):
                    if _stop_event.is_set():
                        break
                    gopay.update_status(t_id, f"[INFO] Nempel {email} ({attempt}/{MAX_RETRY})")
                    res = process_account(
                        email=email,
                        password=password,
                        phone=phone,
                        pin=pin,
                        thread_id=t_id,
                        webhook_url=w_url,
                    )
                    if res == "already_linked" or res:
                        with stats["lock"]:
                            stats["nempel_ok"] += 1
                        cut_from_gsuite(email)
                        pay_q.put((email, password))
                        ok = True
                        break
                    else:
                        gopay.update_status(t_id, f"[WARN] Nempel gagal #{attempt}, retry 5s...")
                        time.sleep(5)
                if not ok:
                    with stats["lock"]:
                        stats["nempel_fail"] += 1
                        stats["gagal_nempel_list"].append(f"{email}|{password}")
                    append_gagal_nempel(email, password, phone)
                    gopay.update_status(t_id, f"[FAIL] Nempel {email} gagal {MAX_RETRY}x")
                with stats["lock"]:
                    stats["nempel_done"] += 1
                nempel_q.task_done()

        def pay_worker(w_idx):
            while not _stop_event.is_set():
                try:
                    email, password = pay_q.get(timeout=3)
                except queue.Empty:
                    with stats["lock"]:
                        done_cnt = stats["nempel_done"]
                    if done_cnt >= total and pay_q.empty():
                        break
                    continue
                res = yt_process_one(email, password, w_idx, config.HEADLESS)
                with stats["lock"]:
                    if res.get("success"):
                        stats["pay_ok"] += 1
                    elif res.get("already_premium"):
                        stats["pay_sudah"] += 1
                    else:
                        stats["pay_fail"] += 1
                        append_result(email, password, "GAGAL WAKTU PAY DOANG")
                pay_q.task_done()

        n_threads = []
        p_threads = []
        for i in range(num_threads):
            ph, pn = gopay_data[i]
            w_url = f"{base_url}/t{i+1}"
            t1 = Thread(target=nempel_worker, args=(i + 1, ph, pn, w_url), daemon=True)
            t2 = Thread(target=pay_worker, args=(i + 1,), daemon=True)
            t1.start()
            t2.start()
            n_threads.append(t1)
            p_threads.append(t2)

        last_text = ""
        stop_markup = InlineKeyboardMarkup()
        stop_markup.add(InlineKeyboardButton("🛑 Stop Pipeline", callback_data="stop_job"))

        while any(t.is_alive() for t in n_threads + p_threads):
            with stats["lock"]:
                nd = stats["nempel_done"]
                nok = stats["nempel_ok"]
                nfail = stats["nempel_fail"]
                pok = stats["pay_ok"]
                psudah = stats["pay_sudah"]
                pfail = stats["pay_fail"]
            with _status_lock:
                t_lines = [
                    f"<b>T{idx}:</b> <code>{_live_thread_status.get(idx, '-')[:55]}</code>"
                    for idx in range(1, num_threads + 1)
                ]
            live_text = (
                "🎬 <b>PIPELINE NEMPEL + PAY BERJALAN</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📱 <b>Webhook URL:</b>\n{webhook_info}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⏳ Nempel: <code>{render_progress_bar(nd, total)}</code>\n"
                f"🔗 Nempel OK: <b>{nok}</b> | ❌ Fail: <b>{nfail}</b>\n"
                f"🎬 Pay OK: <b>{pok}</b> | 🏅 Sudah Prem: <b>{psudah}</b> | ❌ Pay Fail: <b>{pfail}</b>\n\n"
                "🧵 <b>Status Thread Nempel:</b>\n" + "\n".join(t_lines)
            )
            if live_text != last_text:
                safe_edit_or_send(chat_id, status_msg.message_id, live_text, stop_markup)
                last_text = live_text
            time.sleep(3.5)

        dur_str = format_duration(time.time() - start_ts)
        sisa_gsuite = len(load_gsuite_from_file())
        summary_text = (
            "📊 <b>SUMMARY NEMPEL + PAY PIPELINE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 Nempel OK     : <b>{stats['nempel_ok']}</b>\n"
            f"❌ Nempel Fail   : <b>{stats['nempel_fail']}</b> (tetap di gsuite.txt)\n"
            f"✅ Pay OK        : <b>{stats['pay_ok']}</b>\n"
            f"🏅 Sudah Premium : <b>{stats['pay_sudah']}</b>\n"
            f"❌ Pay Fail      : <b>{stats['pay_fail']}</b> ([GAGAL WAKTU PAY DOANG])\n"
            f"📂 Sisa gsuite.txt: <b>{sisa_gsuite} akun</b>\n"
            f"⏱️ Durasi        : <b>{dur_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        _job_running = False
        markup = build_main_menu_markup()
        if stats["nempel_fail"] > 0:
            markup.row(
                InlineKeyboardButton(
                    f"🔄 Retry Nempel ({sisa_gsuite} Akun di gsuite.txt)",
                    callback_data="nempel_pay_start",
                )
            )
        if stats["pay_fail"] > 0:
            markup.row(
                InlineKeyboardButton(
                    f"🔄 Retry Pay ({stats['pay_fail']} Akun Gagal Pay)",
                    callback_data="nempel_pay_retry",
                )
            )
        safe_edit_or_send(chat_id, status_msg.message_id, summary_text, markup)

        if os.path.exists(RESULT_FILE):
            with open(RESULT_FILE, "rb") as f:
                bot.send_document(chat_id, f, caption="📄 File <b>RESULT.txt</b> terbaru")

    Thread(target=run_pipeline, daemon=True).start()


def start_background_retry_pay(chat_id: int, gagal_list: list, num_threads: int):
    """Jalankan Retry Pay untuk akun yang berstatus [GAGAL WAKTU PAY DOANG]."""
    global _job_running
    with _job_lock:
        if _job_running:
            bot.send_message(chat_id, "⚠️ Proses lain sedang berjalan!")
            return
        _job_running = True
        _stop_event.clear()

    def run_retry():
        global _job_running
        start_ts = time.time()
        emails_to_retry = [item.split("|")[0].strip() for item in gagal_list]
        remove_gagal_pay_from_result(emails_to_retry)

        accounts = []
        for item in gagal_list:
            parts = item.split("|", 1)
            if len(parts) == 2:
                accounts.append((parts[0].strip(), parts[1].strip()))

        status_msg = bot.send_message(
            chat_id,
            f"🔄 <b>Memulai Retry Pay ({len(accounts)} akun, {num_threads} thread)...</b>",
        )

        prem_baru = 0
        sudah_prem = 0
        gagal = 0
        gagal_details = []
        pw_map = {em: pw for em, pw in accounts}

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = {
                executor.submit(yt_process_one, em, pw, idx + 1, config.HEADLESS): (em, pw)
                for idx, (em, pw) in enumerate(accounts)
            }
            for fut in concurrent.futures.as_completed(futures):
                try:
                    res = fut.result()
                    em = res.get("email", "?")
                    pw = pw_map.get(em, "")
                    if res.get("success"):
                        prem_baru += 1
                    elif res.get("already_premium"):
                        sudah_prem += 1
                    else:
                        gagal += 1
                        reason = res.get("reason", "?")
                        gagal_details.append(f"• <code>{em}</code> — {reason}")
                        if pw:
                            append_result(em, pw, "GAGAL WAKTU PAY DOANG")
                except Exception as e:
                    gagal += 1
                    gagal_details.append(f"• Error: {e}")

        dur_str = format_duration(time.time() - start_ts)
        detail_str = "\n".join(gagal_details[:20]) if gagal_details else "-"
        summary_text = (
            "📊 <b>SUMMARY RETRY PAY</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Premium Baru  : <b>{prem_baru}</b>\n"
            f"🏅 Sudah Premium : <b>{sudah_prem}</b>\n"
            f"❌ Gagal Pay     : <b>{gagal}</b>\n"
            f"⏱️ Durasi        : <b>{dur_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Detail Gagal:</b>\n{detail_str}"
        )
        _job_running = False
        safe_edit_or_send(
            chat_id, status_msg.message_id, summary_text, build_main_menu_markup()
        )

    Thread(target=run_retry, daemon=True).start()


def _shutdown_signal(sig, frame):
    print("\n[INFO] Menghentikan Telegram Bot & Ngrok...")
    kill_ngrok_existing()
    os._exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _shutdown_signal)
    ensure_webhook_server()
    print("=======================================================")
    print("  🤖 GSUITE x GOPAY TELEGRAM BOT V2 AKTIF!")
    print(f"  🌐 OTP Webhook Listener : Port {PORT}")
    print("  📲 Buka bot Anda di Telegram dan ketik /start")
    print("=======================================================")
    bot.infinity_polling(timeout=20, long_polling_timeout=10)
