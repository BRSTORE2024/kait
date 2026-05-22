_N='application/json'
_M='Content-Type'
_L='t(\\d+)'
_K='gagal'
_J='berhasil'
_I='lock'
_H='timestamp'
_G='gagal_akun'
_F='otp'
_E='utf-8'
_D=None
_C='='
_B=False
_A=True
from playwright.sync_api import sync_playwright
try:from playwright_stealth import stealth_sync;HAS_STEALTH=_A
except ImportError:HAS_STEALTH=_B
from colorama import Fore,Style
from datetime import datetime
from http.server import HTTPServer,BaseHTTPRequestHandler
from threading import Thread,Lock
from config import HEADLESS,DEBUG,MAX_THREADS,NGROK_EXE_PATH,NGROK_CONFIG_PATH,NGROK_MANUAL_AUTH
import json,time,os,re,sys,socket,queue
PORT=5000
MAX_RETRY=3
OTP_TIMEOUT=15
info=f"{Fore.CYAN}[INFO]{Style.RESET_ALL}"
success=f"{Fore.GREEN}[OK]{Style.RESET_ALL}"
failed=f"{Fore.RED}[FAIL]{Style.RESET_ALL}"
warning=f"{Fore.YELLOW}[WARN]{Style.RESET_ALL}"
otp_storage={}
otp_lock=Lock()
print_lock=Lock()
public_url=''
IS_LINUX=sys.platform.startswith('linux')
thread_status={}
num_dashboard_threads=0
dashboard_initialized=_B
def init_dashboard(num_threads):
	'Inisialisasi dashboard dengan jumlah thread.';A=num_threads;global num_dashboard_threads,dashboard_initialized;num_dashboard_threads=A;dashboard_initialized=_A
	if DEBUG:
		with print_lock:print(f"\n[DEBUG MODE] Dashboard disabled, plain log aktif.");print(f"[DEBUG MODE] Threads: {A}");sys.stdout.flush()
		return
	with print_lock:
		print(f"\n{_C*60}");print(f"  THREAD STATUS DASHBOARD");print(f"{_C*60}")
		for B in range(1,A+1):thread_status[B]='Menunggu...';print(f"  T{B}: Menunggu...")
		print(f"{_C*60}");sys.stdout.flush()
def update_status(thread_id,msg):
	'Update status satu thread. DEBUG=True: plain log, DEBUG=False: dashboard.';B=msg;A=thread_id
	if DEBUG:
		with print_lock:print(f"  T{A}: {B}");sys.stdout.flush()
		return
	if not dashboard_initialized:
		with print_lock:print(f"  T{A}: {B}");sys.stdout.flush()
		return
	thread_status[A]=B
	with print_lock:
		C=num_dashboard_threads-A+1;sys.stdout.write(f"[{C}A");sys.stdout.write(f"[2K");D=B[:56];sys.stdout.write(f"  T{A}: {D}\n")
		if C>1:sys.stdout.write(f"[{C-1}B")
		sys.stdout.flush()
def safe_print(msg):
	'Legacy safe_print - tetap ada untuk backward compatibility.'
	with print_lock:print(msg);sys.stdout.flush()
def extract_otp(text):
	B=['(\\d{6})\\s+adalah\\s+kode','kode\\s*(?:verifikasi|otp|pemulihan|sandi)\\s*[:.]?\\s*(\\d{4,6})','(\\d{6})']
	for C in B:
		A=re.search(C,text,re.IGNORECASE)
		if A:return A.group(1)
	return''
def get_local_ip():
	try:A=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);A.connect(('8.8.8.8',80));B=A.getsockname()[0];A.close();return B
	except Exception:return'127.0.0.1'
