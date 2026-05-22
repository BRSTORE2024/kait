'\nmain.py — GSUITE x GOPAY CLI (Full Interactive CLI, No Telegram, No Database)\nSemua menu menggunakan selector di terminal.\n'
_f='[GAGAL WAKTU PAY DOANG]'
_e='GAGAL WAKTU PAY DOANG'
_d='already_premium'
_c='networkidle'
_b='done'
_a='ngrok'
_Z='clear'
_Y='show'
_X='add'
_W='gagal_akun'
_V='  > '
_U='0.0.0.0'
_T='gopay.txt'
_S='gsuitexGoPay.txt'
_R='berhasil_akun'
_Q='Kembali ke menu utama'
_P='gagal'
_O='berhasil'
_N='gsuite.txt'
_M='processed'
_L='back'
_K='r'
_J='reason'
_I='email'
_H='success'
_G='='
_F='lock'
_E='|'
_D='utf-8'
_C=False
_B='─'
_A=True
import os,sys,time,queue,json,signal
from datetime import datetime
from threading import Thread,Lock
from http.server import HTTPServer
from colorama import Fore,Style,init as colorama_init
colorama_init(autoreset=_A)
def _handle_ctrl_c(sig,frame):
	print(f"\n\n  {Fore.RED}👋 CTRL+C — Bot dihentikan.{Style.RESET_ALL}\n")
	try:from pyngrok import ngrok;ngrok.kill()
	except Exception:pass
	os._exit(0)
signal.signal(signal.SIGINT,_handle_ctrl_c)
from gopay import WebhookHandler,start_ngrok,get_local_ip,worker,safe_print,PORT,MAX_THREADS,MAX_RETRY,init_dashboard,update_status,process_account,info,warning,failed as failed_label,success as success_label
from config import HEADLESS,DEBUG
RESULT_FILE='RESULT.txt'
_result_lock=Lock()
_gsuite_lock=Lock()
def append_result(email,password,tag=''):
	'Append satu baris ke RESULT.txt. Thread-safe.';A=f"{email}|{password}"+(f" [{tag}]"if tag else'')
	with _result_lock:
		with open(RESULT_FILE,'a',encoding=_D)as B:B.write(A+'\n')
def cut_from_gsuite(email):
	'Hapus email dari gsuite.txt. Thread-safe.'
	with _gsuite_lock:
		if not os.path.exists(_N):return
		with open(_N,_K,encoding=_D)as A:C=A.readlines()
		with open(_N,'w',encoding=_D)as A:
			for B in C:
				if B.strip()and email not in B:A.write(B)
def clear_screen():os.system('cls'if os.name=='nt'else _Z)
def format_duration(seconds):
	'Format durasi: detik saja / menit+detik / jam+menit+detik';A=seconds;A=int(A)
	if A<60:return f"{A} detik"
	elif A<3600:B,C=divmod(A,60);return f"{B} menit {C} detik"
	else:D,E=divmod(A,3600);B,C=divmod(E,60);return f"{D} jam {B} menit {C} detik"
def print_banner():'Print banner header.';A='═';clear_screen();print(f"\n{Fore.CYAN}{A*55}");print(f"  🤖 GSUITE x GOPAY — SINDU SAGA YG FIX");print(f"{A*55}{Style.RESET_ALL}");print(f"  Browser  : Chromium (Playwright)");print(f"  Headless : {Fore.YELLOW}{HEADLESS}{Style.RESET_ALL}");print(f"  Debug    : {Fore.YELLOW}{DEBUG}{Style.RESET_ALL}");print(f"{Fore.CYAN}{A*55}{Style.RESET_ALL}\n")
def load_gopay_from_file():
	'Load data GoPay dari gopay.txt. Format: nohp|pin'
	if not os.path.exists(_T):return[]
	with open(_T,_K,encoding=_D)as E:F=[A.strip()for A in E if A.strip()and _E in A]
	A=[]
	for G in F:
		B=G.split(_E,1);C=B[0].strip();D=B[1].strip()
		if C and D:A.append((C,D))
	return A
def load_gsuite_from_file():
	'Load data GSuite dari gsuite.txt. Format: email|password'
	if not os.path.exists(_N):return[]
	with open(_N,_K,encoding=_D)as E:F=[A.strip()for A in E if A.strip()and _E in A]
	A=[]
	for G in F:
		B=G.split(_E,1);C=B[0].strip();D=B[1].strip()
		if C and D:A.append((C,D))
	return A
def parse_gsuite_data(text):
	'Parse gsuite data format: email|password dari text input.';B=[]
	for A in text.strip().splitlines():
		A=A.strip()
		if A and _E in A:
			C=A.split(_E,1);D=C[0].strip();E=C[1].strip()
			if D and E:B.append((D,E))
	return B
def show_selector(title,options):
	'\n    Tampilkan menu selector interaktif.\n    options = list of (label, value)\n    Return: value yang dipilih\n    ';A=options;print(f"\n  {Fore.CYAN}{title}{Style.RESET_ALL}");print(f"  {_B*40}")
	for(C,(D,F))in enumerate(A,1):print(f"  {Fore.GREEN}[{C}]{Style.RESET_ALL} {D}")
	print(f"  {_B*40}")
	while _A:
		try:
			E=input(f"\n  {Fore.YELLOW}Pilih [1-{len(A)}]: {Style.RESET_ALL}").strip();B=int(E)-1
			if 0<=B<len(A):return A[B][1]
			else:print(f"  {Fore.RED}❌ Pilihan tidak valid!{Style.RESET_ALL}")
		except ValueError:print(f"  {Fore.RED}❌ Masukkan angka!{Style.RESET_ALL}")
		except KeyboardInterrupt:print(f"\n\n  {Fore.RED}👋 Keluar...{Style.RESET_ALL}");sys.exit(0)
def confirm(prompt):
	'Konfirmasi Y/n.'
	while _A:
		try:
			A=input(f"  {Fore.YELLOW}{prompt} (Y/n): {Style.RESET_ALL}").strip().lower()
			if A in('','y','yes'):return _A
			elif A in('n','no'):return _C
			else:print(f"  {Fore.RED}❌ Jawab Y atau n{Style.RESET_ALL}")
		except KeyboardInterrupt:print(f"\n\n  {Fore.RED}👋 Keluar...{Style.RESET_ALL}");sys.exit(0)
