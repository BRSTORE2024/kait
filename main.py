"""
main.py — GSUITE x GOPAY via Telegram Bot (Telethon)
Menu utama: Mulai, Add GoPay, Show URL Webhook
GSuite input via kirim file atau text langsung (format: email|password)
"""

import os
import re as _re
import time
import queue
import asyncio
from datetime import datetime
from threading import Thread, Lock
from http.server import HTTPServer

from telethon import TelegramClient, events, Button

from gopay import (
    WebhookHandler, start_ngrok, get_local_ip,
    PORT, MAX_THREADS, MAX_RETRY, init_dashboard, update_status,
    process_account, info
)
from config import HEADLESS, DEBUG, BOT_TOKEN, API_ID, API_HASH, ADMIN_IDS

# ========================= STATE =========================

# Simpan state per user chat
user_states = {}
# Global server & url
http_server = None
public_url_global = ""
running_process = False
running_lock = Lock()


# ========================= UTILITAS =========================

def load_gopay_from_file():
    if not os.path.exists("gopay.txt"):
        return []
    with open("gopay.txt", "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip() and "|" in line]
    result = []
    for line in lines:
        parts = line.split("|", 1)
        phone = parts[0].strip()
        pin = parts[1].strip()
        if phone and pin:
            result.append((phone, pin))
    return result


def load_gsuite_from_file():
    if not os.path.exists("gsuite.txt"):
        return []
    with open("gsuite.txt", "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip() and "|" in line]
    result = []
    for line in lines:
        parts = line.split("|", 1)
        email = parts[0].strip()
        password = parts[1].strip()
        if email and password:
            result.append((email, password))
    return result


def parse_gsuite_data(text):
    lines = []
    for line in text.strip().splitlines():
        line = line.strip()
        if line and "|" in line:
            parts = line.split("|", 1)
            email = parts[0].strip()
            password = parts[1].strip()
            if email and password:
                lines.append((email, password))
    return lines


def format_duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} detik"
    elif seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m} menit {s} detik"
    else:
        h, remainder = divmod(seconds, 3600)
        m, s = divmod(remainder, 60)
        return f"{h} jam {m} menit {s} detik"


def ensure_ngrok():
    """Start HTTP server + ngrok jika belum jalan. Return public_url."""
    global http_server, public_url_global

    if http_server is None:
        http_server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
        # Tambahkan agar port bisa langsung digunakan kembali setelah shutdown
        http_server.allow_reuse_address = True 
        Thread(target=http_server.serve_forever, daemon=True).start()

    if not public_url_global:
        public_url_global = start_ngrok(PORT) or ""

    return public_url_global


def get_webhook_urls():
    """Return list of webhook URL strings per gopay account."""
    gopay_data = load_gopay_from_file()
    if not gopay_data:
        return None, "File gopay.txt kosong atau tidak ada."

    pub = ensure_ngrok()
    ip = get_local_ip()
    base = pub if pub else f"http://{ip}:{PORT}"

    num = min(len(gopay_data), MAX_THREADS)
    urls = []
    for i in range(num):
        phone, _ = gopay_data[i]
        urls.append((f"HP {i+1} ({phone})", f"{base}/t{i+1}"))
    return urls, base


# ========================= CONFIG UTILS =========================

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")


