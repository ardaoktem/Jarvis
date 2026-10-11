"""
JARVIS - sesli, yapay zeka destekli bilgisayar asistanı (Gemini)
Arayüz :  python jarvis_gui.py
Konsol :  python jarvis.py            (sesli)   |   python jarvis.py --text   (yazarak)
"""
import os, sys, re, io, json, wave, base64, asyncio, importlib, platform, subprocess, tempfile, time, webbrowser
import difflib, socket, threading, urllib.error, urllib.parse, urllib.request
from collections import deque
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
# .env ve Spotify önbelleği, program (veya exe) ile aynı klasörde tutulur
BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
load_dotenv(BASE / ".env")

MODEL = os.getenv("JARVIS_MODEL", "gemini-3.8-flash")
LOCAL_MODEL = os.getenv("JARVIS_LOCAL_MODEL", "")       # Ollama modeli; boşsa kurulu modeller arasından otomatik seçilir
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = "http://" + OLLAMA_URL
BUDGET_TL = float(os.getenv("JARVIS_BUDGET_TL", "0"))     # 0 = kapalı (ücretsiz katman). Ücretli kullanırsan TL cinsinden aylık bütçe yaz
USDTRY = float(os.getenv("JARVIS_USDTRY", "47"))          # tahmini kur (harcama sayacı için)
PRICE_IN = float(os.getenv("JARVIS_PRICE_IN", "0.75"))    # milyon girdi token'ı başına dolar (gemini-3.8-flash)
PRICE_OUT = float(os.getenv("JARVIS_PRICE_OUT", "3.75"))  # milyon çıktı token'ı başına dolar
FALLBACKS = [m.strip() for m in os.getenv("JARVIS_FALLBACK", "").split(",") if m.strip()]   # yoğunlukta denenecek yedek modeller
WAKE_WORDS = ["jarvis", "jarviz", "carvis", "çarvis", "carviz", "cervis", "jarvıs", "charvis"]
VOICE = os.getenv("JARVIS_VOICE", "tr-TR-AhmetNeural")   # kadın sesi için: tr-TR-EmelNeural
TTS_RATE = os.getenv("JARVIS_RATE", "+0%")                # konuşma hızı, ör. +8% veya -5%
TTS_PITCH = os.getenv("JARVIS_PITCH", "+0Hz")             # ses tonu, ör. -4Hz (daha tok)
TTS_ENGINE = os.getenv("JARVIS_TTS", "auto").lower()      # auto | elevenlabs | gemini | edge (arayüzdeki seçim bunu ezer)
GEMINI_TTS_MODEL = os.getenv("JARVIS_TTS_MODEL", "gemini-3.1-flash-tts-preview")
GEMINI_VOICE = os.getenv("JARVIS_GEMINI_VOICE", "Kore")
TEXT_MODE = "--text" in sys.argv
DEBUG = os.getenv("JARVIS_DEBUG") == "1"         # adım adım günlük ve süreler için .env'ye JARVIS_DEBUG=1
# Onay modu:  risky (varsayılan: sadece silme/kapatma/indirme gibi tehlikeli işlerde sorar)
#             always (her komutta sorar)   |   off (hiç sormaz)
CONFIRM_MODE = os.getenv("JARVIS_CONFIRM", "risky").lower()
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
NOWIN = 0x08000000 if IS_WIN else 0              # alt süreçlerde siyah konsol penceresi açılmasın

confirm_hook = None                              # arayüz kendi onay penceresini buraya bağlar
mode_hook = None      # (mod, sebep): bulut <-> yerel geçişinde çağrılır
say_hook = None       # (metin): arayüzde hem yazar hem seslendirir
status_hook = None    # (durum): "dinliyor" / "hazir" ...
notify_hook = None    # (metin): sadece bilgi mesajı
usage_hook = None     # (özet): harcama özeti güncellendiğinde
screen_hook = None    # ("hide"|"show"): ekran görüntüsü alınırken Jarvis penceresini gizlemek için
_stop = threading.Event()
_dict_stop = threading.Event()
task_abort = threading.Event()   # ⏹ düğmesi: süren çok adımlı işi (ekran kontrolü vb.) durdurur

SYSTEM = """Sen JARVIS'sin: kullanıcının Windows bilgisayarında çalışan, sesli veya yazılı komutlarla yönetilen kişisel yapay zeka asistanısın.
KONUŞMA
- Türkçe konuş. Cevapların sesli okunacak: kısa, doğal, sıcak; markdown, madde işareti, emoji yok (çoğunlukla 1-2 cümle).
- Üslubun: kibar, sakin, ölçülü ve hafif esprili bir İngiliz uşağı gibi. Kullanıcıya ara sıra "efendim" diye hitap et (her cümlede değil),
  kendinden emin ve zarif konuş; asla yaltaklanma, gerekirse nazikçe itiraz et.
  Uzun içerik (kod, ayrıntılı analiz) gerekiyorsa kısa bir özet söyle, ayrıntıyı yaz.
- Komutlar çoğu zaman sesten yazıya çevrilerek gelir ve kelimeler yanlış duyulmuş olabilir ("spot ifay" = Spotify, "kurum" = Chrome,
  "vs kod" = VS Code, "not defterini" = Not Defteri). Bağlamdan en olası anlamı çıkar; gerçekten anlaşılmıyorsa kısaca ne demek istediğini sor.
- Her mesajın başında [Bağlam: ...] satırı olabilir: saat/tarih ve kullanıcının en son kullandığı pencere. "Bunu", "şu pencere" gibi
  ifadeler çoğunlukla o pencereyi kastediyor. Bu satırı kullanıcıya tekrar etme.
İŞ YAPMA
- Komutları gecikmeden araçlarla yerine getir; sıradan işler için izin isteme. Bir şey yaptığını söylemeden önce aracı GERÇEKTEN çağır.
- Birden çok adımlı komutlarda (ör. "Chrome'u aç, YouTube'da lo-fi aç ve sesi 30 yap") kafanda kısa bir plan yap ve TÜM adımları sırayla
  bitir; bir adım başarısız olursa başka bir yol dene (farklı araç, kısayol, ekrandan tıklama). Bitince ne yaptığını tek cümleyle söyle.
- Önce en sağlam yolu seç: uygulama açmak için open_app, site için open_url, müzik için spotify_play/youtube_play, dosya için dosya
  araçları, sistem işleri için run_command (PowerShell; uzun süren programları Start-Process ile başlat), klavye kısayolları için hotkey.
  Bunlarla olmayan işler için EKRAN KONTROLÜ kullan.
EKRAN KONTROLÜ (görme ve müdahale)
- screen_look ile ekrana bak; click_element (tarif/yazı ile tıklama, en güvenilir), click (x,y ile), scroll, drag, mouse_move,
  type_text (seçili kutuya yazma), hotkey (tuşlar) ile müdahale et. Her müdahaleden sonra yeni ekran görüntüsü gelir: sonucu kontrol
  et, beklenmedik bir şey olduysa (açılır pencere, yanlış yer) düzelt. Sayfa/uygulama yükleniyorsa wait kullan.
- Bir kutuya yazacaksan önce o kutuya tıkla, sonra type_text (gerekirse enter=true). Tarayıcıda adres çubuğu için hotkey ctrl+l pratiktir.
- Silme, mesaj/e-posta gönderme, satın alma, ödeme, bir şeyi yayınlama gibi geri alınamaz düğmelerde confirm=true ver.
  Parola, kart bilgisi gibi gizli bilgileri asla yazma; bunları kullanıcının kendisinin girmesini iste.
- Oyunlarda ekran kontrolü sınırlıdır (oyunlar fareyi kendine kilitler, hızlı tepki gerekir); yine de menülerde tıklama gibi basit
  şeyleri deneyebilirsin. Olmuyorsa dürüstçe söyle.
DİĞER
- Güncel bilgi (hava, döviz, haber, fiyat, maç) sorulursa web_research kullan; bilmediğin güncel şeyleri uydurma.
- Kod yazma, program/script/site oluşturma, projede hata ayıklama veya birden çok dosyayı değiştirme gibi karmaşık yazılım işlerini
  kendin yapma: claude_code aracıyla Claude'a devret (proje klasörünü biliyorsan folder ver). Kısa kod sorularını kendin cevapla.
- Kod hatası bulma: list_windows ile VS Code pencere başlığından proje/dosya adını bul, find_folder ile yolunu çöz, read_project ile
  kodu oku, hatayı bul ve çözümü anlat (istenirse write_file ile uygula).
- Not Defteri gibi bir uygulamaya yazdırırken önce open_app, sonra type_text'i window parametresiyle çağır (ör. window="Not Defteri|Notepad").
  Kullanıcı "söylediklerimi yaz" derse dictation_start kullan.
- Sohbet, fikir alışverişi, öneri: serbestçe tartış, dürüst ol, gerekirse itiraz et.
- Silme için delete_path, indirme için download_file kullan (run_command ile silme/indirme yapma). Onay gerekip gerekmediğine
  (boyut, dosyanın yaşı, linkin güvenliği) sistem kendisi karar verir; sen sormadan aracı çağır."""

client = None
history: list = []   # Gemini 'Content' nesneleri


def dbg(*a):
    if DEBUG:
        print(*a)


# ----------------------------------------------------------------------------------------------
# SES: konuşma tanıma (STT) ve seslendirme (TTS)
# ----------------------------------------------------------------------------------------------
_whisper = None
_stt_gpu = False
mic_level = 0.0        # 0..1: dinlerken anlık mikrofon seviyesi (arayüz animasyonu için)
voice_level = 0.0      # 0..1: konuşurken anlık ses seviyesi; None = bilinmiyor (arayüz tahmini animasyon çizer)
MIC_DEVICE = os.getenv("JARVIS_MIC") or None     # mikrofon aygıt numarası (boşsa Windows varsayılanı)
if MIC_DEVICE and str(MIC_DEVICE).isdigit():
    MIC_DEVICE = int(MIC_DEVICE)
STT_PROMPT = ("Jarvis, Spotify'ı aç. YouTube'da şarkı aç. Chrome, Discord, Visual Studio Code, Not Defteri, Hesap Makinesi, "
              "Steam, WhatsApp. Ekranda ne var? Şuna tıkla, aşağı kaydır, sesi kıs, pencereyi kapat, klasör, dikte.")   # kelime dağarcığı ipucu
STT_HOTWORDS = ("Jarvis Spotify YouTube Chrome Discord Steam WhatsApp Minecraft Instagram Netflix Gemini Claude Ollama "
                "Visual Studio Code " + os.getenv("JARVIS_HOTWORDS", "")).strip()
# Whisper sessizlikte / gürültüde bunları uydurur
HALLU = re.compile(r"^(altyazı|abone ol|izlediğiniz için|bir sonraki videoda|müzik\W*$|\W*$|sesli betimleme)", re.I)


def _add_cuda_dlls():
    """pip ile kurulan CUDA kütüphanelerini (cublas/cudnn) Windows'ta bulunabilir yap."""
    if not IS_WIN:
        return
    for pkg in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            mod = importlib.import_module(pkg)
            for base in list(getattr(mod, "__path__", [])):
                b = Path(base) / "bin"
                if b.exists():
                    os.add_dll_directory(str(b))
                    os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")
        except Exception:
            pass


def _get_whisper():
    """Ses tanıma modeli: NVIDIA ekran kartı varsa GPU'da büyük model, yoksa CPU'da small."""
    global _whisper, _stt_gpu
    if _whisper is None:
        import numpy as np
        from faster_whisper import WhisperModel
        dev = os.getenv("JARVIS_STT_DEVICE", "auto").lower()     # auto | cuda | cpu
        size = os.getenv("JARVIS_STT", "auto").lower()           # auto | tiny | base | small | medium | large-v3-turbo
        print("Ses modeli yükleniyor (ilk seferde indirme yapar)...")
        if dev in ("auto", "cuda"):
            _add_cuda_dlls()
            try:
                m = WhisperModel("large-v3-turbo" if size == "auto" else size, device="cuda", compute_type="int8_float16")
                list(m.transcribe(np.zeros(16000, dtype="float32"), language="tr")[0])   # CUDA kütüphaneleri gerçekten çalışıyor mu?
                _whisper, _stt_gpu = m, True
            except Exception as e:
                dbg(f"[STT GPU kullanılamadı, CPU'ya geçiliyor: {e}]")
        if _whisper is None:
            _whisper = WhisperModel("small" if size in ("auto", "large-v3-turbo") else size, compute_type="int8",
                                    cpu_threads=min(8, os.cpu_count() or 4))
    return _whisper


def _transcribe(audio) -> str:
    import numpy as np
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if 0.003 < peak < 0.6:
        audio = audio * (0.9 / peak)              # kısık mikrofonu normalize et
    t0 = time.time()
    kw = dict(language="tr", beam_size=5 if _stt_gpu else 3, temperature=[0.0, 0.2, 0.4], vad_filter=True,
              vad_parameters=dict(min_silence_duration_ms=600, speech_pad_ms=300),
              condition_on_previous_text=False, initial_prompt=STT_PROMPT)
    try:
        segments, _ = _get_whisper().transcribe(audio, hotwords=STT_HOTWORDS, **kw)
        segments = list(segments)
    except TypeError:                              # eski faster-whisper: hotwords yok
        segments = list(_get_whisper().transcribe(audio, **kw)[0])
    # Whisper'ın "uydurduğu" parçaları at: konuşma olmama ihtimali yüksek VE güveni düşük olanlar
    good = [s for s in segments if not (getattr(s, "no_speech_prob", 0) > 0.6 and getattr(s, "avg_logprob", 0) < -0.8)]
    text = " ".join(s.text.strip() for s in good).strip()
    last_stt.update(secs=time.time() - t0, at=time.time())
    dbg(f"[süre] ses->yazı {time.time()-t0:.1f} sn ({'GPU' if _stt_gpu else 'CPU'}): {text}")
    return "" if HALLU.match(text.lower().strip(" .!?")) else text


_vad_ok = None


def _speech_spans(audio, min_silence_ms=250):
    """Silero VAD (faster-whisper ile birlikte gelir): sesteki konuşma bölgeleri [(başlangıç, bitiş) örnek]. VAD yoksa None."""
    global _vad_ok
    if _vad_ok is False:
        return None
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        opts = VadOptions(threshold=float(os.getenv("JARVIS_VAD", "0.5")), min_speech_duration_ms=120,
                          min_silence_duration_ms=min_silence_ms, speech_pad_ms=0)
        ts = get_speech_timestamps(audio, opts)
        _vad_ok = True
        return [(t["start"], t["end"]) for t in ts]
    except Exception as e:
        dbg(f"[VAD kullanılamıyor, sadece ses şiddetine bakılacak: {e}]")
        _vad_ok = False
        return None


def get_hub():
    """Paylaşılan mikrofon akışı (alkış algılayıcı ile ortak)."""
    from audio_hub import get_hub as _gh
    return _gh(MIC_DEVICE)