def kill_ngrok_existing():
	'Kill semua tunnel ngrok yang sedang berjalan sebelum start baru.'
	try:from pyngrok import ngrok;ngrok.kill()
	except Exception:pass
	import subprocess as A
	try:
		if os.name=='nt':A.run(['taskkill','/F','/IM','ngrok.exe'],capture_output=_A)
		else:A.run(['pkill','-f',_a],capture_output=_A)
	except Exception:pass
	import time;time.sleep(1)
def menu_status():
	'Tampilkan status konfigurasi saat ini.';print_banner();B=load_gopay_from_file();A=load_gsuite_from_file();print(f"  {Fore.CYAN}📊 STATUS KONFIGURASI{Style.RESET_ALL}");print(f"  {_B*40}");print(f"  📧 GSuite (gsuite.txt)   : {Fore.GREEN}{len(A)} akun{Style.RESET_ALL}");print(f"  📱 GoPay  (gopay.txt)    : {Fore.GREEN}{len(B)} akun{Style.RESET_ALL}");print(f"  🧵 Max Threads           : {Fore.GREEN}{MAX_THREADS}{Style.RESET_ALL}");print(f"  🌐 Port OTP Listener     : {Fore.GREEN}{PORT}{Style.RESET_ALL}");print(f"  {_B*40}")
	if A:
		print(f"\n  {Fore.CYAN}📧 Data GSuite:{Style.RESET_ALL}")
		for(C,(D,E))in enumerate(A[:10],1):print(f"     {C}. {D}")
		if len(A)>10:print(f"     ... dan {len(A)-10} akun lainnya")
	if B:
		print(f"\n  {Fore.CYAN}📱 Data GoPay:{Style.RESET_ALL}")
		for(C,(F,E))in enumerate(B,1):print(f"     {C}. {F}")
	print();input(f"  {Fore.YELLOW}Tekan ENTER untuk kembali ke menu...{Style.RESET_ALL}")
def menu_generate_ngrok():
	'Generate ngrok URL (sama seperti runfirst.py).';print_banner();A=load_gopay_from_file()
	if not A:print(f"  {Fore.RED}❌ File gopay.txt tidak ditemukan atau kosong!{Style.RESET_ALL}");print(f"  ℹ️  Buat file gopay.txt dengan format: nohp|pin (satu per baris)");input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali...{Style.RESET_ALL}");return
	E=min(len(A),MAX_THREADS);kill_ngrok_existing();B=HTTPServer((_U,PORT),WebhookHandler);Thread(target=B.serve_forever,daemon=_A).start();print(f"  ✅ OTP Listener aktif di port {PORT}");print(f"  ⏳ Starting ngrok tunnel...\n");C=start_ngrok(PORT);H=get_local_ip()
	if not C:print(f"  {Fore.RED}⚠️  Ngrok gagal start! Pastikan authtoken sudah di-set.{Style.RESET_ALL}");print(f"  📝 Jalankan: ngrok config add-authtoken TOKEN_KAMU");B.shutdown();input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali...{Style.RESET_ALL}");return
	print(f"{_G*55}");print(f"  📡 NGROK URL BERHASIL DI-GENERATE!");print(f"{_G*55}");print(f"  🌐 Public URL: {Fore.GREEN}{C}{Style.RESET_ALL}");print(f"{_B*55}");print(f"  📱 Setup URL berikut di Notif Forwarder (per HP):\n")
	for D in range(E):F,I=A[D];G=f"{C}/t{D+1}";print(f"     HP {D+1} (GoPay {F}):");print(f"     👉 {Fore.GREEN}{G}{Style.RESET_ALL}\n")
	print(f"{_G*55}");print(f"  ✅ Copy URL di atas ke aplikasi Notif Forwarder di HP.");print(f"{_G*55}\n")
	try:input(f"  {Fore.YELLOW}Tekan ENTER atau Ctrl+C untuk menutup ngrok...{Style.RESET_ALL}\n")
	except KeyboardInterrupt:pass
	print(f"\n  🛑 Menutup ngrok...")
	try:from pyngrok import ngrok;ngrok.kill()
	except Exception:pass
	try:B.shutdown()
	except Exception:pass
	print(f"  ✅ Ngrok ditutup.\n")
def menu_mulai_proses():
	'Menu utama untuk mulai proses GSuite x GoPay linking.';H='manual';G='file';print_banner();C=show_selector('📧 Sumber Data GSuite',[('Dari file gsuite.txt',G),('Input manual (ketik langsung)',H),(_Q,_L)])
	if C==_L:return
	A=[]
	if C==G:
		A=load_gsuite_from_file()
		if not A:print(f"\n  {Fore.RED}❌ File gsuite.txt tidak ditemukan atau kosong!{Style.RESET_ALL}");print(f"  ℹ️  Buat file gsuite.txt dengan format: email|password (satu per baris)");input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali...{Style.RESET_ALL}");return
		print(f"\n  ✅ {Fore.GREEN}{len(A)} akun GSuite{Style.RESET_ALL} di-load dari gsuite.txt")
	elif C==H:
		print(f"\n  {Fore.CYAN}Ketik data GSuite (format: email|password, satu per baris){Style.RESET_ALL}");print(f"  {Fore.YELLOW}Ketik 'done' setelah selesai memasukkan data:{Style.RESET_ALL}\n");E=[]
		while _A:
			try:
				D=input(_V).strip()
				if D.lower()==_b:break
				if D:E.append(D)
			except KeyboardInterrupt:print();return
		I='\n'.join(E);A=parse_gsuite_data(I)
		if not A:print(f"\n  {Fore.RED}❌ Tidak ada data valid! Format: email|password{Style.RESET_ALL}");input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali...{Style.RESET_ALL}");return
		print(f"\n  ✅ {Fore.GREEN}{len(A)} akun GSuite{Style.RESET_ALL} diterima dari input manual")
	B=load_gopay_from_file()
	if not B:print(f"\n  {Fore.RED}❌ File gopay.txt tidak ditemukan atau kosong!{Style.RESET_ALL}");print(f"  ℹ️  Pastikan file gopay.txt ada dengan format: nohp|pin (satu per baris)");input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali...{Style.RESET_ALL}");return
	F=min(len(B),MAX_THREADS);print(f"\n  {Fore.CYAN}{_B*40}");print(f"  📋 RINGKASAN PROSES");print(f"  {_B*40}{Style.RESET_ALL}");print(f"  📧 GSuite  : {Fore.GREEN}{len(A)} akun{Style.RESET_ALL}");print(f"  📱 GoPay   : {Fore.GREEN}{len(B)} akun{Style.RESET_ALL}");print(f"  🧵 Threads : {Fore.GREEN}{F}{Style.RESET_ALL}");print(f"  {Fore.CYAN}{_B*40}{Style.RESET_ALL}")
	if not confirm('Lanjutkan proses?'):print(f"\n  {Fore.YELLOW}❎ Proses dibatalkan.{Style.RESET_ALL}");input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali...{Style.RESET_ALL}");return
	execute_process(A,B,F);input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali ke menu utama...{Style.RESET_ALL}")