class WebhookHandler(BaseHTTPRequestHandler):
	def do_POST(B):
		O='app_name';N='package';M='text';L='title';global otp_storage;F=B.rfile.read(int(B.headers.get('Content-Length',0))).decode(_E,errors='replace')
		try:A=json.loads(F)
		except Exception:A={'raw':F}
		P=B.path.strip('/');C=0;G=re.match(_L,P)
		if G:C=int(G.group(1))
		D=A.get(L,'')or'';H=A.get(M,'')or'';E=A.get('big_text','')or'';Q=A.get('package_name','')or A.get(N,'')or'';I=A.get(O,'')or'';W=A.get('rule_name','')or'';J=E if E else H;R=f"{D} {H} {E} {I}".lower();S=any(A in R for A in['gopay','gojek','go-pay','kode verifikasi','kode pemulihan'])
		if S:
			T=extract_otp(J)or extract_otp(D);K={_H:datetime.now().strftime('%Y-%m-%d %H:%M:%S'),L:D,M:J,_F:T,N:Q,O:I,'thread_id':C}
			with otp_lock:otp_storage[C]=K
			try:
				U=f"gopay_otp_t{C}.json"
				with open(U,'w',encoding=_E)as V:json.dump([K],V,indent=2,ensure_ascii=_B)
			except Exception:pass
		B.send_response(200);B.send_header(_M,_N);B.end_headers();B.wfile.write(json.dumps({'ok':_A}).encode())
	def do_GET(A):D=A.path.strip('/');B=re.match(_L,D);C=int(B.group(1))if B else 0;E=otp_storage.get(C,{});A.send_response(200);A.send_header(_M,_N);A.end_headers();A.wfile.write(json.dumps({'status':'running','thread':C,'last_otp':E}).encode())
	def log_message(A,*B):0
def wait_for_new_otp(old_timestamp,timeout=OTP_TIMEOUT,thread_id=0):
	'Tunggu OTP baru yang timestamp-nya berbeda dari old_timestamp untuk thread tertentu.';E=old_timestamp;B=thread_id;global otp_storage;I=time.time();F=f"gopay_otp_t{B}.json"
	while time.time()-I<timeout:
		with otp_lock:C=otp_storage.get(B,{})
		G=C.get(_H,'')
		if G and G!=E and C.get(_F):return C[_F]
		try:
			if os.path.exists(F):
				with open(F,'r',encoding=_E)as J:
					D=json.load(J)
					if isinstance(D,list)and D:
						A=D[-1];H=A.get(_H,'')
						if H and H!=E and A.get(_F):
							with otp_lock:otp_storage[B]=A
							return A[_F]
		except Exception:pass
		time.sleep(2)
def start_ngrok(port):
	'Start ngrok tunnel dan return public URL';C='http'
	try:
		from pyngrok import ngrok as A;from pyngrok.conf import PyngrokConfig as D;E=NGROK_CONFIG_PATH and os.path.exists(NGROK_CONFIG_PATH)
		if not E and NGROK_MANUAL_AUTH:A.set_auth_token(NGROK_MANUAL_AUTH)
		if NGROK_EXE_PATH or NGROK_CONFIG_PATH:F=D(ngrok_path=NGROK_EXE_PATH or _D,config_path=NGROK_CONFIG_PATH or _D);B=A.connect(addr=port,proto=C,pyngrok_config=F)
		else:B=A.connect(addr=port,proto=C)
		return B.public_url
	except ImportError:safe_print(failed+'pyngrok belum terinstall. Jalankan: pip install pyngrok');return
	except Exception as G:safe_print(failed+f"Ngrok error: {G}");safe_print(warning+'Cek path ngrok.exe dan file ngrok.yml');return