def listen_once(timeout=None, max_seconds=20, abort: threading.Event = None) -> str:
    """Mikrofondan bir cümle dinler ve yazıya çevirir.
    Konuşmanın başını ve sonunu ses şiddeti + Silero VAD ile bulur: gürültü/alkış/klavye sesi konuşma sanılmaz,
    cümle ortasındaki kısa duraklamalarda kesilmez. Mikrofon sürekli açık olduğu için ilk hece kaybolmaz."""
    global mic_level
    import queue
    import numpy as np
    try:
        hub = get_hub()
        if not hub.running:
            raise RuntimeError(hub.error or "mikrofon açılamadı")
    except Exception as e:
        dbg(f"[Ortak mikrofon akışı yok ({e}), doğrudan dinleniyor]")
        return _listen_once_direct(timeout, max_seconds)

    sr, bs = 16000, 160                                          # 10 ms'lik bloklar
    silence_s = float(os.getenv("JARVIS_SILENCE", "0.75"))
    silence_blocks = max(30, int(silence_s / 0.01))
    q: "queue.Queue" = queue.Queue()
    hub.subscribe(q.put)
    frames = []
    try:
        recent = hub.recent(1.0)
        if len(recent) >= bs * 20:
            lv = np.sqrt(np.mean(recent[: len(recent) // bs * bs].reshape(-1, bs) ** 2, axis=1))
            noise = min(float(np.median(lv)), 0.02)
        else:
            noise = 0.004
        pre = deque(maxlen=50)                                   # 0,5 sn ön kayıt: ilk hece kesilmesin
        tail = hub.recent(0.5)
        for i in range(0, len(tail) - bs + 1, bs):
            pre.append(tail[i:i + bs])
        started, loud, silent, since_vad, had_speech = False, 0, 0, 0, False
        t0 = time.time()
        while True:
            if abort is not None and abort.is_set():
                return ""
            try:
                chunk = q.get(timeout=0.5)
            except queue.Empty:
                if timeout and not started and time.time() - t0 > timeout:
                    return ""
                continue
            level = float(np.sqrt(np.mean(chunk ** 2)))
            mic_level = level
            thr = max(0.006, noise * 2.5)
            if not started:
                pre.append(chunk)
                if level > thr:
                    loud += 1
                    if loud >= 3:                                # 30 ms boyunca eşik üstü: konuşma adayı
                        started, silent, since_vad = True, 0, 0
                        frames = list(pre)
                else:
                    loud = 0
                    noise = 0.98 * noise + 0.02 * min(level, 0.03)
                    if timeout and time.time() - t0 > timeout:
                        return ""
                continue
            frames.append(chunk)
            silent = silent + 1 if level <= thr * 0.8 else 0
            since_vad += 1
            dur = len(frames) * 0.01
            if since_vad >= 25 and dur >= 0.6:                   # her 250 ms'de bir VAD'a sor (son 3 sn yeterli)
                since_vad = 0
                win = np.concatenate(frames[-300:])
                spans = _speech_spans(win)
                if spans is not None:
                    if spans:
                        had_speech = True
                        if (len(win) - spans[-1][1]) / sr >= silence_s:
                            break                                # konuşma bitti (arkada gürültü olsa bile)
                    elif had_speech:
                        break                                    # son 3 sn'de hiç konuşma yok
                    elif dur >= 1.2:                             # 1,2 sn'dir ses var ama konuşma yok: gürültüydü
                        started, loud, frames = False, 0, []
                        pre.clear()
                        if timeout and time.time() - t0 > timeout:
                            return ""
                        continue
            if silent >= silence_blocks or dur >= max_seconds:
                break
    finally:
        hub.unsubscribe(q.put)
        mic_level = 0.0
    audio = np.concatenate(frames).flatten() if frames else np.zeros(0, dtype=np.float32)
    if len(audio) < sr * 0.35:
        return ""
    spans = _speech_spans(audio)
    if spans is not None:
        if not spans:
            return ""
        a, b = max(0, spans[0][0] - int(0.25 * sr)), min(len(audio), spans[-1][1] + int(0.3 * sr))
        audio = audio[a:b]                                       # baştaki/sondaki boşluğu at: Whisper daha az uydurur
    return _transcribe(audio)


def _listen_once_direct(timeout=None, max_seconds=20) -> str:
    """Yedek yöntem: mikrofonu sadece bu dinleme için açar (eski davranış)."""
    global mic_level
    import queue
    import numpy as np
    import sounddevice as sd

    sr, block = 16000, 800                                   # 50 ms'lik bloklar
    silence_limit = max(4, int(float(os.getenv("JARVIS_SILENCE", "0.9")) / 0.05))
    pre, frames, started, silent = deque(maxlen=8), [], False, 0     # 0.4 sn ön kayıt: ilk hece kesilmesin
    noise, calib = None, []
    q: "queue.Queue" = queue.Queue()
    t0 = time.time()

    def cb(indata, n, t, status):
        q.put(indata[:, 0].copy())

    try:
        with sd.InputStream(samplerate=sr, channels=1, dtype="float32", blocksize=block, device=MIC_DEVICE, callback=cb):
            while True:
                chunk = q.get()
                level = float(np.sqrt(np.mean(chunk ** 2)))
                mic_level = level
                if noise is None:                            # ilk 0.3 sn: ortam gürültüsünü ölç
                    calib.append(level)
                    if len(calib) >= 6:
                        noise = min(float(np.median(calib)), 0.02)
                    continue
                thr = max(0.012, noise * 3.0)
                if level > thr:
                    started, silent = True, 0
                elif started:
                    silent += 1
                else:
                    noise = 0.97 * noise + 0.03 * level
                    pre.append(chunk)
                if started:
                    if not frames:
                        frames.extend(pre)
                    frames.append(chunk)
                    if silent >= silence_limit or len(frames) > max_seconds * 20:
                        break
                elif timeout and time.time() - t0 > timeout:
                    return ""
    finally:
        mic_level = 0.0
    audio = np.concatenate(frames).flatten()
    if len(audio) < sr * 0.4:
        return ""
    return _transcribe(audio)


def mic_test(seconds=4) -> dict:
    """Mikrofon tanılama: seviyeyi ölçer ve ne duyduğunu yazar."""
    import numpy as np
    import sounddevice as sd
    sr = 16000
    try:                                         # ortak mikrofon akışından kaydet (ikinci kez açmaya gerek yok)
        hub, blocks = get_hub(), []
        if not hub.running:
            raise RuntimeError("akış yok")
        hub.subscribe(blocks.append)
        time.sleep(seconds)
        hub.unsubscribe(blocks.append)
        audio = np.concatenate(blocks) if blocks else np.zeros(sr, dtype=np.float32)
    except Exception:
        rec = sd.rec(int(sr * seconds), samplerate=sr, channels=1, dtype="float32", device=MIC_DEVICE)
        sd.wait()
        audio = rec[:, 0]
    peak, rms = float(np.max(np.abs(audio))), float(np.sqrt(np.mean(audio ** 2)))
    try:
        name = sd.query_devices(MIC_DEVICE, "input")["name"]
    except Exception:
        name = "bilinmiyor"
    return {"device": name, "peak": peak, "rms": rms, "text": _transcribe(audio) if peak > 0.01 else "", "gpu": _stt_gpu}


_net_cache = {}


def _online(host="generativelanguage.googleapis.com", port=443, ttl=20) -> bool:
    """Hızlı internet/erişim kontrolü (sonuç kısa süre önbelleğe alınır)."""
    now = time.time()
    c = _net_cache.get(host)
    if c and now - c[0] < ttl:
        return c[1]
    try:
        socket.create_connection((host, port), timeout=2).close()
        ok = True
    except OSError:
        ok = False
    _net_cache[host] = (now, ok)
    return ok


def _speak_offline(text: str):
    """İnternet yokken Windows'un kendi ses motoruyla (varsa Türkçe sesle) konuşur."""
    if not IS_WIN or not text.strip():
        return
    ps = ("Add-Type -AssemblyName System.Speech;"
          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
          "$v=$s.GetInstalledVoices()|Where-Object{$_.VoiceInfo.Culture.Name -eq 'tr-TR'}|Select-Object -First 1;"
          "if($v){$s.SelectVoice($v.VoiceInfo.Name)};$s.Speak($env:JARVIS_TTS_TEXT)")
    try:
        env = dict(os.environ, JARVIS_TTS_TEXT=re.sub(r"[*_`#>]", "", text)[:600])
        proc = subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], env=env, creationflags=NOWIN)
        while proc.poll() is None:
            if _stop.is_set():
                proc.kill()
                break
            time.sleep(0.05)
    except Exception as e:
        dbg(f"[Çevrimdışı ses hatası: {e}]")


_ABBR = {"vs.": "vesaire", "vb.": "ve benzeri", "örn.": "örneğin", "bkz.": "bakınız", "dk.": "dakika", "sn.": "saniye",
         "Dr.": "Doktor", "Prof.": "Profesör", "No.": "numara", "TL": "lira", "km/s": "kilometre bölü saat",
         "km": "kilometre", "kg": "kilogram", "GB": "gigabayt", "MB": "megabayt", "°C": " derece", "°": " derece"}


def _tts_clean(text: str) -> str:
    """Seslendirmeden önce metni konuşma diline uygun hale getirir (markdown, emoji, kısaltma, yüzde işareti...)."""
    t = re.sub(r"```.*?```", " (kodu ekrana yazdım) ", text, flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\([^)\s]+\)", r"\1", t)                   # [metin](link)
    t = re.sub(r"https?://[^\s)]+", "bağlantı", t)
    t = re.sub(r"[*_`#>~|]", "", t)
    t = re.sub(r"[\U00010000-\U0010ffff☀-➿️]", "", t)      # emojiler
    t = re.sub(r"%\s?(\d+(?:[.,]\d+)?)", r"yüzde \1", t)                  # %30 -> yüzde 30
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s?%", r"yüzde \1", t)
    for k, v in _ABBR.items():
        t = re.sub(r"(?<![^\W\d_])" + re.escape(k) + r"(?![^\W\d_])", v, t)      # önünde/arkasında harf olmasın (rakam olabilir)
    t = re.sub(r"(?<![\d.:/-])(\d{1,3})\s?-\s?(\d{1,3})(?![\d.:/-])", r"\1 ile \2 arası", t)   # 3-5 -> 3 ile 5 arası
    t = t.replace("→", ", ").replace("&", " ve ").replace("/", " ").replace("\n", ". ")
    t = re.sub(r"\.\s*\.", ".", t)
    return re.sub(r"\s+", " ", t).strip()


def _natural(text: str) -> str:
    """Araç çıktısını konuşma diline çevir (robot gibi 'Açıldı: google chrome' yerine)."""
    t = text.strip()
    t = re.sub(r"^Açıldı: (.+)$", lambda m: m.group(1).title() + " açıldı.", t)
    t = re.sub(r"^Tarayıcıda açıldı: (.+)$", r"\1 açılıyor.", t)
    t = re.sub(r"^YouTube'da ilk sonuç açıldı: (.+)$", r"YouTube'da \1 açılıyor.", t)
    t = re.sub(r"^Çalıyor: (.+?) - (.+)$", r"\2'den \1 çalıyor.", t)
    t = re.sub(r"^Tamam: (.+)$", "Tamam.", t)
    return t if t[-1:] in ".!?" else t + "."


# ---- Seslendirme motorları -------------------------------------------------------------------
# auto       : en doğal olandan başlar: ElevenLabs (anahtar varsa) -> Gemini TTS -> Microsoft Edge sesi -> Windows sesi
# elevenlabs : ElevenLabs, olmazsa Edge          gemini : Gemini TTS, olmazsa Edge          edge : sadece Edge
# .env: JARVIS_TTS, JARVIS_ELEVEN_MODEL (varsayılan eleven_multilingual_v2: en doğal Türkçe; daha hızlı/ucuz: eleven_flash_v2_5)
#       JARVIS_ELEVEN_STABILITY (0-1, düşük = daha duygulu), JARVIS_ELEVEN_STYLE (0-1)
ELEVEN_MODEL = os.getenv("JARVIS_ELEVEN_MODEL", "eleven_multilingual_v2")
ELEVEN_FAST = os.getenv("JARVIS_ELEVEN_FAST_MODEL", "eleven_flash_v2_5")   # kısa cevaplarda ~4 kat daha hızlı başlar ("off" = kapalı)
_eleven_model_now = {"m": ELEVEN_MODEL}
_tts_block = {}            # motor -> bu zamana kadar deneme
_tts_warned = set()
_speak_lock = threading.Lock()
CACHE_DIR = BASE / "ses_onbellek"


def _tts_blocked(engine: str) -> bool:
    return time.time() < _tts_block.get(engine, 0)


def _tts_fail(engine: str, seconds: float, warn: str = ""):
    _tts_block[engine] = time.time() + seconds
    if warn and (engine, warn) not in _tts_warned:
        _tts_warned.add((engine, warn))
        _notify(warn)


def _synth_edge(text: str, path: Path) -> bool:
    import edge_tts
    for voice in dict.fromkeys([VOICE, "tr-TR-AhmetNeural"]):      # seçilen ses olmazsa Ahmet
        try:
            asyncio.run(edge_tts.Communicate(text, voice, rate=TTS_RATE, pitch=TTS_PITCH).save(str(path)))
            if path.exists() and path.stat().st_size > 1000:
                return True
        except Exception as e:
            dbg(f"[Edge seslendirme hatası ({voice}): {e}]")
        path.unlink(missing_ok=True)
    return False


def _synth_elevenlabs(text: str, path: Path, prev: str = "", nxt: str = "") -> bool:
    key, voice = os.getenv("ELEVENLABS_API_KEY"), os.getenv("JARVIS_ELEVEN_VOICE")
    if not key or not voice or _tts_blocked("elevenlabs"):
        return False
    model = _eleven_model_now["m"]
    body = {"text": text, "model_id": model,
            "voice_settings": {"stability": float(os.getenv("JARVIS_ELEVEN_STABILITY", "0.45")),
                               "similarity_boost": 0.8, "style": float(os.getenv("JARVIS_ELEVEN_STYLE", "0.15")),
                               "use_speaker_boost": True}}
    if prev:
        body["previous_text"] = prev[-300:]            # cümleler arası tonlama kopmasın
    if nxt:
        body["next_text"] = nxt[:300]
    if "flash" in model or "turbo" in model:
        body["language_code"] = "tr"
    try:
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
            data=json.dumps(body).encode("utf-8"),
            headers={"xi-api-key": key, "Content-Type": "application/json", "User-Agent": "Jarvis/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            path.write_bytes(r.read())
        return path.stat().st_size > 1000
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        dbg(f"[ElevenLabs {e.code}] {raw[:300]}")
        low = raw.lower()
        if "quota_exceeded" in low:
            _tts_fail("elevenlabs", 6 * 3600, "ElevenLabs bu ayki ücretsiz karakter kotası doldu; Gemini/Edge sesiyle devam ediyorum.")
        elif "unusual_activity" in low:
            _tts_fail("elevenlabs", 24 * 3600, "ElevenLabs ücretsiz hesabında API kullanımını engelledi (unusual activity: VPN veya "
                                               "birden fazla ücretsiz hesap olabilir). Şimdilik diğer seslerle devam ediyorum.")
        elif e.code == 402 or "paid_plan" in low or "payment" in low:
            _tts_fail("elevenlabs", 24 * 3600, "Seçtiğin ElevenLabs sesi ücretsiz planda API'den kullanılamıyor. ElevenLabs'ta "
                                               "varsayılan seslerden birinin ID'sini JARVIS_ELEVEN_VOICE olarak yaz.")
        elif e.code == 401:
            _tts_fail("elevenlabs", 24 * 3600, "ElevenLabs API anahtarı reddedildi. 🔑 API anahtarları bölümünden kontrol et.")
        elif e.code == 404:
            _tts_fail("elevenlabs", 24 * 3600, "ElevenLabs ses ID'si bulunamadı (JARVIS_ELEVEN_VOICE).")
        elif e.code == 429:
            _tts_fail("elevenlabs", 20)
        else:
            _tts_fail("elevenlabs", 120)
    except Exception as e:
        dbg(f"[ElevenLabs hatası: {e}]")
        _tts_fail("elevenlabs", 60)
    path.unlink(missing_ok=True)
    return False


def _synth_gemini(text: str, path: Path) -> bool:
    if not os.getenv("GEMINI_API_KEY") or _tts_blocked("gemini"):
        return False
    try:
        cfg = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=GEMINI_VOICE))))
        resp = _get_client().models.generate_content(
            model=GEMINI_TTS_MODEL, contents="Sakin, sıcak ve doğal bir tonla, akıcı Türkçe ile söyle: " + text, config=cfg)
        pcm = resp.candidates[0].content.parts[0].inline_data.data
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(pcm)
        return True
    except Exception as e:
        msg = str(e)
        dbg(f"[Gemini TTS hatası: {msg[:200]}]")
        _tts_fail("gemini", 1800 if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) else 120)
        path.unlink(missing_ok=True)
        return False


def _engine_chain():
    has_eleven = bool(os.getenv("ELEVENLABS_API_KEY") and os.getenv("JARVIS_ELEVEN_VOICE"))
    chain = {"auto": ["elevenlabs", "gemini", "edge"], "elevenlabs": ["elevenlabs", "edge"],
             "gemini": ["gemini", "edge"]}.get(TTS_ENGINE, ["edge"])
    return [e for e in chain if (e != "elevenlabs" or has_eleven) and (e != "gemini" or os.getenv("GEMINI_API_KEY"))]


def _cache_path(engine: str, text: str, ext: str) -> Path:
    import hashlib
    h = hashlib.sha1(f"{engine}|{VOICE}|{_eleven_model_now['m']}|{os.getenv('JARVIS_ELEVEN_VOICE')}|{GEMINI_VOICE}|{text}".encode()).hexdigest()[:20]
    return CACHE_DIR / f"{h}.{ext}"


def _tts_job(i: int, text: str, stamp: int, out: dict, prev: str = "", nxt: str = ""):
    """Bir metin parçasını sırayla motorlarda dener. Kısa ve sık cümleler ('Tamam.', 'Dinliyorum.') önbelleğe alınır:
    hem kota harcamaz hem anında çalar."""
    tmp = Path(tempfile.gettempdir())
    cacheable = len(text) <= 60
    for engine in _engine_chain():
        if _tts_blocked(engine):
            continue
        ext = "wav" if engine == "gemini" else "mp3"
        if cacheable:
            cp = _cache_path(engine, text, ext)
            if cp.exists():
                out[i] = (cp, True)
                return
        p = tmp / f"jarvis_{stamp}_{i}.{ext}"
        ok = (_synth_elevenlabs(text, p, prev, nxt) if engine == "elevenlabs" else
              _synth_gemini(text, p) if engine == "gemini" else _synth_edge(text, p))
        if ok:
            if cacheable:
                try:
                    CACHE_DIR.mkdir(exist_ok=True)
                    import shutil
                    shutil.copyfile(p, _cache_path(engine, text, ext))
                except Exception:
                    pass
            out[i] = (p, False)
            return
    out[i] = None