def execute_process(gsuite_data,gopay_data,num_threads):
	'Eksekusi proses GSuite x GoPay linking.';K=gopay_data;G=num_threads;F=gsuite_data;import gopay as S;print(f"\n  {Fore.CYAN}🚀 Memulai proses...{Style.RESET_ALL}\n");T=time.time();L=HTTPServer((_U,PORT),WebhookHandler);Thread(target=L.serve_forever,daemon=_A).start();print(f"  ✅ OTP Listener aktif di port {PORT}");print(f"  ⏳ Starting ngrok tunnel...");B=start_ngrok(PORT);S.public_url=B if B else'';M=get_local_ip();N=B if B else f"http://{M}:{PORT}"
	if B:print(f"  ✅ Ngrok: {Fore.GREEN}{B}{Style.RESET_ALL}")
	else:print(f"  ⚠️  Ngrok gagal, pakai local: {Fore.YELLOW}http://{M}:{PORT}{Style.RESET_ALL}")
	print(f"\n  {_B*50}");print(f"  📱 Webhook URL per HP:")
	for A in range(G):H,c=K[A];print(f"     HP {A+1} ({H}): {N}/t{A+1}")
	print(f"  {_B*50}\n");O=queue.Queue()
	for(U,V)in F:O.put((U,V))
	I=len(F);C={_O:0,_P:0,_M:0,_W:[],_R:[],_F:Lock()}
	def W(thread_id,gopay_phone,gopay_pin,gsuite_q,ctrs,webhook_url):
		E=gsuite_q;C=thread_id;A=ctrs
		while _A:
			try:H=E.get(timeout=1)
			except queue.Empty:update_status(C,f"{info} Selesai - idle");break
			B,D=H;F=_C
			for G in range(1,MAX_RETRY+1):
				update_status(C,f"{info} {B} ({G}/{MAX_RETRY})");I=process_account(email=B,password=D,phone=gopay_phone,pin=gopay_pin,thread_id=C,webhook_url=webhook_url)
				if I:
					with A[_F]:A[_O]+=1;A[_R].append(f"{B}|{D}");A[_M]+=1
					F=_A;cut_from_gsuite(B);append_result(B,D);break
				else:update_status(C,f"{warning} Gagal #{G}, retry 5s...");time.sleep(5)
			if not F:
				with A[_F]:A[_P]+=1;A[_W].append(f"{B}|{D}");A[_M]+=1
				update_status(C,f"{failed_label} {B} gagal {MAX_RETRY}x")
			E.task_done()
	init_dashboard(G);J=[]
	for A in range(G):H,X=K[A];Y=f"{N}/t{A+1}";D=Thread(target=W,args=(A+1,H,X,O,C,Y));D.start();J.append(D)
	P=0
	try:
		while any(A.is_alive()for A in J):
			with C[_F]:E=C[_M]
			if E!=P:P=E;Q=int(E/I*100)if I>0 else 0;R=int(Q/5);Z=f"{"█"*R}{"░"*(20-R)}";sys.stdout.write(f"\r  ⏳ Progress: [{Z}] {E}/{I} ({Q}%)");sys.stdout.flush()
			time.sleep(1)
	except KeyboardInterrupt:print(f"\n\n  {Fore.RED}⚠️  FORCE SHUTDOWN! Menunggu threads selesai...{Style.RESET_ALL}")
	for D in J:D.join(timeout=10)
	a=time.time()-T;b=format_duration(a);print(f"\n\n  {Fore.CYAN}{_G*50}");print(f"  📊 SUMMARY");print(f"  {_G*50}{Style.RESET_ALL}");print(f"  📧 Total    : {len(F)}");print(f"  ✅ Berhasil : {Fore.GREEN}{C[_O]}{Style.RESET_ALL}");print(f"  ❌ Gagal    : {Fore.RED}{C[_P]}{Style.RESET_ALL}  (tetap di gsuite.txt)");print(f"  ⏱️  Durasi   : {b}");print(f"  📄 Result   : {Fore.GREEN}{RESULT_FILE}{Style.RESET_ALL}");print(f"  {Fore.CYAN}{_G*50}{Style.RESET_ALL}")
	try:from pyngrok import ngrok;ngrok.kill()
	except Exception:pass
	try:L.shutdown()
	except Exception:pass