def process_account(email,password,phone,pin,thread_id=0,webhook_url=''):
	A8='Simpan dan lanjutkan';A7='[^a-zA-Z ]';A6='input[type="text"]';A5='#phone-number-input';A4='iframe[name="hnyNZeIframe"]';A3='input[type="password"]';A2='Berikutnya';A1='input[type="email"]';A0='domcontentloaded';z='Accept-Language';n=phone;m='visible';l='https://play.google.com/store/paymentmethods?hl=id';k='id-ID';b='GoPay User';T=password;N='Enter';M='button';E=email;A=thread_id;global otp_storage;update_status(A,f"{info} Login {E}")
	try:
		with open('button.json','r',encoding=_E)as H:A9=json.load(H)
	except FileNotFoundError:A9={}
	U=_D;V=_D
	try:
		U=sync_playwright().start();V=U.chromium.launch(headless=HEADLESS,args=['--disable-web-security','--disable-features=site-per-process','--disable-blink-features=AutomationControlled','--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--disable-software-rasterizer','--disable-extensions','--disable-background-networking','--disable-default-apps','--disable-sync','--disable-translate','--metrics-recording-only','--no-first-run','--incognito','--lang=id-ID','--blink-settings=imagesEnabled=false']);AA=V.new_context(locale=k,viewport={'width':1280,'height':720},extra_http_headers={z:k},bypass_csp=_A);B=AA.new_page()
		if HAS_STEALTH:stealth_sync(B)
		try:
			update_status(A,f"{info} Buka Google Play...");B.set_extra_http_headers({z:k});B.goto(l,timeout=300000);B.wait_for_load_state(A0);time.sleep(2);update_status(A,f"{info} Input email...")
			try:B.get_by_label('Email atau nomor telepon').fill(E)
			except:B.wait_for_selector(A1,timeout=30000);B.locator(A1).fill(E)
			update_status(A,f"{info} Email diisi, klik Berikutnya...")
			try:B.get_by_role(M,name=A2).click(timeout=4000)
			except:B.keyboard.press(N)
			time.sleep(3);update_status(A,f"{info} Input password...");B.wait_for_selector(A3,timeout=10000)
			try:B.get_by_label('Masukkan sandi').fill(T)
			except:B.locator(A3).fill(T)
			update_status(A,f"{info} Password diisi, klik Berikutnya...")
			try:B.get_by_role(M,name=A2).click(timeout=4000)
			except:B.keyboard.press(N)
			time.sleep(3)
			try:B.locator('input[name="confirm"][value="Saya mengerti"]').click(timeout=4000);update_status(A,f"{success} Klik 'Saya mengerti'")
			except:
				try:B.locator('input[name="confirm"]').click(timeout=3000);update_status(A,f"{success} Klik confirm")
				except:update_status(A,f"{warning} Tombol confirm tidak ada, lanjut...")
			try:
				B.wait_for_url('**/passkeyenrollment**',timeout=8000);time.sleep(2)
				try:B.get_by_text('Lain kali').click(timeout=5000)
				except:B.get_by_text('Not now').click(timeout=5000)
			except:pass
			try:B.wait_for_url(l,timeout=15000)
			except:pass
			B.wait_for_load_state(A0,timeout=60000);time.sleep(3);c=B.evaluate("() => {\n                const cards = document.querySelectorAll('div.HgYqic');\n                return Array.from(cards).some(el => el.textContent.includes('••••'));\n            }")
			if c:update_status(A,f"{success} GoPay sudah terpasang: {E}");return'already_linked'
			update_status(A,f"{info} Klik Tambahkan GoPay...")
			try:B.get_by_role(M,name='Tambahkan GoPay').click(timeout=10000);update_status(A,f"{success} Klik GoPay via role button")
			except:
				try:
					o=B.evaluate("() => {\n                        const elements = document.querySelectorAll('*');\n                        for (const el of elements) {\n                            if (el.textContent.trim() === 'Tambahkan GoPay' && el.offsetParent !== null) {\n                                el.click();\n                                return 'clicked: ' + el.tagName + '.' + el.className;\n                            }\n                        }\n                        for (const el of elements) {\n                            if (el.childElementCount === 0 && el.textContent.trim().includes('GoPay') && el.offsetParent !== null) {\n                                el.click();\n                                return 'partial: ' + el.tagName + '.' + el.className;\n                            }\n                        }\n                        return 'not_found';\n                    }")
					if'not_found'not in o:update_status(A,f"{success} Klik GoPay via JS: {o[:50]}")
					else:B.screenshot(path=f"debug_gopay_btn_t{A}.png");raise Exception('Tombol GoPay tidak ditemukan')
				except Exception as C:
					if'tidak ditemukan'in str(C):raise
					B.screenshot(path=f"debug_gopay_btn_t{A}.png");raise Exception(f"Tombol GoPay gagal diklik: {C}")
			update_status(A,f"{info} Tunggu iframe payment...");time.sleep(3);p=_B
			for P in range(10):
				try:
					AB=B.locator(A4)
					if AB.count()>0:p=_A;break
				except:pass
				time.sleep(2)
				if P%2==1:update_status(A,f"{info} Tunggu iframe... ({(P+1)*2}s)")
			if not p:
				B.screenshot(path=f"debug_lanjutkan_t{A}.png")
				for(q,D)in enumerate(B.frames):update_status(A,f"{info} Frame[{q}]: {D.url[:60]}")
				raise Exception('iframe hnyNZeIframe tidak muncul')
			update_status(A,f"{info} Klik Lanjutkan di iframe...")
			with B.expect_popup()as AC:
				r=B.locator(A4).content_frame
				try:r.get_by_role(M,name='Lanjutkan').click(timeout=10000)
				except:r.get_by_role(M,name='Continue').click(timeout=5000)
			update_status(A,f"{success} Klik Lanjutkan berhasil");time.sleep(5);O=AC.value;O.wait_for_load_state('load',timeout=30000)
			try:O.wait_for_url('**/app/authorize**',timeout=30000)
			except:pass
			O.wait_for_load_state('load',timeout=30000);update_status(A,f"{info} Cari form GoPay...");I=_D
			for(q,D)in enumerate(O.frames):
				try:
					J=D.locator(A5)
					if J.count()>0:I=D;break
				except:continue
			if I is _D:update_status(A,f"{failed} Form GoPay tidak ditemukan!");return _B
			update_status(A,f"{info} Input HP {n}...");d=I.locator(A5);d.click(timeout=5000);d.fill('');d.press_sequentially(n,delay=50);time.sleep(1);I.locator('button#submit[value="phone-number"]:not([disabled])').click(timeout=10000)
			with otp_lock:AD=otp_storage.get(A,{})
			AE=AD.get(_H,'');update_status(A,f"{info} Menunggu OTP...");time.sleep(5);e=wait_for_new_otp(AE,thread_id=A)
			if e:update_status(A,f"{success} OTP: {e} - Input...");f=I.locator('#firstInput');f.wait_for(state=m,timeout=10000);f.click();f.press_sequentially(e,delay=50)
			else:update_status(A,f"{failed} OTP timeout!");return _B
			time.sleep(1);I.locator('button[value="validate-otp"]').click(timeout=10000);time.sleep(2);update_status(A,f"{info} Input PIN...");g=I.locator('input[type="password"].pin');g.wait_for(state=m,timeout=10000);g.click();g.press_sequentially(pin,delay=50);time.sleep(1);I.locator('button[value="validate-pin"]').click(timeout=10000);time.sleep(3);update_status(A,f"{info} Mencari halaman konfirmasi...");W=_B;h=_D;i=_B;D=_D;s=['input[placeholder="Nama lengkap"]','input[placeholder*="Nama"]','input[placeholder*="Name"]','#c1','input[name="RECIPIENT"]','input[autocomplete="name"]','input[type="search"]',A6]
			for P in range(20):
				t=list(B.frames)
				try:t+=list(O.frames)
				except:pass
				for H in t:
					for X in s:
						try:
							J=H.locator(X).first
							if J.count()>0 and J.is_visible(timeout=300):W=_A;h=H;update_status(A,f"{success} Form nama ditemukan! sel={X} frame={H.url[:40]}");break
						except:continue
					if W:break
				if W:break
				try:
					D=B.frame(name='hnyNZeIframe')
					if D:i=_A;update_status(A,f"{success} Iframe hnyNZeIframe ditemukan");break
				except:pass
				time.sleep(2)
				if P%2==1:update_status(A,f"{info} Menunggu konfirmasi... ({(P+1)*2}s)")
			if W:
				G=E.split('@')[0];G=re.sub(A7,' ',G).strip()or'User';update_status(A,f"{info} Isi nama: {G}");F=_D
				for X in s:
					try:
						J=h.locator(X).first
						if J.count()>0 and J.is_visible(timeout=500):F=J;break
					except:continue
				if F:
					try:
						F.click(timeout=5000);time.sleep(.3);F.press_sequentially(G,delay=80);time.sleep(.8);K=F.input_value()
						if K and len(K.strip())>0:update_status(A,f"{success} Nama terisi: '{K}'")
						else:update_status(A,f"{warning} Nama tidak terisi!")
					except Exception as C:update_status(A,f"{warning} Gagal isi nama: {str(C)[:50]}")
				else:update_status(A,f"{warning} Input nama tidak ditemukan di frame!")
				Q=_B
				for j in[B,O,h]:
					try:j.get_by_role(M,name=A8).click(timeout=5000);Q=_A;update_status(A,f"{success} Klik Simpan dan lanjutkan");break
					except:continue
				if not Q:
					update_status(A,f"{warning} Tombol Simpan tidak ditemukan, coba Enter...")
					try:B.keyboard.press(N)
					except:pass
				time.sleep(3)
			if i:
				u=_B
				try:u=D.evaluate("() => !!document.querySelector('#c1')")
				except:pass
				if u:
					G=E.split('@')[0];G=re.sub(A7,' ',G).strip()or'User';update_status(A,f"{info} Isi nama: {G}");F=D.locator('#c1');F.wait_for(state=m,timeout=10000);F.click(timeout=5000);time.sleep(.5);F.press_sequentially(G,delay=80);time.sleep(.8);K=F.input_value()
					if K and len(K.strip())>0:update_status(A,f"{success} Nama terisi: '{K}'")
					else:update_status(A,f"{warning} Nama tidak terisi, lanjut...")
					Q=_B
					for j in[B,D]:
						try:j.get_by_role(M,name=A8).click(timeout=8000);Q=_A;update_status(A,f"{success} Klik Simpan dan lanjutkan");break
						except:continue
					if not Q:update_status(A,f"{warning} Tombol Simpan tidak ditemukan, coba Enter...");B.keyboard.press(N)
					time.sleep(3)
				else:
					update_status(A,f"{info} Mengisi nama di iframe...")
					try:L=D.get_by_label('Name');L.click(timeout=5000);L.fill(b);L.press(N);update_status(A,f"{success} Nama diisi di iframe")
					except:
						try:L=D.get_by_label('Nama');L.click(timeout=5000);L.fill(b);L.press(N);update_status(A,f"{success} Nama diisi di iframe")
						except Exception as C:update_status(A,f"{warning} Gagal isi nama di iframe: {str(C)[:30]}")
					time.sleep(3)
				try:B.get_by_role('link',name='Edit metode pembayaran').click(timeout=5000);time.sleep(1);update_status(A,f"{success} GoPay linked: {E}")
				except:update_status(A,f"{warning} Tombol edit metode tidak muncul, tapi proses mungkin berhasil")
			else:
				update_status(A,f"{warning} Iframe tidak muncul, mencoba mode cadangan...")
				try:B.screenshot(path=f"debug_fallback_t{A}.png")
				except:pass
				Y=_B;AF=[A6,'input[name*="name" i]','input[name*="nama" i]','input[placeholder*="name" i]','input[placeholder*="nama" i]','input[id*="name" i]','input[id*="nama" i]','[aria-label*="Name" i]','[aria-label*="Nama" i]']
				for Z in AF:
					try:
						a=B.locator(Z).first
						if a.count()>0:a.click(timeout=3000);a.fill('');a.fill(b);update_status(A,f"{success} Nama diisi via selector: {Z[:40]}");Y=_A;break
					except:continue
				if Y:
					AG=['button:has-text("Simpan")','button:has-text("Simpan dan lanjutkan")','button:has-text("Save")','button:has-text("Save and continue")','button:has-text("Lanjutkan")','button:has-text("Continue")','[role="button"]:has-text("Simpan")','[role="button"]:has-text("Lanjutkan")'];v=_B
					for Z in AG:
						try:
							w=B.locator(Z).first
							if w.count()>0:w.click(timeout=5000);update_status(A,f"{success} Klik tombol Simpan/Lanjutkan");v=_A;time.sleep(3);break
						except:continue
					if not v:
						try:B.keyboard.press(N);update_status(A,f"{info} Tekan Enter untuk submit");time.sleep(3)
						except:pass
				if not Y:
					try:
						AH=B.content()
						if any(A in AH.lower()for A in['nama','name','billing','pemilik']):
							update_status(A,f"{info} Mendeteksi form nama, mencoba interaksi manual...");R=B.locator('input:visible');x=R.count()
							if x>0:
								for S in range(x):
									y=R.nth(S).get_attribute('type')
									if y and y!='password':R.nth(S).click(timeout=3000);R.nth(S).fill('');R.nth(S).fill(b);update_status(A,f"{success} Mengisi input field #{S+1}");Y=_A;break
					except Exception as C:update_status(A,f"{warning} Error deteksi form: {str(C)[:30]}")
				time.sleep(3)
				try:
					B.wait_for_url(l,timeout=10000);c=B.evaluate("() => {\n                        const cards = document.querySelectorAll('div.HgYqic');\n                        return Array.from(cards).some(el => el.textContent.includes('••••'));\n                    }")
					if c:update_status(A,f"{success} GoPay linked via mode cadangan: {E}")
					else:update_status(A,f"{warning} Link belum terkonfirmasi, cek manual")
				except:update_status(A,f"{warning} Tidak bisa verifikasi status link")
			with open('gsuitexGoPay.txt','a')as H:
				if i:H.write(f"{E}|{T}\n")
				else:H.write(f"{E}|{T} (via mode cadangan)\n")
			return _A
		except Exception as C:update_status(A,f"{failed} Error: {str(C)[:40]}");return _B
	except Exception as C:safe_print(failed+f"[Thread-{A}] Error membuat browser: {C}");return _B
	finally:
		try:
			if V:V.close()
		except:pass
		try:
			if U:U.stop()
		except:pass
