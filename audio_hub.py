"""
Tek mikrofon akışı (AudioHub).
Eskiden alkış algılayıcı ve konuşma dinleyici mikrofonu ayrı ayrı açıp kapatıyordu: sürekli dinlemede her 3 saniyede
akış yeniden açılıyor, bu arada söylenen ilk kelimeler kayboluyordu; alkış algılayıcı da dinleme sırasında duruyordu.
Artık mikrofon bir kez açılır ve hep açık kalır; her blok (10 ms) tüm abonelere dağıtılır. Son ~1,5 sn bir halka
tamponda tutulur, böylece dinleme başladığında konuşmanın başı da yakalanır.
"""
import threading
import time
from collections import deque

import numpy as np

SR = 16000
BLOCK = 160            # 10 ms


class AudioHub:
    def __init__(self, device=None, ring_seconds=1.5):
        self.device = device
        self._subs = []                      # callable(np.ndarray)
        self._lock = threading.Lock()
        self._ring = deque(maxlen=int(ring_seconds * SR / BLOCK))
        self._stream = None
        self._alive = False
        self.error = None
        self.last_block_time = 0.0

    # ------------------------------------------------------------------ akış
    def start(self):
        if self._alive:
            return
        self._alive = True
        threading.Thread(target=self._watchdog, daemon=True).start()
        self._open()                         # hata olursa yükseltir; watchdog yine de tekrar dener

    def _open(self):
        import sounddevice as sd

        def cb(indata, frames, tinfo, status):
            x = indata[:, 0].copy()
            self.last_block_time = time.time()
            self._ring.append(x)
            with self._lock:
                subs = list(self._subs)
            for s in subs:
                try:
                    s(x)
                except Exception:
                    pass

        try:
            self._stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=BLOCK,
                                          device=self.device, callback=cb)
            self._stream.start()
            self.error = None
            self.last_block_time = time.time()
        except Exception as e:
            self._stream = None
            self.error = e
            raise

    def _close(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _watchdog(self):
        """Mikrofon çıkarılır/değişirse ya da akış donarsa yeniden açar."""
        while self._alive:
            time.sleep(2.0)
            if not self._alive:
                break
            if self._stream is None or time.time() - self.last_block_time > 3.0:
                self._close()
                try:
                    self._open()
                except Exception:
                    pass

    def stop(self):
        self._alive = False
        self._close()

    @property
    def running(self):
        return self._stream is not None

    # ------------------------------------------------------------------ aboneler
    def subscribe(self, fn):
        with self._lock:
            if fn not in self._subs:
                self._subs.append(fn)

    def unsubscribe(self, fn):
        with self._lock:
            if fn in self._subs:
                self._subs.remove(fn)

    def recent(self, seconds=0.5):
        """Halka tampondaki son `seconds` saniyelik ses."""
        n = max(1, int(seconds * SR / BLOCK))
        blocks = list(self._ring)[-n:]
        return np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.float32)


_hub = None


def get_hub(device=None) -> AudioHub:
    """Paylaşılan hub (ilk çağrıda oluşturulur ve başlatılır)."""
    global _hub
    if _hub is None:
        _hub = AudioHub(device)
    if not _hub._alive:
        _hub.start()
    return _hub