def menu_edit_gopay():
	'Menu untuk mengelola data GoPay.';J='remove'
	while _A:
		print_banner();B=load_gopay_from_file();print(f"  {Fore.CYAN}📱 DATA GOPAY ({len(B)} akun){Style.RESET_ALL}");print(f"  {_B*40}")
		if B:
			for(E,(F,G))in enumerate(B,1):print(f"  {E}. {F} | {"*"*len(G)}")
		else:print(f"  {Fore.YELLOW}(kosong){Style.RESET_ALL}")
		print(f"  {_B*40}");C=show_selector('📱 Kelola GoPay',[('Tambah akun GoPay',_X),('Hapus akun GoPay',J),('Lihat semua (termasuk PIN)',_Y),(_Q,_L)])
		if C==_L:return
		elif C==_X:
			print(f"\n  {Fore.CYAN}Masukkan data GoPay baru (format: nohp|pin){Style.RESET_ALL}");print(f"  {Fore.YELLOW}Ketik 'done' setelah selesai:{Style.RESET_ALL}\n");D=[]
			while _A:
				try:
					A=input(_V).strip()
					if A.lower()==_b:break
					if A and _E in A:D.append(A)
					elif A:print(f"  {Fore.RED}❌ Format salah! Gunakan: nohp|pin{Style.RESET_ALL}")
				except KeyboardInterrupt:print();break
			if D:
				with open(_T,'a',encoding=_D)as H:
					for A in D:H.write(f"{A}\n")
				print(f"\n  ✅ {Fore.GREEN}{len(D)} akun GoPay ditambahkan{Style.RESET_ALL}")
			input(f"\n  {Fore.YELLOW}Tekan ENTER untuk lanjut...{Style.RESET_ALL}")
		elif C==J:
			if not B:print(f"\n  {Fore.RED}❌ Tidak ada data untuk dihapus{Style.RESET_ALL}");input(f"\n  {Fore.YELLOW}Tekan ENTER untuk lanjut...{Style.RESET_ALL}");continue
			print(f"\n  {Fore.YELLOW}Masukkan nomor akun yang akan dihapus (pisah koma, misal: 1,3):{Style.RESET_ALL}")
			try:
				K=input(_V).strip();L=[int(A.strip())-1 for A in K.split(',')];I=[f"{B}|{C}"for(A,(B,C))in enumerate(B)if A not in L]
				with open(_T,'w',encoding=_D)as H:
					for A in I:H.write(f"{A}\n")
				M=len(B)-len(I);print(f"\n  ✅ {Fore.GREEN}{M} akun dihapus{Style.RESET_ALL}")
			except(ValueError,IndexError):print(f"\n  {Fore.RED}❌ Input tidak valid{Style.RESET_ALL}")
			input(f"\n  {Fore.YELLOW}Tekan ENTER untuk lanjut...{Style.RESET_ALL}")
		elif C==_Y:
			if B:
				print(f"\n  {Fore.CYAN}📱 Data GoPay (lengkap):{Style.RESET_ALL}")
				for(E,(F,G))in enumerate(B,1):print(f"  {E}. {F} | {G}")
			else:print(f"\n  {Fore.YELLOW}(kosong){Style.RESET_ALL}")
			input(f"\n  {Fore.YELLOW}Tekan ENTER untuk lanjut...{Style.RESET_ALL}")
def menu_edit_gsuite():
	'Menu untuk mengelola data GSuite.'
	while _A:
		print_banner();A=load_gsuite_from_file();print(f"  {Fore.CYAN}📧 DATA GSUITE ({len(A)} akun){Style.RESET_ALL}");print(f"  {_B*40}")
		if A:
			for(E,(F,I))in enumerate(A[:20],1):print(f"  {E}. {F}")
			if len(A)>20:print(f"  ... dan {len(A)-20} akun lainnya")
		else:print(f"  {Fore.YELLOW}(kosong){Style.RESET_ALL}")
		print(f"  {_B*40}");C=show_selector('📧 Kelola GSuite',[('Tambah akun GSuite',_X),('Hapus semua data GSuite',_Z),('Lihat semua (termasuk password)',_Y),(_Q,_L)])
		if C==_L:return
		elif C==_X:
			print(f"\n  {Fore.CYAN}Masukkan data GSuite baru (format: email|password){Style.RESET_ALL}");print(f"  {Fore.YELLOW}Ketik 'done' setelah selesai:{Style.RESET_ALL}\n");D=[]
			while _A:
				try:
					B=input(_V).strip()
					if B.lower()==_b:break
					if B and _E in B:D.append(B)
					elif B:print(f"  {Fore.RED}❌ Format salah! Gunakan: email|password{Style.RESET_ALL}")
				except KeyboardInterrupt:print();break
			if D:
				with open(_N,'a',encoding=_D)as G:
					for B in D:G.write(f"{B}\n")
				print(f"\n  ✅ {Fore.GREEN}{len(D)} akun GSuite ditambahkan{Style.RESET_ALL}")
			input(f"\n  {Fore.YELLOW}Tekan ENTER untuk lanjut...{Style.RESET_ALL}")
		elif C==_Z:
			if confirm('Yakin hapus semua data GSuite?'):
				with open(_N,'w',encoding=_D)as G:G.write('')
				print(f"\n  ✅ {Fore.GREEN}Semua data GSuite dihapus{Style.RESET_ALL}")
			input(f"\n  {Fore.YELLOW}Tekan ENTER untuk lanjut...{Style.RESET_ALL}")
		elif C==_Y:
			if A:
				print(f"\n  {Fore.CYAN}📧 Data GSuite (lengkap):{Style.RESET_ALL}")
				for(E,(F,H))in enumerate(A,1):print(f"  {E}. {F} | {H}")
			else:print(f"\n  {Fore.YELLOW}(kosong){Style.RESET_ALL}")
			input(f"\n  {Fore.YELLOW}Tekan ENTER untuk lanjut...{Style.RESET_ALL}")
def menu_lihat_hasil():
	'Menu untuk melihat file-file hasil.';H='linked';print_banner();F=sorted([A for A in os.listdir('.')if A.startswith('result-')and A.endswith('.txt')],reverse=_A);B=0
	if os.path.exists(_S):
		with open(_S,_K,encoding=_D)as A:B=sum(1 for A in A if A.strip())
	print(f"  {Fore.CYAN}📁 HASIL PROSES{Style.RESET_ALL}");print(f"  {_B*40}");print(f"  🔗 Akun Linked (gsuitexGoPay.txt): {Fore.GREEN}{B}{Style.RESET_ALL}");print(f"  📄 File result: {Fore.GREEN}{len(F)}{Style.RESET_ALL}");print(f"  {_B*40}")
	if not F and B==0:print(f"\n  {Fore.YELLOW}Belum ada hasil proses.{Style.RESET_ALL}");input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali...{Style.RESET_ALL}");return
	C=[]
	if B>0:C.append(('Lihat akun yang berhasil linked',H))
	for G in F[:5]:C.append((f"Lihat {G}",G))
	C.append((_Q,_L));D=show_selector('📁 Pilih file untuk dilihat',C)
	if D==_L:return
	elif D==H:
		print(f"\n  {Fore.CYAN}🔗 Akun Linked (gsuitexGoPay.txt):{Style.RESET_ALL}")
		with open(_S,_K,encoding=_D)as A:
			for(I,E)in enumerate(A,1):
				E=E.strip()
				if E:print(f"  {I}. {E}")
	else:
		print(f"\n  {Fore.CYAN}📄 Isi {D}:{Style.RESET_ALL}");print(f"  {_B*40}")
		with open(D,_K,encoding=_D)as A:print(A.read())
	input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali...{Style.RESET_ALL}")