def worker(thread_id,gopay_phone,gopay_pin,gsuite_queue,counters,webhook_url):
	'\n    Worker function for each thread.\n    Sekarang TIDAK perlu start server sendiri, semua pakai 1 server + path routing.\n    ';E=gsuite_queue;D=gopay_phone;B=counters;A=thread_id
	while _A:
		try:H=E.get(timeout=1)
		except queue.Empty:update_status(A,f"{success} Selesai - idle");break
		C,I=H;F=_B
		for G in range(1,MAX_RETRY+1):
			update_status(A,f"{info} {C} (percobaan {G}/{MAX_RETRY})");J=process_account(email=C,password=I,phone=D,pin=gopay_pin,thread_id=A,webhook_url=webhook_url)
			if J:
				with B[_I]:B[_J]+=1
				F=_A;break
			else:update_status(A,f"{warning} Gagal #{G}, retry 5s...");time.sleep(5)
		if not F:
			with B[_I]:B[_K]+=1;B[_G].append(f"{C} | {D}")
			update_status(A,f"{failed} {C} gagal {MAX_RETRY}x")
		E.task_done()
def main():
	Q='gopay.txt';P='gsuite.txt';E='|';global public_url;print(f"\n{_C*55}");print('  GSUITE x GOPAY - AUTO LINK (NGROK + PATH ROUTING)');print(f"{_C*55}");print(f"  Browser: Chromium (Playwright) | Headless: {HEADLESS}")
	if not os.path.exists(P):print(failed+'File gsuite.txt tidak ditemukan!');print(info+'Buat file gsuite.txt dengan format: email|password (satu per baris)');sys.exit(1)
	if not os.path.exists(Q):print(failed+'File gopay.txt tidak ditemukan!');print(info+'Buat file gopay.txt dengan format: nomor|pin (satu per baris)');sys.exit(1)
	with open(P,'r',encoding=_E)as C:F=[A.strip()for A in C if A.strip()and E in A]
	with open(Q,'r',encoding=_E)as C:D=[A.strip()for A in C if A.strip()and E in A]
	if not F:print(failed+'gsuite.txt kosong atau format salah! Format: email|password');sys.exit(1)
	if not D:print(failed+'gopay.txt kosong atau format salah! Format: nomor|pin');sys.exit(1)
	H=min(len(D),MAX_THREADS);print(info+f"GSuite Accounts : {len(F)}");print(info+f"GoPay Accounts  : {len(D)}");print(info+f"Threads         : {H}");L=HTTPServer(('0.0.0.0',PORT),WebhookHandler);Thread(target=L.serve_forever,daemon=_A).start();print(success+f"OTP Listener aktif di port {PORT}");print(info+'Starting ngrok tunnel...');public_url=start_ngrok(PORT);I=get_local_ip();print(f"\n{_C*55}")
	if public_url:print(f"  📡 NGROK AKTIF!");print(f"  🌐 Public URL: {public_url}")
	else:print(f"  ⚠️  Ngrok gagal, pakai local IP");print(f"  🏠 Local URL: http://{I}:{PORT}")
	print(f"{"─"*55}");print(f"  📱 Set Webhook URL di APK Notif Forwarder (per HP):")
	for A in range(H):J=public_url if public_url else f"http://{I}:{PORT}";G=D[A].split(E)[0].strip();print(f"     HP {A+1} (GoPay {G}): {J}/t{A+1}")
	print(f"{_C*55}\n");input('  Tekan ENTER untuk mulai proses...\n');M=queue.Queue()
	for R in F:S,T=R.split(E,1);M.put((S.strip(),T.strip()))
	B={_J:0,_K:0,_G:[],_I:Lock()};N=[]
	for A in range(H):U=D[A];G,V=U.split(E,1);J=public_url if public_url else f"http://{I}:{PORT}";W=f"{J}/t{A+1}";O=Thread(target=worker,args=(A+1,G.strip(),V.strip(),M,B,W));O.start();N.append(O);safe_print(info+f"Started Thread-{A+1} with GoPay: {G.strip()}")
	try:
		while any(A.is_alive()for A in N):time.sleep(1)
	except KeyboardInterrupt:
		print(f"\n{failed} FORCE SHUTDOWN DETECTED! Exiting immediately...")
		try:from pyngrok import ngrok;ngrok.kill()
		except:pass
		os._exit(1)
	print(f"\n{_C*55}");print(f"  SUMMARY");print(f"{_C*55}");print(f"  Total   : {len(F)}");print(f"  Berhasil: {B[_J]}");print(f"  Gagal   : {B[_K]}")
	if B[_G]:
		print(f"\n  Akun yang gagal:")
		for K in B[_G]:print(f"    ❌ {K}")
		with open('gagal.txt','w',encoding=_E)as C:
			for K in B[_G]:C.write(K+'\n')
		print(info+'Akun gagal disimpan ke gagal.txt')
	print(f"{_C*55}\n")
	try:from pyngrok import ngrok;ngrok.kill()
	except:pass
	try:L.shutdown()
	except:pass
if __name__=='__main__':main()