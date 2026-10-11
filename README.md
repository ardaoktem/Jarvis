# JARVIS – Sesli Yapay Zeka Masaüstü Asistanı

Gemini (ücretsiz katman) + Ollama (yerel) karma beyin · animasyonlu arayüz · çift alkışla uyanma · Windows ile başlama

## Kurulum (Windows 10/11)

### Kolay yol: tek dosya
1. **[Jarvis_Kur.bat'ı indir](https://github.com/ardaoktem/Jarvis/releases/latest/download/Jarvis_Kur.bat)** ve çift tıkla.
2. O kadar. Jarvis'i indirir, Python yoksa kurar (3.12, yönetici izni gerekmez), kütüphaneleri kurar, NVIDIA ekran kartın varsa GPU
   ses tanımayı ekler, masaüstüne **Jarvis** kısayolu koyar ve açar. Kurulum yeri: `C:\Users\<sen>\Jarvis`.
3. İlk açılışta ücretsiz **Gemini API anahtarını** sorar: [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
   (faturalandırması kapalı bir projeden al, böylece hep ücretsiz kalır).

Güncellemek için aynı dosyayı tekrar çalıştır: API anahtarların ve ayarların korunur.
Windows "Bilinmeyen yayıncı" uyarısı verirse: **Ek bilgi → Yine de çalıştır**.

### Elle kurulum
```
git clone https://github.com/ardaoktem/Jarvis.git
cd Jarvis
kurulum.bat
```
Sonra masaüstündeki **Jarvis** kısayolu veya `baslat.bat`.

### İsteğe bağlı
- **Daha doğal ses (ElevenLabs, ücretsiz plan):** anahtarını `.env` dosyasına `ELEVENLABS_API_KEY=` olarak yaz ve `ses_ayarla.bat`'ı çalıştır.
  Ücretsiz planda API'den çalışan İngiliz aksanlı sesi bulur, test eder ve kendisi ayarlar.
- **Yerel mod (internetsiz):** [ollama.com](https://ollama.com)'dan Ollama'yı kur, `ollama pull llama3.1:8b`.
- **Ek ücretsiz yapay zekalar:** Groq, NVIDIA, Cerebras, Mistral, OpenRouter anahtarlarını ⚙ Ayarlar → 🔑 API anahtarları'na gir.
  Kısa komutlar Groq varsa önce ona gider (çok hızlı).
- **Claude Code:** Claude Pro aboneliğin varsa ve [Claude Code](https://claude.com/claude-code) kuruluysa, karmaşık kod işlerini ona devreder.
- **Exe:** `build_exe.bat` → `dist\Jarvis\Jarvis.exe`.

Gereksinimler: Windows 10 (2004+) veya 11, mikrofon, internet (ilk kurulum ve bulut modelleri için). İlk sesli komutta ses tanıma
modeli bir kez iner (GPU: ~1,6 GB, CPU: ~0,5 GB).

## Arayüz
- **Ortadaki mavi küre** duruma göre değişir: *hazır* (nefes alır), *dinliyor* (mikrofona tepki veren dalgalar), *düşünüyor* (dönen yaylar),
  *konuşuyor* (sesin şiddetine tepki veren çubuk halkası).
- Altta sohbet, 📎 görsel ekleme (Ctrl+V ile panodan da), 🎤 konuş, ⏹ sustur. 💬 sohbeti gizler/gösterir.
- ⚙ Ayarlar: sesli cevap, sürekli dinleme ("Jarvis" de), **çift alkışla uyandırma**, **Windows ile başlat**, alkış hassasiyeti,
  ses seçimi, **mikrofon testi**, **alkış testi**.
- Pencerenin X'ine basınca kapanmaz, **sistem tepsisine** iner (saatin yanındaki simge). Çıkmak için simgeye sağ tık → Çıkış.

## Uyandırma
- **Çift alkış** (ayarlardan açık): Jarvis penceresi açılır ve doğrudan seni dinler; "Jarvis" demen gerekmez.
- **"Jarvis ..."** (Sürekli dinle açıkken) ya da 🎤 düğmesi.
- **Windows ile başlat** açıksa bilgisayar açılınca Jarvis tepside, simge durumunda başlar.

## Beyin: nasıl çalışır?
Sıra (anahtarı olmayan sağlayıcı atlanır; **🔑 API anahtarları** düğmesinden girersin, `.env` ile uğraşmana gerek yok):
1. **Yerel komutlar** ("Chrome'u aç", "sesi 30 yap", "YouTube'da ... aç", "söylediklerimi yaz"): model kullanmaz, anında çalışır.
2. **Gemini** (ücretsiz): önce `JARVIS_MODEL`; limiti dolarsa hesabındaki diğer Gemini flash modellerine geçer.
3. **NVIDIA Build** (build.nvidia.com, ücretsiz, ~40 istek/dk): büyük açık modeller (ör. Qwen3.5 122B), model otomatik seçilir.
4. **Groq**, **Cerebras**, **Mistral**, **OpenRouter (ücretsiz modeller)**: hepsi isteğe bağlı ek ücretsiz kotalar.
5. **Ollama** (yerel): hiçbir bulut sağlayıcıya ulaşılamazsa otomatik geçer; bulut dönünce geri döner.

Bir sağlayıcı limit/hata verirse bir süre atlanır, arayüzde hangisinin aktif olduğu görünür.
**Ekran ve görsel işleri her zaman Gemini'ye gider** (diğer bulut sağlayıcılar metin tabanlı). Sırayı değiştirmek için `.env`:
`JARVIS_PROVIDERS=nvidia,gemini,groq,ollama` (NVIDIA'yı 1. sıraya almak gibi).

## Neler yapar?
- Yüklü her uygulamayı açar, pencere yönetir, YouTube açar, medya tuşları, ses ayarı, dosya/klasör işlemleri, PowerShell komutları
- **Dikte:** "Not defteri aç ve söylediklerimi yaz" → "dikteyi bitir" diyene kadar yazar ("yeni satır" = Enter)
- **Ekranı görme (isteğe bağlı, sürekli değil):** "Ekranımda ne var?", "bu hata ne demek?" dediğinde o an bir görüntü alır
  (Jarvis penceresi kısa süre gizlenir) ve Gemini'ye gönderir. Yerel (Ollama) modda ekran okuma yok.
- **Görsel sohbet:** 📎 ile eklediğin resim hakkında soru sorabilirsin (yerel modda görsel bir Ollama modeli gerekir: `qwen2.5vl`/`llava`)
- Kod projesinde hata arar, sohbet eder, fikir verir

- **Ekran kontrolü:** "Şu kaydet düğmesine bas", "Chrome'da arama kutusuna hava durumu yaz", "aşağı kaydır", "bu pencerede
  ayarlara gir" gibi işleri ekrana bakarak yapar (sadece Gemini ile; yedek sağlayıcılarda ekran yok).

## Sınırlar
- Oyunlar fareyi kendine kilitlediği ve hızlı tepki istediği için oyun oynamada (Minecraft'ta blok kırma vb.) güvenilir değil.
- Ekranı sürekli izlemez, sadece gerektiğinde bakar (ücretsiz kota ve gizlilik). Her bakış/tıklama bir Gemini isteği harcar.
- Jarvis penceresi ekran görüntülerinde görünmez (Windows 10 2004+); bu yüzden **ekran paylaşımında da görünmez**.
  İstemezsen `.env`: `JARVIS_CAPTURE_EXCLUDE=off`.

## Gizlilik
- Ücretsiz Gemini katmanında gönderdiğin içerik (komutlar, ekran görüntüleri, görseller) Google tarafından ürün geliştirmede kullanılabilir.
  Parola, özel mesaj gibi şeyler ekrandayken ekran özelliğini kullanma.
- Alkış algılayıcı mikrofonu dinler ama **kaydetmez ve yazıya çevirmez**; sadece ses şiddetine bakar.

## Ayarlar (.env)
- Anahtarlar: `GEMINI_API_KEY`, `NVIDIA_API_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY` (🔑 düğmesi bunları yazar)
- `JARVIS_PROVIDERS` – sağlayıcı sırası; `NVIDIA_MODEL`, `GROQ_MODEL`... – o sağlayıcıda belirli model(ler) kullan (virgülle ayır)
- `GEMINI_API_KEY`, `JARVIS_MODEL` (varsayılan `gemini-3.8-flash`), `JARVIS_FALLBACK=model1,model2` (Gemini yedek zinciri)
- `JARVIS_LOCAL_MODEL` – Ollama modeli (boşsa kurulu olandan seçer)
- `JARVIS_STT=auto|tiny|base|small|medium|large-v3-turbo`, `JARVIS_STT_DEVICE=auto|cuda|cpu`, `JARVIS_SILENCE=0.9` (cümle sonu bekleme sn)
- `JARVIS_MIC=<aygıt no>` – mikrofon seçimi (Mikrofon testi aygıt adını gösterir)
- Ses: `JARVIS_VOICE=tr-TR-AhmetNeural|tr-TR-EmelNeural`, `JARVIS_RATE=+5%`, `JARVIS_PITCH=-3Hz`, `JARVIS_TTS=edge|gemini`
- `JARVIS_CONFIRM=risky|always|off` – tehlikeli işlerde onay (varsayılan: sadece silme/zorla kapatma/indirme gibi işlerde sorar)
- `JARVIS_THINKING=low|minimal|off`, `JARVIS_THINKING_COMPLEX=medium` (çok adımlı işler), `JARVIS_MAX_STEPS=30`
- `JARVIS_MONITOR=1` (ekran görüntüsü/tıklama hangi monitörde), `JARVIS_CONTROL=off` (fare/klavye kontrolünü kapatır), `JARVIS_DEBUG=1`
- Ses tanıma: `JARVIS_VAD=0.5` (konuşma algılama eşiği; gürültülü ortamda 0.6), `JARVIS_HOTWORDS="Valorant Obsidian ..."` (sık kullandığın özel adlar)
- ElevenLabs: `ELEVENLABS_API_KEY`, `JARVIS_ELEVEN_VOICE` (ses ID), `JARVIS_ELEVEN_MODEL` (varsayılan `eleven_multilingual_v2`;
  daha hızlı ve kotayı yarı harcayan: `eleven_flash_v2_5`), `JARVIS_ELEVEN_STABILITY=0.45`, `JARVIS_ELEVEN_STYLE=0.15`
- Sadece ücretli kullanırsan: `JARVIS_BUDGET_TL`, `JARVIS_USDTRY`, `JARVIS_PRICE_IN`, `JARVIS_PRICE_OUT`

## Sorun giderme
- **Açılmıyor:** `baslat.bat` hata gösterir; ayrıca `jarvis_hata.txt` dosyasına yazılır. Kurulumu sınamak için: `kurulum.bat /test`.
- **Yavaş:** her komutun adım adım süresi `jarvis_log.txt` dosyasına yazılır.
- **Sesli komutları anlamıyor:** ⚙ → **Mikrofon testi**. Seviye "kısık" ise Windows Ayarlar → Ses → Giriş'ten artır; ekran kartın varsa `kurulum_gpu.bat`;
  yanlış mikrofon seçiliyse `JARVIS_MIC`. Arayüzde "Duyulan: ..." satırı Jarvis'in ne anladığını gösterir.
- **Alkış algılanmıyor / yanlışlıkla tetikleniyor:** ⚙ → **Alkış testi**, sonra hassasiyet çubuğunu ayarla.
- **Ses yapay:** ⚙ → Ses: **Otomatik** seçili olsun ve 🔊 Ses testi'ne bas. ElevenLabs çalışmıyorsa nedeni sohbete yazılır
  (kota, ücretsiz planda kullanılamayan ses, "unusual activity" engeli). ElevenLabs ücretsiz kotası ayda ~10.000 karakter
  (`eleven_flash_v2_5` ile ~20.000); dolunca Gemini sesine, o da dolunca Ahmet'e geçer.
- **Yanlış yere tıklıyor:** Windows ölçekleme (%125/%150) desteklenir; birden çok monitörün varsa `JARVIS_MONITOR` ile doğru ekranı seç.
  Öğenin üzerindeki yazıyı söylemek ("Kaydet yazan düğmeye bas") isabeti artırır.
- **503 / limit:** Jarvis kendisi diğer Gemini modellerine ve Ollama'ya geçer.
- Konsol sürümü: `python jarvis.py` (sesli) veya `python jarvis.py --text`
