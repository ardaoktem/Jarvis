"""
ElevenLabs ses seçici: ücretsiz planda API'den kullanılabilen, İngiliz aksanlı, sakin ve kibar bir erkek sesi bulur,
gerçekten ses üretebildiğini test eder ve .env'ye yazar.

Çalıştırma:  ses_ayarla.bat   (veya: venv\\Scripts\\python.exe eleven_ses_sec.py)
Sonuç:       ses_test_sonuc.txt  ve  ses_ornekleri\\ klasöründeki mp3 örnekleri
API anahtarı ekrana veya dosyaya yazılmaz.
"""
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
ENV = BASE / ".env"
LOG = BASE / "ses_test_sonuc.txt"
SAMPLES = BASE / "ses_ornekleri"
MODEL = "eleven_multilingual_v2"          # en doğal Türkçe
TEST_TEXT = "Emredersiniz efendim. Tüm sistemler çevrimiçi, size nasıl yardımcı olabilirim?"
# ElevenLabs'ın herkese açık varsayılan (premade) sesleri: ücretsiz planda API ile kullanılabilir.
KNOWN = {"Daniel": "onwK4e9ZLuTAKqWW03F9",     # İngiliz, derin, ölçülü, haber sunucusu tonu
         "George": "JBFqnCBsd6RMkjVDRZzb"}     # İngiliz, sıcak, olgun anlatıcı
PREFER = ["Daniel", "George"]
SETTINGS = {"JARVIS_ELEVEN_MODEL": MODEL, "JARVIS_ELEVEN_STABILITY": "0.6", "JARVIS_ELEVEN_STYLE": "0.1", "JARVIS_TTS": "auto"}

lines = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    lines.append(s)


def read_env(path: Path) -> dict:
    out = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def write_env(path: Path, vals: dict):
    """Sadece verilen anahtarların satırlarını günceller/ekler; diğer satırlara dokunmaz. Önce yedek alır."""
    if not path.exists():
        return False
    shutil.copyfile(path, path.with_name(".env.yedek"))
    src = path.read_text(encoding="utf-8").splitlines()
    out, seen = [], set()
    for ln in src:
        k = ln.split("=", 1)[0].strip()
        if "=" in ln and k in vals:
            out.append(f"{k}={vals[k]}")
            seen.add(k)
        else:
            out.append(ln)
    out += [f"{k}={v}" for k, v in vals.items() if k not in seen]
    path.write_text("\n".join(out).strip("\n") + "\n", encoding="utf-8")
    return True