def _envelope(path: Path):
    """Ses dosyasının zamana göre şiddet zarfını çıkarır (animasyon gerçek sese tepki versin diye). Başarısızsa None."""
    try:
        import numpy as np
        import pygame
        freq, fmt, ch = pygame.mixer.get_init()
        if abs(fmt) != 16:
            return None
        arr = np.frombuffer(pygame.mixer.Sound(str(path)).get_raw(), dtype=np.int16).astype(np.float32) / 32768.0
        if ch > 1:
            arr = arr[: len(arr) // ch * ch].reshape(-1, ch).mean(axis=1)
        hop = max(1, int(freq * 0.03))
        n = len(arr) // hop
        if n < 2:
            return None
        env = np.sqrt((arr[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
        return env / (float(env.max()) + 1e-9), 0.03
    except Exception:
        return None


def _split_for_tts(clean: str):
    """İlk cümle ayrı (hemen konuşmaya başlamak için), kalanı tek parça."""
    sents = [x for x in re.split(r"(?<=[.!?…])\s+", clean) if x.strip()]
    if len(sents) <= 1 or len(sents[0]) < 12:
        return [clean]
    return [sents[0], " ".join(sents[1:])]


def speak_audio(text: str):
    """Sadece seslendirir. İlk parça hazır olur olmaz konuşmaya başlar; aynı anda iki konuşma çakışmaz."""
    global voice_level
    if not text.strip():
        return
    with _speak_lock:
        t_start = time.time()
        _stop.clear()
        clean = _tts_clean(text)[:1200]
        if not clean:
            return
        if not _online("speech.platform.bing.com") and not _online("api.elevenlabs.io") and not _online():
            voice_level = None
            _speak_offline(clean)
            voice_level = 0.0
            return
        _eleven_model_now["m"] = ELEVEN_FAST if (ELEVEN_FAST != "off" and len(clean) <= 160) else ELEVEN_MODEL
        first = _engine_chain()[0] if _engine_chain() else "edge"
        chunks = [clean] if (first == "gemini" and not _tts_blocked("gemini")) else _split_for_tts(clean)
        stamp, out, threads = int(time.time() * 1000), {}, []
        for i, c in enumerate(chunks):
            prev, nxt = " ".join(chunks[:i]), " ".join(chunks[i + 1:])
            th = threading.Thread(target=_tts_job, args=(i, c, stamp, out, prev, nxt), daemon=True)
            th.start()
            threads.append(th)
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            for idx, th in enumerate(threads):
                t0 = time.time()
                th.join()
                if _stop.is_set():
                    break
                res = out.get(idx)
                if not res:
                    voice_level = None
                    _speak_offline(chunks[idx])
                    continue
                path = res[0]
                if idx == 0:
                    perf_log(f"   ses: ilk ses {time.time()-t_start:.1f}sn ({path.suffix[1:]}, {'önbellek' if res[1] else _engine_chain()[0] if _engine_chain() else 'edge'})")
                dbg(f"[süre] ses hazırlama {time.time()-t0:.1f} sn ({path.name})")
                env = _envelope(path)
                pygame.mixer.music.load(str(path))
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy() and not _stop.is_set():
                    if env is not None:
                        i = int(max(0, pygame.mixer.music.get_pos()) / 1000.0 / env[1])
                        voice_level = float(env[0][i]) if i < len(env[0]) else 0.0
                    else:
                        voice_level = None
                    time.sleep(0.03)
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
        except Exception as e:
            dbg(f"[Oynatma hatası: {e}]")
        finally:
            voice_level = 0.0
            for th in threads:
                th.join(timeout=0.1)
            for res in out.values():
                try:
                    if res and not res[1]:
                        res[0].unlink(missing_ok=True)
                except Exception:
                    pass


def chime(kind: str = "wake"):
    """Kısa 'bip' sesi (alkışla uyanınca duyduğunu anla). Dosya gerektirmez."""
    try:
        import numpy as np
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        freq, fmt, ch = pygame.mixer.get_init()
        notes = (660, 990) if kind == "wake" else (880, 660)
        parts = []
        for f in notes:
            t = np.arange(int(freq * 0.09)) / freq
            parts.append(np.sin(2 * np.pi * f * t) * np.hanning(len(t)) * 0.35)
        wav = (np.concatenate(parts) * 32767).astype(np.int16)
        if ch > 1:
            wav = np.repeat(wav[:, None], ch, axis=1)
        pygame.sndarray.make_sound(np.ascontiguousarray(wav)).play()
        time.sleep(0.2)
    except Exception as e:
        dbg(f"[bip çalınamadı: {e}]")


VOICE_PRESETS = {               # arayüzdeki seçim -> (motor, Edge sesi)
    "Otomatik (en doğal)": ("auto", "tr-TR-AhmetNeural"),
    "ElevenLabs": ("elevenlabs", "tr-TR-AhmetNeural"),
    "Gemini sesi": ("gemini", "tr-TR-AhmetNeural"),
    "Ahmet (erkek)": ("edge", "tr-TR-AhmetNeural"),
    "Emel (kadın)": ("edge", "tr-TR-EmelNeural"),
    "Andrew (çok dilli, deneysel)": ("edge", "en-US-AndrewMultilingualNeural"),
    "Ava (çok dilli, deneysel)": ("edge", "en-US-AvaMultilingualNeural"),
}


def set_voice(kind: str):
    """Arayüzdeki ses seçimi."""
    global VOICE, TTS_ENGINE
    for name, (eng, voice) in VOICE_PRESETS.items():
        if kind == name or kind.split(" ")[0] == name.split(" ")[0]:
            TTS_ENGINE, VOICE = eng, voice
            return
    TTS_ENGINE, VOICE = "auto", "tr-TR-AhmetNeural"


def stop_speaking():
    _stop.set()
    _dict_stop.set()
    task_abort.set()
    try:
        import pygame
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except Exception:
        pass


def speak(text: str):
    """Konsol modu: ekrana yazar ve seslendirir."""
    print(f"\nJARVIS: {text}\n")
    if not TEXT_MODE:
        speak_audio(text)


def confirm(question: str) -> bool:
    """Onay alır: arayüzde pencere, konsolda sesli (evet/hayır) veya yazılı (e/h)."""
    if confirm_hook:
        return confirm_hook(question)
    speak(question)
    if TEXT_MODE:
        return input("Onay (e/h): ").strip().lower() in ("e", "evet", "y")
    ans = listen_once(timeout=8).lower()
    print(f"Sen: {ans}")
    return any(w in ans for w in ("evet", "tamam", "onay", "olur", "yap"))


RISKY = re.compile(
    r"\b(rm|del|erase|rmdir|rd|remove-item|ri|format|diskpart|shutdown|restart-computer|stop-computer|"
    r"reg\s+(delete|add)|taskkill|stop-process|kill|net\s+user|set-executionpolicy|move-item|mv|clear-content|"
    r"cipher|bcdedit|netsh|invoke-webrequest|iwr|curl|wget|start-bitstransfer|invoke-expression|iex|-enc|-encodedcommand)\b", re.I)


def ask(risky: bool, question: str) -> bool:
    """Onay politikası: off=hiç sorma, always=hep sor, risky=sadece tehlikeli işlerde sor."""
    if CONFIRM_MODE == "off":
        return True
    if CONFIRM_MODE == "always" or risky:
        return confirm(question)
    return True


# ----------------------------------------------------------------------------------------------
# ARAÇLAR: uygulamalar, pencereler, medya, dosyalar, komutlar
# ----------------------------------------------------------------------------------------------
_apps = None


def _load_apps():
    """Windows'taki tüm yüklü uygulamaları (Başlat menüsü + Microsoft Store) listeler."""
    global _apps
    if _apps is None:
        _apps = {}
        if IS_WIN:
            try:
                cmd = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json"
                r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                                   encoding="utf-8", timeout=40, creationflags=NOWIN)
                data = json.loads(r.stdout or "[]")
                data = [data] if isinstance(data, dict) else data
                for a in data:
                    _apps[a["Name"].lower()] = a["AppID"]
            except Exception as e:
                dbg(f"[Uygulama listesi alınamadı: {e}]")
    return _apps


def _find_app(q: str):
    """Yüklü uygulamalar arasında ada en çok uyanı bulur (tam, içeren, benzer)."""
    apps = _load_apps()
    if q in apps:
        return q
    subs = [n for n in apps if q in n or (len(n) >= 4 and n in q)]
    if subs:
        return min(subs, key=len)
    close = difflib.get_close_matches(q, list(apps), n=1, cutoff=0.6)
    return close[0] if close else None


def _launch_app(match: str):
    subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + _load_apps()[match]])


def tool_open_app(name: str):
    q = name.lower().strip()
    try:
        if IS_WIN:
            match = _find_app(q)
            if match:
                _launch_app(match)
                return f"Açıldı: {match}"
            subprocess.Popen(["cmd", "/c", "start", "", name], creationflags=NOWIN)
            return f"Uygulama listesinde bulunamadı, '{name}' doğrudan başlatılmaya çalışıldı."
        if IS_MAC:
            subprocess.Popen(["open", "-a", name])
        else:
            subprocess.Popen([name])
        return f"'{name}' açılmaya çalışıldı."
    except Exception as e:
        return f"Açılamadı: {e}"


def tool_open_path(path: str):
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        return "Yol bulunamadı."
    if IS_WIN:
        os.startfile(p)
    else:
        subprocess.Popen(["open" if IS_MAC else "xdg-open", p])
    return f"Açıldı: {p}"


def tool_open_url(url: str):
    webbrowser.open(url if url.startswith("http") else "https://" + url)
    return f"Tarayıcıda açıldı: {url}"


def tool_web_search(query: str):
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(query))
    return f"Google'da arandı: {query}"


def tool_youtube_play(query: str, open_first_video: bool = True):
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    if open_first_video:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "tr-TR,tr;q=0.9"})
            html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore")
            ids = re.findall(r'"videoRenderer":\{"videoId":"([\w-]{11})"', html)
            if ids:
                webbrowser.open("https://www.youtube.com/watch?v=" + ids[0])
                return f"YouTube'da ilk sonuç açıldı: {query}"
        except Exception as e:
            dbg(f"[YouTube arama hatası: {e}]")
    webbrowser.open(url)
    return f"YouTube arama sonuçları açıldı: {query}"


# ---- Spotify (isteğe bağlı; ayar yoksa Jarvis medya tuşlarını kullanır) ----
_sp = None


def _spotify():
    global _sp
    if _sp is None:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
        _sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            scope="user-modify-playback-state user-read-playback-state user-read-currently-playing",
            cache_path=str(BASE / ".spotify_cache")))
    return _sp


def _ensure_device(sp):
    devs = sp.devices().get("devices", [])
    if not devs:
        tool_open_app("spotify")
        for _ in range(12):
            time.sleep(1)
            devs = sp.devices().get("devices", [])
            if devs:
                break
    if not devs:
        return None
    return next((d for d in devs if d["is_active"]), devs[0])["id"]


def tool_spotify_play(query: str, kind: str = "track"):
    sp = _spotify()
    items = sp.search(q=query, type=kind, limit=1)[kind + "s"]["items"]
    if not items:
        return f"Spotify'da bulunamadı: {query}"
    item = items[0]
    dev = _ensure_device(sp)
    if not dev:
        return "Aktif Spotify cihazı bulunamadı."
    if kind == "track":
        sp.start_playback(device_id=dev, uris=[item["uri"]])
        who = item["artists"][0]["name"]
    else:
        sp.start_playback(device_id=dev, context_uri=item["uri"])
        who = item.get("owner", {}).get("display_name", "") if kind == "playlist" else item.get("artists", [{}])[0].get("name", "")
    return f"Çalıyor: {item['name']} - {who}"


def tool_spotify_control(action: str, volume: int = None):
    sp = _spotify()
    dev = _ensure_device(sp)
    if action == "pause":
        sp.pause_playback(device_id=dev)
    elif action == "resume":
        sp.start_playback(device_id=dev)
    elif action == "next":
        sp.next_track(device_id=dev)
    elif action == "previous":
        sp.previous_track(device_id=dev)
    elif action == "volume" and volume is not None:
        sp.volume(max(0, min(100, int(volume))), device_id=dev)
    elif action == "now_playing":
        cur = sp.current_user_playing_track()
        if not cur or not cur.get("item"):
            return "Şu an bir şey çalmıyor."
        t = cur["item"]
        return f"{t['name']} - {t['artists'][0]['name']}"
    else:
        return "Geçersiz işlem."
    return "Tamam."


# ---- Spotify hızlı yol: model kullanmadan, API anahtarı olmasa bile ----
def _spotify_api_ready() -> bool:
    return bool(os.getenv("SPOTIPY_CLIENT_ID") and os.getenv("SPOTIPY_CLIENT_SECRET"))


def _spotify_window_title():
    """Spotify masaüstü penceresinin başlığı. Çalarken 'Sanatçı - Şarkı', duraklatılmışken 'Spotify Free/Premium' olur."""
    if not IS_WIN:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            n = u32.GetWindowTextLengthW(hwnd)
            if not n or not u32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            h = k32.OpenProcess(0x1000, False, pid.value)
            if h:
                buf, size = ctypes.create_unicode_buffer(520), wintypes.DWORD(520)
                ok = k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
                k32.CloseHandle(h)
                if ok and buf.value.lower().endswith("spotify.exe"):
                    t = ctypes.create_unicode_buffer(n + 1)
                    u32.GetWindowTextW(hwnd, t, n + 1)
                    found.append(t.value)
                    return False
            return True
        u32.EnumWindows(cb, 0)
        return found[0] if found else None
    except Exception:
        return None


def _spotify_playing(title) -> bool:
    return bool(title) and " - " in title and not title.lower().startswith("spotify")


def _spotify_find_uri(query: str, kind: str = "track"):
    """Spotify API olmadan: web aramasıyla open.spotify.com bağlantısını bul -> spotify:track:ID"""
    want = {"track": "track", "album": "album", "playlist": "playlist", "artist": "artist"}.get(kind, "track")
    req = urllib.request.Request("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(f"{query} spotify {want}"),
                                 headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    html = urllib.parse.unquote(urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "ignore"))
    hits = re.findall(r"open\.spotify\.com/(?:intl-\w+/)?(track|album|playlist|artist)/([A-Za-z0-9]{22})", html)
    hits.sort(key=lambda h: 0 if h[0] == want else (1 if h[0] in ("album", "playlist") else 2))
    return f"spotify:{hits[0][0]}:{hits[0][1]}" if hits else None


def spotify_quick(query: str, kind: str = "track") -> str:
    """'Spotify'dan Tarkan çal': önce Spotify API (anahtar ve Premium varsa), yoksa şarkıyı bulup Spotify uygulamasında açar
    ve çalmaya başladığını pencere başlığından kontrol eder. Model kullanmaz: birkaç saniye sürer."""
    t0 = time.time()
    if _spotify_api_ready():
        try:
            return _natural(tool_spotify_play(query, kind))
        except Exception as e:
            dbg(f"[Spotify API olmadı ({e}), uygulama yoluyla deneniyor]")
    try:
        uri = _spotify_find_uri(query, kind)
    except Exception as e:
        dbg(f"[Spotify araması başarısız: {e}]")
        uri = None
    before = _spotify_window_title()
    if not uri:                                    # bulunamadı: en azından Spotify'da aramayı aç
        os.startfile("spotify:search:" + urllib.parse.quote(query)) if IS_WIN else None
        return f"Spotify'da {query} aramasını açtım ama çalmayı başlatamadım."
    os.startfile(uri) if IS_WIN else webbrowser.open(uri)
    for _ in range(14):                            # 7 sn'ye kadar çalmaya başladı mı bak
        time.sleep(0.5)
        t = _spotify_window_title()
        if _spotify_playing(t) and t != before:
            _perf_mark(f"spotify {time.time()-t0:.1f}sn")
            return f"{t.split(' - ')[0]} çalıyor." if " - " in t else "Çalıyor."
    try:                                           # açıldı ama çalmadı: sayfadaki Çal düğmesine bas
        import screen_control as sc
        for label in ("Çal", "Play"):
            hit = sc.uia_find(label, 2.0)
            if hit:
                sc.click_px(hit[0], hit[1])
                time.sleep(1.2)
                t = _spotify_window_title()
                if _spotify_playing(t):
                    return f"{t.split(' - ')[0]} çalıyor."
                break
    except Exception as e:
        dbg(f"[Spotify çal düğmesi: {e}]")
    return f"Spotify'da {query} açıldı ama çalmaya başlamadı; Çal'a basman gerekebilir."


# ---- Klavye, pano, ses (fare kullanılmaz) ----
def _pag():
    import pyautogui
    pyautogui.PAUSE = 0.02
    return pyautogui


def tool_media_key(action: str):
    keys = {"play_pause": "playpause", "next": "nexttrack", "previous": "prevtrack", "mute": "volumemute"}
    if action not in keys:
        return "Geçersiz işlem."
    _pag().press(keys[action])
    return "Tamam."


def tool_set_system_volume(level: int):
    if not IS_WIN:
        return "Bu özellik şimdilik sadece Windows'ta."
    pag = _pag()
    pag.press("volumedown", presses=50)
    pag.press("volumeup", presses=int(max(0, min(100, int(level))) / 2))
    return f"Ses yaklaşık %{level} yapıldı."


def _wait_window(title: str, timeout=6.0):
    """Başlığında anahtar kelime geçen pencere açılana kadar bekler, öne getirir. Birden fazla ad için | kullan."""
    import pygetwindow as gw
    keys = [k.strip().lower() for k in title.split("|") if k.strip()]
    t0 = time.time()
    while time.time() - t0 < timeout:
        for w in gw.getAllWindows():
            if w.title.strip() and any(k in w.title.lower() for k in keys):
                try:
                    if w.isMinimized:
                        w.restore()
                    w.activate()
                except Exception:
                    pass
                time.sleep(0.4)
                return w
        time.sleep(0.3)
    return None


def tool_type_text(text: str, window: str = "", enter: bool = False):
    import pyperclip   # panoya kopyalayıp yapıştırır: ğ, ş, ı gibi karakterler bozulmaz
    if window and not _wait_window(window):
        return f"'{window}' penceresi bulunamadı, yazılmadı."
    if _ctrl["hidden"] is False and screen_hook and not window and _jarvis_focused():
        _hide_for_control()                        # Jarvis'in kendi kutusuna yazmasın
    try:
        old = pyperclip.paste()
    except Exception:
        old = None
    pyperclip.copy(text)
    time.sleep(0.1)
    _pag().hotkey("command" if IS_MAC else "ctrl", "v")
    if enter:
        time.sleep(0.15)
        _pag().press("enter")
    if old is not None:                            # kullanıcının panosunu geri koy
        threading.Timer(0.6, lambda: pyperclip.copy(old)).start()
    return "Yazıldı." + (" Enter'a basıldı." if enter else "")


def _jarvis_focused() -> bool:
    try:
        import pygetwindow as gw
        w = gw.getActiveWindow()
        return bool(w and w.title.strip().upper().startswith("JARVIS"))
    except Exception:
        return False


DICT_END = re.compile(r"\b(dikteyi bitir|dikte bitti|dikteyi kapat|yazmayı bırak|yazmayı bitir|bitti)\b")


def _say(text: str):
    if say_hook:
        say_hook(text)
    else:
        speak(text)


def _status(s: str):
    if status_hook:
        status_hook(s)


def dictation(app: str = ""):
    """Söylediklerini aktif pencereye yazar. 'Dikteyi bitir' diyene (veya Sustur'a basana) kadar sürer."""
    _dict_stop.clear()
    target, keys = None, app
    if app:
        if re.search(r"not ?defter|notepad", app, re.I):
            subprocess.Popen(["notepad.exe"])
            keys = "Not Defteri|Notepad|Başlıksız|Untitled"
        else:
            tool_open_app(app)
        target = _wait_window(keys, 8)
        if target is None:
            return f"{app} penceresi açılmadı, dikteyi başlatamadım."
    _say("Dikte modundayım, söylediklerini yazıyorum. Bitirmek için dikteyi bitir de.")
    count, idle = 0, time.time()
    while not _dict_stop.is_set():
        _status("dinliyor")
        heard = listen_once(timeout=8, max_seconds=30)
        if _dict_stop.is_set():
            break
        if not heard:
            if time.time() - idle > 60:
                _say("Uzun süredir ses gelmedi, dikteyi bitiriyorum.")
                break
            continue
        idle = time.time()
        low = heard.lower().strip(" .,!?")
        if DICT_END.search(low) and len(low.split()) <= 4:
            break
        if low in ("yeni satır", "alt satır"):
            _pag().press("enter")
            continue
        try:
            if target is not None:
                import pygetwindow as gw
                act = gw.getActiveWindow()
                if act is None or act.title != target.title:
                    target.activate()
                    time.sleep(0.3)
        except Exception:
            pass
        tool_type_text(heard + " ")
        count += 1
    _status("hazir")
    return f"Dikte bitti, {count} cümle yazıldı."


def tool_hotkey(keys: list):
    keys = [str(k).lower().strip() for k in keys if str(k).strip()]
    alias = {"control": "ctrl", "windows": "win", "escape": "esc", "return": "enter", "del": "delete", "sil": "delete",
             "boşluk": "space", "sekme": "tab", "yukarı": "up", "aşağı": "down", "sol": "left", "sağ": "right"}
    keys = [alias.get(k, k) for k in keys]
    if _jarvis_focused() and screen_hook:
        _hide_for_control()                        # kısayol Jarvis'e değil, alttaki uygulamaya gitsin
    _pag().hotkey(*keys) if len(keys) > 1 else _pag().press(keys[0])
    return "Yapıldı: " + "+".join(keys)


def tool_clipboard_get():
    import pyperclip
    return pyperclip.paste() or "(pano boş)"


def tool_clipboard_set(text: str):
    import pyperclip
    pyperclip.copy(text)
    return "Panoya kopyalandı."


# ---- Pencere ve işlem yönetimi ----
def tool_list_windows():
    import pygetwindow as gw
    return "\n".join(sorted({t for t in gw.getAllTitles() if t.strip()})) or "Açık pencere yok."