def load_nempelpay_from_file():
	'Load data dari nempelpay.txt. Format: email|password';E='nempelpay.txt'
	if not os.path.exists(E):return[]
	with open(E,_K,encoding=_D)as F:G=[A.strip()for A in F if A.strip()and _E in A]
	A=[]
	for H in G:
		B=H.split(_E,1);C=B[0].strip();D=B[1].strip()
		if C and D:A.append((C,D))
	return A
def save_premium(email,password,tag=''):'Simpan akun premium ke RESULT.txt.';A=email;B=tag if tag else'PREMIUM';append_result(A,password,B);print(f"HIT YT SAVED: {A} [{B}]")
def yt_login_google(page,email,password):
	'Login Google via Playwright. Return True jika berhasil.';F='() => { const el = document.querySelector(\'input[name="Passwd"]\'); if(el) el.value=\'\'; }';E="() => {\n        const btn = Array.from(document.querySelectorAll('button'))\n            .find(b => b.querySelector('span')?.textContent.trim() === 'Next');\n        if (btn) btn.click();\n    }";C='input[name="Passwd"]';B=password;A=page;from playwright.sync_api import TimeoutError as G;A.goto('https://accounts.google.com/',wait_until=_c);A.wait_for_timeout(2000);A.fill('input#identifierId',email);A.evaluate(E);A.wait_for_timeout(5000)
	try:A.wait_for_selector(C,state='visible',timeout=30000)
	except G:return _C
	for H in range(5):
		try:
			I=A.evaluate('() => {\n                const el = document.querySelector(\'input[name="Passwd"]\');\n                if (!el) return false;\n                const s = window.getComputedStyle(el);\n                return !el.disabled && s.display !== \'none\' && s.visibility !== \'hidden\';\n            }')
			if I:break
		except Exception:pass
		A.wait_for_timeout(1000)
	A.evaluate(F);A.type(C,B,delay=150);J=A.evaluate('() => document.querySelector(\'input[name="Passwd"]\')?.value || \'\'')
	if J!=B:A.evaluate(F);A.wait_for_timeout(500);A.type(C,B,delay=150)
	A.evaluate(E);A.wait_for_timeout(5000)
	for H in range(20):
		D=A.url
		if'myaccount.google.com'in D or'accounts.google.com/signin/v2/challenge'in D:return _A
		A.wait_for_timeout(1000)
	return _C
def yt_process_one(email,password,idx,headless=_C):
	'Proses satu akun YouTube Premium. Return dict result.';Q='OR_PMCR_32';P='OR_FGVEM_21';G='iframe#buyFlowDivIdIframe';E=password;B=idx;A=email;from playwright.sync_api import sync_playwright as R,TimeoutError as H;print(f"HIT YT [{B}] {A}")
	with R()as S:
		I=S.chromium.launch(headless=headless,args=['--no-sandbox','--disable-setuid-sandbox','--disable-blink-features=AutomationControlled','--disable-dev-shm-usage','--lang=en-US','--disable-web-security']);F=I.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',locale='en-US',extra_http_headers={'Accept-Language':'en-US,en;q=0.9'});F.add_init_script("\n            Object.defineProperty(navigator, 'webdriver', { get: () => false });\n            Object.defineProperty(navigator, 'plugins',   { get: () => [1,2,3,4,5] });\n            Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });\n            window.chrome = { runtime: {} };\n        ");C=F.new_page()
		try:
			T=yt_login_google(C,A,E)
			if not T:print(f"HIT YT [{B}] Login gagal");return{_I:A,_H:_C,_J:'LOGIN GAGAL'}
			print(f"HIT YT [{B}] Login OK");C.goto('https://music.youtube.com/youtube_premium/student',wait_until=_c);C.wait_for_timeout(3000);U=['Lanjutkan dengan Mendaftar','Continue With Signup','Continue with Signup','Lanjutkan','Continue'];V=C.evaluate("(targets) => {\n                for (const btn of document.querySelectorAll('button')) {\n                    const txt = btn.textContent || '';\n                    if (targets.some(t => txt.includes(t))) { btn.click(); return true; }\n                }\n                return false;\n            }",U)
			if not V:
				C.goto('https://music.youtube.com/paid_memberships',wait_until=_c);C.wait_for_timeout(3000);W=C.evaluate("() => {\n                    const els = document.querySelectorAll('yt-formatted-string#text.style-scope.ytmusic-toggle-button-renderer');\n                    return Array.from(els).some(el => el.textContent.includes('Kelola langganan') || el.textContent.includes('Manage subscription'));\n                }")
				if W:print(f"HIT YT [{B}] Sudah Premium");save_premium(A,E,'PREMIUM DULUAN');return{_I:A,_H:_C,_d:_A}
				print(f"HIT YT [{B}] Tombol daftar tidak ditemukan");return{_I:A,_H:_C,_J:'TOMBOL TIDAK ADA'}
			print(f"HIT YT [{B}] Klik daftar OK");C.wait_for_timeout(5000)
			try:
				C.wait_for_selector(G,timeout=10000);X=C.frame_locator(G);Y=X.locator('span.VfPpkd-vQzf8d').all();J=_C
				for K in Y:
					if K.inner_text().strip()in('Beli','Buy'):K.locator('..').click();J=_A;break
				if not J:print(f"HIT YT [{B}] Tombol Beli tidak ada");return{_I:A,_H:_C,_J:'TOMBOL BELI TIDAK ADA'}
				print(f"HIT YT [{B}] Klik Beli OK")
			except H:print(f"HIT YT [{B}] Iframe timeout");return{_I:A,_H:_C,_J:'IFRAME TIMEOUT'}
			C.wait_for_timeout(5000);D=None
			try:
				L=C.frame_locator(G)
				for Z in["div[id^='id-'][data-ur].n806",'div.d2Nfqe',"div[jsname='Cjx5Nb']",'div.LXRPh']:
					a=L.locator(Z).first
					try:
						M=a.inner_text(timeout=1000).strip()
						if 0<len(M)<400:D=M;break
					except Exception:pass
				if not D:
					b=L.locator('body').inner_text(timeout=2000)
					for N in[P,Q,'Saldo rekening Anda tidak akan menutupi','Transaksi Anda tidak dapat diselesaikan']:
						if N in b:D=N;break
			except Exception:pass
			if D:
				if P in D or'Saldo rekening'in D:print(f"HIT YT [{B}] Saldo GoPay kurang");return{_I:A,_H:_C,_J:'SALDO KURANG'}
				elif Q in D or'Transaksi Anda tidak'in D:print(f"HIT YT [{B}] Transaksi ditolak");return{_I:A,_H:_C,_J:'DITOLAK'}
				print(f"HIT YT [{B}] Error: {D}");return{_I:A,_H:_C,_J:'ERROR LAIN'}
			O=_C
			try:C.wait_for_function("() => {\n                    const el = document.querySelector('yt-formatted-string#title.style-scope.yt-confirm-dialog-renderer');\n                    if (!el) return false;\n                    const t = el.textContent.trim();\n                    return t.includes('Selamat datang di YouTube Premium') || t.includes('Welcome to YouTube Premium');\n                }",timeout=10000);O=_A
			except H:pass
			if O:print(f"HIT YT [{B}] BERHASIL PREMIUM!");save_premium(A,E);return{_I:A,_H:_A}
			print(f"HIT YT [{B}] Status tidak jelas");return{_I:A,_H:_C,_J:'STATUS TIDAK JELAS'}
		except Exception as c:print(f"HIT YT [{B}] Error: {c}");return{_I:A,_H:_C,_J:'ERROR'}
		finally:
			try:F.close();I.close()
			except Exception:pass
