"""
JARVIS arayüzü
Çalıştırma:  python jarvis_gui.py          (normal pencere)
             python jarvis_gui.py --tray   (Windows ile açılışta: simge durumunda başlar)
"""
import os, sys

# Konsolsuz (pythonw / exe) çalışırken stdout/stderr None olur; bazı kütüphaneler çöker, bunu önle
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import io, json, queue, re, threading, time, traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox


def _fatal(e):
    """Açılış hatasını dosyaya yazar ve pencerede gösterir (pythonw/exe'de hata görünmez olurdu)."""
    here = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    try:
        (here / "jarvis_hata.txt").write_text(traceback.format_exc(), encoding="utf-8")
    except Exception:
        pass
    try:
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("JARVIS başlatılamadı", f"{e}\n\nAyrıntı: jarvis_hata.txt dosyasında.")
    except Exception:
        pass
    sys.exit(1)


try:
    import customtkinter as ctk
    import jarvis as jv
    from clap_detector import ClapDetector
    from orb import Orb
except Exception as e:
    _fatal(e)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

BG = "#0d1117"
STATES = {
    "hazir": "Hazır",
    "dinliyor": "Dinliyorum...",
    "dusunuyor": "Düşünüyorum...",
    "konusuyor": "Konuşuyorum...",
    "yukleniyor": "Ses modeli yükleniyor (ilk seferde indirme yapar)...",
}
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
SETTINGS_FILE = jv.BASE / "jarvis_settings.json"
DEFAULTS = {"voice": True, "continuous": False, "clap": True, "clap_sens": 5, "control": True,
            "voice_kind": "Otomatik (en doğal)", "chat_visible": True, "ver": 2}
VOICE_KINDS = list(jv.VOICE_PRESETS)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
SMOKE = "--smoke" in sys.argv          # kurulum testi: açılır, bileşenleri dener, smoke_sonuc.txt yazar ve kapanır


# ---------------------------------------------------------------------- yardımcılar
def load_settings():
    try:
        cfg = {**DEFAULTS, "ver": 1, **json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))}
    except Exception:
        cfg = dict(DEFAULTS, ver=1)
    if cfg.get("voice_kind") not in VOICE_KINDS:
        cfg["voice_kind"] = next((k for k in VOICE_KINDS if k.split(" ")[0] == str(cfg.get("voice_kind", "")).split(" ")[0]),
                                 DEFAULTS["voice_kind"])
    return cfg


def migrate(cfg) -> list:
    """Yeni sürüme ilk geçişte: en doğal ses zinciri, alkışla uyanma ve Windows ile başlama açılır."""
    notes = []
    fresh = not SETTINGS_FILE.exists()               # yeni kurulum: kullanıcının izni olmadan otomatik başlatma açma
    if cfg.get("ver", 1) < 2:
        cfg["voice_kind"] = "Otomatik (en doğal)"
        cfg["clap"] = True
        cfg["control"] = True
        cfg["ver"] = 2
        if sys.platform == "win32" and not fresh and not SMOKE and not autostart_enabled():
            try:
                set_autostart(True)
                notes.append("Windows açılışında simge durumunda başlayacağım; böylece çift alkışla her zaman açılabilirim "
                             "(Ayarlar'dan kapatabilirsin).")
            except Exception:
                pass
        save_settings(cfg)
    return notes


def save_settings(cfg):
    try:
        SETTINGS_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def autostart_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "Jarvis")
        return True
    except Exception:
        return False


def set_autostart(on: bool):
    """Windows açılışında Jarvis'i simge durumunda (--tray) başlatır."""
    import winreg
    if getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}" --tray'
    else:
        pyw = Path(sys.executable).with_name("pythonw.exe")
        cmd = f'"{pyw if pyw.exists() else sys.executable}" "{Path(__file__).resolve()}" --tray'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "Jarvis", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, "Jarvis")
            except FileNotFoundError:
                pass


KEY_ROWS = [("GEMINI_API_KEY", "Gemini  (aistudio.google.com/apikey)"),
            ("NVIDIA_API_KEY", "NVIDIA  (build.nvidia.com → Get API Key)"),
            ("GROQ_API_KEY", "Groq  (console.groq.com/keys)"),
            ("CEREBRAS_API_KEY", "Cerebras  (cloud.cerebras.ai)"),
            ("MISTRAL_API_KEY", "Mistral  (console.mistral.ai)"),
            ("OPENROUTER_API_KEY", "OpenRouter  (openrouter.ai/keys)")]


def save_env(vals: dict, path=None):
    """.env dosyasındaki anahtar satırlarını günceller (boş değer = satırı siler); diğer satırlara dokunmaz."""
    path = Path(path) if path else jv.BASE / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, seen = [], set()
    for ln in lines:
        k = ln.split("=", 1)[0].strip()
        if "=" in ln and k in vals:
            seen.add(k)
            if vals[k]:
                out.append(f"{k}={vals[k]}")
            continue
        out.append(ln)
    out += [f"{k}={v}" for k, v in vals.items() if v and k not in seen]
    path.write_text("\n".join(out).strip("\n") + "\n", encoding="utf-8")