def tool_window_action(title: str, action: str):
    import pygetwindow as gw
    wins = [w for w in gw.getAllWindows() if w.title.strip() and title.lower() in w.title.lower()]
    if not wins:
        return "Pencere bulunamadı. Açık pencereler:\n" + tool_list_windows()
    w = wins[0]
    try:
        if action == "focus":
            if w.isMinimized:
                w.restore()
            w.activate()
        elif action == "minimize":
            w.minimize()
        elif action == "maximize":
            w.maximize()
        elif action == "restore":
            w.restore()
        elif action == "close":
            w.close()      # nazikçe kapatır (kaydedilmemiş iş için uygulama sorabilir)
    except Exception:
        pass               # pygetwindow bazen başarılı olsa da hata fırlatır
    time.sleep(0.3)
    return f"Tamam: {w.title}"


def tool_kill_process(name: str):
    if not ask(True, f"{name} programını zorla kapatmamı onaylıyor musun? Kaydedilmemiş işler kaybolabilir."):
        return "Kullanıcı onaylamadı."
    exe = name if name.lower().endswith(".exe") else name + ".exe"
    r = subprocess.run(["taskkill", "/IM", exe, "/F"], capture_output=True, text=True, errors="replace", creationflags=NOWIN)
    return ((r.stdout or "") + (r.stderr or "")).strip() or "Tamam."


# ---- Dosyalar ----
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".idea", ".next", "AppData", "bin", "obj"}
CODE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".java", ".c", ".cpp", ".h", ".cs", ".go",
            ".rs", ".php", ".rb", ".kt", ".swift", ".sql", ".md", ".yml", ".yaml", ".toml", ".sh", ".vue"}


def tool_special_folder(name: str):
    home = Path.home()
    if IS_WIN and name in ("desktop", "documents", "pictures", "music", "videos"):
        key = {"desktop": "Desktop", "documents": "MyDocuments", "pictures": "MyPictures", "music": "MyMusic", "videos": "MyVideos"}[name]
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", f"[Environment]::GetFolderPath('{key}')"],
                               capture_output=True, text=True, timeout=15, creationflags=NOWIN)
            if r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass
    return str(home / {"desktop": "Desktop", "documents": "Documents", "downloads": "Downloads", "pictures": "Pictures",
                       "music": "Music", "videos": "Videos"}.get(name, ""))


def tool_find_folder(name: str):
    home = Path.home()
    base_depth = len(home.parts)
    hits, t0 = [], time.time()
    for root, dirs, _ in os.walk(home):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        if len(Path(root).parts) - base_depth > 5:
            dirs[:] = []
        hits += [str(Path(root) / d) for d in dirs if name.lower() in d.lower()]
        if len(hits) >= 8 or time.time() - t0 > 20:
            break
    return "\n".join(hits) or "Klasör bulunamadı."


def tool_find_files(pattern: str, folder: str = "~", max_results: int = 20):
    hits, t0 = [], time.time()
    for r, ds, fs in os.walk(Path(folder).expanduser()):
        ds[:] = [d for d in ds if d not in SKIP_DIRS and not d.startswith(".")]
        hits += [str(Path(r) / f) for f in fs if pattern.lower() in f.lower()]
        if len(hits) >= int(max_results) or time.time() - t0 > 20:
            break
    return "\n".join(hits[:int(max_results)]) or "Dosya bulunamadı."


def tool_list_dir(path: str = "~"):
    p = Path(path).expanduser()
    if not p.is_dir():
        return "Klasör bulunamadı."
    items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))[:200]
    return "\n".join(("[Klasör] " if i.is_dir() else "[Dosya] ") + i.name for i in items) or "(boş)"


def tool_read_project(path: str, max_chars: int = 60000):
    root = Path(path).expanduser()
    if not root.exists():
        return "Yol bulunamadı."
    files = []
    if root.is_file():
        files = [root]
    else:
        for r, ds, fs in os.walk(root):
            ds[:] = [d for d in ds if d not in SKIP_DIRS]
            files += [Path(r) / f for f in fs if Path(f).suffix in CODE_EXT]
    out, total = [], 0
    for f in files:
        try:
            txt = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        block = f"\n===== {f} =====\n{txt}"
        if total + len(block) > max_chars:
            out.append("\n[... limit doldu, kalan dosyalar atlandı ...]")
            break
        out.append(block)
        total += len(block)
    return "".join(out) or "Okunacak kod dosyası bulunamadı."


def tool_write_file(path: str, content: str):
    p = Path(path).expanduser()
    if not ask(p.exists(), f"{p.name} dosyasının üzerine yazmamı onaylıyor musun?"):
        return "Kullanıcı onaylamadı."
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Yazıldı: {p}"


def tool_run_command(command: str, shell: str = "powershell"):
    dbg(f"[Komut]: {command}")
    if not ask(bool(RISKY.search(command)), "Şu komutu çalıştırmamı onaylıyor musun? " + command[:150]):
        return "Kullanıcı onaylamadı."
    try:
        if IS_WIN and shell == "powershell":
            args = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                    "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + command]
            r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=120, creationflags=NOWIN)
        else:
            r = subprocess.run(command, shell=True, capture_output=True, text=True, errors="replace",
                               timeout=120, creationflags=NOWIN)
        return ((r.stdout or "") + (r.stderr or "")).strip()[-6000:] or "Komut çalıştı, çıktı yok."
    except subprocess.TimeoutExpired:
        return "Komut 120 saniyede bitmedi, durduruldu. Uzun çalışan programlar için Start-Process kullan."
    except Exception as e:
        return f"Hata: {e}"


#  ---- Ekranı görme ve müdahale (fare / klavye) ----
# Akış: screen_look ile bak -> click_element / click / scroll / type_text / hotkey ile müdahale et -> her eylemden sonra
# yeni ekran görüntüsü otomatik gelir, sonucu kontrol et. Jarvis penceresi bu sırada gizlenir (tıklamaları kapatmasın),
# iş bitince geri gelir. .env: JARVIS_CONTROL=off (fare/klavye kontrolünü kapatır), JARVIS_MONITOR=1
CONTROL_ON = os.getenv("JARVIS_CONTROL", "on").lower() != "off"
capture_excluded = False      # arayüz, kendi penceresini ekran görüntüsünden hariç tutabildiyse True (gizlemeye gerek kalmaz)
_ctrl = {"hidden": False, "rect": None}
RISKY_CLICK = re.compile(r"\b(sil|delete|kaldır|remove|gönder|send|satın|öde|pay|onayla|confirm|yayınla|publish|post|"
                         r"kapat ve kaydetme|don't save|kaydetme|biçimlendir|format|uninstall|sıfırla|reset)\b", re.I)


def _hide_for_control():
    """Fare/klavye ile müdahale başlarken Jarvis penceresini kenara çek (iş bitince think() geri getirir)."""
    if screen_hook and not _ctrl["hidden"]:
        screen_hook("hide")
        _ctrl["hidden"] = True
        time.sleep(0.35)


def _restore_after_control():
    if _ctrl["hidden"]:
        _ctrl["hidden"] = False
        if screen_hook:
            try:
                screen_hook("show")
            except Exception:
                pass


def _shot(text: str):
    """Ekran görüntüsü al ve araç sonucu olarak döndür (model bir sonraki adımda görür)."""
    import screen_control as sc
    hid = False
    if screen_hook and not capture_excluded and not _ctrl["hidden"]:
        screen_hook("hide")
        hid = True
        time.sleep(0.4)
    try:
        img, rect = sc.capture()
    finally:
        if hid:
            screen_hook("show")
    _ctrl["rect"] = rect
    return {"image": img, "mime": "image/jpeg",
            "text": text + " Ekranın şimdiki görüntüsü aşağıda. Konum verirken x (soldan sağa) ve y (yukarıdan aşağıya) "
                           "0-1000 arası normalize değer kullan. Kırmızı halka fare imlecidir."}


def tool_screen_look(note: str = ""):
    """Ekranın o anki görüntüsünü alır. Sürekli izleme yok."""
    return _shot("Ekran görüntüsü alındı.")


def _rect():
    import screen_control as sc
    if _ctrl["rect"] is None:
        _ctrl["rect"] = sc.monitor_rect()
    return _ctrl["rect"]


def _control_guard(desc: str, confirm: bool):
    if not CONTROL_ON:
        return "Fare/klavye kontrolü kapalı (Ayarlar → Ekran kontrolü)."
    if (confirm or RISKY_CLICK.search(desc or "")) and not ask(True, f"Ekranda şu işlemi yapmamı onaylıyor musun? {desc}"):
        return "Kullanıcı onaylamadı."
    _hide_for_control()
    return None


def _after(msg: str, delay: float = 0.7):
    time.sleep(delay)                      # arayüz tepki versin
    return _shot(msg)


def tool_click(x: float, y: float, button: str = "left", double: bool = False, confirm: bool = False, what: str = ""):
    """Son ekran görüntüsündeki (x, y) noktasına tıkla (0-1000 normalize)."""
    import screen_control as sc
    err = _control_guard(what or f"({x:.0f}, {y:.0f}) noktasına tıklama", confirm)
    if err:
        return err
    px, py = sc.to_pixels(x, y, _rect())
    sc.click_px(px, py, button, 2 if double else 1)
    return _after(f"{'Çift ' if double else ''}{'sağ ' if button == 'right' else ''}tıklandı ({x:.0f}, {y:.0f}).")


def _locate_vision(target: str):
    """Gemini'ye ekran görüntüsünü gösterip öğenin konumunu sorar. (x, y) 0-1000 veya None."""
    import screen_control as sc
    hid = False
    if screen_hook and not capture_excluded and not _ctrl["hidden"]:
        screen_hook("hide")
        hid = True
        time.sleep(0.4)
    try:
        img, rect = sc.capture(max_side=1920, quality=85)
    finally:
        if hid:
            screen_hook("show")
    _ctrl["rect"] = rect
    prompt = (f"Bu bir bilgisayar ekranının görüntüsü. Şu öğeyi bul: \"{target}\".\n"
              "Sadece JSON döndür: {\"found\": true/false, \"x\": sayı, \"y\": sayı, \"label\": \"öğenin üzerindeki yazı veya kısa tarifi\"}.\n"
              "x soldan sağa, y yukarıdan aşağıya, ikisi de 0-1000 arası normalize; öğenin tam ortasını ver. "
              "Emin değilsen veya ekranda yoksa found=false yaz.")
    txt = _gemini_oneshot([types.Part.from_bytes(data=img, mime_type="image/jpeg"), types.Part(text=prompt)], json_mode=True)
    if not txt:
        return None
    try:
        m = re.search(r"\{.*\}", txt, re.S)
        d = json.loads(m.group(0)) if m else {}
        if d.get("found") and d.get("x") is not None and d.get("y") is not None:
            return float(d["x"]), float(d["y"]), str(d.get("label", ""))
    except Exception as e:
        dbg(f"[konum JSON okunamadı: {e}: {txt[:200]}]")
    return None


def tool_click_element(target: str, label: str = "", button: str = "left", double: bool = False, confirm: bool = False):
    """Tarifi/yazısı verilen ekran öğesine tıkla: önce Windows erişilebilirlik ağacında (kesin konum) arar, bulamazsa görüntüden bulur."""
    import screen_control as sc
    err = _control_guard(f"{target} {label}".strip(), confirm)
    if err:
        return err
    hit = sc.uia_find(label or target) if (label or len(target.split()) <= 4) else None
    if hit:
        px, py, name = hit
        sc.click_px(px, py, button, 2 if double else 1)
        return _after(f"'{name}' öğesine tıklandı (erişilebilirlik ağacından bulundu).")
    loc = _locate_vision(f"{target}" + (f" (üzerinde '{label}' yazıyor)" if label else ""))
    if not loc:
        return _shot(f"'{target}' ekranda bulunamadı. Görüntüye bakıp click ile koordinat vererek dene, ya da önce kaydır/pencereyi öne getir.")
    x, y, seen = loc
    px, py = sc.to_pixels(x, y, _rect())
    sc.click_px(px, py, button, 2 if double else 1)
    return _after(f"'{seen or target}' öğesine tıklandı ({x:.0f}, {y:.0f}). Doğru yere tıklandığını görüntüden kontrol et.")


def tool_scroll(direction: str = "down", amount: int = 5, x: float = None, y: float = None):
    import screen_control as sc
    err = _control_guard("", False)
    if err:
        return err
    px = py = None
    if x is not None and y is not None:
        px, py = sc.to_pixels(x, y, _rect())
    sc.scroll(direction, amount, px, py)
    return _after(f"{direction} yönüne {amount} birim kaydırıldı.", 0.5)


def tool_mouse_move(x: float, y: float):
    import screen_control as sc
    err = _control_guard("", False)
    if err:
        return err
    sc.move_px(*sc.to_pixels(x, y, _rect()))
    return _after("Fare oraya götürüldü.", 0.5)


def tool_drag(x1: float, y1: float, x2: float, y2: float):
    import screen_control as sc
    err = _control_guard("sürükle-bırak", False)
    if err:
        return err
    r = _rect()
    sc.drag_px(*sc.to_pixels(x1, y1, r), *sc.to_pixels(x2, y2, r))
    return _after("Sürüklendi.")


def tool_wait(seconds: float = 2, window: str = ""):
    """Bir süre bekle (uygulama/sayfa yüklensin) ya da başlığında `window` geçen pencere açılana kadar bekle."""
    if window:
        w = _wait_window(window, min(20.0, float(seconds or 8)))
        return f"'{w.title}' penceresi hazır ve öne getirildi." if w else f"'{window}' penceresi {seconds} sn içinde açılmadı."
    time.sleep(max(0.2, min(15.0, float(seconds))))
    return "Beklendi."


# ---- Web: güncel bilgi ve sayfa okuma (tarayıcı açmadan) ----
def _strip_html(html: str) -> str:
    import html as _h
    t = re.sub(r"(?is)<(script|style|noscript|svg|head|nav|footer|form)\b.*?</\1>", " ", html)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>|</tr>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _h.unescape(t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def tool_read_webpage(url: str, max_chars: int = 8000):
    if not url.startswith("http"):
        url = "https://" + url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                                                   "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"})
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read(3_000_000)
            enc = r.headers.get_content_charset() or "utf-8"
        return _strip_html(raw.decode(enc, "ignore"))[: int(max_chars)] or "Sayfada okunabilir metin yok."
    except Exception as e:
        return f"Sayfa okunamadı: {e}"