def execute_youtube_hit(berhasil_akun,thread_num=1):
	'Jalankan YouTube Premium hit — semua akun serentak, log sederhana.';H=thread_num;G=berhasil_akun
	if not G:print('\n[HIT TRIAL] Tidak ada akun untuk diproses.');return
	try:from playwright.sync_api import sync_playwright
	except ImportError:print('\n[HIT TRIAL] ERROR: Playwright belum terinstall!');print('  Jalankan: pip install playwright && playwright install chromium');return
	A=[]
	for L in G:
		C=L.split(_E,1)
		if len(C)==2:A.append((C[0].strip(),C[1].strip()))
	if not A:print('[HIT TRIAL] Tidak ada akun valid.');return
	print(f"\n== MEMULAI PROSES HIT TRIAL ({len(A)} akun, {H} thread) ==");import concurrent.futures;I=0;J=0;D=0;E=[];M={A:B for(A,B)in A}
	with concurrent.futures.ThreadPoolExecutor(max_workers=H)as N:
		O={N.submit(yt_process_one,A,B,C+1,HEADLESS):(A,B)for(C,(A,B))in enumerate(A)}
		for P in concurrent.futures.as_completed(O):
			try:
				B=P.result();F=B.get(_I,'?');K=M.get(F,'')
				if B.get(_H):I+=1
				elif B.get(_d):J+=1
				else:
					D+=1;Q=B.get(_J,'?');E.append(f"{F} — {Q}")
					if K:append_result(F,K,_e)
			except Exception as R:D+=1;E.append(f"? — {R}")
	print(f"\n== SELESAI HIT TRIAL ==");print(f"   PREMIUM BARU  : {I}");print(f"   SUDAH PREMIUM : {J}");print(f"   GAGAL         : {D}")
	for S in E:print(f"   GAGAL PAY  : {S}")
def load_gsuitexgopay_from_file():
	'Load akun dari gsuitexGoPay.txt. Format: email|password atau email|password|...'
	if not os.path.exists(_S):return[]
	with open(_S,_K,encoding=_D)as E:F=[A.strip()for A in E if A.strip()and _E in A]
	B=[]
	for G in F:
		A=G.split(_E);C=A[0].strip();D=A[1].strip()if len(A)>1 else''
		if C and D:B.append(f"{C}|{D}")
	return B
def load_gagal_pay():
	'Baca RESULT.txt, ambil akun yang [GAGAL WAKTU PAY DOANG].'
	if not os.path.exists(RESULT_FILE):return[]
	C=[]
	with open(RESULT_FILE,_K,encoding=_D)as D:
		for A in D:
			A=A.strip()
			if _f in A:
				E=A.replace(' [GAGAL WAKTU PAY DOANG]','').strip();B=E.split(_E,1)
				if len(B)==2:C.append(f"{B[0].strip()}|{B[1].strip()}")
	return C
def remove_gagal_pay_from_result(emails):
	'Hapus baris [GAGAL WAKTU PAY DOANG] dari RESULT.txt untuk email yg sudah di-retry.'
	if not os.path.exists(RESULT_FILE):return
	with open(RESULT_FILE,_K,encoding=_D)as A:C=A.readlines()
	with open(RESULT_FILE,'w',encoding=_D)as A:
		for B in C:
			D=_f in B and any(A in B for A in emails)
			if not D:A.write(B)
def menu_nempel_pay():
	'Menu Nempel + Pay: GSuite x GoPay linking lalu langsung YouTube hit.';F='retry';print_banner();E=show_selector('🎬 NEMPEL + PAY',[('Nempel + Pay (proses baru dari gsuite.txt)','nempel'),('Retry Pay (ambil dari RESULT.txt yg GAGAL PAY)',F),(_Q,_L)])
	if E==_L:return
	if E==F:
		C=load_gagal_pay()
		if not C:print(f"\n  {Fore.YELLOW}Tidak ada akun [GAGAL WAKTU PAY DOANG] di RESULT.txt.{Style.RESET_ALL}");input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali...{Style.RESET_ALL}");return
		A=load_gopay_from_file()
		if not A:print(f"\n  {Fore.RED}❌ File gopay.txt kosong!{Style.RESET_ALL}");input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali...{Style.RESET_ALL}");return
		B=min(len(A),MAX_THREADS);print(f"\n  Retry Pay: {Fore.GREEN}{len(C)} akun{Style.RESET_ALL}, {B} thread")
		if not confirm('Lanjutkan Retry Pay?'):input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali...{Style.RESET_ALL}");return
		G=[A.split(_E)[0]for A in C];remove_gagal_pay_from_result(G);execute_youtube_hit(C,thread_num=B);input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali ke menu utama...{Style.RESET_ALL}");return
	D=load_gsuite_from_file()
	if not D:print(f"\n  {Fore.RED}❌ File gsuite.txt tidak ditemukan atau kosong!{Style.RESET_ALL}");print(f"  ℹ️  Format: email|password (satu per baris)");input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali...{Style.RESET_ALL}");return
	A=load_gopay_from_file()
	if not A:print(f"\n  {Fore.RED}❌ File gopay.txt tidak ditemukan atau kosong!{Style.RESET_ALL}");input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali...{Style.RESET_ALL}");return
	B=min(len(A),MAX_THREADS);print(f"\n  {Fore.CYAN}{_B*40}");print(f"  📋 NEMPEL + PAY");print(f"  {_B*40}{Style.RESET_ALL}");print(f"  📧 Akun  : {Fore.GREEN}{len(D)}{Style.RESET_ALL}  (gsuite.txt)");print(f"  📱 GoPay : {Fore.GREEN}{len(A)} akun{Style.RESET_ALL}");print(f"  🧵 Thread: {Fore.GREEN}{B}{Style.RESET_ALL}");print(f"  {Fore.CYAN}{_B*40}{Style.RESET_ALL}")
	if not confirm('Lanjutkan Nempel + Pay?'):print(f"\n  {Fore.YELLOW}❎ Dibatalkan.{Style.RESET_ALL}");input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali...{Style.RESET_ALL}");return
	execute_nempel_pipeline(D,A,B);input(f"\n  {Fore.YELLOW}Tekan ENTER untuk kembali ke menu utama...{Style.RESET_ALL}")