def read_config_value(key):
    """Baca value dari config.py berdasarkan key."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    m = _re.search(rf'^{key}\s*=\s*(.+?)(\s*#.*)?$', content, _re.MULTILINE)
    if m:
        try:
            return eval(m.group(1).strip())
        except Exception:
            return m.group(1).strip()
    return None


def write_config_value(key, value):
    """Tulis value ke config.py, replace baris yang ada."""
    import config
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    if isinstance(value, str):
        value_str = f'"{value}"'
    elif isinstance(value, bool):
        value_str = "True" if value else "False"
    elif isinstance(value, list):
        value_str = repr(value)
    else:
        value_str = str(value)

    # Replace baris yang ada, pertahankan komentar inline
    new_content = _re.sub(
        rf'^({key}\s*=\s*)(.+?)(\s*#.*)?$',
        rf'\g<1>{value_str}\3',
        content,
        flags=_re.MULTILINE
    )
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)

    # Reload config module
    import importlib
    importlib.reload(config)

    # Update variabel global di main.py
    import gopay as gopay_module
    global HEADLESS, DEBUG, MAX_THREADS, ADMIN_IDS
    HEADLESS = config.HEADLESS
    DEBUG = config.DEBUG
    MAX_THREADS = config.MAX_THREADS
    ADMIN_IDS = config.ADMIN_IDS
    gopay_module.MAX_THREADS = config.MAX_THREADS


# ========================= MAIN MENU KEYBOARD =========================

def main_menu_buttons():
    return [
        [Button.inline("🚀 Mulai", b"menu_mulai")],
        [Button.inline("📱 Kelola GoPay", b"menu_gopay")],
        [Button.inline("🌐 Show URL Webhook", b"menu_show_url")],
        [Button.inline("⚙️ Kelola Config", b"menu_config")],
    ]


def main_menu_text():
    gopay_data = load_gopay_from_file()
    gsuite_data = load_gsuite_from_file()
    return (
        "🤖 **GSUITE x GOPAY — Telegram Bot**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🖥 Browser : Chromium (Playwright)\n"
        f"👻 Headless: `{HEADLESS}` | 🐛 Debug: `{DEBUG}`\n"
        f"📧 GSuite  : **{len(gsuite_data)} akun**\n"
        f"📱 GoPay   : **{len(gopay_data)} akun**\n"
        f"🧵 Threads : **{MAX_THREADS}**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 Pilih menu di bawah:"
    )


# ========================= EXECUTE PROCESS =========================

def execute_process_sync(gsuite_data, gopay_data, num_threads, chat_id, loop):
    """Run the linking process (blocking, called in thread)."""
    import gopay as gopay_module
    global running_process, http_server, public_url_global

    start_time = time.time()

    pub = ensure_ngrok()
    gopay_module.public_url = pub if pub else ""
    ip = get_local_ip()
    base_url = pub if pub else f"http://{ip}:{PORT}"

    # Setup Queue
    gsuite_queue = queue.Queue()
    for email, password in gsuite_data:
        gsuite_queue.put((email, password))

    total_akun = len(gsuite_data)

    counters = {
        "berhasil": 0,
        "gagal": 0,
        "processed": 0,
        "gagal_akun": [],
        "berhasil_akun": [],
        "lock": Lock(),
    }

    def patched_worker(thread_id, gopay_phone, gopay_pin, gsuite_q, ctrs, wh_url):
        while True:
            try:
                gsuite_item = gsuite_q.get(timeout=1)
            except queue.Empty:
                break

            email, password = gsuite_item
            berhasil = False

            for attempt in range(1, MAX_RETRY + 1):
                update_status(thread_id, f"{info} {email} ({attempt}/{MAX_RETRY})")
                result = process_account(
                    email=email, password=password,
                    phone=gopay_phone, pin=gopay_pin,
                    thread_id=thread_id, webhook_url=wh_url,
                )
                if result:
                    with ctrs["lock"]:
                        ctrs["berhasil"] += 1
                        ctrs["berhasil_akun"].append(f"{email}|{password}")
                        ctrs["processed"] += 1
                    berhasil = True
                    break
                else:
                    time.sleep(5)

            if not berhasil:
                with ctrs["lock"]:
                    ctrs["gagal"] += 1
                    ctrs["gagal_akun"].append(f"{email}|{password}")
                    ctrs["processed"] += 1

            gsuite_q.task_done()

    init_dashboard(num_threads)

    workers = []
    for i in range(num_threads):
        phone, pin = gopay_data[i]
        wh_url = f"{base_url}/t{i+1}"
        t = Thread(target=patched_worker, args=(i + 1, phone, pin, gsuite_queue, counters, wh_url))
        t.start()
        workers.append(t)

    # Kirim progress ke telegram
    last_reported = 0
    while any(t.is_alive() for t in workers):
        with counters["lock"]:
            current = counters["processed"]
        if current != last_reported and current % 5 == 0:
            last_reported = current
            pct = int(current / total_akun * 100) if total_akun > 0 else 0
            asyncio.run_coroutine_threadsafe(
                bot.send_message(chat_id, f"Progress: {current}/{total_akun} ({pct}%)"),
                loop
            )
        time.sleep(2)

    for t in workers:
        t.join(timeout=10)

    elapsed = time.time() - start_time
    duration_str = format_duration(elapsed)

    # Save result file
    now = datetime.now()
    result_filename = f"result-{now.strftime('%d%m%Y-%H%M%S')}.txt"
    with open(result_filename, "w", encoding="utf-8") as f:
        f.write(f"GSUITE x GOPAY - RESULT\n")
        f.write(f"Waktu: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Durasi: {duration_str}\n")
        f.write(f"Total: {len(gsuite_data)}\n")
        f.write(f"Berhasil: {counters['berhasil']}\n")
        f.write(f"Gagal: {counters['gagal']}\n\n")
        if counters["berhasil_akun"]:
            f.write("BERHASIL:\n")
            for akun in counters["berhasil_akun"]:
                f.write(f"{akun}\n")
            f.write("\n")
        if counters["gagal_akun"]:
            f.write("GAGAL:\n")
            for akun in counters["gagal_akun"]:
                f.write(f"{akun}\n")

    if counters["gagal_akun"]:
        with open("gagal.txt", "w", encoding="utf-8") as f:
            for akun in counters["gagal_akun"]:
                f.write(akun + "\n")

    caption = (
        f"📊 **RESULT**\n"
        f"✅ Berhasil: {counters['berhasil']}\n"
        f"❌ Gagal: {counters['gagal']}\n"
        f"⏱ Durasi: {duration_str}"
    )

    async def send_result():
        await bot.send_file(
            chat_id,
            result_filename,
            caption=caption,
        )
        await bot.send_message(
            chat_id,
            "Proses selesai. Kembali ke menu utama:",
            buttons=main_menu_buttons(),
        )
        # BERSIHKAN FILE DARI SERVER SETELAH TERKIRIM
        if os.path.exists(result_filename):
            os.remove(result_filename)

    asyncio.run_coroutine_threadsafe(send_result(), loop)

    # --- KOSONGKAN STATUS GSUITE SETELAH SELESAI ---
    try:
        with open("gsuite.txt", "w", encoding="utf-8") as f:
            f.write("") # Mengosongkan isi file
    except Exception:
        pass

    # --- FIX NGROK 400 ERROR ---
    time.sleep(5) 

    try:
        from pyngrok import ngrok
        ngrok.kill()
    except Exception:
        pass
    
    try:
        if http_server:
            http_server.shutdown()
            http_server.server_close()
    except Exception:
        pass

    http_server = None
    public_url_global = ""
    with running_lock:
        running_process = False


# ========================= BOT SETUP =========================

bot = TelegramClient("bot_session", API_ID, API_HASH).start(bot_token=BOT_TOKEN)


def is_admin(event):
    return event.sender_id in ADMIN_IDS


@bot.on(events.NewMessage(pattern="/start"))
async def handler_start(event):
    if not is_admin(event):
        await event.respond("⛔ Akses ditolak.")
        return
    user_states.pop(event.chat_id, None)
    await event.respond(main_menu_text(), buttons=main_menu_buttons(), parse_mode="md")


@bot.on(events.CallbackQuery(data=b"menu_utama"))
async def handler_back_menu(event):
    if not is_admin(event):
        return
    user_states.pop(event.chat_id, None)
    await event.edit(main_menu_text(), buttons=main_menu_buttons(), parse_mode="md")


# ─── MULAI ───

@bot.on(events.CallbackQuery(data=b"menu_mulai"))
async def handler_mulai(event):
    if not is_admin(event):
        return
    global running_process

    with running_lock:
        if running_process:
            await event.answer("Proses sedang berjalan, tunggu hingga selesai.", alert=True)
            return

    gopay_data = load_gopay_from_file()
    if not gopay_data:
        await event.answer("gopay.txt kosong! Tambah GoPay dulu.", alert=True)
        return

    gsuite_data = load_gsuite_from_file()
    text = (
        "**MULAI PROSES**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"GSuite di file: **{len(gsuite_data)} akun**\n\n"
        "Pilih sumber data GSuite:"
    )
    # TOMBOL 'Dari file gsuite.txt' DIHAPUS
    buttons = [
        [Button.inline("Kirim file / text baru", b"mulai_input")],
        [Button.inline("Kembali", b"menu_utama")],
    ]
    await event.edit(text, buttons=buttons, parse_mode="md")


@bot.on(events.CallbackQuery(data=b"mulai_file"))
async def handler_mulai_file(event):
    if not is_admin(event):
        return
    global running_process

    gsuite_data = load_gsuite_from_file()
    if not gsuite_data:
        await event.answer("gsuite.txt kosong! Kirim file atau text dulu.", alert=True)
        return

    gopay_data = load_gopay_from_file()
    num_threads = min(len(gopay_data), MAX_THREADS)

    with running_lock:
        if running_process:
            await event.answer("Proses sedang berjalan!", alert=True)
            return
        running_process = True

    await event.edit(
        f"Memulai proses...\n"
        f"GSuite: {len(gsuite_data)} | GoPay: {len(gopay_data)} | Threads: {num_threads}",
        buttons=None, parse_mode="md"
    )

    loop = asyncio.get_event_loop()
    chat_id = event.chat_id

    Thread(
        target=execute_process_sync,
        args=(gsuite_data, gopay_data, num_threads, chat_id, loop),
        daemon=True
    ).start()


@bot.on(events.CallbackQuery(data=b"mulai_input"))
async def handler_mulai_input(event):
    if not is_admin(event):
        return
    user_states[event.chat_id] = "waiting_gsuite"
    await event.edit(
        "**Kirim data GSuite:**\n\n"
        "Bisa kirim **file .txt** atau ketik langsung format:\n"
        "`email|password`\n"
        "(satu per baris)\n\n"
        "Ketik /cancel untuk batal.",
        buttons=None, parse_mode="md"
    )


# ─── KELOLA GOPAY ───

def gopay_list_text():
    gopay_data = load_gopay_from_file()
    lines = ""
    if gopay_data:
        for i, (phone, pin) in enumerate(gopay_data, 1):
            lines += f"  {i}. `{phone}` | `{'*' * len(pin)}`\n"
    else:
        lines = "  (kosong)\n"
    return (
        f"📱 **DATA GOPAY ({len(gopay_data)} akun)**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{lines}"
    )


@bot.on(events.CallbackQuery(data=b"menu_gopay"))
async def handler_gopay_menu(event):
    if not is_admin(event):
        return
    gopay_data = load_gopay_from_file()
    buttons = [
        [Button.inline("➕ Add GoPay", b"gopay_add")],
    ]
    if gopay_data:
        for i, (phone, _) in enumerate(gopay_data):
            buttons.append([Button.inline(f"🗑 Hapus {phone}", f"gopay_del_{i}".encode())])
    buttons.append([Button.inline("🔙 Kembali", b"menu_utama")])

    await event.edit(gopay_list_text(), buttons=buttons, parse_mode="md")


@bot.on(events.CallbackQuery(data=b"gopay_add"))
async def handler_gopay_add(event):
    if not is_admin(event):
        return
    user_states[event.chat_id] = "waiting_gopay"
    await event.edit(
        gopay_list_text() + "\n"
        "Kirim data GoPay baru format:\n"
        "`nohp|pin`\n"
        "(satu per baris)\n\n"
        "Ketik /cancel untuk batal.",
        buttons=None, parse_mode="md"
    )


@bot.on(events.CallbackQuery(pattern=rb"gopay_del_(\d+)"))
async def handler_gopay_delete(event):
    if not is_admin(event):
        return
    idx = int(event.pattern_match.group(1))
    gopay_data = load_gopay_from_file()

    if idx < 0 or idx >= len(gopay_data):
        await event.answer("Data tidak ditemukan.", alert=True)
        return

    removed_phone, _ = gopay_data[idx]
    gopay_data.pop(idx)

    with open("gopay.txt", "w", encoding="utf-8") as f:
        for phone, pin in gopay_data:
            f.write(f"{phone}|{pin}\n")

    await event.answer(f"{removed_phone} dihapus!")

    # Refresh menu
    buttons = [
        [Button.inline("➕ Add GoPay", b"gopay_add")],
    ]
    if gopay_data:
        for i, (phone, _) in enumerate(gopay_data):
            buttons.append([Button.inline(f"🗑 Hapus {phone}", f"gopay_del_{i}".encode())])
    buttons.append([Button.inline("🔙 Kembali", b"menu_utama")])

    await event.edit(gopay_list_text(), buttons=buttons, parse_mode="md")


# ─── KELOLA CONFIG ───

def config_text():
    return (
        "⚙️ **KONFIGURASI**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧵 MAX_THREADS : `{read_config_value('MAX_THREADS')}`\n"
        f"👻 HEADLESS    : `{read_config_value('HEADLESS')}`\n"
        f"🐛 DEBUG       : `{read_config_value('DEBUG')}`\n"
        f"👤 ADMIN_IDS   : `{read_config_value('ADMIN_IDS')}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Pilih yang mau diubah:"
    )


def config_buttons():
    headless = read_config_value('HEADLESS')
    debug = read_config_value('DEBUG')
    return [
        [Button.inline(f"🧵 MAX_THREADS: {read_config_value('MAX_THREADS')}", b"cfg_threads")],
        [Button.inline(f"👻 HEADLESS: {'ON' if headless else 'OFF'}", b"cfg_headless")],
        [Button.inline(f"🐛 DEBUG: {'ON' if debug else 'OFF'}", b"cfg_debug")],
        [Button.inline("👤 Edit ADMIN_IDS", b"cfg_admins")],
        [Button.inline("🔙 Kembali", b"menu_utama")],
    ]


@bot.on(events.CallbackQuery(data=b"menu_config"))
async def handler_config_menu(event):
    if not is_admin(event):
        return
    await event.edit(config_text(), buttons=config_buttons(), parse_mode="md")


@bot.on(events.CallbackQuery(data=b"cfg_headless"))
async def handler_cfg_headless(event):
    if not is_admin(event):
        return
    current = read_config_value('HEADLESS')
    write_config_value('HEADLESS', not current)
    await event.answer(f"HEADLESS → {'OFF' if current else 'ON'}")
    await event.edit(config_text(), buttons=config_buttons(), parse_mode="md")


@bot.on(events.CallbackQuery(data=b"cfg_debug"))
async def handler_cfg_debug(event):
    if not is_admin(event):
        return
    current = read_config_value('DEBUG')
    write_config_value('DEBUG', not current)
    await event.answer(f"DEBUG → {'OFF' if current else 'ON'}")
    await event.edit(config_text(), buttons=config_buttons(), parse_mode="md")


@bot.on(events.CallbackQuery(data=b"cfg_threads"))
async def handler_cfg_threads(event):
    if not is_admin(event):
        return
    user_states[event.chat_id] = "waiting_cfg_threads"
    await event.edit(
        f"🧵 **MAX_THREADS** saat ini: `{read_config_value('MAX_THREADS')}`\n\n"
        "Kirim angka baru (1-50):\n\n"
        "Ketik /cancel untuk batal.",
        buttons=None, parse_mode="md"
    )


@bot.on(events.CallbackQuery(data=b"cfg_admins"))
async def handler_cfg_admins(event):
    if not is_admin(event):
        return
    user_states[event.chat_id] = "waiting_cfg_admins"
    current = read_config_value('ADMIN_IDS')
    ids_str = "\n".join(f"  - `{uid}`" for uid in current)
    await event.edit(
        f"👤 **ADMIN_IDS** saat ini:\n{ids_str}\n\n"
        "Kirim daftar user ID baru (satu per baris atau pisah koma):\n\n"
        "Ketik /cancel untuk batal.",
        buttons=None, parse_mode="md"
    )


# ─── SHOW URL WEBHOOK ───

@bot.on(events.CallbackQuery(data=b"menu_show_url"))
async def handler_show_url(event):
    if not is_admin(event):
        return
    await event.answer("Generating webhook URL...")

    urls, base = get_webhook_urls()
    if urls is None:
        await event.edit(
            f"**Error:** {base}",
            buttons=[[Button.inline("Kembali", b"menu_utama")]],
            parse_mode="md"
        )
        return

    text = (
        "🌐 **WEBHOOK URL**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Set URL berikut di Notif Forwarder per HP:\n\n"
    )
    for label, url in urls:
        text += f"📱 {label}:\n`{url}`\n\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    await event.edit(
        text,
        buttons=[[Button.inline("🔙 Kembali", b"menu_utama")]],
        parse_mode="md"
    )


# ─── HANDLE TEXT & FILE INPUT ───

@bot.on(events.NewMessage(pattern="/cancel"))
async def handler_cancel(event):
    if not is_admin(event):
        return
    state = user_states.pop(event.chat_id, None)
    if state:
        await event.respond("Dibatalkan.", buttons=main_menu_buttons(), parse_mode="md")
    else:
        await event.respond(main_menu_text(), buttons=main_menu_buttons(), parse_mode="md")


@bot.on(events.NewMessage())
async def handler_message(event):
    if not is_admin(event):
        return
    # Skip commands
    if event.text and event.text.startswith("/"):
        return

    chat_id = event.chat_id
    state = user_states.get(chat_id)

    if state == "waiting_gsuite":
        await handle_gsuite_input(event)
    elif state == "waiting_gopay":
        await handle_gopay_input(event)
    elif state == "waiting_cfg_threads":
        await handle_cfg_threads_input(event)
    elif state == "waiting_cfg_admins":
        await handle_cfg_admins_input(event)


async def handle_gsuite_input(event):
    global running_process
    chat_id = event.chat_id
    text_content = ""

    # Cek apakah ada file yang dikirim
    if event.file:
        await event.respond("Mengunduh file...")
        file_bytes = await event.download_media(bytes)
        if file_bytes:
            text_content = file_bytes.decode("utf-8", errors="replace")
    elif event.text:
        text_content = event.text

    if not text_content:
        await event.respond("Tidak ada data. Kirim file .txt atau ketik langsung format `email|password`.", parse_mode="md")
        return

    gsuite_data = parse_gsuite_data(text_content)
    if not gsuite_data:
        await event.respond("Tidak ada data valid. Format: `email|password` (satu per baris).", parse_mode="md")
        return

    # Simpan ke gsuite.txt
    with open("gsuite.txt", "w", encoding="utf-8") as f:
        for email, password in gsuite_data:
            f.write(f"{email}|{password}\n")

    user_states.pop(chat_id, None)

    gopay_data = load_gopay_from_file()
    if not gopay_data:
        await event.respond(
            f"**{len(gsuite_data)} akun GSuite** diterima dan disimpan.\n\n"
            "Tapi gopay.txt kosong! Tambah GoPay dulu.",
            buttons=main_menu_buttons(), parse_mode="md"
        )
        return

    num_threads = min(len(gopay_data), MAX_THREADS)

    buttons = [
        [Button.inline(f"Mulai ({len(gsuite_data)} gsuite, {len(gopay_data)} gopay)", b"mulai_file")],
        [Button.inline("Kembali ke menu", b"menu_utama")],
    ]
    await event.respond(
        f"**{len(gsuite_data)} akun GSuite** diterima dan disimpan ke gsuite.txt.\n"
        f"GoPay: {len(gopay_data)} akun | Threads: {num_threads}\n\n"
        "Klik tombol di bawah untuk mulai proses:",
        buttons=buttons, parse_mode="md"
    )


async def handle_gopay_input(event):
    chat_id = event.chat_id
    text_content = ""

    if event.file:
        file_bytes = await event.download_media(bytes)
        if file_bytes:
            text_content = file_bytes.decode("utf-8", errors="replace")
    elif event.text:
        text_content = event.text

    if not text_content:
        await event.respond("Tidak ada data. Kirim format `nohp|pin` (satu per baris).", parse_mode="md")
        return

    new_entries = []
    for line in text_content.strip().splitlines():
        line = line.strip()
        if line and "|" in line:
            parts = line.split("|", 1)
            phone = parts[0].strip()
            pin = parts[1].strip()
            if phone and pin:
                new_entries.append((phone, pin))

    if not new_entries:
        await event.respond("Tidak ada data valid. Format: `nohp|pin` (satu per baris).", parse_mode="md")
        return

    # Append ke gopay.txt
    with open("gopay.txt", "a", encoding="utf-8") as f:
        for phone, pin in new_entries:
            f.write(f"{phone}|{pin}\n")

    user_states.pop(chat_id, None)

    await event.respond(
        f"**{len(new_entries)} akun GoPay** ditambahkan ke gopay.txt.",
        buttons=main_menu_buttons(), parse_mode="md"
    )


async def handle_cfg_threads_input(event):
    chat_id = event.chat_id
    text = (event.text or "").strip()

    try:
        val = int(text)
        if val < 1 or val > 50:
            raise ValueError
    except ValueError:
        await event.respond("❌ Masukkan angka 1-50.", parse_mode="md")
        return

    write_config_value('MAX_THREADS', val)
    user_states.pop(chat_id, None)
    await event.respond(
        f"✅ MAX_THREADS diubah ke `{val}`",
        buttons=config_buttons(), parse_mode="md"
    )


async def handle_cfg_admins_input(event):
    chat_id = event.chat_id
    text = (event.text or "").strip()

    # Parse: bisa koma atau newline separated
    raw = _re.split(r'[,\n]+', text)
    ids = []
    for item in raw:
        item = item.strip()
        if item.isdigit():
            ids.append(int(item))

    if not ids:
        await event.respond("❌ Tidak ada ID valid. Kirim angka user ID (pisah koma atau baris baru).", parse_mode="md")
        return

    # Pastikan user sendiri tetap ada di list agar tidak terkunci
    if event.sender_id not in ids:
        ids.insert(0, event.sender_id)
        await event.respond(f"⚠️ ID kamu (`{event.sender_id}`) otomatis ditambahkan agar tidak terkunci.", parse_mode="md")

    write_config_value('ADMIN_IDS', ids)
    user_states.pop(chat_id, None)
    ids_str = ", ".join(str(i) for i in ids)
    await event.respond(
        f"✅ ADMIN_IDS diubah ke `[{ids_str}]`",
        buttons=config_buttons(), parse_mode="md"
    )


# ========================= RUN =========================

def main():
    print("Bot Telegram GSUITE x GOPAY aktif...")
    print(f"Headless: {HEADLESS} | Debug: {DEBUG} | Max Threads: {MAX_THREADS}")
    bot.run_until_disconnected()


if __name__ == "__main__":
    main()