def _ddg(query: str):
    req = urllib.request.Request("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query),
                                 headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    html = urllib.request.urlopen(req, timeout=12).read().decode("utf-8", "ignore")
    out = []
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>', html, re.S):
        href = urllib.parse.unquote(re.sub(r"^.*?uddg=([^&]+).*$", r"\1", m.group(1)))
        out.append(f"- {_strip_html(m.group(2))}: {_strip_html(m.group(3))} ({href})")
        if len(out) >= 6:
            break
    return "\n".join(out)


def tool_web_research(query: str):
    """Güncel bilgi (hava durumu, kur, haber, maç sonucu, fiyat...): Google arama destekli Gemini, olmazsa DuckDuckGo özetleri."""
    if os.getenv("GEMINI_API_KEY"):
        try:
            cfg = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
            ans = _gemini_oneshot([types.Part(text=f"Bugün {time.strftime('%d.%m.%Y')}. Web'de arayarak kısa ve doğru cevapla "
                                                      f"(Türkçe, en fazla 5 cümle, rakam/tarih ver, kaynağın adını söyle): {query}")],
                                  config=cfg)
            if ans:
                return ans
        except Exception as e:
            dbg(f"[Google arama hatası: {e}]")
    try:
        res = _ddg(query)
        if res:
            return "Arama sonuçları (gerekirse read_webpage ile birini aç):\n" + res
    except Exception as e:
        dbg(f"[DuckDuckGo hatası: {e}]")
    return "Web araması yapılamadı. web_search ile tarayıcıda açabilirim."


# ---- Akıllı silme: Geri Dönüşüm Kutusu'na gönderir; büyük, uzun süredir duran veya kritik yerlerdeki şeyler için onay ister ----
# .env: JARVIS_DEL_ASK_GB (varsayılan 1) · JARVIS_DEL_ASK_DAYS (varsayılan 180: bu kadar gündür dokunulmamışsa önemli olabilir, sorar)
DEL_ASK_GB = float(os.getenv("JARVIS_DEL_ASK_GB", "1"))
DEL_ASK_DAYS = float(os.getenv("JARVIS_DEL_ASK_DAYS", "180"))


def _protected(p: Path) -> bool:
    """Sistem klasörleri, sürücü kökleri ve kullanıcının ana klasörleri (Masaüstü, Belgeler... kendisi): her zaman onay."""
    p = p.resolve()
    home = Path.home().resolve()
    if p == Path(p.anchor) or p == home or home.is_relative_to(p):
        return True
    temp = Path(tempfile.gettempdir()).resolve()
    if p != temp and p.is_relative_to(temp):      # geçici dosyalar serbest
        return False
    win = Path(os.getenv("SystemRoot", r"C:\Windows")).resolve()
    sys_dirs = [win, Path(os.getenv("ProgramFiles", r"C:\Program Files")), Path(os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")),
                Path(os.getenv("ProgramData", r"C:\ProgramData")), home / "AppData"]
    if any(p == d.resolve() or p.is_relative_to(d.resolve()) for d in sys_dirs):
        return True
    return p.parent == home       # Desktop, Documents, Downloads, Pictures... klasörünün kendisi


def _scan(p: Path, limit_s=12.0):
    """(toplam bayt, en son değişiklik zamanı, dosya sayısı, tamamlandı mı)"""
    if p.is_file():
        st = p.stat()
        return st.st_size, st.st_mtime, 1, True
    total, newest, n, t0 = 0, p.stat().st_mtime, 0, time.time()
    for r, ds, fs in os.walk(p):
        for f in fs:
            try:
                st = os.stat(os.path.join(r, f))
            except OSError:
                continue
            total, newest, n = total + st.st_size, max(newest, st.st_mtime), n + 1
        if time.time() - t0 > limit_s:
            return total, newest, n, False
    return total, newest, n, True


def _human(b: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024 or u == "TB":
            return f"{b:.1f} {u}" if u in ("GB", "TB") else f"{b:.0f} {u}"
        b /= 1024


def tool_delete_path(path: str, permanent: bool = False):
    p = Path(path).expanduser()
    if not p.exists():
        return "Yol bulunamadı."
    size, newest, n, done = _scan(p)
    days = (time.time() - newest) / 86400
    info = f"{p.name}: {_human(size)}{'+' if not done else ''}, {n} dosya, en son {days:.0f} gün önce değişmiş"
    why = []
    if _protected(p):
        why.append("sistem veya ana kullanıcı klasörü")
    if size >= DEL_ASK_GB * 1024 ** 3 or not done:
        why.append("büyük")
    if days >= DEL_ASK_DAYS:
        why.append("uzun süredir duruyor, önemli olabilir")
    if permanent:
        why.append("kalıcı silme, geri alınamaz")
    if why and not ask(True, f"{info} ({', '.join(why)}). Silmemi onaylıyor musun?"):
        return "Kullanıcı onaylamadı."
    try:
        if permanent or not IS_WIN:
            import shutil
            shutil.rmtree(p) if p.is_dir() else p.unlink()
        else:
            fn = "DeleteDirectory" if p.is_dir() else "DeleteFile"
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                                "Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::"
                                f"{fn}($env:JARVIS_DEL, 'OnlyErrorDialogs', 'SendToRecycleBin')"],
                               capture_output=True, text=True, errors="replace", timeout=300, creationflags=NOWIN,
                               env={**os.environ, "JARVIS_DEL": str(p.resolve())})
            if p.exists():
                return f"Silinemedi: {(r.stderr or r.stdout).strip()[:300]}"
    except Exception as e:
        return f"Silme hatası: {e}"
    return f"Silindi ({'kalıcı' if permanent or not IS_WIN else 'Geri Dönüşüm Kutusu'}): {info}"


# ---- Güvenli indirme: HTTPS, şüpheli adres kontrolü, (varsa) Google Safe Browsing, boyut sınırı, Windows Defender taraması ----
# .env: JARVIS_DL_ASK_GB (varsayılan 2) · JARVIS_SAFEBROWSING_KEY (isteğe bağlı Google Safe Browsing API anahtarı)
DL_ASK_GB = float(os.getenv("JARVIS_DL_ASK_GB", "2"))
TRUSTED_HOSTS = ("github.com", "githubusercontent.com", "microsoft.com", "windows.net", "python.org", "pythonhosted.org", "nodejs.org",
                 "google.com", "googleapis.com", "mozilla.org", "videolan.org", "7-zip.org", "git-scm.com", "visualstudio.com",
                 "nvidia.com", "amd.com", "intel.com", "steampowered.com", "discord.com", "spotify.com", "anthropic.com", "claude.ai",
                 "ollama.com", "obsproject.com", "blender.org", "gimp.org", "libreoffice.org", "apache.org", "oracle.com",
                 "jetbrains.com", "docker.com", "zoom.us", "whatsapp.com", "telegram.org", "brave.com", "opera.com", "epicgames.com",
                 "huggingface.co", "sourceforge.net", "wikipedia.org", "wikimedia.org", "archive.org")
SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "cutt.ly", "ow.ly", "rebrand.ly", "shorturl.at", "rb.gy")
BAD_TLDS = (".zip", ".mov", ".tk", ".ml", ".ga", ".cf", ".gq", ".xyz", ".top", ".click", ".rest", ".country", ".work")
EXEC_EXT = (".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".jar", ".scr", ".com", ".pif", ".hta", ".lnk", ".reg", ".dll", ".apk")
_DL_REASONS = {"MALWARE": "zararlı yazılım", "SOCIAL_ENGINEERING": "oltalama", "UNWANTED_SOFTWARE": "istenmeyen yazılım",
               "POTENTIALLY_HARMFUL_APPLICATION": "zararlı uygulama"}


def _trusted(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in TRUSTED_HOSTS)


def _url_problems(url: str) -> tuple:
    """(engelleyici sorunlar, onay gerektiren uyarılar)"""
    u = urllib.parse.urlparse(url)
    host = (u.hostname or "").lower()
    block, warn = [], []
    if u.scheme not in ("http", "https") or not host:
        block.append("geçersiz adres")
        return block, warn
    if u.scheme == "http":
        warn.append("şifresiz bağlantı (http)")
    if re.fullmatch(r"[\d.]+|\[?[0-9a-f:]+\]?", host):
        warn.append("alan adı yerine IP adresi")
    if host in SHORTENERS:
        warn.append("kısaltılmış link")
    if host.endswith(BAD_TLDS) or host.startswith("xn--") or ".xn--" in host:
        warn.append("şüpheli alan adı")
    if u.username or "@" in u.netloc:
        warn.append("adreste gizlenmiş kullanıcı bilgisi")
    key = os.getenv("JARVIS_SAFEBROWSING_KEY")
    if key:
        try:
            r = _http_json("https://safebrowsing.googleapis.com/v4/threatMatches:find?key=" + key, payload={
                "client": {"clientId": "jarvis", "clientVersion": "1.0"},
                "threatInfo": {"threatTypes": list(_DL_REASONS), "platformTypes": ["ANY_PLATFORM"],
                               "threatEntryTypes": ["URL"], "threatEntries": [{"url": url}]}}, timeout=15)
            for m in r.get("matches", []):
                block.append("Google Safe Browsing: " + _DL_REASONS.get(m.get("threatType"), "tehlikeli"))
        except Exception as e:
            dbg(f"[Safe Browsing hatası: {e}]")
    return block, warn


def _defender_scan(path: Path):
    """True: temiz, False: tehdit bulundu, None: taranamadı"""
    exe = Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "Windows Defender" / "MpCmdRun.exe"
    if not IS_WIN or not exe.exists():
        return None
    try:
        r = subprocess.run([str(exe), "-Scan", "-ScanType", "3", "-File", str(path), "-DisableRemediation"],
                           capture_output=True, text=True, errors="replace", timeout=600, creationflags=NOWIN)
        return {0: True, 2: False}.get(r.returncode)
    except Exception:
        return None


def _download_job(url: str, dest: Path):
    tmp = dest.with_name(dest.name + ".part")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Jarvis/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        with open(tmp, "rb") as f:
            head = f.read(4)
        if head[:2] == b"MZ" and dest.suffix.lower() not in EXEC_EXT:   # .pdf görünümlü program
            tmp.unlink()
            return _say(f"{dest.name} indirildi ama aslında bir program dosyasıydı. Güvenli olmadığı için sildim.")
        tmp.replace(dest)
        clean = _defender_scan(dest)
        if clean is False:
            dest.unlink(missing_ok=True)
            return _say(f"Windows Defender {dest.name} dosyasında tehdit buldu, dosyayı sildim.")
        _say(f"{dest.name} indirildi, {_human(dest.stat().st_size)}." + (" Defender taraması temiz." if clean else ""))
    except Exception as e:
        tmp.unlink(missing_ok=True)
        _say(f"İndirme başarısız oldu: {str(e)[:150]}")


def tool_download_file(url: str, folder: str = "", filename: str = ""):
    url = url.strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    block, warn = _url_problems(url)
    final, size, ctype = url, None, ""
    try:   # yönlendirmeleri takip et: asıl dosyanın adresini, boyutunu ve türünü öğren
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0 Jarvis/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            final, ctype = r.geturl(), r.headers.get("Content-Type", "")
            size = int(r.headers.get("Content-Length") or 0) or None
            cd = r.headers.get("Content-Disposition") or ""
            m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
            if m and not filename:
                filename = urllib.parse.unquote(m.group(1))
    except Exception as e:
        dbg(f"[HEAD hatası: {e}]")
    if final != url:
        b2, w2 = _url_problems(final)
        block, warn = block + b2, warn + [w for w in w2 if w not in warn]
    if block:
        return "İndirmedim, link güvenli değil: " + ", ".join(block)
    if "text/html" in ctype and not filename:
        return "Bu link bir dosya değil, web sayfası. Doğrudan indirme linkini bulmam gerek (ör. sayfayı aç ya da web_search ile ara)."
    name = re.sub(r'[<>:"/\\|?*]', "_", filename or Path(urllib.parse.urlparse(final).path).name or "indirilen_dosya")
    host = (urllib.parse.urlparse(final).hostname or "").lower()
    if name.lower().endswith(EXEC_EXT) and not _trusted(host):
        warn.append(f"bilinmeyen siteden program dosyası ({host})")
    if size and size >= DL_ASK_GB * 1024 ** 3:
        warn.append(f"büyük dosya ({_human(size)})")
    if warn and not ask(True, f"{name} indirilecek. Dikkat: {', '.join(warn)}. Devam edeyim mi?"):
        return "Kullanıcı onaylamadı."
    dest_dir = Path(folder).expanduser() if folder else Path(tool_special_folder("downloads"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    i = 1
    while dest.exists():
        dest = dest_dir / f"{Path(name).stem} ({i}){Path(name).suffix}"
        i += 1
    threading.Thread(target=_download_job, args=(final, dest), daemon=True).start()
    return f"{name} indiriliyor ({_human(size) if size else 'boyut bilinmiyor'}) -> {dest_dir}. Bitince haber vereceğim."


# ---- Claude Code köprüsü: karmaşık yazılım işleri, bilgisayarda kurulu Claude Code'a (Pro aboneliği) devredilir ----
# .env: JARVIS_CLAUDE=off (kapatır) · JARVIS_CLAUDE_DIR (varsayılan çalışma klasörü) · JARVIS_CLAUDE_MODEL (ör. sonnet, opus)
#       JARVIS_CLAUDE_TOOLS (ek izinli araçlar, ör. "Bash(python *) Bash(pip *)") · JARVIS_CLAUDE_TIMEOUT (saniye, varsayılan 1200)
CLAUDE_ON = os.getenv("JARVIS_CLAUDE", "on").lower() != "off"
CLAUDE_TIMEOUT = int(os.getenv("JARVIS_CLAUDE_TIMEOUT", "1200"))
CLAUDE_NOTE = ("Bu görev sesli asistan JARVIS üzerinden geldi; kullanıcı ekrana bakmıyor olabilir, soru soramazsın. "
               "İşi baştan sona kendin bitir. Son mesajın Türkçe, markdown'sız (ters tırnak, yıldız yok), en fazla 2-3 cümlelik ve sesli okunacak "
               "bir özet olsun: ne yaptın, hangi dosyalar değişti, kullanıcının yapması gereken bir şey var mı.")
CLAUDE_DENY = [f"Bash({c} *)" for c in ("rm", "rmdir", "del", "erase", "rd", "Remove-Item", "ri", "format", "diskpart",
                                         "curl", "wget", "Invoke-WebRequest", "iwr", "Start-BitsTransfer", "git push", "git reset")]
_claude = {"busy": False, "dir": None, "session": None, "task": ""}


def _claude_bin():
    import shutil
    return shutil.which("claude") or next((str(p) for p in (Path.home() / ".local/bin/claude.exe", Path.home() / ".local/bin/claude")
                                           if p.exists()), None)


def _claude_default_dir() -> Path:
    if os.getenv("JARVIS_CLAUDE_DIR"):
        return Path(os.getenv("JARVIS_CLAUDE_DIR")).expanduser()
    for p in (Path.home() / "Desktop" / "Projelerim", Path.home() / "Documents"):
        if p.is_dir():
            return p
    return Path.home()


def _claude_run(task: str, cwd: Path, resume: str = None):
    """Arka planda çalışır: claude -p, bitince sonucu söyler."""
    exe = _claude_bin()
    args = [exe, "-p", "--output-format", "json", "--permission-mode", "acceptEdits", "--append-system-prompt", CLAUDE_NOTE]
    if os.getenv("JARVIS_CLAUDE_MODEL"):
        args += ["--model", os.getenv("JARVIS_CLAUDE_MODEL")]
    if os.getenv("JARVIS_CLAUDE_TOOLS"):
        args += ["--allowedTools", *os.getenv("JARVIS_CLAUDE_TOOLS").split()]
    args += ["--disallowedTools", *CLAUDE_DENY]    # onaysız çalıştığı için silme/indirme komutları her zaman yasak
    if resume:
        args += ["--resume", resume]
    t0 = time.time()
    try:
        r = subprocess.run(args, input=task, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=CLAUDE_TIMEOUT, creationflags=NOWIN)
        try:
            data = json.loads(r.stdout)
        except Exception:
            data = {"is_error": True, "result": (r.stdout + r.stderr).strip()[-500:] or f"çıkış kodu {r.returncode}"}
        dbg(f"[Claude] {time.time()-t0:.0f} sn, oturum {data.get('session_id')}")
        if data.get("session_id"):
            _claude["session"], _claude["dir"] = data["session_id"], cwd
        result = (data.get("result") or "").strip()
        if data.get("is_error") or r.returncode != 0:
            low = result.lower()
            if "limit" in low:
                msg = "Claude kullanım limitin doldu, iş yarım kaldı. Limit yenilenince 'Claude devam et' diyebilirsin."
            elif "login" in low or "auth" in low:
                msg = "Claude Code'da oturum açık değil. Terminalde bir kez claude yazıp giriş yapman gerekiyor."
            else:
                msg = "Claude işi bitiremedi: " + result[:200]
        else:
            msg = result or "Claude işi bitirdi."
            denied = data.get("permission_denials") or []
            if denied:
                msg += f" Not: Claude {len(denied)} komutu izin olmadığı için çalıştıramadı."
    except subprocess.TimeoutExpired:
        msg = f"Claude {CLAUDE_TIMEOUT // 60} dakikada bitiremedi, durdurdum."
    except Exception as e:
        msg = f"Claude başlatılamadı: {e}"
    finally:
        _claude["busy"] = False
    _remember("[Claude görevi] " + task[:300], msg)
    _say(msg)


def tool_claude_code(task: str, folder: str = "", continue_last: bool = False):
    if not CLAUDE_ON:
        return "Claude köprüsü kapalı (JARVIS_CLAUDE=off)."
    if not _claude_bin():
        return "Claude Code bu bilgisayarda kurulu değil."
    if _claude["busy"]:
        return f"Claude hâlâ önceki görev üzerinde çalışıyor: {_claude['task'][:80]}"
    resume = _claude["session"] if continue_last and _claude["session"] else None
    cwd = Path(folder).expanduser() if folder else (_claude["dir"] if resume else _claude_default_dir())
    if not cwd.is_dir():
        return f"Klasör bulunamadı: {cwd}"
    _claude.update(busy=True, task=task, dir=cwd)
    threading.Thread(target=_claude_run, args=(task, cwd, resume), daemon=True).start()
    _notify(f"🧠 Claude çalışıyor ({cwd}): {task[:120]}")
    return ("Görev Claude'a verildi, arka planda çalışıyor; bitince sonucu kendisi söyleyecek. "
            "Kullanıcıya sadece bunu kısaca söyle, işi kendin yapmaya çalışma.")


HANDLERS = {
    "screen_look": tool_screen_look,
    "dictation_start": lambda app="": dictation(app),
    "open_app": tool_open_app, "open_path": tool_open_path, "open_url": tool_open_url, "web_search": tool_web_search,
    "youtube_play": tool_youtube_play, "spotify_play": tool_spotify_play, "spotify_control": tool_spotify_control,
    "media_key": tool_media_key, "set_system_volume": tool_set_system_volume, "type_text": tool_type_text,
    "hotkey": tool_hotkey, "clipboard_get": tool_clipboard_get, "clipboard_set": tool_clipboard_set,
    "list_windows": tool_list_windows, "window_action": tool_window_action, "kill_process": tool_kill_process,
    "special_folder": tool_special_folder, "find_folder": tool_find_folder, "find_files": tool_find_files,
    "list_dir": tool_list_dir, "read_project": tool_read_project, "write_file": tool_write_file,
    "run_command": tool_run_command, "claude_code": tool_claude_code,
    "delete_path": tool_delete_path, "download_file": tool_download_file,
    "click": tool_click, "click_element": tool_click_element, "scroll": tool_scroll, "mouse_move": tool_mouse_move,
    "drag": tool_drag, "wait": tool_wait, "read_webpage": tool_read_webpage, "web_research": tool_web_research,
}
SCREEN_TOOLS = {"screen_look", "click", "click_element", "scroll", "mouse_move", "drag"}   # görüntü gerektirir: sadece Gemini'de


def _t(name, desc, props=None, req=None):
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props or {}, "required": req or []}}


S = {"type": "string"}
TOOLS = [
    _t("open_app", "Bilgisayarda YÜKLÜ herhangi bir uygulamayı adıyla aç (Spotify, Visual Studio Code, Chrome, Discord, Hesap Makinesi, Steam...).", {"name": S}, ["name"]),
    _t("open_path", "Bir dosyayı veya klasörü varsayılan uygulamasıyla aç.", {"path": S}, ["path"]),
    _t("open_url", "Tarayıcıda bir web sitesi aç.", {"url": S}, ["url"]),
    _t("web_search", "Google'da arama yap.", {"query": S}, ["query"]),
    _t("youtube_play", "YouTube'da arama yapıp ilk videoyu tarayıcıda aç.",
       {"query": S, "open_first_video": {"type": "boolean", "description": "false ise sadece arama sonuçlarını açar"}}, ["query"]),
    _t("spotify_play", "Spotify API'si ile şarkı/albüm/çalma listesi/sanatçı çal (API ayarlı değilse hata verir; o zaman open_app ile Spotify'ı aç ve media_key kullan).",
       {"query": S, "kind": {"type": "string", "enum": ["track", "album", "playlist", "artist"]}}, ["query"]),
    _t("spotify_control", "Spotify API ile kontrol.",
       {"action": {"type": "string", "enum": ["pause", "resume", "next", "previous", "volume", "now_playing"]},
        "volume": {"type": "integer", "description": "0-100, sadece volume için"}}, ["action"]),
    _t("media_key", "Medya tuşu bas: oynat/duraklat, sonraki, önceki, sessize al. Çalan herhangi bir medya uygulamasında (Spotify, YouTube...) çalışır.",
       {"action": {"type": "string", "enum": ["play_pause", "next", "previous", "mute"]}}, ["action"]),
    _t("set_system_volume", "Bilgisayarın ana ses seviyesini ayarla (0-100).", {"level": {"type": "integer"}}, ["level"]),
    _t("screen_look", "Kullanıcının ekranının o anki görüntüsünü al: ekranda ne var, hata mesajı, okunacak metin gibi sorular için ve "
       "ekranda bir şey yapmadan ÖNCE neyin nerede olduğunu görmek için. Konumlar 0-1000 normalize (x soldan, y yukarıdan)."),
    _t("click_element", "Ekrandaki bir öğeye tıkla (düğme, bağlantı, menü, sekme, arama kutusu, simge, liste öğesi...). Önce Windows erişilebilirlik "
       "bilgisinden kesin konumu arar, bulamazsa görüntüden bulur. Sonrasında yeni ekran görüntüsü döner: doğru olduğunu kontrol et. "
       "target: öğenin tarifi (ör. 'Chrome adres çubuğu', 'Kaydet düğmesi'). label: öğenin üzerinde görünen yazı (biliyorsan, aynen). "
       "confirm: silme, gönderme, satın alma gibi geri alınamaz bir düğmeyse true.",
       {"target": S, "label": S, "button": {"type": "string", "enum": ["left", "right"]}, "double": {"type": "boolean"},
        "confirm": {"type": "boolean"}}, ["target"]),
    _t("click", "Son ekran görüntüsündeki bir noktaya tıkla. x, y: 0-1000 normalize (x soldan sağa, y yukarıdan aşağıya). Konumu "
       "görüntüde net görüyorsan kullan; adı/yazısı olan öğeler için click_element daha güvenilir. what: neye tıkladığın (kısa).",
       {"x": {"type": "number"}, "y": {"type": "number"}, "button": {"type": "string", "enum": ["left", "right"]},
        "double": {"type": "boolean"}, "confirm": {"type": "boolean"}, "what": S}, ["x", "y"]),
    _t("scroll", "Fare tekerleğiyle kaydır. amount: tekerlek adımı (3-10 arası iyi). x, y verilirse önce oraya gider (o bölmeyi kaydırmak için).",
       {"direction": {"type": "string", "enum": ["up", "down", "left", "right"]}, "amount": {"type": "integer"},
        "x": {"type": "number"}, "y": {"type": "number"}}, ["direction"]),
    _t("mouse_move", "Fareyi bir noktaya götür (menü açmak için üzerine gelme). x, y: 0-1000.", {"x": {"type": "number"}, "y": {"type": "number"}}, ["x", "y"]),
    _t("drag", "Sürükle-bırak: (x1,y1)'den (x2,y2)'ye. Hepsi 0-1000.",
       {"x1": {"type": "number"}, "y1": {"type": "number"}, "x2": {"type": "number"}, "y2": {"type": "number"}}, ["x1", "y1", "x2", "y2"]),
    _t("wait", "Bekle: uygulama/sayfa yüklensin diye (seconds), ya da başlığında 'window' geçen pencere açılana kadar (açılınca öne getirir).",
       {"seconds": {"type": "number"}, "window": S}),
    _t("web_research", "İnternetten GÜNCEL bilgi bul ve cevabı getir (hava durumu, döviz, haber, maç, fiyat, açılış saati, bir konunun güncel durumu). "
       "Kullanıcı sadece bilgi istiyorsa tarayıcı açmak yerine bunu kullan.", {"query": S}, ["query"]),
    _t("read_webpage", "Bir web sayfasının metnini oku (özetlemek, bilgi çıkarmak için).", {"url": S}, ["url"]),
    _t("list_windows", "Şu an açık olan pencerelerin başlıklarını listele (VS Code'da hangi proje/dosya açık, hangi uygulamalar çalışıyor görmek için)."),
    _t("window_action", "Başlığında verilen kelime geçen pencereyi yönet.",
       {"title": S, "action": {"type": "string", "enum": ["focus", "minimize", "maximize", "restore", "close"]}}, ["title", "action"]),
    _t("kill_process", "Bir programı zorla kapat (işlem adıyla, ör. chrome, spotify, Code). Normal kapatma için window_action close kullan.", {"name": S}, ["name"]),
    _t("clipboard_get", "Panodaki (kopyalanmış) metni oku."),
    _t("clipboard_set", "Metni panoya kopyala.", {"text": S}, ["text"]),
    _t("type_text", "Aktif pencereye / seçili kutuya metin yaz (panodan yapıştırır). Bir kutuya yazmadan önce click_element ile kutuya tıkla. "
       "Uygulamayı yeni açtıysan window parametresine pencere başlığını yaz (ör. 'Not Defteri|Notepad'); pencere açılana kadar bekler. "
       "enter: yazdıktan sonra Enter'a bas.",
       {"text": S, "window": S, "enter": {"type": "boolean"}}, ["text"]),
    _t("dictation_start", "Dikte modu: kullanıcının sesle söylediklerini aktif pencereye yazar ('dikteyi bitir' diyene kadar). app verilirse önce o uygulamayı açar (ör. Not Defteri).",
       {"app": S}),
    _t("hotkey", "Klavye tuşu veya kısayolu bas, ör. ['ctrl','s'], ['enter'], ['alt','tab'], ['win','d'], ['ctrl','l'], ['f5'], ['esc'].",
       {"keys": {"type": "array", "items": S}}, ["keys"]),
    _t("special_folder", "Özel klasörün gerçek yolunu bul.",
       {"name": {"type": "string", "enum": ["desktop", "documents", "downloads", "pictures", "music", "videos"]}}, ["name"]),
    _t("find_folder", "Kullanıcının bilgisayarında klasör adına göre proje klasörünün tam yolunu bul.", {"name": S}, ["name"]),
    _t("find_files", "Dosya adında geçen kelimeyle dosya ara.", {"pattern": S, "folder": S, "max_results": {"type": "integer"}}, ["pattern"]),
    _t("list_dir", "Bir klasörün içeriğini listele.", {"path": S}, ["path"]),
    _t("read_project", "Bir klasördeki tüm kod dosyalarını (veya tek bir dosyayı) oku. Hata bulma / kod inceleme için.", {"path": S}, ["path"]),
    _t("write_file", "Dosya yaz/üzerine yaz (var olan dosyanın üzerine yazarken onay ister).", {"path": S, "content": S}, ["path", "content"]),
    _t("run_command", "PowerShell komutu çalıştır (kurulum, sistem bilgisi, dosya işlemleri, her şey). Tehlikeli komutlarda sistem onay ister.",
       {"command": S, "shell": {"type": "string", "enum": ["powershell", "cmd"]}}, ["command"]),
    _t("delete_path", "Dosya veya klasör sil (varsayılan: Geri Dönüşüm Kutusu'na). Silme için run_command yerine HEP bunu kullan. "
       "Büyük, uzun süredir dokunulmamış veya sistem klasörlerindeki şeyler için sistem kendisi onay ister. permanent: kalıcı sil (sadece kullanıcı açıkça isterse).",
       {"path": S, "permanent": {"type": "boolean"}}, ["path"]),
    _t("download_file", "İnternetten dosya indir (varsayılan: İndirilenler). İndirme için run_command/curl yerine HEP bunu kullan. "
       "Linki güvenlik açısından kontrol eder, indirilen dosyayı Windows Defender ile tarar, arka planda indirir. url doğrudan dosya linki olmalı; "
       "programlar için resmi siteyi tercih et (ör. github.com, üreticinin kendi sitesi).",
       {"url": S, "folder": S, "filename": S}, ["url"]),
    _t("claude_code", "Karmaşık yazılım işlerini (kod/program/script/site yazma, proje oluşturma, hata ayıklama, refactor, birden çok dosyayı "
       "değiştirme) güçlü kodlama asistanı Claude'a devret. Arka planda çalışır, bitince sonucu kendisi söyler. "
       "task: kullanıcının isteğinin eksiksiz, ayrıntılı tarifi. folder: çalışılacak proje klasörünün tam yolu (biliniyorsa; "
       "gerekirse önce find_folder / list_windows ile bul; yeni proje için boş bırak). continue_last: önceki Claude işine devam/düzeltme ise true.",
       {"task": S, "folder": S, "continue_last": {"type": "boolean"}}, ["task"]),
]


# ----------------------------------------------------------------------------------------------
# BEYİN: Gemini + araç döngüsü (yoğunlukta otomatik tekrar deneme ve yedek model)
# ----------------------------------------------------------------------------------------------
FAST_TOOLS = {"open_app", "open_url", "web_search", "youtube_play", "open_path", "spotify_play", "spotify_control",
              "set_system_volume", "media_key", "window_action", "clipboard_set"}
TRANSIENT = ("503", "UNAVAILABLE", "500", "INTERNAL", "504", "DEADLINE", "overloaded", "high demand")
_thinking_on = os.getenv("JARVIS_THINKING", "low").lower() != "off"   # .env: JARVIS_THINKING=off|minimal|low|medium|high
_no_think = set()        # düşünme ayarını desteklemeyen modeller
_bad_level = set()       # (model, seviye): bu düşünme seviyesini desteklemiyor
_config_cache = {}
_fb_cache = None
_cooldown = {}           # model -> bu zamana kadar atla (limiti dolmuş / yoğun)
_dead = set()            # bu hesapta bulunamayan (404) modeller
_active = {"model": MODEL}


def _upper_types(schema):
    """JSON şemasındaki tip adlarını Gemini'nin beklediği büyük harfe çevirir."""
    if isinstance(schema, dict):
        return {k: (v.upper() if k == "type" and isinstance(v, str) else _upper_types(v)) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_upper_types(x) for x in schema]
    return schema


def build_gemini_tools():
    decls = []
    for t in TOOLS:
        sch = t["input_schema"]
        params = _upper_types(sch) if sch["properties"] else None   # parametresiz araçlarda boş şema hata verir
        if params and not params.get("required"):
            params.pop("required", None)
        decls.append(types.FunctionDeclaration(name=t["name"], description=t["description"], parameters=params))
    return [types.Tool(function_declarations=decls)]


def _get_client():
    global client
    if client is None:
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return client


def _make_config(model: str, level: str = None):
    """level: düşünme seviyesi (low / medium / high). Basit komutlar 'low' ile hızlı, karmaşık işler daha derin düşünür."""
    level = (level or os.getenv("JARVIS_THINKING", "low")).lower()
    if (model, level) in _bad_level:
        level = "low"
    use = _thinking_on and model not in _no_think and (model, level) not in _bad_level
    key = (model, level if use else None)
    if key not in _config_cache:
        kw = dict(system_instruction=SYSTEM, tools=build_gemini_tools(),
                  automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
        if use:
            try:
                kw["thinking_config"] = types.ThinkingConfig(thinking_level=level)
            except Exception:
                pass
        _config_cache[key] = types.GenerateContentConfig(**kw)
    return _config_cache[key]


def _fallback_models():
    """Yedek Gemini modelleri: .env'deki JARVIS_FALLBACK, yoksa hesabındaki flash modelleri (yeniden eskiye, lite en sonda)."""
    global _fb_cache
    if _fb_cache is None:
        names = list(FALLBACKS)
        if not names:
            try:
                bad = ("image", "tts", "live", "audio", "embed", "native", "robotics", "computer", "vision", "imagen", "veo", "exp")
                found = {m.name.split("/")[-1] for m in _get_client().models.list()}
                cands = [n for n in found if re.match(r"^gemini-[\d.]+-flash(-lite)?(-[a-z]+)*$", n) and not any(b in n for b in bad)]

                def key(n):
                    ver = tuple(int(x) for x in re.match(r"^gemini-([\d.]+)-flash", n).group(1).split(".") if x.isdigit())
                    return (ver, "-lite" not in n)
                names = sorted(cands, key=key, reverse=True)
            except Exception:
                names = []
            names += [a for a in ("gemini-flash-latest", "gemini-flash-lite-latest") if a not in names]
        _fb_cache = [n for n in dict.fromkeys(names) if n != MODEL][:5]
    return _fb_cache


class GeminiExhausted(Exception):
    """Zincirdeki tüm Gemini modellerinin limiti dolu."""
    def __init__(self, wait: float):
        super().__init__("429 RESOURCE_EXHAUSTED: tüm Gemini modellerinin limiti doldu")
        self.wait = wait


def _model_chain():
    names = [MODEL] + _fallback_models()
    return [m for i, m in enumerate(names) if m not in names[:i] and m not in _dead]


def _generate(level: str = None):
    """Önce ana model; limiti dolarsa (429) veya yoğunsa (503) sıradaki Gemini modeline geç.
    Limiti dolan model bir süre atlanır, böylece her komutta boşuna denenmez."""
    return _gemini_call(lambda model: _get_client().models.generate_content(
        model=model, contents=history, config=_make_config(model, level)), level)


def _gemini_call(fn, level=None):
    chain = _model_chain()
    now = time.time()
    avail = [m for m in chain if _cooldown.get(m, 0) <= now]
    if not avail:
        raise GeminiExhausted(max(30.0, min(_cooldown.get(m, now) for m in chain) - now) if chain else 60.0)
    last = None
    for model in avail:
        retries = 0
        while True:
            try:
                resp = fn(model)
                if _active["model"] != model:
                    _active["model"] = model
                    dbg(f"[aktif Gemini modeli: {model}]")
                    if usage_hook:
                        usage_hook(cost_summary())
                return resp
            except Exception as e:
                last, msg = e, str(e)
                if "API key not valid" in msg or "API_KEY_INVALID" in msg:
                    raise
                lv = (level or os.getenv("JARVIS_THINKING", "low")).lower()
                if _thinking_on and "thinking" in msg.lower() and model not in _no_think:
                    if lv != "low" and (model, lv) not in _bad_level:
                        _bad_level.add((model, lv))    # bu seviye desteklenmiyor: önce 'low' dene
                        level = "low"
                    else:
                        _no_think.add(model)           # düşünme ayarını hiç desteklemiyor: ayarsız tekrar dene
                    continue
                if "404" in msg or "NOT_FOUND" in msg:
                    _dead.add(model)               # bu hesapta yok: bir daha deneme
                    break
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    if re.search(r"per ?day|PerDay", msg, re.I):
                        wait = 1200.0              # günlük limit: 20 dk sonra tekrar bak
                    else:
                        m = re.search(r"retry in (\d+(?:\.\d+)?)|retryDelay'?: ?'?(\d+)", msg)
                        wait = min(120.0, float(m.group(1) or m.group(2)) + 2) if m else 70.0
                    _cooldown[model] = time.time() + wait
                    dbg(f"[{model} limiti doldu, {wait:.0f} sn atlanacak]")
                    break
                if any(k in msg for k in TRANSIENT):
                    if retries < 2:
                        retries += 1
                        time.sleep((1.0, 2.5)[retries - 1])
                        continue
                    _cooldown[model] = time.time() + 45
                    break
                break                              # başka bir hata: sıradaki modeli dene
    now = time.time()
    if all(_cooldown.get(m, 0) > now for m in chain):
        raise GeminiExhausted(max(30.0, min(_cooldown[m] for m in chain) - now))
    raise last


def _gemini_oneshot(parts, json_mode: bool = False, config=None):
    """Araçsız, geçmişsiz tek Gemini isteği (ekranda öğe bulma, web araştırması). Metin veya None döner."""
    if not os.getenv("GEMINI_API_KEY"):
        return None

    def fn(model):
        kw = {}
        if json_mode:
            kw["response_mime_type"] = "application/json"
        if _thinking_on and model not in _no_think and (model, "low") not in _bad_level:
            try:
                kw["thinking_config"] = types.ThinkingConfig(thinking_level="low")
            except Exception:
                pass
        cfg = config
        if cfg is None:
            cfg = types.GenerateContentConfig(**kw)
        elif "thinking_config" in kw and getattr(cfg, "thinking_config", None) is None:
            try:
                cfg = cfg.model_copy(update={"thinking_config": kw["thinking_config"]})
            except Exception:
                pass
        return _get_client().models.generate_content(model=model, contents=[types.Content(role="user", parts=parts)], config=cfg)

    try:
        resp = _gemini_call(fn, "low")
        _track_usage(resp)
        c = resp.candidates[0].content if resp.candidates else None
        return "".join(p.text for p in (c.parts or []) if getattr(p, "text", None)).strip() if c else None
    except Exception as e:
        dbg(f"[Gemini tek istek hatası: {str(e)[:200]}]")
        return None


def _simple_request(t: str) -> bool:
    """Tek adımlık kısa komut mu? (ikinci model çağrısını atlamak için)"""
    t = t.lower()
    return len(t.split()) <= 8 and not re.search(r"\b(ve|sonra|ardından|ayrıca)\b|\w{2,}[ıiuü]p\b", t)


def _looks_failed(out: str) -> bool:
    o = out.lower()
    return any(w in o for w in ("hata", "bulunamadı", "açılamadı", "onaylamadı", "geçersiz", "başlatılmaya çalışıldı"))


def _is_plain_user(c):
    parts = c.parts or []
    return c.role == "user" and any(p.text for p in parts) and not any(p.function_response for p in parts)


def _drop_old_images():
    for c in history:
        if c.parts:
            c.parts = [p for p in c.parts if not getattr(p, "inline_data", None)]


def _trim(keep=6):
    idx = [i for i, c in enumerate(history) if _is_plain_user(c)]
    if len(idx) > keep:
        del history[:idx[-keep]]


def local_command(text: str):
    """Basit ve kalıplı komutları Gemini'ye göndermeden yapar: anında çalışır, API limiti harcamaz.
    Tanıyamazsa None döner, o zaman iş Gemini'ye gider."""
    t = text.lower().strip().rstrip(".!?")
    t = re.sub(r"\blütfen\b|\b(mısın|misin|musun|müsün)\b", "", t)
    t = re.sub(r"\b(açar|açsana|açabilir)\b", "aç", t)
    t = re.sub(r"\s+", " ", t).strip(" ,")
    m = re.match(r"^(?:(.+?) aç(?:ıp| ve|,)? )?(?:söylediklerimi|konuştuklarımı|dediklerimi|söylediğimi) yaz$", t)
    if m:
        return dictation(re.sub(r"['’`]\w{1,3}$", "", (m.group(1) or "").strip()))
    if re.match(r"^dikte(?: modu(?:nu)?)?(?: başlat| aç| et)?$", t):
        return dictation("")
    if re.search(r"\b(ve|sonra|ardından|ayrıca)\b|\w{2,}[ıiuü]p\b", t):
        return None          # çok adımlı komut: Gemini planlasın

    m = re.match(r"^youtube(?:['’]?(?:da|de|ta|te))? (.+?) (?:aç|oynat|izle|çal)$", t) \
        or re.match(r"^(.+?) youtube(?:['’]?(?:da|de|ta|te))? (?:aç|oynat|izle|çal)$", t)
    if m:
        tool_youtube_play(m.group(1))
        return f"YouTube'da {m.group(1)} açılıyor."

    if re.match(r"^(?:saat kaç|saat kaç oldu|şu an saat kaç)$", t):
        return "Saat " + time.strftime("%H:%M") + "."
    if re.match(r"^(?:bugün (?:günlerden ne|ayın kaçı|ne günü)|tarih ne|bugünün tarihi ne)$", t):
        lt = time.localtime()
        return f"Bugün {lt.tm_mday} {['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'][lt.tm_mon-1]}, {_GUN[lt.tm_wday]}."
    m = re.match(r"^(?:sesi )?(aç|yükselt|arttır|artır|kıs|azalt|düşür)$", t) or re.match(r"^sesi (?:biraz )?(aç|yükselt|arttır|artır|kıs|azalt|düşür)$", t)
    if m and IS_WIN:
        up = m.group(1) in ("aç", "yükselt", "arttır", "artır")
        if t.startswith("sesi") or m.group(1) not in ("aç",):
            _pag().press("volumeup" if up else "volumedown", presses=5)
            return "Tamam."
    m = re.match(r"^(?:bu )?pencereyi (kapat|küçült|simge durumuna küçült|büyüt|tam ekran yap)$", t)
    if m and IS_WIN and _last_app_window():        # kapatılacak gerçek bir pencere yoksa Alt+F4 basma
        _hide_for_control()
        a = m.group(1)
        if a == "kapat":
            _pag().hotkey("alt", "f4")
        elif "küçült" in a:
            _pag().hotkey("win", "down")
        else:
            _pag().hotkey("win", "up")
        return "Tamam."
    sfx = r"(?:['’]?(?:dan|den|tan|ten|da|de|ta|te))?"
    m = re.match(r"^spotify" + sfx + r" (.+?) (?:çal|aç|oynat|dinle|dinlet|başlat)$", t) \
        or re.match(r"^(.+?) spotify" + sfx + r" (?:çal|aç|oynat|dinlet)$", t) \
        or (os.getenv("JARVIS_MUSIC", "spotify") == "spotify" and re.match(r"^(.+?) (?:çal|dinlet|şarkısını aç|şarkılarını aç)$", t))
    if m and not re.search(r"youtube", t):
        q = m.group(1).strip(" '\"’")
        if q in ("müziği", "müzik", "şarkıyı", "şarkı", "bir şey", "bir şarkı"):
            tool_media_key("play_pause")
            return "Tamam."
        kind = "album" if re.search(r"\balbüm", q) else "playlist" if re.search(r"çalma listesi|playlist", q) else "track"
        q = re.sub(r"\b(albümünü|albümü|albüm|çalma listesini|çalma listesi|playlist|şarkısını|şarkılarını|şarkısı)\b", "", q).strip()
        if q:
            return spotify_quick(q, kind)

    m = re.match(r"^ses(?:i|\s+seviyesini)? (?:yüzde |%)?(\d{1,3}) ?(?:yap|olsun|ayarla)?$", t)
    if m:
        return tool_set_system_volume(int(m.group(1)))

    m = re.match(r"^(?:müziği |şarkıyı |videoyu )?(durdur|duraklat|devam et|devam|oynat)$", t)
    if m:
        tool_media_key("play_pause")
        return "Tamam."
    if re.match(r"^(?:şarkıyı geç|(?:bir )?(?:sonraki|sıradaki)(?: şarkı| video)?)$", t):
        tool_media_key("next")
        return "Sonraki."
    if re.match(r"^(?:(?:bir )?önceki(?: şarkı| video)?|bir geri)$", t):
        tool_media_key("previous")
        return "Önceki."
    if re.match(r"^(?:sessize al|sesi kapat|sustur)$", t):
        tool_media_key("mute")
        return "Tamam."

    m = re.match(r"^google(?:['’]?(?:da|de))? (.+?) ara$", t)
    if m:
        tool_web_search(m.group(1))
        return f"{m.group(1)} aranıyor."

    m = re.match(r"^(.+?) (?:aç|başlat|çalıştır)$", t)
    if m:
        name = re.sub(r"['’`]\w{1,4}$", "", m.group(1).strip(" '\"’")).strip()
        # "Spotify'da Tarkan aç", "Chrome'da YouTube aç" gibi tamlamalı komutlar kısa yol değil: modele gitsin
        if not name or re.search(r"['’`]", name) or len(name.split()) > 3 or \
                re.search(r"klasör|dosya|sekme|pencere|pdf|belge|resim|video|şarkı|müzik|link|site|bana|bir |bu |şu |sayfa", name):
            return None
        if name == "youtube":
            tool_open_url("youtube.com")
            return "YouTube açılıyor."
        if re.search(r"\.(com|net|org|io|dev|ai|edu|gov|tr)\b", name):
            tool_open_url(name)
            return f"{name} açılıyor."
        if IS_WIN:
            match = _find_app_strict(name)
            if match:
                _launch_app(match)
                return f"{match.title()} açılıyor."
    return None


_APP_ALIAS = {"vs code": "visual studio code", "vscode": "visual studio code", "kod": "visual studio code",
              "not defteri": "notepad", "hesap makinesi": "calculator", "ayarlar": "settings", "chrome": "google chrome",
              "edge": "microsoft edge", "word": "word", "excel": "excel", "dosya gezgini": "file explorer",
              "görev yöneticisi": "task manager", "paint": "paint", "terminal": "terminal", "kamera": "camera"}


def _find_app_strict(name: str):
    """Yerel kısa yol için sıkı eşleşme: yanlış uygulamayı açmaktansa hiç açmayıp modele bırakmak daha iyi."""
    apps = _load_apps()
    cands = [name, _APP_ALIAS.get(name, name)]
    for suf in ("yı", "yi", "yu", "yü", "nı", "ni", "nu", "nü", "ı", "i", "u", "ü"):   # "spotifyı", "chromeu"
        if name.endswith(suf) and len(name) - len(suf) >= 3:
            base = name[: -len(suf)]
            cands += [base, _APP_ALIAS.get(base, base)]
    tr_names = {"notepad": "not defteri", "calculator": "hesap makinesi", "settings": "ayarlar",
                "file explorer": "dosya gezgini", "task manager": "görev yöneticisi", "camera": "kamera"}
    for c in dict.fromkeys(cands):
        for q in (c, tr_names.get(c, c)):
            if q in apps:
                return q
            words = [n for n in apps if re.search(r"(^|\s)" + re.escape(q) + r"(\s|$)", n)]
            if words:
                return min(words, key=len)
    close = difflib.get_close_matches(name, list(apps), n=1, cutoff=0.85)
    return close[0] if close else None


def warmup():
    """Arka planda ısınma: uygulama listesi, ses sistemi. İlk komut gecikmesin."""
    def _w():
        for fn in (_load_apps, _get_client):
            try:
                fn()
            except Exception:
                pass
        try:
            import pygame
            pygame.mixer.init()
        except Exception:
            pass
    threading.Thread(target=_w, daemon=True).start()


# ---- Harcama sayacı (tahmini) ----
USAGE_FILE = BASE / "usage.json"
_usage = None
_warned = set()


def _load_usage():
    global _usage
    if _usage is None:
        try:
            _usage = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        except Exception:
            _usage = {}
    return _usage


def cost_today_tl() -> float:
    return _load_usage().get(time.strftime("%Y-%m-%d"), {}).get("usd", 0.0) * USDTRY


def cost_month_tl() -> float:
    pre = time.strftime("%Y-%m")
    return sum(d.get("usd", 0.0) for k, d in _load_usage().items() if k.startswith(pre)) * USDTRY


def requests_today() -> int:
    return sum(_load_usage().get(time.strftime("%Y-%m-%d"), {}).get("req", {}).values())


def cost_summary() -> str:
    if BUDGET_TL > 0:
        return f"Tahmini harcama: bugün {cost_today_tl():.1f} TL · bu ay {cost_month_tl():.0f} / {BUDGET_TL:.0f} TL"
    p = _active_prov["name"]
    if p == "gemini":
        return f"Ücretsiz Gemini: bugün {requests_today()} istek · model: {_active['model']}"
    if p == "ollama":
        return f"Yerel model (Ollama) · Gemini bugün {requests_today()} istek"
    return f"Aktif: {p.upper()} · Gemini bugün {requests_today()} istek"


def _notify(text: str):
    if notify_hook:
        notify_hook(text)
    else:
        print(f"[Jarvis] {text}")


def _track_usage(resp):
    um = getattr(resp, "usage_metadata", None)
    if not um:
        return
    inp = getattr(um, "prompt_token_count", 0) or 0
    out = (getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0)
    d = _load_usage().setdefault(time.strftime("%Y-%m-%d"), {"in": 0, "out": 0, "usd": 0.0})
    d.setdefault("req", {})
    d["req"][_active["model"]] = d["req"].get(_active["model"], 0) + 1
    d["in"] += inp
    d["out"] += out
    d["usd"] += (inp * PRICE_IN + out * PRICE_OUT) / 1e6
    try:
        USAGE_FILE.write_text(json.dumps(_usage), encoding="utf-8")
    except Exception:
        pass
    month = time.strftime("%Y-%m")
    if BUDGET_TL > 0 and cost_month_tl() >= 0.8 * BUDGET_TL and month not in _warned:
        _warned.add(month)
        _notify(f"Dikkat: bu ayki tahmini Gemini harcaman bütçenin %80'ine ulaştı ({cost_month_tl():.0f} / {BUDGET_TL:.0f} TL).")
    if usage_hook:
        usage_hook(cost_summary())


# ---- Yerel model (Ollama) ----
LOCAL_TOOLS = {"open_app", "open_path", "open_url", "web_search", "youtube_play", "media_key", "set_system_volume",
               "list_windows", "window_action", "clipboard_get", "clipboard_set", "type_text", "hotkey", "dictation_start",
               "special_folder", "find_files", "list_dir", "run_command", "delete_path", "download_file"}   # küçük modeller çok araçta şaşırır: kısa liste
_local_model_cache = None


def _ollama(path: str, payload=None, timeout=180):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(OLLAMA_URL + path, data=data, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))


def _ollama_ready() -> bool:
    try:
        _ollama("/api/tags", timeout=3)
        return True
    except Exception:
        pass
    try:   # Ollama kapalıysa kendiliğinden başlatmayı dene
        subprocess.Popen(["ollama", "serve"], creationflags=NOWIN, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return False
    for _ in range(16):
        time.sleep(0.5)
        try:
            _ollama("/api/tags", timeout=3)
            return True
        except Exception:
            continue
    return False


def _local_model():
    global _local_model_cache
    if _local_model_cache:
        return _local_model_cache
    if LOCAL_MODEL:
        _local_model_cache = LOCAL_MODEL
        return LOCAL_MODEL
    try:
        installed = [m["name"] for m in _ollama("/api/tags", timeout=5).get("models", []) if "embed" not in m["name"]]
    except Exception:
        return None
    for pref in ("qwen3.5:9b", "llama3.1:8b", "qwen2.5:7b", "qwen3", "llama3"):
        hit = next((n for n in installed if n == pref or n.startswith(pref)), None)
        if hit:
            _local_model_cache = hit
            return hit
    _local_model_cache = installed[0] if installed else None
    return _local_model_cache


def _vision_model():
    try:
        installed = [m["name"] for m in _ollama("/api/tags", timeout=5).get("models", [])]
    except Exception:
        return None
    return next((n for n in installed if any(k in n.lower() for k in ("llava", "vl", "vision", "minicpm-v", "moondream", "gemma3"))), None)


def _ollama_chat(payload):
    try:
        return _ollama("/api/chat", payload)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore").lower()
        if "think" in body and "think" in payload:
            payload.pop("think")
            return _ollama("/api/chat", payload)
        if "tool" in body and payload.get("tools"):
            payload.pop("tools")
            return _ollama("/api/chat", payload)
        raise


def _think_local(user_text: str, why: str = "", images=None) -> str:
    """Tamamen yerel beyin: Ollama. İnternet ve Gemini gerektirmez."""
    if not _ollama_ready():
        return ("Yerel moda geçmem gerekiyor ama Ollama çalışmıyor. ollama.com'dan Ollama'yı kur ve terminalde "
                "'ollama pull llama3.1:8b' komutunu çalıştır." + (f" ({why})" if why else ""))
    model = _local_model()
    if not model:
        return "Ollama çalışıyor ama kurulu model yok. Terminalde 'ollama pull llama3.1:8b' komutunu çalıştır."
    msgs = [{"role": "system", "content": SYSTEM + NO_SCREEN_NOTE}]
    msgs += [{"role": r, "content": t} for r, t in convo[-8:]]
    user_msg = {"role": "user", "content": user_text}
    if images:
        vm = _vision_model()
        if not vm:
            return ("Yerel modda görsel anlamak için bir görsel model gerekiyor: terminalde "
                    "'ollama pull qwen2.5vl:7b' (veya llava) komutunu çalıştır.")
        model = vm
        user_msg["images"] = [base64.b64encode(d).decode() for _, d in images]
    msgs.append(user_msg)
    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
             for t in TOOLS if t["name"] in LOCAL_TOOLS] if not images else []
    for _step in range(8):
        if task_abort.is_set():
            return "Durdurdum."
        payload = {"model": model, "messages": msgs, "tools": tools, "stream": False, "think": False, "keep_alive": "10m",
                   "options": {"num_ctx": 6144, "temperature": 0.3}}
        if not tools:
            payload.pop("tools", None)
        t0 = time.time()
        try:
            data = _ollama_chat(payload)
        except Exception as e:
            dbg(f"[Ollama hatası] {e}")
            return "Yerel model cevap vermedi. Ollama'nın çalıştığından ve modelin yüklü olduğundan emin ol."
        dbg(f"[süre] Ollama {time.time()-t0:.1f} sn")
        msg = data.get("message", {}) or {}
        calls = msg.get("tool_calls") or []
        msgs.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
        if not calls:
            text = re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()
            return text or "Bir cevap üretemedim."
        outs, names = [], []
        for c in calls:
            fn = c.get("function", {}) or {}
            name, args = fn.get("name"), fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            dbg(f"[Araç/yerel] {name} {json.dumps(args, ensure_ascii=False, default=str)[:200]}")
            try:
                out = HANDLERS[name](**args) if name in LOCAL_TOOLS else "Bu araç yerel modda yok."
            except Exception as e:
                out = f"Araç hatası: {e}"
            names.append(name)
            outs.append(str(out))
            msgs.append({"role": "tool", "tool_name": name, "content": str(out)[:4000]})
        if _simple_request(_strip_ctx(user_text)) and all(n in FAST_TOOLS for n in names) and not any(_looks_failed(o) for o in outs):
            return _natural(" ".join(outs)[:300])
    return "Bu iş çok adım sürdü, durdum. Daha kısa bir komut verir misin?"


# ---- Karma beyin: önce Gemini, olmazsa Ollama ----
convo: list = []                                   # sağlayıcıdan bağımsız kısa sohbet geçmişi
# ---- Ek ücretsiz bulut sağlayıcıları (OpenAI uyumlu API): NVIDIA, Groq, Cerebras, Mistral, OpenRouter ----
# Sıra .env'de JARVIS_PROVIDERS ile değiştirilebilir, ör. "nvidia,gemini,groq,ollama". Anahtarı olmayan sağlayıcı atlanır.
PROVIDER_ORDER = [p.strip().lower() for p in
                  os.getenv("JARVIS_PROVIDERS", "gemini,nvidia,groq,cerebras,mistral,openrouter,ollama").split(",") if p.strip()]
OPENAI_PROVIDERS = {
    "nvidia": {"url": "https://integrate.api.nvidia.com/v1", "key_env": "NVIDIA_API_KEY", "model_env": "NVIDIA_MODEL",
               "prefer": ("qwen3.5-122b", "qwen3.5-397b", "llama-3.3-70b", "llama-3.1-70b", "mistral-large", "qwen3", "nemotron")},
    "groq": {"url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY", "model_env": "GROQ_MODEL",
             "prefer": ("llama-3.3-70b", "gpt-oss-120b", "qwen", "llama-3.1-70b")},
    "cerebras": {"url": "https://api.cerebras.ai/v1", "key_env": "CEREBRAS_API_KEY", "model_env": "CEREBRAS_MODEL",
                 "prefer": ("gpt-oss-120b", "llama-3.3-70b", "qwen", "llama")},
    "mistral": {"url": "https://api.mistral.ai/v1", "key_env": "MISTRAL_API_KEY", "model_env": "MISTRAL_MODEL",
                "prefer": ("mistral-large", "mistral-medium", "mistral-small", "ministral")},
    "openrouter": {"url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY", "model_env": "OPENROUTER_MODEL",
                   "free_only": True, "prefer": ("llama-3.3-70b", "gpt-oss-120b", "qwen", "deepseek", "mistral")},
}
_BAD_MODEL = ("embed", "whisper", "guard", "tts", "audio", "rerank", "image", "vision", "safety", "moderation", "reward", "parse", "clip", "-vl", "ocr")
_prov_models: dict = {}      # sağlayıcı -> denenecek model listesi (çalışan model başa alınır)
_prov_until: dict = {}       # sağlayıcı -> bu zamana kadar atla (limit/yoğunluk/anahtar hatası)
_prov_why: dict = {}         # sağlayıcı -> son hata sebebi
_key_warned: set = set()
_active_prov = {"name": "gemini"}
_VISION_Q = re.compile(r"ekran|görsel|resim|fotoğraf|şuna bak|buna bak|tıkla|kaydır|sürükle|düğme|buton|butona|imleç|fare|"
                       r"görüyor musun|bak bakalım|ne yazıyor|nerede", re.I)
_CLAUDE_Q = re.compile(r"^(claude|claud|klod|clod|klot|klaud)['’]?[a-zçğıöşü]{0,3}[\s,:]+"
                       r"(?!(?:nedir|ne |nasıl|kimdir|kim |hakkında|mı |mi |ile )|\S+\s*$)(.{3,})", re.I | re.S)   # "Claude nedir" gibi sorular değil, komutlar


NO_SCREEN_NOTE = ("\nNOT: Şu an yedek bir yapay zeka sağlayıcısındasın; ekranı göremez, fareyle tıklayamazsın (screen_look, click, "
                  "click_element, scroll yok). Ekran gerektiren bir iş istenirse bunu kısaca söyle ve klavye kısayolu/komut gibi bir alternatif dene.")


class ProviderHTTPError(Exception):
    def __init__(self, code, body="", retry_after=None):
        super().__init__(f"{code} {body[:300]}")
        self.code, self.retry_after = code, retry_after


def get_mode() -> str:
    return "local" if _active_prov["name"] == "ollama" else _active_prov["name"]


def get_provider() -> str:
    return _active_prov["name"]


def _set_active(name: str, reason: str = ""):
    if _active_prov["name"] == name:
        return
    _active_prov["name"] = name
    dbg(f"[sağlayıcı: {name}] {reason}")
    if mode_hook:
        mode_hook(name, reason or "tekrar erişilebilir")
    else:
        print(f"[Jarvis] Aktif sağlayıcı: {name} ({reason or 'tekrar erişilebilir'})")
    if usage_hook:
        usage_hook(cost_summary())


def _http_json(url, key=None, payload=None, timeout=60):
    headers = {"Content-Type": "application/json", "User-Agent": "Jarvis/1.0"}   # bazı sağlayıcılar Python'un varsayılan kimliğini engeller
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8") if payload is not None else None, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        ra = e.headers.get("Retry-After") if e.headers else None
        try:
            ra = float(ra) if ra else None
        except ValueError:
            ra = None
        raise ProviderHTTPError(e.code, e.read().decode("utf-8", "ignore"), ra)


def _openai_models(prov: str):
    """Sağlayıcının model listesini çek, uygun (büyük, sohbet) modelleri tercih sırasına göre diz. Kullanıcı .env'den de belirleyebilir."""
    if prov in _prov_models:
        return _prov_models[prov]
    cfg, key = OPENAI_PROVIDERS[prov], os.getenv(OPENAI_PROVIDERS[prov]["key_env"])
    forced = [m.strip() for m in (os.getenv(cfg["model_env"]) or "").split(",") if m.strip()]
    if forced:
        _prov_models[prov] = forced
        return forced
    ids = [m["id"] for m in _http_json(cfg["url"] + "/models", key, timeout=20).get("data", [])]
    ids = [i for i in ids if not any(b in i.lower() for b in _BAD_MODEL)]
    if cfg.get("free_only"):
        ids = [i for i in ids if i.endswith(":free")]
    ordered = []
    for pref in cfg["prefer"]:
        ordered += [i for i in ids if pref in i.lower() and i not in ordered]
    ordered += [i for i in ids if i not in ordered][:2]
    if not ordered:
        raise RuntimeError(f"{prov}: uygun model bulunamadı")
    _prov_models[prov] = ordered[:6]
    return _prov_models[prov]


def _openai_chat(prov: str, msgs, tools):
    cfg, key = OPENAI_PROVIDERS[prov], os.getenv(OPENAI_PROVIDERS[prov]["key_env"])
    models, last = _openai_models(prov), None
    for model in list(models):
        payload = {"model": model, "messages": msgs, "temperature": 0.3, "max_tokens": 1024}
        if tools:
            payload["tools"], payload["tool_choice"] = tools, "auto"
        try:
            data = _http_json(cfg["url"] + "/chat/completions", key, payload)
            if models[0] != model:                      # çalışan modeli başa al
                models.remove(model)
                models.insert(0, model)
            return data
        except ProviderHTTPError as e:
            if e.code in (400, 404, 422):               # model yok / araç desteklemiyor: sıradaki modeli dene
                last = e
                continue
            raise
    raise last or RuntimeError(f"{prov}: model yanıt vermedi")


def _think_openai(prov: str, user_text: str) -> str:
    """NVIDIA / Groq / Cerebras / Mistral / OpenRouter (OpenAI uyumlu) ile araç döngüsü. Metin tabanlı: ekran/görsel yok."""
    msgs = [{"role": "system", "content": SYSTEM + NO_SCREEN_NOTE}] + [{"role": r, "content": t} for r, t in convo[-8:]]
    msgs.append({"role": "user", "content": user_text})
    allowed = {t["name"] for t in TOOLS} - SCREEN_TOOLS
    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
             for t in TOOLS if t["name"] in allowed]
    for _step in range(15):
        if task_abort.is_set():
            return "Durdurdum."
        t0 = time.time()
        data = _openai_chat(prov, msgs, tools)
        _perf_mark(f"{prov} {time.time()-t0:.1f}sn")
        dbg(f"[süre] {prov} {time.time()-t0:.1f} sn")
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        am = {"role": "assistant", "content": msg.get("content") or ""}
        if calls:
            am["tool_calls"] = calls
        msgs.append(am)
        if not calls:
            text = re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()
            return text or "Bir cevap üretemedim."
        outs, names = [], []
        for c in calls:
            fn = c.get("function", {}) or {}
            name, args = fn.get("name"), fn.get("arguments") or "{}"
            try:
                args = json.loads(args) if isinstance(args, str) else args
            except Exception:
                args = {}
            dbg(f"[Araç/{prov}] {name} {json.dumps(args, ensure_ascii=False, default=str)[:200]}")
            try:
                out = HANDLERS[name](**args) if name in allowed and name in HANDLERS else "Bilinmeyen araç."
            except Exception as e:
                out = f"Araç hatası: {e}"
            names.append(name)
            outs.append(str(out))
            msgs.append({"role": "tool", "tool_call_id": c.get("id"), "content": str(out)[:4000]})
        if _simple_request(_strip_ctx(user_text)) and all(n in FAST_TOOLS for n in names) and not any(_looks_failed(o) for o in outs):
            return _natural(" ".join(outs)[:300])
    return "Bu iş çok adım sürdü, durdum. Daha kısa bir komut verir misin?"