def execute_nempel_pipeline(gsuite_data,gopay_data,num_threads):
	'\n    Pipeline: worker nempel + worker pay jalan paralel.\n    Tiap akun sukses nempel langsung masuk pay queue — tidak tunggu semua selesai.\n    ';U=gopay_data;T=gsuite_data;S='pay_sudah';R='nempel_fail';L='pay_fail';K='pay_ok';J='nempel_ok';I='count';F=num_threads;import gopay as a,concurrent.futures;print(f"\n  {Fore.CYAN}🚀 Memulai pipeline Nempel → Pay...{Style.RESET_ALL}\n");b=time.time();kill_ngrok_existing();V=HTTPServer((_U,PORT),WebhookHandler);Thread(target=V.serve_forever,daemon=_A).start();print(f"  ✅ OTP Listener aktif di port {PORT}");print(f"  ⏳ Starting ngrok tunnel...");D=start_ngrok(PORT);a.public_url=D if D else'';W=get_local_ip();X=D if D else f"http://{W}:{PORT}"
	if D:print(f"  ✅ Ngrok: {Fore.GREEN}{D}{Style.RESET_ALL}")
	else:print(f"  ⚠️  Ngrok gagal, pakai local: {Fore.YELLOW}http://{W}:{PORT}{Style.RESET_ALL}")
	print(f"\n  {_B*50}");print(f"  📱 Webhook URL per HP:")
	for B in range(F):M,k=U[B];print(f"     HP {B+1} ({M}): {X}/t{B+1}")
	print(f"  {_B*50}\n");N=queue.Queue()
	for(c,d)in T:N.put((c,d))
	E=queue.Queue();G=len(T);O={I:0};A={J:0,R:0,K:0,L:0,S:0,_F:Lock()};init_dashboard(F)
	def e(thread_id,gopay_phone,gopay_pin,webhook_url):
		C=thread_id
		while _A:
			try:K=N.get(timeout=1)
			except queue.Empty:update_status(C,f"{info} Nempel selesai - idle");break
			B,D=K;F=_C
			for G in range(1,MAX_RETRY+1):
				update_status(C,f"{info} Nempel {B} ({G}/{MAX_RETRY})");H=process_account(email=B,password=D,phone=gopay_phone,pin=gopay_pin,thread_id=C,webhook_url=webhook_url)
				if H=='already_linked':
					with A[_F]:A[J]+=1
					cut_from_gsuite(B);E.put(f"{B}|{D}");update_status(C,f"[OK] GoPay sudah ada, langsung pay: {B}");F=_A;break
				elif H:
					with A[_F]:A[J]+=1
					cut_from_gsuite(B);E.put(f"{B}|{D}");F=_A;break
				else:update_status(C,f"{warning} Nempel gagal #{G}, retry 5s...");time.sleep(5)
			if not F:
				with A[_F]:A[R]+=1
				update_status(C,f"{failed_label} Nempel {B} gagal {MAX_RETRY}x")
			with A[_F]:O[I]+=1
			N.task_done()
	def f(worker_idx):
		C=worker_idx
		while _A:
			try:J=E.get(timeout=3)
			except queue.Empty:
				with A[_F]:M=O[I]
				if M>=G and E.empty():break
				continue
			D=J.split(_E,1)
			if len(D)<2:E.task_done();continue
			B,H=D[0].strip(),D[1].strip();print(f"HIT YT [{C}] {B}");F=yt_process_one(B,H,C,HEADLESS)
			with A[_F]:
				if F.get(_H):A[K]+=1
				elif F.get(_d):A[S]+=1
				else:A[L]+=1;N=F.get(_J,'?');append_result(B,H,_e);print(f"HIT YT [{C}] GAGAL PAY: {B} — {N}")
			E.task_done()
	P=[]
	for B in range(F):M,g=U[B];h=f"{X}/t{B+1}";C=Thread(target=e,args=(B+1,M,g,h));C.start();P.append(C)
	Q=[]
	for B in range(F):C=Thread(target=f,args=(B+1,));C.start();Q.append(C)
	Y=0
	try:
		while any(A.is_alive()for A in P+Q):
			with A[_F]:H=O[I]
			if H!=Y:Y=H;Z=int(H/G*100)if G>0 else 0;i=f"{"█"*int(Z/5)}{"░"*(20-int(Z/5))}";sys.stdout.write(f"\r  ⏳ Nempel [{i}] {H}/{G} | Pay OK:{A[K]} Gagal:{A[L]}");sys.stdout.flush()
			time.sleep(1)
	except KeyboardInterrupt:print(f"\n\n  {Fore.RED}⚠️  FORCE SHUTDOWN!{Style.RESET_ALL}")
	for C in P+Q:C.join(timeout=10)
	j=format_duration(time.time()-b);print(f"\n\n  {Fore.CYAN}{_G*50}");print(f"  📊 SUMMARY NEMPEL + PAY PIPELINE");print(f"  {_G*50}{Style.RESET_ALL}");print(f"  🔗 Nempel OK   : {Fore.GREEN}{A[J]}{Style.RESET_ALL}");print(f"  ❌ Nempel Fail : {Fore.RED}{A[R]}{Style.RESET_ALL}  (tetap di gsuite.txt)");print(f"  ✅ Pay OK      : {Fore.GREEN}{A[K]}{Style.RESET_ALL}");print(f"  🏅 Sudah Premium:{Fore.YELLOW}{A[S]}{Style.RESET_ALL}");print(f"  ❌ Pay Fail    : {Fore.RED}{A[L]}{Style.RESET_ALL}  (RESULT.txt [GAGAL PAY])");print(f"  ⏱️  Durasi      : {j}");print(f"  📄 Result      : {Fore.GREEN}{RESULT_FILE}{Style.RESET_ALL}");print(f"  {Fore.CYAN}{_G*50}{Style.RESET_ALL}")
	try:from pyngrok import ngrok;ngrok.kill()
	except Exception:pass
	try:V.shutdown()
	except Exception:pass