def api(key, path, body=None, timeout=30):
    req = urllib.request.Request("https://api.elevenlabs.io" + path,
                                 data=json.dumps(body).encode("utf-8") if body is not None else None,
                                 headers={"xi-api-key": key, "Content-Type": "application/json", "User-Agent": "Jarvis/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def err_text(e: urllib.error.HTTPError) -> str:
    raw = e.read().decode("utf-8", "ignore")
    try:
        d = json.loads(raw).get("detail")
        if isinstance(d, dict):
            return f"{e.code} {d.get('status', '')}: {d.get('message', '')}"[:300]
        return f"{e.code} {d}"[:300]
    except Exception:
        return f"{e.code} {raw[:200]}"


def tts(key, voice_id, name):
    body = {"text": TEST_TEXT, "model_id": MODEL,
            "voice_settings": {"stability": 0.6, "similarity_boost": 0.8, "style": 0.1, "use_speaker_boost": True}}
    t0 = time.time()
    try:
        audio = api(key, f"/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128", body, timeout=40)
    except urllib.error.HTTPError as e:
        return False, err_text(e)
    except Exception as e:
        return False, f"bağlantı hatası: {e}"
    if len(audio) < 1000:
        return False, "boş ses döndü"
    SAMPLES.mkdir(exist_ok=True)
    (SAMPLES / f"{name}.mp3").write_bytes(audio)
    return True, f"{len(audio) // 1024} KB, {time.time() - t0:.1f} sn"


def main():
    env = read_env(ENV)
    key = env.get("ELEVENLABS_API_KEY", "")
    log(f"=== ElevenLabs ses testi  {time.strftime('%d.%m.%Y %H:%M')} ===")
    if not key:
        log("HATA: .env içinde ELEVENLABS_API_KEY yok.")
        return
    try:
        sub = json.loads(api(key, "/v1/user/subscription"))
        log(f"Plan: {sub.get('tier')} | bu ay kullanılan karakter: {sub.get('character_count')} / {sub.get('character_limit')}")
    except urllib.error.HTTPError as e:
        log("Abonelik bilgisi okunamadı (anahtarın bu izni olmayabilir):", err_text(e))
    except Exception as e:
        log("ElevenLabs'a bağlanılamadı:", e)
        return

    cands = {}                                         # ad -> (id, puan, açıklama)
    try:
        voices = json.loads(api(key, "/v2/voices?page_size=100")).get("voices", [])
    except Exception:
        try:
            voices = json.loads(api(key, "/v1/voices")).get("voices", [])
        except Exception as e:
            voices = []
            log("Ses listesi okunamadı, bilinen varsayılan seslerle denenecek:", e)
    for v in voices:
        lb = {k: str(x).lower() for k, x in (v.get("labels") or {}).items()}
        desc = " ".join(lb.values()) + " " + str(v.get("description") or "").lower()
        score = 0
        score += 3 if "british" in desc else 0
        score += 2 if lb.get("gender") == "male" else -5
        score += 1 if lb.get("age") in ("middle_aged", "middle aged", "old") else 0
        score += sum(1 for w in ("calm", "deep", "authoritative", "sophisticated", "refined", "warm", "news", "narrat", "butler")
                     if w in desc)
        score += 1 if v.get("category") == "premade" else 0
        nm = (v.get("name") or "").split(" - ")[0].strip()
        if score >= 4:
            cands[nm] = (v["voice_id"], score, f"{v.get('category')}; {desc[:80]}")
    for nm, vid in KNOWN.items():
        cands.setdefault(nm, (vid, 6, "varsayılan ElevenLabs sesi"))

    cur = env.get("JARVIS_ELEVEN_VOICE", "")
    if cur:
        ok, info = tts(key, cur, "mevcut_ses")
        log(f"Şu anki ses ({cur[:6]}...): {'ÇALIŞIYOR' if ok else 'ÇALIŞMIYOR'} -> {info}")

    order = [n for n in PREFER if n in cands] + sorted((n for n in cands if n not in PREFER), key=lambda n: -cands[n][1])
    working = []
    for nm in order[:4]:
        vid, score, info = cands[nm]
        ok, res = tts(key, vid, nm)
        log(f"{nm:10} ({vid}) [{info}] -> {'ÇALIŞIYOR' if ok else 'HATA'}: {res}")
        if ok:
            working.append((nm, vid))
        elif "quota" in res or "unusual" in res:
            log("Hesap düzeyinde bir sorun var (kota veya engel); diğer sesleri denemeyi bırakıyorum.")
            break

    if not working:
        log("SONUÇ: Hiçbir ElevenLabs sesi çalışmadı. .env değiştirilmedi; Jarvis Gemini/Edge sesiyle devam edecek.")
        return
    nm, vid = working[0]
    vals = dict(SETTINGS, JARVIS_ELEVEN_VOICE=vid)
    write_env(ENV, vals)
    dist_env = BASE / "dist" / "Jarvis" / ".env"
    if dist_env.exists():
        write_env(dist_env, vals)
    log(f"SONUÇ: Seçilen ses: {nm} ({vid}). .env güncellendi (eski hali .env.yedek). Çalışan diğer sesler: "
        + (", ".join(f'{n} ({i})' for n, i in working[1:]) or "-"))
    log(f"Örnekler: {SAMPLES}")
    try:
        import pygame
        pygame.mixer.init()
        pygame.mixer.music.load(str(SAMPLES / f"{nm}.mp3"))
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    finally:
        LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
