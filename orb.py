"""
Jarvis'in animasyonlu küresi. tkinter Canvas'ına çizer (create_oval / create_arc / create_line / delete yeterli).
Her durum için ayrı animasyon, durumlar arası yumuşak geçişle:

  hazir      yavaş "nefes alan" küre + etrafında yavaşça dönen noktalar
  dinliyor   mikrofon seviyesine tepki veren küre + dışa yayılan dalga halkaları
  dusunuyor  küre etrafında dönen yaylar ve yörüngedeki noktalar
  konusuyor  ses seviyesine tepki veren radyal çubuklar (ses dalgası halkası) + atan küre
"""
import math
import random
import time

BG = (13, 17, 23)
WHITE = (255, 255, 255)

COLORS = {
    "hazir": (47, 129, 247),
    "dinliyor": (56, 189, 248),
    "dusunuyor": (99, 102, 241),
    "konusuyor": (96, 165, 250),
    "yukleniyor": (110, 125, 150),
}
FX_FOR = {"hazir": "idle", "yukleniyor": "idle", "dinliyor": "listen", "dusunuyor": "think", "konusuyor": "speak"}


def mix(a, b, k):
    k = max(0.0, min(1.0, k))
    return tuple(a[i] + (b[i] - a[i]) * k for i in range(3))


def hexc(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in c)