def execute_process_and_return(gsuite_data,gopay_data,num_threads):
	'Sama seperti execute_process tapi return list akun yang berhasil.';K=gopay_data;J=gsuite_data;F=num_threads;import gopay as S;print(f"\n  {Fore.CYAN}🚀 Memulai proses Nempel...{Style.RESET_ALL}\n");T=time.time();L=HTTPServer((_U,PORT),WebhookHandler);Thread(target=L.serve_forever,daemon=_A).start();print(f"  ✅ OTP Listener aktif di port {PORT}");print(f"  ⏳ Starting ngrok tunnel...");B=start_ngrok(PORT);S.public_url=B if B else'';M=get_local_ip();N=B if B else f"http://{M}:{PORT}"
	if B:print(f"  ✅ Ngrok: {Fore.GREEN}{B}{Style.RESET_ALL}")
	else:print(f"  ⚠️  Ngrok gagal, pakai local: {Fore.YELLOW}http://{M}:{PORT}{Style.RESET_ALL}")
	print(f"\n  {_B*50}");print(f"  📱 Webhook URL per HP:")
	for A in range(F):G,c=K[A];print(f"     HP {A+1} ({G}): {N}/t{A+1}")
	print(f"  {_B*50}\n");O=queue.Queue()
	for(U,V)in J:O.put((U,V))
	H=len(J);C={_O:0,_P:0,_M:0,_W:[],_R:[],_F:Lock()}
	def W(thread_id,gopay_phone,gopay_pin,gsuite_q,ctrs,webhook_url):
		E=gsuite_q;C=thread_id;A=ctrs
		while _A:
			try:H=E.get(timeout=1)
			except queue.Empty:update_status(C,f"{info} Selesai - idle");break
			B,D=H;F=_C
			for G in range(1,MAX_RETRY+1):
				update_status(C,f"{info} {B} ({G}/{MAX_RETRY})");I=process_account(email=B,password=D,phone=gopay_phone,pin=gopay_pin,thread_id=C,webhook_url=webhook_url)
				if I:
					with A[_F]:A[_O]+=1;A[_R].append(f"{B}|{D}");A[_M]+=1
					cut_from_gsuite(B);F=_A;break
				else:update_status(C,f"{warning} Gagal #{G}, retry 5s...");time.sleep(5)
			if not F:
				with A[_F]:A[_P]+=1;A[_W].append(f"{B}|{D}");A[_M]+=1
				update_status(C,f"{failed_label} {B} gagal {MAX_RETRY}x")
			E.task_done()
	init_dashboard(F);I=[]
	for A in range(F):G,X=K[A];Y=f"{N}/t{A+1}";D=Thread(target=W,args=(A+1,G,X,O,C,Y));D.start();I.append(D)
	P=0
	try:
		while any(A.is_alive()for A in I):
			with C[_F]:E=C[_M]
			if E!=P:P=E;Q=int(E/H*100)if H>0 else 0;R=int(Q/5);Z=f"{"█"*R}{"░"*(20-R)}";sys.stdout.write(f"\r  ⏳ Progress: [{Z}] {E}/{H} ({Q}%)");sys.stdout.flush()
			time.sleep(1)
	except KeyboardInterrupt:print(f"\n\n  {Fore.RED}⚠️  FORCE SHUTDOWN!{Style.RESET_ALL}")
	for D in I:D.join(timeout=10)
	a=time.time()-T;b=format_duration(a);print(f"\n\n  {Fore.CYAN}{_G*50}");print(f"  📊 SUMMARY NEMPEL");print(f"  {_G*50}{Style.RESET_ALL}");print(f"  ✅ Berhasil : {Fore.GREEN}{C[_O]}{Style.RESET_ALL}");print(f"  ❌ Gagal    : {Fore.RED}{C[_P]}{Style.RESET_ALL}  (tetap di gsuite.txt)");print(f"  ⏱️  Durasi   : {b}");print(f"  📄 Result   : {Fore.GREEN}{RESULT_FILE}{Style.RESET_ALL}");print(f"  {Fore.CYAN}{_G*50}{Style.RESET_ALL}")
	try:from pyngrok import ngrok;ngrok.kill()
	except Exception:pass
	try:L.shutdown()
	except Exception:pass
	return C[_R]
def main():
	'Main entry point — Menu utama CLI.';H='exit';G='hasil';F='status';E='gopay';D='gsuite';C='nempel_pay';B='mulai'
	while _A:
		print_banner();I=load_gopay_from_file();J=load_gsuite_from_file();print(f"  📧 GSuite : {Fore.GREEN}{len(J)} akun{Style.RESET_ALL}   📱 GoPay : {Fore.GREEN}{len(I)} akun{Style.RESET_ALL}   🧵 Threads : {Fore.GREEN}{MAX_THREADS}{Style.RESET_ALL}\n");A=show_selector('📋 MENU UTAMA',[('🚀 Mulai Proses (GSuite x GoPay)',B),('🎬 Nempel + Pay (GSuite → YouTube Premium)',C),('📡 Generate Ngrok URL',_a),('📧 Kelola Data GSuite',D),('📱 Kelola Data GoPay',E),('📊 Status Konfigurasi',F),('📁 Lihat Hasil',G),('🚪 Keluar',H)])
		if A==B:menu_mulai_proses()
		elif A==C:menu_nempel_pay()
		elif A==_a:menu_generate_ngrok()
		elif A==D:menu_edit_gsuite()
		elif A==E:menu_edit_gopay()
		elif A==F:menu_status()
		elif A==G:menu_lihat_hasil()
		elif A==H:print(f"\n  {Fore.CYAN}👋 Sampai jumpa!{Style.RESET_ALL}\n");sys.exit(0)
if __name__=='__main__':main()