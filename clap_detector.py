"""
Çift alkış algılayıcı.
Jarvis'in tek mikrofon akışını (AudioHub) dinler ama hiçbir şeyi kaydetmez ve yazıya çevirmez: sadece ses şiddetine, ani artışa ve kısa süreye bakar.
Eşikler tahmindir; mikrofonuna göre arayüzdeki hassasiyet çubuğuyla ve "Alkış testi" düğmesiyle ayarla.
"""
import threading
import time

import numpy as np


class ClapDetector:
    DT = 0.01                # 10 ms'lik analiz bloğu

    def __init__(self, on_double_clap=None, sensitivity=5, device=None, samplerate=16000, hf_min=0.45):
        self.on_double_clap = on_double_clap
        self.sr = samplerate
        self.device = device
        self.hf_min = hf_min
        self.block = int(samplerate * self.DT)
        self.paused = False
        self.singles = 0
        self.doubles = 0
        self.stats = []      # (zaman, tepe seviye, yüksek frekans oranı) — son alkışlar
        self._hub = None
        self._buf = np.zeros(0, dtype=np.float32)
        self.set_sensitivity(sensitivity)
        self.reset()

    # ------------------------------------------------------------------ ayar
    def set_sensitivity(self, s):
        s = max(1, min(10, int(s)))
        self.sens = s
        self.k = 16 - s                  # gürültünün kaç katı alkış sayılır (s=5 -> 11 kat)
        self.min_abs = 0.06 - 0.005 * s  # mutlak alt sınır (s=5 -> 0.035)

    def reset(self):
        self.n = 0
        self.noise = 0.004
        self.prev = 0.0
        self.state = "idle"
        self.t0 = self.peak = self.hf0 = 0.0
        self.last_clap = None
        self.cool_until = 0.0
        self.pending = None              # ikinci alkıştan sonra kısa sessizlik bekleniyor (konuşmayı alkış sanmasın)

    def threshold(self):
        return max(self.min_abs, self.noise * self.k)

    # ------------------------------------------------------------------ analiz
    def feed(self, samples) -> bool:
        """Ses örneklerini ver; çift alkış algılanırsa True döner."""
        if self.paused:
            self._buf = self._buf[:0]
            self.state, self.last_clap, self.pending = "idle", None, None
            return False
        self._buf = np.concatenate([self._buf, np.asarray(samples, dtype=np.float32).reshape(-1)])
        fired = False
        while len(self._buf) >= self.block:
            blk, self._buf = self._buf[: self.block], self._buf[self.block:]
            if self._process(blk):
                fired = True
        return fired

    def _process(self, x) -> bool:
        t = self.n * self.DT
        self.n += 1
        rms = float(np.sqrt(np.mean(x * x))) + 1e-9
        hf = float(np.sqrt(np.mean(np.diff(x) ** 2))) / rms    # geniş bantlı (patlama gibi) sesler yüksek çıkar, ünlü harfler düşük
        thr = self.threshold()
        fired = False
        if self.pending is not None:     # çift alkış adayı: ardından ~0,3 sn sessizlik olmalı
            if rms > thr * 0.6 and t - self.pending > 0.06:
                self.pending = None      # hemen ses devam etti: büyük ihtimalle konuşma/müzik
            elif t - self.pending >= 0.32:
                self.pending = None
                self.doubles += 1
                self.cool_until = t + 1.5
                fired = True
        if self.state == "idle":
            if t < self.cool_until:
                pass
            elif rms > thr and rms > 2.5 * self.prev and hf >= self.hf_min:
                self.state, self.t0, self.peak, self.hf0 = "clap", t, rms, hf
            elif rms < self.noise * 3 + 1e-4:
                self.noise = max(0.0005, 0.995 * self.noise + 0.005 * rms)
        elif self.state == "clap":
            self.peak = max(self.peak, rms)
            if rms > thr * 0.35:
                if t - self.t0 > 0.22:        # çok uzun: konuşma/müzik, alkış değil
                    self.state = "cool"
            else:                             # enerji hızla düştü: alkış
                if self._accept(self.t0):
                    self.pending = t
                self.state = "idle"
        else:                                 # cool: yüksek ses bitene kadar bekle
            if rms < thr * 0.35:
                self.state = "idle"
        self.prev = rms
        return fired

    def _accept(self, t0) -> bool:
        self.singles += 1
        self.stats.append((round(t0, 2), round(self.peak, 3), round(self.hf0, 2)))
        del self.stats[:-20]
        if self.last_clap is not None and 0.18 <= t0 - self.last_clap <= 0.9:
            self.last_clap = None
            return True
        self.last_clap = t0
        return False

    # ------------------------------------------------------------------ mikrofon (paylaşılan AudioHub üzerinden)
    def _cb(self, x):
        try:
            if self.feed(x) and self.on_double_clap:
                threading.Thread(target=self.on_double_clap, daemon=True).start()
        except Exception:
            pass

    def start(self, hub=None):
        """Mikrofonu ayrıca açmaz: Jarvis'in tek mikrofon akışına (AudioHub) abone olur."""
        if self._hub is not None:
            return
        if hub is None:
            from audio_hub import get_hub
            hub = get_hub(self.device)
        self._hub = hub
        hub.subscribe(self._cb)

    def stop(self):
        if self._hub is not None:
            self._hub.unsubscribe(self._cb)
            self._hub = None

    @property
    def running(self):
        return self._hub is not None

    def run_test(self, seconds=6) -> dict:
        """Ayar testi: birkaç kez alkışla; kaç alkış/çift alkış algılandığını ve seviyeleri döndürür."""
        from audio_hub import get_hub
        hub = self._hub or get_hub(self.device)
        was_running = self._hub is not None
        self.stop()
        self.reset()
        self.singles = self.doubles = 0
        self.stats = []
        paused, self.paused = self.paused, False
        feed = lambda x: self.feed(x)
        hub.subscribe(feed)
        try:
            time.sleep(seconds)
        finally:
            hub.unsubscribe(feed)
            self.paused = paused
        res = {"singles": self.singles, "doubles": self.doubles, "stats": list(self.stats),
               "noise": self.noise, "threshold": self.threshold()}
        self.reset()
        if was_running:
            self.start(hub)
        return res