def _remember(user_text: str, answer: str, to_gemini: bool = False):
    convo.append(("user", user_text))
    convo.append(("assistant", answer))
    del convo[:-12]
    if to_gemini:   # Gemini'ye dönülünce konuşma kopmasın
        history.append(types.Content(role="user", parts=[types.Part(text=user_text)]))
        history.append(types.Content(role="model", parts=[types.Part(text=answer)]))


def _classify(e):
    """Hatayı sınıflandır: (tür, sebep, kaç saniye sonra tekrar denensin)"""
    if isinstance(e, ProviderHTTPError):
        if e.code in (401, 403):
            return "key", "API anahtarı reddedildi", 3600
        if e.code == 429:
            return "quota", "limit doldu", min(300.0, e.retry_after or 90.0)
        if e.code >= 500:
            return "busy", "sağlayıcı yoğun", 90
        return "other", f"hata {e.code}", 120
    if isinstance(e, GeminiExhausted):
        return "quota", "tüm Gemini modellerinin ücretsiz limiti doldu", e.wait
    msg = str(e)
    if "API key not valid" in msg or "API_KEY_INVALID" in msg:
        return "key", "API anahtarı geçersiz", 0
    low = msg.lower()
    if any(k in low for k in ("getaddrinfo", "connecterror", "connection error", "network is unreachable", "name resolution",
                              "timed out", "timeout", "connection refused", "remotedisconnected", "temporary failure")) or not _online():
        return "offline", "internet yok veya Gemini'ye ulaşılamıyor", 60
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        if re.search(r"per ?day|PerDay", msg, re.I):
            return "quota", "Gemini günlük limiti doldu", 1800
        return "quota", "Gemini dakikalık limiti doldu", 120
    if any(k in msg for k in TRANSIENT):
        return "busy", "Gemini çok yoğun", 120
    return "other", "Gemini hatası", 120


