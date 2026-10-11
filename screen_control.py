"""
Ekranı görme ve müdahale (fare / klavye) için düşük seviyeli yardımcılar.

Koordinat sistemi: Jarvis'in yapay zekası ekran görüntüsündeki konumları 0-1000 arası normalize edilmiş (x: soldan sağa,
y: yukarıdan aşağıya) değerlerle verir; burada gerçek piksele çevrilir. Çoklu monitör ve Windows ölçekleme (%125, %150)
desteklenir: süreç "DPI farkında" yapılır, böylece ekran görüntüsü pikselleri ile fare pikselleri aynı olur.

Güvenlik: pyautogui'nin acil durdurma özelliği açık — fareyi ekranın bir köşesine götürürsen işlem durur.
"""
import io
import os
import platform
import time

IS_WIN = platform.system() == "Windows"
_dpi_done = False


def ensure_dpi_aware():
    global _dpi_done
    if _dpi_done or not IS_WIN:
        return
    _dpi_done = True
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _pag():
    import pyautogui
    pyautogui.PAUSE = 0.05
    pyautogui.FAILSAFE = True
    return pyautogui


# ---------------------------------------------------------------------- ekran görüntüsü
def monitor_rect(index: int = None):
    """(sol, üst, genişlik, yükseklik) — mss monitör listesinden; 1 = ana monitör."""
    import mss
    ensure_dpi_aware()
    if index is None:
        index = int(os.getenv("JARVIS_MONITOR", "1"))
    with mss.mss() as sct:
        mons = sct.monitors
        m = mons[min(max(1, index), len(mons) - 1)]
        return m["left"], m["top"], m["width"], m["height"]


def capture(index: int = None, max_side: int = 1600, quality: int = 80):
    """Ekran görüntüsü: (jpeg baytları, monitör dikdörtgeni). İmleç konumu görüntüye küçük bir halka olarak çizilir."""
    import mss
    from PIL import Image, ImageDraw
    ensure_dpi_aware()
    rect = monitor_rect(index)
    with mss.mss() as sct:
        shot = sct.grab({"left": rect[0], "top": rect[1], "width": rect[2], "height": rect[3]})
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    try:                                    # fare imlecini işaretle: model nereye tıkladığını görebilsin
        cx, cy = _pag().position()
        cx, cy = cx - rect[0], cy - rect[1]
        if 0 <= cx < rect[2] and 0 <= cy < rect[3]:
            d = ImageDraw.Draw(img)
            r = max(8, rect[2] // 160)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 0, 80), width=3)
    except Exception:
        pass
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue(), rect


def to_pixels(x: float, y: float, rect):
    """0-1000 normalize koordinatı gerçek ekran pikseline çevirir."""
    x = max(0.0, min(1000.0, float(x)))
    y = max(0.0, min(1000.0, float(y)))
    px = rect[0] + int(round(x / 1000.0 * (rect[2] - 1)))
    py = rect[1] + int(round(y / 1000.0 * (rect[3] - 1)))
    return px, py


# ---------------------------------------------------------------------- fare / klavye
def click_px(px: int, py: int, button: str = "left", clicks: int = 1):
    pag = _pag()
    pag.moveTo(px, py, duration=0.12)
    time.sleep(0.05)
    pag.click(px, py, clicks=max(1, int(clicks)), interval=0.09, button=button if button in ("left", "right", "middle") else "left")


def move_px(px: int, py: int):
    _pag().moveTo(px, py, duration=0.15)


def scroll(direction: str = "down", amount: int = 5, px: int = None, py: int = None):
    pag = _pag()
    amount = max(1, min(50, int(amount)))
    if px is not None and py is not None:
        pag.moveTo(px, py, duration=0.1)
    if direction in ("left", "right"):
        pag.keyDown("shift")                # Windows'ta yatay kaydırma: Shift + tekerlek
        try:
            pag.scroll((120 if IS_WIN else 1) * amount * (1 if direction == "left" else -1))
        finally:
            pag.keyUp("shift")
    else:
        pag.scroll((120 if IS_WIN else 1) * amount * (1 if direction == "up" else -1))


def drag_px(x1: int, y1: int, x2: int, y2: int):
    pag = _pag()
    pag.moveTo(x1, y1, duration=0.12)
    pag.dragTo(x2, y2, duration=0.5, button="left")


# ---------------------------------------------------------------------- Windows UI Automation (isteğe bağlı)
_GENERIC = r"\b(düğmesi|düğme|butonu|buton|tuşu|simgesi|ikonu|ikon|sekmesi|sekme|menüsü|menü|bağlantısı|linki|kutusu|yazan|yazısı|" \
           r"seçeneği|öğesi|alanı|button|icon|tab|link)\b"
_PREFER = ("Button", "MenuItem", "Hyperlink", "ListItem", "TabItem", "Edit", "CheckBox", "RadioButton", "TreeItem", "ComboBox",
           "SplitButton", "MenuBarItem")


def uia_find(label: str, time_budget: float = 2.5):
    """Öndeki penceredeki erişilebilirlik ağacında adı `label` olan öğeyi arar.
    Bulursa (merkez_x, merkez_y, 'Tür: Ad') döner (gerçek piksel), bulamazsa None. 'uiautomation' paketi yoksa None."""
    if not IS_WIN or not label or not label.strip():
        return None
    import re
    want = re.sub(_GENERIC, "", label.lower().strip(" '\"“”‘’")).strip()
    want = re.sub(r"\s+", " ", want)
    if not want or len(want) > 60:
        return None
    try:
        import uiautomation as auto
    except Exception:
        return None
    ensure_dpi_aware()
    best, t0, n = None, time.time(), 0
    try:
        with auto.UIAutomationInitializerInThread():
            root = auto.GetForegroundControl()
            if root is None:
                return None
            for c, depth in auto.WalkControl(root, includeTop=False, maxDepth=18):
                n += 1
                if n > 4000 or time.time() - t0 > time_budget:
                    break
                try:
                    name = (c.Name or "").strip()
                    if not name or len(name) > 120:
                        continue
                    low = name.lower()
                    if low == want:
                        score = 3
                    elif low.startswith(want) or re.search(r"\b" + re.escape(want) + r"\b", low):
                        score = 2
                    elif want in low:
                        score = 1
                    else:
                        continue
                    if c.IsOffscreen:
                        continue
                    r = c.BoundingRectangle
                    if r.width() <= 2 or r.height() <= 2:
                        continue
                    ctype = c.ControlTypeName.replace("Control", "")
                    score += 0.5 if ctype in _PREFER else 0
                    if best is None or score > best[0]:
                        best = (score, (r.left + r.right) // 2, (r.top + r.bottom) // 2, f"{ctype}: {name}")
                        if score >= 3.5:
                            break
                except Exception:
                    continue
    except Exception:
        return None
    if best is None:
        return None
    return best[1], best[2], best[3]