def prep_image(src):
    """Dosya yolu veya PIL görseli -> ('image/jpeg', bytes); en uzun kenar 1600 px."""
    from PIL import Image
    img = Image.open(src) if isinstance(src, (str, Path)) else src
    img = img.convert("RGB")
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return "image/jpeg", buf.getvalue()


def make_tray_image():
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for r, c in ((30, (30, 70, 140, 255)), (24, (47, 129, 247, 255)), (14, (160, 205, 255, 255))):
        d.ellipse((32 - r, 32 - r, 32 + r, 32 + r), fill=c)
    return im


# ---------------------------------------------------------------------- uygulama
class App(ctk.CTk):
    def __init__(self, start_hidden=False):
        super().__init__()
        self.cfg = load_settings()
        migrate_notes = migrate(self.cfg)
        self.title("JARVIS")
        self.geometry("980x860")
        self.minsize(780, 660)
        self.configure(fg_color=BG)

        self.q: "queue.Queue" = queue.Queue()
        self.voice_on = bool(self.cfg["voice"])
        self.continuous = bool(self.cfg["continuous"])
        self.jstate = "hazir"
        self.busy = False
        self.listen_abort = threading.Event()   # çift alkış, süren arka plan dinlemesini keser
        self.attachments = []            # [(mime, bytes, ad)]
        self.tray = None
        self.clap = None
        self.clap_on = False
        self._was_visible = True
        self._tray_hint = False
        self.orb = Orb()

        self._build()
        jv.confirm_hook = self.ask_confirm
        jv.mode_hook = self.on_mode
        jv.say_hook = self.reply                        # dikte gibi uzun işlemlerde yazıp seslendirir
        jv.status_hook = self.set_state
        jv.notify_hook = lambda t: self.add("Jarvis", t)
        jv.usage_hook = lambda s: self.after(0, lambda: self.cost_lbl.configure(text=s))
        jv.screen_hook = self.screen_hook
        jv.set_voice(self.cfg["voice_kind"])
        jv.CONTROL_ON = bool(self.cfg["control"])

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.hub = None
        try:
            self.hub = jv.get_hub()                   # mikrofon bir kez açılır; alkış ve konuşma aynı akışı paylaşır
        except Exception as e:
            self.add("Jarvis", f"Mikrofon açılamadı: {e}. Mikrofon takılınca kendiliğinden tekrar deneyeceğim.")
        self._worker_thread = threading.Thread(target=self.worker, daemon=True)
        self._worker_thread.start()
        jv.warmup()
        self.animate()
        self._start_tray()
        if self.cfg["clap"]:
            self.set_clap(True, save=False)
        if self.cfg["clap"] or self.continuous:      # ses modelini önceden yükle: alkıştan sonra beklemeden dinlesin
            threading.Thread(target=self._preload_stt, daemon=True).start()
        self.after(800, self._exclude_from_capture)
        self.add("Jarvis", "Merhaba, ben Jarvis. Yazabilir, 🎤'ya basabilir ya da çift alkışlayıp konuşabilirsin. "
                           "Ekrana bakıp tıklayabilir, yazı yazabilir ve kaydırabilirim: \"ekranımda ne var?\" ya da "
                           "\"şu düğmeye tıkla\" de. Bir işi durdurmak için ⏹'e bas.")
        for n in migrate_notes:
            self.add("Jarvis", n)
        if start_hidden and self.tray:
            self.after(150, self.withdraw)

    # ------------------------------------------------------------------ arayüz
    def _build(self):
        self.top = ctk.CTkFrame(self, fg_color="transparent")
        self.top.pack(fill="x", padx=18, pady=(12, 0))
        left = ctk.CTkFrame(self.top, fg_color="transparent")
        left.pack(side="left")
        ctk.CTkLabel(left, text="J.A.R.V.I.S", font=("Segoe UI", 22, "bold"), text_color="#e6edf3").pack(anchor="w")
        self.mode_lbl = ctk.CTkLabel(left, text="☁ Gemini", font=("Segoe UI", 12, "bold"), text_color="#79c0ff")
        self.mode_lbl.pack(anchor="w")
        self.cost_lbl = ctk.CTkLabel(left, text=jv.cost_summary(), font=("Segoe UI", 11), text_color="#6e7681")
        self.cost_lbl.pack(anchor="w")
        right = ctk.CTkFrame(self.top, fg_color="transparent")
        right.pack(side="right")
        ctk.CTkButton(right, text="💬", width=40, height=34, fg_color="#21262d", hover_color="#30363d",
                      command=self.toggle_chat).pack(side="left", padx=4)
        ctk.CTkButton(right, text="⚙ Ayarlar", width=96, height=34, fg_color="#21262d", hover_color="#30363d",
                      command=self.toggle_settings).pack(side="left", padx=4)

        # ayarlar paneli (başta gizli)
        self.settings = ctk.CTkFrame(self, fg_color="#161b22", corner_radius=12, border_width=1, border_color="#30363d")
        g = self.settings
        self.sw_voice = ctk.CTkSwitch(g, text="Sesli cevap", command=self.toggle_voice)
        self.sw_listen = ctk.CTkSwitch(g, text="Sürekli dinle (\"Jarvis\" de)", command=self.toggle_listen)
        self.sw_clap = ctk.CTkSwitch(g, text="Çift alkışla uyandır", command=self.toggle_clap)
        self.sw_auto = ctk.CTkSwitch(g, text="Windows ile başlat (simge durumunda)", command=self.toggle_autostart)
        self.sw_ctrl = ctk.CTkSwitch(g, text="Ekran kontrolü (tıklama/yazma)", command=self.toggle_control)
        for sw, on in ((self.sw_voice, self.voice_on), (self.sw_listen, self.continuous),
                       (self.sw_clap, self.cfg["clap"]), (self.sw_auto, autostart_enabled()), (self.sw_ctrl, self.cfg["control"])):
            if on:
                sw.select()
        self.sw_voice.grid(row=0, column=0, padx=16, pady=(12, 6), sticky="w")
        self.sw_listen.grid(row=0, column=1, padx=16, pady=(12, 6), sticky="w")
        self.sw_clap.grid(row=1, column=0, padx=16, pady=6, sticky="w")
        self.sw_auto.grid(row=1, column=1, padx=16, pady=6, sticky="w")
        self.sw_ctrl.grid(row=2, column=0, padx=16, pady=6, sticky="w")
        ctk.CTkLabel(g, text="Alkış hassasiyeti", font=("Segoe UI", 12)).grid(row=3, column=0, padx=16, pady=6, sticky="w")
        self.sl_clap = ctk.CTkSlider(g, from_=1, to=10, number_of_steps=9, command=self.change_clap_sens, width=200)
        self.sl_clap.set(self.cfg["clap_sens"])
        self.sl_clap.grid(row=3, column=1, padx=16, pady=6, sticky="w")
        ctk.CTkLabel(g, text="Ses", font=("Segoe UI", 12)).grid(row=4, column=0, padx=16, pady=6, sticky="w")
        self.opt_voice = ctk.CTkOptionMenu(g, values=VOICE_KINDS, command=self.change_voice, width=240)
        self.opt_voice.set(self.cfg["voice_kind"])
        self.opt_voice.grid(row=4, column=1, padx=16, pady=6, sticky="w")
        btns = ctk.CTkFrame(g, fg_color="transparent")
        btns.grid(row=5, column=0, columnspan=2, padx=12, pady=(6, 12), sticky="w")
        ctk.CTkButton(btns, text="🔑 API anahtarları", width=150, command=self.open_keys_dialog).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="🎚 Mikrofon testi", width=150, command=lambda: self.q.put(("miktest",))).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="👏 Alkış testi", width=130, command=lambda: self.q.put(("claptest",))).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="🔊 Ses testi", width=120, command=lambda: self.q.put(("voicetest",))).pack(side="left", padx=4)

        self.bar = ctk.CTkFrame(self, fg_color="transparent")
        self.bar.pack(fill="x", padx=18, pady=(4, 14), side="bottom")

        # büyük animasyonlu küre
        self.orb_cv = tk.Canvas(self, bg=BG, highlightthickness=0, height=240)
        self.orb_cv.pack(fill="both", expand=True, padx=10, pady=(4, 0))
        self.status = ctk.CTkLabel(self, text="Hazır", font=("Segoe UI", 18), text_color="#c9d1d9")
        self.status.pack(pady=(0, 0))
        self.heard_lbl = ctk.CTkLabel(self, text="", font=("Segoe UI", 12), text_color="#6e7681", wraplength=760)
        self.heard_lbl.pack(pady=(0, 4))

        self.chat_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.log = ctk.CTkTextbox(self.chat_frame, wrap="word", font=("Segoe UI", 14), fg_color="#161b22", height=170,
                                  border_width=1, border_color="#30363d", corner_radius=12)
        self.log.pack(fill="both", expand=True)
        self.log.tag_config("you", foreground="#7ee787")
        self.log.tag_config("jarvis", foreground="#79c0ff")
        self.log.configure(state="disabled")

        if self.cfg["chat_visible"]:
            self.chat_frame.pack(fill="x", padx=18, pady=(0, 6), after=self.heard_lbl)
        ctk.CTkButton(self.bar, text="📎", width=44, height=42, fg_color="#21262d", hover_color="#30363d",
                      command=self.attach_files).pack(side="left", padx=(0, 6))
        self.chip_lbl = ctk.CTkLabel(self.bar, text="", font=("Segoe UI", 12), text_color="#79c0ff")
        self.chip_x = ctk.CTkButton(self.bar, text="✕", width=28, height=28, fg_color="#21262d", hover_color="#30363d",
                                    command=self.clear_attachments)
        self.entry = ctk.CTkEntry(self.bar, placeholder_text="Bir komut yaz, görsel ekle (📎 veya Ctrl+V) ve Enter'a bas...",
                                  height=42, font=("Segoe UI", 14))
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self.send())
        self.entry.bind("<Control-v>", self._paste_image, add="+")
        ctk.CTkButton(self.bar, text="Gönder", width=84, height=42, command=self.send).pack(side="left", padx=(8, 0))
        ctk.CTkButton(self.bar, text="🎤", width=52, height=42, fg_color="#2fa572", hover_color="#248a5d",
                      command=lambda: self.q.put(("ptt",))).pack(side="left", padx=(8, 0))
        ctk.CTkButton(self.bar, text="⏹", width=52, height=42, fg_color="#6e7681", hover_color="#57606a",
                      command=jv.stop_speaking).pack(side="left", padx=(8, 0))

    # ------------------------------------------------------------------ küre animasyonu
    def animate(self):
        try:
            if self.winfo_viewable():
                cv = self.orb_cv
                mic = jv.mic_level if self.jstate == "dinliyor" else 0.0
                self.orb.draw(cv, cv.winfo_width(), cv.winfo_height(), self.jstate, mic, jv.voice_level)
        except Exception:
            pass
        self.after(33, self.animate)

    def set_state(self, s):
        self.jstate = s
        if self.clap:
            # Jarvis konuşurken/düşünürken alkış algılama dursun (kendi sesini alkış sanmasın); dinlerken açık
            self.clap.paused = s not in ("hazir", "dinliyor")
        self.after(0, lambda: self.status.configure(text=STATES.get(s, s)))

    def set_heard(self, text):
        self.after(0, lambda: self.heard_lbl.configure(text=f"Duyulan: “{text}”" if text else ""))

    def _preload_stt(self):
        time.sleep(3)
        try:
            jv._get_whisper()
        except Exception as e:
            jv.dbg(f"[ses modeli önceden yüklenemedi: {e}]")

    def _exclude_from_capture(self):
        """Windows 10 (2004+) / 11: Jarvis penceresi ekran görüntülerinde görünmesin; böylece ekrana bakarken gizlenmesi gerekmez.
        (Not: ekran paylaşımında da Jarvis penceresi görünmez.)"""
        if sys.platform != "win32" or os.getenv("JARVIS_CAPTURE_EXCLUDE", "on").lower() == "off":
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            if ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x11):
                jv.capture_excluded = True
        except Exception:
            pass

    def add(self, who, text):
        self.after(0, self._add, who, text)

    def _add(self, who, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{who}: ", "you" if who == "Sen" else "jarvis")
        self.log.insert("end", text.strip() + "\n\n")
        self.log.configure(state="disabled")
        self.log.see("end")

    # ------------------------------------------------------------------ pencere / tepsi
    def show_window(self):
        self.deiconify()
        self.attributes("-topmost", True)
        self.lift()
        self.focus_force()
        self.after(400, lambda: self.attributes("-topmost", False))

    def screen_hook(self, action):
        """Ekran görüntüsü alınırken Jarvis penceresi görüntüyü kapatmasın diye gizlenir. Worker thread'inden çağrılır."""
        done = threading.Event()

        def f():
            if action == "hide":
                self._was_visible = bool(self.winfo_viewable())
                if self._was_visible:
                    self.withdraw()
            elif self._was_visible:
                self.deiconify()
            done.set()

        self.after(0, f)
        done.wait(2)

    def _start_tray(self):
        try:
            import pystray
            self.tray = pystray.Icon("jarvis", make_tray_image(), "Jarvis", pystray.Menu(
                pystray.MenuItem("Jarvis'i göster", lambda *a: self.after(0, self.show_window), default=True),
                pystray.MenuItem("Dinle 🎤", lambda *a: self.q.put(("clap",))),
                pystray.MenuItem("Çift alkışla uyandır", lambda *a: self.after(0, self.sw_clap.toggle),
                                 checked=lambda item: self.clap_on),
                pystray.MenuItem("Çıkış", lambda *a: self.after(0, self.quit_app))))
            self.tray.run_detached()
        except Exception as e:
            self.tray = None
            jv.dbg(f"[Tepsi simgesi açılamadı: {e}]")

    def on_close(self):
        if self.tray:                                  # X'e basınca kapanmaz, tepsiye iner
            self.withdraw()
            if not self._tray_hint:
                self._tray_hint = True
                try:
                    self.tray.notify("Jarvis arka planda çalışıyor. Çift alkışla veya simgeye tıklayarak aç.", "Jarvis")
                except Exception:
                    pass
        else:
            self.quit_app()

    def quit_app(self):
        jv.stop_speaking()
        for fn in (lambda: self.clap and self.clap.stop(), lambda: self.tray and self.tray.stop()):
            try:
                fn()
            except Exception:
                pass
        self.destroy()

    # ------------------------------------------------------------------ ayarlar
    def toggle_settings(self):
        if self.settings.winfo_manager():
            self.settings.pack_forget()
        else:
            self.settings.pack(fill="x", padx=18, pady=(8, 0), after=self.top)

    def toggle_chat(self):
        if self.chat_frame.winfo_manager():
            self.chat_frame.pack_forget()
        else:
            self.chat_frame.pack(fill="x", padx=18, pady=(0, 6), after=self.heard_lbl)
        self.cfg["chat_visible"] = bool(self.chat_frame.winfo_manager())
        save_settings(self.cfg)

    def toggle_voice(self):
        self.voice_on = bool(self.sw_voice.get())
        self.cfg["voice"] = self.voice_on
        save_settings(self.cfg)
        if not self.voice_on:
            jv.stop_speaking()

    def toggle_control(self):
        self.cfg["control"] = bool(self.sw_ctrl.get())
        jv.CONTROL_ON = self.cfg["control"]
        save_settings(self.cfg)

    def toggle_listen(self):
        self.continuous = bool(self.sw_listen.get())
        self.cfg["continuous"] = self.continuous
        save_settings(self.cfg)

    def toggle_clap(self):
        self.set_clap(bool(self.sw_clap.get()))

    def set_clap(self, on, save=True):
        if on:
            try:
                if self.clap is None:
                    self.clap = ClapDetector(self.on_double_clap, self.cfg["clap_sens"], device=jv.MIC_DEVICE)
                self.clap.start(jv.get_hub())
                self.clap_on = True
            except Exception as e:
                self.clap_on = False
                self.sw_clap.deselect()
                self.add("Jarvis", f"Alkış algılayıcı mikrofonu açamadı: {e}")
        else:
            if self.clap:
                self.clap.stop()
            self.clap_on = False
        if save:
            self.cfg["clap"] = self.clap_on
            save_settings(self.cfg)

    def change_clap_sens(self, v):
        self.cfg["clap_sens"] = int(round(v))
        if self.clap:
            self.clap.set_sensitivity(self.cfg["clap_sens"])
        save_settings(self.cfg)

    def toggle_autostart(self):
        on = bool(self.sw_auto.get())
        try:
            set_autostart(on)
            self.add("Jarvis", "Windows açılışında simge durumunda başlayacağım." if on else "Windows ile otomatik başlatma kapatıldı.")
        except Exception as e:
            self.sw_auto.deselect()
            self.add("Jarvis", f"Otomatik başlatma ayarlanamadı: {e}")

    def change_voice(self, kind):
        jv.set_voice(kind)
        self.cfg["voice_kind"] = kind
        save_settings(self.cfg)
        if kind.startswith("Otomatik"):
            self.add("Jarvis", "En doğal sesten başlarım: ElevenLabs (anahtarın varsa) → Gemini sesi → Microsoft Ahmet. "
                               "Birinin ücretsiz kotası dolunca otomatik sıradakine geçerim.")
        elif kind.startswith("Gemini"):
            self.add("Jarvis", "Gemini sesi doğal ama ücretsiz katmanda istek sayısı çok kısıtlı. Limit dolunca Ahmet'e dönerim.")
        elif "deneysel" in kind:
            self.add("Jarvis", "Çok dilli sesler Türkçeyi hafif aksanla okuyabilir; beğenmezsen Otomatik'e dön.")

    def open_keys_dialog(self):
        win = ctk.CTkToplevel(self)
        win.title("API anahtarları")
        win.geometry("540x560")
        win.attributes("-topmost", True)
        ctk.CTkLabel(win, text="Anahtarı olan sağlayıcılar sırayla kullanılır (Gemini → NVIDIA → Groq → Cerebras → Mistral → OpenRouter → yerel). "
                               "Boş bırakılanlar atlanır.", wraplength=490, justify="left", font=("Segoe UI", 12)).pack(padx=20, pady=(16, 6), anchor="w")
        entries = {}
        for k, label in KEY_ROWS:
            ctk.CTkLabel(win, text=label, font=("Segoe UI", 12)).pack(padx=20, pady=(8, 0), anchor="w")
            e = ctk.CTkEntry(win, width=500, show="•")
            if os.getenv(k):
                e.insert(0, os.getenv(k))
            e.pack(padx=20, anchor="w")
            entries[k] = e

        def save():
            vals = {k: e.get().strip() for k, e in entries.items()}
            try:
                save_env(vals)
            except Exception as ex:
                self.add("Jarvis", f"Anahtarlar kaydedilemedi: {ex}")
                return
            for k, v in vals.items():
                if v:
                    os.environ[k] = v
                else:
                    os.environ.pop(k, None)
            jv.client = None                          # Gemini anahtarı değiştiyse istemci yeniden kurulsun
            jv._prov_until.clear()
            jv._prov_models.clear()
            jv._key_warned.clear()
            win.destroy()
            self.add("Jarvis", "Anahtarlar kaydedildi.")

        ctk.CTkButton(win, text="Kaydet", width=140, command=save).pack(pady=18)

    def on_double_clap(self):
        if not self.busy and self.jstate in ("hazir", "dinliyor"):   # cevap verirken alkışı yok say
            self.listen_abort.set()                   # süren arka plan dinlemesini kes
            self.q.put(("clap",))

    def on_mode(self, name, reason):
        """Gemini <-> yerel (Ollama) geçişini ekranda göster."""
        label, color = {"gemini": ("☁ Gemini", "#79c0ff"), "ollama": ("💻 Yerel (Ollama)", "#e0a800"),
                        "local": ("💻 Yerel (Ollama)", "#e0a800")}.get(name, (f"☁ {name.upper()}", "#a371f7"))
        self.after(0, lambda: self.mode_lbl.configure(text=label, text_color=color))
        if name in ("ollama", "local"):
            self.add("Jarvis", f"Yerel moda geçtim ({reason}). Ollama + yerel ses ile devam ediyorum; bulut sağlayıcılar erişilebilir olunca otomatik döneceğim.")
        elif reason == "tekrar erişilebilir":
            self.add("Jarvis", f"{name.upper()} tekrar erişilebilir, ona döndüm.")
        else:
            self.add("Jarvis", f"{name.upper()} sağlayıcısına geçtim ({reason}).")

    def ask_confirm(self, question):
        """Riskli işlemlerde onay penceresi gösterir. Worker thread'inden çağrılır."""
        done, res = threading.Event(), {"ok": False}

        def show():
            hidden = not self.winfo_viewable()
            if hidden:
                self.show_window()
            res["ok"] = messagebox.askyesno("JARVIS - Onay", question, parent=self)
            if hidden and jv._ctrl.get("hidden"):     # ekran kontrolü sürüyor: pencere tıklamaların önünde durmasın
                self.withdraw()
            done.set()

        self.after(0, show)
        done.wait()
        return res["ok"]

    # ------------------------------------------------------------------ görsel ekleme
    def attach_files(self):
        paths = filedialog.askopenfilenames(title="Görsel seç", filetypes=[("Görseller", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"), ("Tümü", "*.*")])
        for p in paths:
            self._attach(p, Path(p).name)

    def _attach(self, src, name):
        if len(self.attachments) >= 4:
            self.add("Jarvis", "En fazla 4 görsel ekleyebilirsin.")
            return
        try:
            mime, data = prep_image(src)
            self.attachments.append((mime, data, name))
        except Exception as e:
            self.add("Jarvis", f"Görsel eklenemedi: {e}")
        self._refresh_chip()

    def _paste_image(self, event=None):
        try:
            from PIL import Image, ImageGrab
            im = ImageGrab.grabclipboard()
            if isinstance(im, Image.Image):
                self._attach(im, "pano görseli")
            elif isinstance(im, list):
                for f in im:
                    if str(f).lower().endswith(IMG_EXT):
                        self._attach(f, Path(f).name)
        except Exception:
            pass                                       # metin yapıştırma normal şekilde devam eder

    def _refresh_chip(self):
        if self.attachments:
            self.chip_lbl.configure(text=f"📎 {len(self.attachments)} görsel")
            self.chip_lbl.pack(side="left", padx=(0, 4), before=self.entry)
            self.chip_x.pack(side="left", padx=(0, 6), before=self.entry)
        else:
            self.chip_lbl.pack_forget()
            self.chip_x.pack_forget()

    def clear_attachments(self):
        self.attachments.clear()
        self._refresh_chip()

    def send(self):
        t = self.entry.get().strip()
        imgs = list(self.attachments)
        if not t and not imgs:
            return
        self.entry.delete(0, "end")
        self.clear_attachments()
        self.q.put(("text", t or "Bu görselde ne var? Kısaca anlat.", [(m, d) for m, d, _ in imgs] or None, len(imgs)))

    # ------------------------------------------------------------------ arka plan işleyicisi
    def reply(self, text):
        self.add("Jarvis", text)
        if self.voice_on:
            prev = self.jstate
            self.set_state("konusuyor")
            try:
                jv.speak_audio(text)
            finally:
                if threading.current_thread() is not self._worker_thread and prev == "hazir" and not self.busy:
                    self.set_state("hazir")           # arka plandan gelen mesaj (Claude sonucu vb.) bitince eski haline dön

    def ensure_stt(self):
        if jv._whisper is None:
            self.set_state("yukleniyor")
            jv._get_whisper()

    def handle(self, text, images=None, nimg=0):
        self.add("Sen", text + (f"   📎×{nimg}" if nimg else ""))
        self.busy = True
        try:
            self.set_state("dusunuyor")
            answer = jv.think(text, images) or "..."
            self.reply(answer)
        finally:
            self.busy = False
            self.set_state("hazir")

    def do_voice_test(self):
        self.add("Jarvis", f"Ses testi ({self.cfg['voice_kind']}): motor sırası {' → '.join(jv._engine_chain()) or 'edge'}.")
        self.set_state("konusuyor")
        try:
            jv.speak_audio("Merhaba, ben Jarvis. Sesim şimdi nasıl geliyor? Daha doğal olduysa ne mutlu bana.")
        finally:
            self.set_state("hazir")
        blocked = [e for e in ("elevenlabs", "gemini") if jv._tts_blocked(e)]
        if blocked:
            self.add("Jarvis", "Şu an kullanılamayan ses motorları: " + ", ".join(blocked) + " (kota/hata; bir süre sonra tekrar denerim).")

    def do_mic_test(self):
        self.add("Jarvis", "Mikrofon testi: şimdi 4 saniye boyunca bir cümle söyle…")
        try:
            self.ensure_stt()
            self.set_state("dinliyor")
            r = jv.mic_test(4)
        except Exception as e:
            self.set_state("hazir")
            self.add("Jarvis", f"Mikrofon açılamadı: {e}")
            return
        self.set_state("hazir")
        lvl = "çok kısık" if r["peak"] < 0.05 else "kısık" if r["peak"] < 0.15 else "iyi"
        msg = (f"Mikrofon: {r['device']}\nSeviye: {lvl} (tepe %{r['peak'] * 100:.0f})\n"
               f"Ses tanıma: {'GPU' if r['gpu'] else 'CPU'}\nDuyduğum: “{r['text'] or '—'}”")
        if r["peak"] < 0.05:
            msg += "\nSes çok kısık: Windows Ayarlar → Sistem → Ses → Giriş bölümünden mikrofon seviyesini artır."
        self.add("Jarvis", msg)

    def do_clap_test(self):
        if not self.clap:
            self.add("Jarvis", "Alkış algılayıcı kapalı. Ayarlardan \"Çift alkışla uyandır\" anahtarını aç.")
            return
        self.add("Jarvis", "Alkış testi: şimdi 6 saniye içinde birkaç kez çift çift alkışla…")
        self.after(0, lambda: self.status.configure(text="Alkış testi..."))
        try:
            r = self.clap.run_test(6)
        except Exception as e:
            self.add("Jarvis", f"Alkış testi yapılamadı: {e}")
            return
        finally:
            self.after(0, lambda: self.status.configure(text=STATES["hazir"]))
        if r["singles"] == 0:
            tip = "Hiç alkış algılanmadı: Ayarlardan hassasiyet çubuğunu sağa kaydır ve mikrofon seviyesini kontrol et."
        elif r["doubles"] == 0:
            tip = "Tek alkışlar algılandı ama çift değil: iki alkış arası yaklaşık 0,2-0,9 saniye olsun."
        else:
            tip = "Çalışıyor. Yanlışlıkla çok tetikleniyorsa hassasiyeti düşür."
        self.add("Jarvis", f"{r['singles']} alkış, {r['doubles']} çift alkış algılandı. Ortam gürültüsü {r['noise']:.4f}, eşik {r['threshold']:.3f}.\n{tip}")

    def worker(self):
        awake_until = 0.0
        while True:
            task = None
            try:
                task = self.q.get(timeout=0.05 if self.continuous else 0.3)
            except queue.Empty:
                pass
            try:
                if task is None:
                    if not self.continuous:
                        continue
                    self.ensure_stt()
                    self.set_state("dinliyor")
                    self.listen_abort.clear()
                    heard = jv.listen_once(timeout=3, abort=self.listen_abort)
                    self.set_state("hazir")
                    if not heard:
                        continue
                    woke, cmd = jv.strip_wake(heard)
                    if not woke and time.time() > awake_until:
                        self.set_heard(f"{heard}   (yok sayıldı: \"Jarvis\" demedin)")
                        continue
                    self.set_heard(heard)
                    if not cmd:
                        jv.chime("wake")                 # "Dinliyorum" demek yerine anında bip (TTS beklemesi yok)
                        self.set_state("dinliyor")
                        cmd = jv.listen_once(timeout=8)
                        self.set_state("hazir")
                        if not cmd:
                            continue
                        self.set_heard(cmd)
                    task = ("text", cmd, None, 0)
                elif task[0] == "clap":                  # çift alkış: pencereyi aç, bip, "Jarvis" demeden dinle
                    self.after(0, self.show_window)
                    self.ensure_stt()
                    jv.chime("wake")
                    self.set_state("dinliyor")
                    self.listen_abort.clear()
                    heard = jv.listen_once(timeout=8)
                    self.set_state("hazir")
                    if not heard:
                        self.set_heard("Ses algılanmadı")
                        continue
                    self.set_heard(heard)
                    _, cmd = jv.strip_wake(heard)
                    task = ("text", cmd or heard, None, 0)
                elif task[0] == "voicetest":
                    self.do_voice_test()
                    continue
                elif task[0] == "ptt":
                    self.ensure_stt()
                    self.set_state("dinliyor")
                    heard = jv.listen_once(timeout=8)
                    self.set_state("hazir")
                    if not heard:
                        self.set_heard("Ses algılanmadı")
                        self.add("Jarvis", "Seni duyamadım, tekrar dener misin? (Sorun sürerse Ayarlar → Mikrofon testi)")
                        continue
                    self.set_heard(heard)
                    _, cmd = jv.strip_wake(heard)
                    task = ("text", cmd or heard, None, 0)
                elif task[0] == "miktest":
                    self.do_mic_test()
                    continue
                elif task[0] == "claptest":
                    self.do_clap_test()
                    continue

                text = task[1]
                if len(text.split()) <= 4 and re.search(r"\b(kapan|görüşürüz|kendini kapat)\b", text.lower()):
                    self.reply("Görüşmek üzere.")
                    self.after(0, self.quit_app)
                    return
                self.handle(text, task[2], task[3])
                awake_until = time.time() + 20      # cevaptan sonra 20 sn "Jarvis" demeden devam edebilirsin
            except Exception as e:
                self.add("Jarvis", f"Bir hata oldu: {e}")
                self.set_state("hazir")


def ensure_key(app):
    """İlk açılışta Gemini anahtarını sorar ve .env dosyasına kaydeder."""
    if os.getenv("GEMINI_API_KEY"):
        return
    dlg = ctk.CTkInputDialog(text="Gemini API anahtarını yapıştır\n(ücretsiz: aistudio.google.com/apikey)", title="JARVIS kurulum")
    key = (dlg.get_input() or "").strip()
    if not key:
        app.add("Jarvis", "API anahtarı girilmedi: sadece yerel modda (Ollama) çalışacağım. Anahtarı sonra .env dosyasına GEMINI_API_KEY=... olarak ekleyebilirsin.")
        return
    os.environ["GEMINI_API_KEY"] = key
    try:
        save_env({"GEMINI_API_KEY": key})
    except Exception as e:
        app.add("Jarvis", f"Anahtar .env dosyasına yazılamadı: {e}")
        return
    jv.client = None
    app.add("Jarvis", "Anahtar kaydedildi. Diğer ücretsiz sağlayıcıları ⚙ Ayarlar → 🔑 API anahtarları'ndan ekleyebilirsin.")


def smoke_test(app):
    """Kurulum doğrulaması: ağır bileşenleri yükler, sonucu smoke_sonuc.txt'ye yazar, kapanır."""
    import importlib
    res = [f"python {sys.version.split()[0]}", "arayuz: OK"]
    for mod in ("faster_whisper", "ctranslate2", "edge_tts", "google.genai", "pygame", "sounddevice", "mss", "pyautogui",
                "pygetwindow", "pystray", "uiautomation", "spotipy", "PIL"):
        try:
            importlib.import_module(mod)
            res.append(f"{mod}: OK")
        except Exception as e:
            res.append(f"{mod}: HATA {type(e).__name__}: {e}")
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        import numpy as np
        get_speech_timestamps(np.zeros(16000, dtype="float32"), VadOptions())
        res.append("silero_vad: OK")
    except Exception as e:
        res.append(f"silero_vad: HATA {e}")
    res.append("mikrofon: " + ("OK" if app.hub is not None and app.hub.running else f"yok/açılamadı ({getattr(app.hub, 'error', '')})"))
    res.append("ekran_haric_tutma: " + ("OK" if jv.capture_excluded else "yok"))
    res.append(f"yerel_komut: {jv.local_command('saat kaç')}")
    try:
        (jv.BASE / "smoke_sonuc.txt").write_text("\n".join(res) + "\n", encoding="utf-8")
    finally:
        app.quit_app()


if __name__ == "__main__":
    try:
        app = App(start_hidden="--tray" in sys.argv)

        def first_run():
            if not os.getenv("GEMINI_API_KEY"):
                app.show_window()
                ensure_key(app)

        if SMOKE:
            app.after(6000, lambda: smoke_test(app))
        else:
            app.after(400, first_run)
        app.mainloop()
    except Exception as e:
        _fatal(e)