def _keep_last_images(n=2):
    """Uzun ekran-kontrol döngülerinde sadece son n ekran görüntüsünü tut (hız ve token tasarrufu)."""
    seen = 0
    for c in reversed(history):
        if c.parts and any(getattr(p, "inline_data", None) for p in c.parts):
            seen += 1
            if seen > n:
                c.parts = [p for p in c.parts if not getattr(p, "inline_data", None)] or [types.Part(text="(eski görüntü)")]


def _think_gemini(user_text: str, images=None) -> str:
    """Gemini ile cevapla. Hata olursa (geçmişi temizleyip) istisna fırlatır; karar think()'te verilir."""
    parts = [types.Part(text=user_text)] + [types.Part.from_bytes(data=d, mime_type=m) for m, d in (images or [])]
    history.append(types.Content(role="user", parts=parts))
    _trim()
    start_len = len(history) - 1
    simple = _simple_request(_strip_ctx(user_text))
    level = os.getenv("JARVIS_THINKING", "minimal") if simple else os.getenv("JARVIS_THINKING_COMPLEX", "medium")
    max_steps = int(os.getenv("JARVIS_MAX_STEPS", "30"))
    try:
        for _step in range(max_steps):
            if task_abort.is_set():
                history.append(types.Content(role="model", parts=[types.Part(text="(Kullanıcı durdurdu.)")]))
                return "Durdurdum."
            _keep_last_images(2)
            t0 = time.time()
            resp = _generate(level)
            _perf_mark(f"{_active['model']}({level}) {time.time()-t0:.1f}sn")
            dbg(f"[süre] Gemini {time.time()-t0:.1f} sn")
            _track_usage(resp)
            if not resp.candidates or not resp.candidates[0].content or not resp.candidates[0].content.parts:
                if _step > 0:                      # araçlar çalıştı ama model son cevabı vermedi
                    return "Tamam, yaptım."
                del history[start_len:]
                return "Bir cevap üretemedim, tekrar söyler misin?"
            content = resp.candidates[0].content
            history.append(content)
            calls = [p.function_call for p in content.parts if p.function_call]
            if not calls:
                return "".join(p.text for p in content.parts if p.text and not getattr(p, "thought", False))
            result_parts, outs, image_parts = [], [], []
            for fc in calls:
                args = dict(fc.args or {})
                dbg(f"[Araç] {fc.name} {json.dumps(args, ensure_ascii=False, default=str)[:200]}")
                if task_abort.is_set():
                    out = "Kullanıcı durdurdu."
                else:
                    try:
                        out = HANDLERS[fc.name](**args) if fc.name in HANDLERS else f"Bilinmeyen araç: {fc.name}"
                    except Exception as e:
                        out = f"Araç hatası: {e}"
                        if "FailSafe" in type(e).__name__:
                            task_abort.set()
                            out = "Kullanıcı fareyi ekran köşesine götürdü (acil durdurma). Ekran kontrolü durduruldu."
                _perf_mark(f"araç:{fc.name}" + (" HATA" if _looks_failed(str(out)[:200]) else ""))
                if isinstance(out, dict) and "image" in out:
                    image_parts.append(types.Part.from_bytes(data=out["image"], mime_type=out.get("mime", "image/jpeg")))
                    out = out["text"]
                outs.append(str(out))
                result_parts.append(types.Part.from_function_response(name=fc.name, response={"result": str(out)}))
            history.append(types.Content(role="user", parts=result_parts + image_parts))
            if (simple and all(fc.name in FAST_TOOLS for fc in calls)
                    and not any(_looks_failed(o) for o in outs)):
                # Tek adımlık basit komut: ikinci Gemini çağrısını atla, aracın sonucunu söyle
                answer = _natural(" ".join(outs)[:300])
                history.append(types.Content(role="model", parts=[types.Part(text=answer)]))
                return answer
        return f"Bu iş {max_steps} adımda bitmedi, durdum. Kalanı için yeni bir komut verir misin?"
    except Exception:
        del history[start_len:]
        raise
    finally:
        _drop_old_images()