class Orb:
    N_BARS = 72

    def __init__(self, seed=1):
        rnd = random.Random(seed)
        self.t0 = time.time()
        self.last = None
        self.color = COLORS["hazir"]
        self.mic = 0.0
        self.voice = 0.0
        self.fx = {"idle": 1.0, "listen": 0.0, "think": 0.0, "speak": 0.0}
        self.phase = [rnd.random() * 6.283 for _ in range(self.N_BARS)]

    @staticmethod
    def _fake_voice(t):
        """Gerçek ses seviyesi bilinmiyorsa (çevrimdışı ses) konuşma ritmini taklit eder."""
        v = 0.25 + 0.55 * abs(math.sin(t * 5.1)) * abs(math.sin(t * 1.9 + 0.6)) + 0.2 * abs(math.sin(t * 11.7))
        return max(0.0, min(1.0, v))

    def draw(self, cv, w, h, state="hazir", mic=0.0, voice=None, now=None) -> int:
        """Bir kare çizer. mic: 0..~0.3 ham mikrofon RMS'i, voice: 0..1 konuşma seviyesi (None = bilinmiyor)."""
        if w < 40 or h < 40:
            return 0
        now = time.time() if now is None else now
        dt = 0.033 if self.last is None else max(0.001, min(0.1, now - self.last))
        self.last = now
        t = now - self.t0

        # ---- yumuşak geçişler
        self.color = mix(self.color, COLORS.get(state, COLORS["hazir"]), 1 - math.exp(-dt * 6))
        self.mic += (min(1.0, mic * 6.0) - self.mic) * (1 - math.exp(-dt * 14))
        v = self._fake_voice(t) if voice is None else max(0.0, min(1.0, voice))
        if state != "konusuyor":
            v = 0.0
        self.voice += (v - self.voice) * (1 - math.exp(-dt * 16))
        want = FX_FOR.get(state, "idle")
        for k in self.fx:
            self.fx[k] += ((1.0 if k == want else 0.0) - self.fx[k]) * (1 - math.exp(-dt * 5))
        fx = self.fx

        cx, cy = w / 2.0, h / 2.0
        R = min(w, h) * 0.20
        col = self.color
        light = mix(col, WHITE, 0.55)
        scale = (1.0 + 0.035 * math.sin(t * 2.0) * fx["idle"]
                 + (0.03 * math.sin(t * 3.0) + 0.28 * self.mic) * fx["listen"]
                 + 0.05 * math.sin(t * 7.0) * fx["think"]
                 + (0.03 * math.sin(t * 4.0) + 0.24 * self.voice) * fx["speak"])
        Rc = R * scale
        n = 0
        cv.delete("all")

        # ---- 1) hale
        for i in range(12, 0, -1):
            r = Rc * (1 + 0.11 * i)
            k = ((13 - i) / 12.0) ** 2 * 0.28
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=hexc(mix(BG, col, k)), outline="")
            n += 1

        # ---- 2) hazır: yavaş dönen noktalar
        if fx["idle"] > 0.03:
            for i in range(28):
                a = t * 0.25 + i * 2 * math.pi / 28
                b = (0.25 + 0.2 * math.sin(t * 1.5 + i)) * fx["idle"]
                r = Rc * 1.55
                x, y = cx + r * math.cos(a), cy + r * math.sin(a)
                cv.create_oval(x - 1.8, y - 1.8, x + 1.8, y + 1.8, fill=hexc(mix(BG, light, b)), outline="")
                n += 1

        # ---- 3) dinliyor: dışa yayılan dalgalar (mikrofona duyarlı)
        if fx["listen"] > 0.03:
            for j in range(3):
                p = (t * 0.65 + j / 3.0) % 1.0
                r = Rc * (1.12 + p * (0.55 + 0.7 * self.mic))
                strength = (1 - p) * fx["listen"] * (0.35 + 0.65 * min(1.0, self.mic * 1.5 + 0.35))
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill="", outline=hexc(mix(BG, light, strength)), width=2)
                n += 1

        # ---- 4) düşünüyor: dönen yaylar + yörünge noktaları
        if fx["think"] > 0.03:
            for idx, (rm, wd, spd, ext) in enumerate(((1.30, 5, 150, 100), (1.52, 4, -105, 75), (1.76, 3, 70, 55))):
                r = Rc * rm
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill="", outline=hexc(mix(BG, col, 0.22 * fx["think"])), width=1)
                cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=(t * spd + idx * 117) % 360, extent=ext,
                              style="arc", outline=hexc(mix(BG, light, 0.95 * fx["think"])), width=wd)
                n += 2
            for j in range(5):
                a = t * 2.4 * (1 if j % 2 == 0 else -1) + j * 2 * math.pi / 5
                r = Rc * 1.95
                x, y = cx + r * math.cos(a), cy + r * math.sin(a)
                cv.create_oval(x - 4, y - 4, x + 4, y + 4, fill=hexc(mix(BG, light, fx["think"])), outline="")
                n += 1

        # ---- 5) konuşuyor: ses seviyesine tepki veren radyal çubuklar
        if fx["speak"] > 0.03:
            N = self.N_BARS
            for i in range(N):
                a = 2 * math.pi * i / N - math.pi / 2 + t * 0.12
                amp = self.voice * (0.30 + 0.70 * abs(math.sin(i * 0.55 + t * 9.0 + self.phase[i])))
                r0 = Rc * 1.14
                r1 = r0 + Rc * (0.07 + 0.62 * amp)
                c = mix(BG, mix(col, WHITE, 0.25 + 0.55 * amp), fx["speak"] * (0.5 + 0.5 * amp))
                cv.create_line(cx + r0 * math.cos(a), cy + r0 * math.sin(a), cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                               fill=hexc(c), width=3, capstyle="round")
                n += 1

        # ---- 6) çekirdek: kademeli renkle "küre" görünümü
        for j in range(9):
            f = j / 8.0
            r = Rc * (1 - 0.095 * j)
            ox = oy = -0.12 * Rc * f
            cv.create_oval(cx + ox - r, cy + oy - r, cx + ox + r, cy + oy + r,
                           fill=hexc(mix(mix(col, BG, 0.35), light, f ** 1.2)), outline="")
            n += 1
        hr = Rc * 0.13
        cv.create_oval(cx - 0.36 * Rc - hr, cy - 0.40 * Rc - hr, cx - 0.36 * Rc + hr, cy - 0.40 * Rc + hr,
                       fill=hexc(mix(light, WHITE, 0.5)), outline="")
        cv.create_oval(cx - Rc, cy - Rc, cx + Rc, cy + Rc, fill="", outline=hexc(mix(col, light, 0.4)), width=2)
        return n + 2