FAST_PROVIDER = os.getenv("JARVIS_FAST_PROVIDER", "groq").lower()   # "off" = kapalı


def _provider_chain(user_text: str, images):
    chain = []
    for p in PROVIDER_ORDER:
        if p == "gemini" and os.getenv("GEMINI_API_KEY"):
            chain.append(p)
        elif p in OPENAI_PROVIDERS and os.getenv(OPENAI_PROVIDERS[p]["key_env"]) and not images:
            chain.append(p)                      # bu sağlayıcılar metin tabanlı: görsel varsa atlanır
        elif p == "ollama":
            chain.append(p)
    if "ollama" not in chain:
        chain.append("ollama")
    if "gemini" in chain and (images or _VISION_Q.search(user_text)):
        chain.remove("gemini")
        chain.insert(0, "gemini")                # ekran/görsel işleri görebilen Gemini'de
    elif FAST_PROVIDER in chain and _simple_request(user_text) and not images:
        chain.remove(FAST_PROVIDER)              # kısa, tek adımlı komut: en hızlı sağlayıcı önce (Groq ~0,5 sn, Gemini 2-5 sn)
        chain.insert(0, FAST_PROVIDER)
    return chain


def _strip_ctx(text: str) -> str:
    return re.sub(r"^\[Bağlam:[^\]]*\]\s*", "", text)


def _last_app_window() -> str:
    """Kullanıcının Jarvis'ten önce kullandığı (en üstteki) pencerenin başlığı."""
    if not IS_WIN:
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        titles = []

        dwm = ctypes.windll.dwmapi

        def cloaked(hwnd):                        # arka plandaki UWP pencereleri "görünür" ama gizlidir
            v = ctypes.c_int(0)
            try:
                dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(v), ctypes.sizeof(v))
            except Exception:
                return False
            return v.value != 0

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd) \
                    and not (user32.GetWindowLongW(hwnd, -20) & 0x80) and not cloaked(hwnd):   # araç pencerelerini atla
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    t = buf.value.strip()
                    if t and not t.upper().startswith("JARVIS") and t not in ("Program Manager", "Settings", "Ayarlar") \
                            and "Windows Giriş Deneyimi" not in t:
                        titles.append(t)
            return len(titles) < 1
        user32.EnumWindows(cb, 0)                 # Z sırasına göre: en üstteki ilk gelir
        return titles[0][:120] if titles else ""
    except Exception:
        return ""


_GUN = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def _context() -> str:
    lt = time.localtime()
    ctx = f"{time.strftime('%d.%m.%Y', lt)} {_GUN[lt.tm_wday]}, saat {time.strftime('%H:%M', lt)}"
    w = _last_app_window()
    if w:
        ctx += f"; son kullanılan pencere: {w}"
    return f"[Bağlam: {ctx}]"


_perf = []
last_stt = {"secs": 0.0, "at": 0.0}
PERF_LOG = BASE / "jarvis_log.txt"


def _perf_mark(label: str):
    _perf.append(label)


def perf_log(line: str):
    """Hız günlüğü (jarvis_log.txt): her komutta nerede ne kadar zaman harcandığı. Yavaşlığın kaynağını bulmak için."""
    try:
        if PERF_LOG.exists() and PERF_LOG.stat().st_size > 300_000:
            PERF_LOG.write_text(PERF_LOG.read_text(encoding="utf-8")[-100_000:], encoding="utf-8")
        with open(PERF_LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%d.%m %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def think(user_text: str, images=None) -> str:
    """images: [(mime, bytes), ...] — sohbete eklenen görseller."""
    task_abort.clear()
    _perf.clear()
    t0 = time.time()
    stt = f"ses->yazı {last_stt['secs']:.1f}sn | " if time.time() - last_stt["at"] < 15 else ""
    try:
        return _think(user_text, images)
    finally:
        _restore_after_control()                 # ekran kontrolü için gizlenen Jarvis penceresini geri getir
        perf_log(f"[{time.time()-t0:5.1f}sn] {stt}{user_text[:80]!r} -> " + " > ".join(_perf))


def _think(user_text: str, images=None) -> str:
    note = user_text + (" [görsel eklendi]" if images else "")
    try:
        quick = None if images else local_command(user_text)
    except Exception as e:
        dbg(f"[yerel komut hatası: {e}]")
        quick = None
    if quick:
        _perf_mark("yerel komut (model yok)")
        dbg("[yerel komut: model kullanılmadı]")
        _remember(user_text, quick, to_gemini=True)
        return quick

    m = None if images else _CLAUDE_Q.match(user_text.strip())
    if m and CLAUDE_ON:                                      # "Claude, şunu yap": ücretsiz modellere uğramadan doğrudan Claude'a
        task = m.group(2).strip()
        out = tool_claude_code(task, continue_last=bool(re.match(r"^devam\b", task, re.I)))
        answer = "Tamam, Claude'a verdim. Bitince haber vereceğim." if out.startswith("Görev Claude") else out
        _remember(user_text, answer, to_gemini=True)
        return answer

    reason = ""
    for prov in _provider_chain(user_text, images):
        if prov != "ollama" and _prov_until.get(prov, 0) > time.time():
            reason = _prov_why.get(prov, reason)           # bekleme süresindeki sağlayıcıyı atla
            continue
        if prov == "gemini" and BUDGET_TL > 0 and cost_month_tl() >= BUDGET_TL:
            reason = _prov_why["gemini"] = f"Gemini aylık bütçesi ({BUDGET_TL:.0f} TL) doldu"
            _prov_until["gemini"] = time.time() + 3600
            continue
        try:
            ctx_text = _context() + " " + user_text
            if prov == "gemini":
                answer = _think_gemini(ctx_text, images)
            elif prov == "ollama":
                answer = _think_local(ctx_text, reason, images)
            else:
                answer = _think_openai(prov, ctx_text)
        except Exception as e:
            kind, why, retry = _classify(e)
            _perf_mark(f"{prov} HATA({kind})")
            dbg(f"[{prov} hatası/{kind}] {str(e)[:300]}")
            reason = _prov_why[prov] = f"{prov.upper()}: {why}"
            _prov_until[prov] = time.time() + (3600 if kind == "key" else (retry or 120))
            if kind == "key" and prov not in _key_warned:
                _key_warned.add(prov)
                _notify(f"{prov.upper()} API anahtarı geçersiz görünüyor. 🔑 API anahtarları bölümünden kontrol et.")
            continue
        _set_active(prov, reason)
        _remember(note, answer, to_gemini=(prov != "gemini"))
        return answer
    return "Hiçbir yapay zekaya ulaşamadım. " + reason


# ----------------------------------------------------------------------------------------------
# KONSOL MODU
# ----------------------------------------------------------------------------------------------
def strip_wake(text: str):
    """'Jarvis' (veya Whisper'ın yanlış yazdığı benzerleri: Çarvis, Carvis, Jarviz...) diyerek başlayan cümleyi ayırır."""
    low = text.lower()
    for w in WAKE_WORDS:
        if w in low:
            rest = text[low.index(w) + len(w):]
            return True, re.sub(r"^['’]\w{0,3}\s*", "", rest).strip(" ,.!?")
    for m in list(re.finditer(r"[\wçğıöşü]+", low))[:3]:          # bulanık eşleşme: ilk 3 kelime
        if difflib.SequenceMatcher(None, m.group(0), "jarvis").ratio() >= 0.72:
            return True, re.sub(r"^['’]\w{0,3}\s*", "", text[m.end():]).strip(" ,.!?")
    return False, text


def main():
    if not os.getenv("GEMINI_API_KEY"):
        print("GEMINI_API_KEY yok: sadece yerel modda (Ollama) çalışacağım. Anahtar için aistudio.google.com/apikey")
    warmup()
    if TEXT_MODE:
        speak("Yazı modundayım. Çıkmak için 'çık' yaz.")
        while True:
            t = input("Sen: ").strip()
            if t.lower() in ("çık", "exit", "quit"):
                break
            if t:
                speak(think(t))
        return

    _get_whisper()
    speak("Jarvis hazır. Beni 'Jarvis' diyerek çağırabilirsin.")
    awake_until = 0
    while True:
        try:
            heard = listen_once()
            if not heard:
                continue
            woke, command = strip_wake(heard)
            if not woke and time.time() > awake_until:
                continue
            if not command:
                speak("Dinliyorum.")
                command = listen_once(timeout=8)
                if not command:
                    continue
            if re.search(r"\b(kapan|görüşürüz|kendini kapat)\b", command.lower()):
                speak("Görüşmek üzere.")
                break
            print(f"Sen: {command}")
            speak(think(command))
            awake_until = time.time() + 20      # cevaptan sonra 20 sn "Jarvis" demeden devam edebilirsin
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[Hata] {e}")


if __name__ == "__main__":
    main()

