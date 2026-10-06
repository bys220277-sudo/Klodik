# -*- coding: utf-8 -*-
"""
Klodik v4.4 — пиксельный краб Клодик на рабочем столе Windows.
Фанатский проект, не связан с Anthropic. Лицензия MIT.
Ходит по панели задач, окнам, иконкам и браузеру, прыгает между мониторами, следит глазами
за курсором, живёт по распорядку (гуляет, играет, творит, отдыхает), рисует карандашом на обоях,
распихивает иконки во все стороны и строит из них домики. Можно гладить, таскать и кидать мышкой.
"""
import os, sys, math, random, time, json, struct, ctypes, traceback, importlib.util, threading, re, queue, shutil, functools
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# Qt работает в физических пикселях — координаты совпадают с Win32 API
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QRect, QSettings, QUrl
from PyQt6.QtGui import (QPainter, QColor, QPen, QPixmap, QIcon, QCursor, QFont, QAction, QImage, QFontMetrics,
                         QGuiApplication, QPainterPath, QPolygonF, QRegion, QActionGroup, QDesktopServices)
from PyQt6.QtWidgets import QApplication, QWidget, QMenu, QSystemTrayIcon, QMessageBox
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

IS_WIN = sys.platform == "win32"
APP_NAME = "Klodik"
OLD_NAME = "ClaudePet"                    # так программа называлась до v4.4: настройки переносим оттуда
_APPDATA = os.environ.get("APPDATA") or os.path.expanduser("~")
DATA_DIR = os.path.join(_APPDATA, APP_NAME)
OLD_DATA_DIR = os.path.join(_APPDATA, OLD_NAME)
LOG_PATH = os.path.join(DATA_DIR, "error.log")


def log_error(title, text=""):
    """Всё, что пошло не так, пишем в %APPDATA%\\Klodik\\error.log (в exe нет консоли)."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 512 * 1024:
            os.replace(LOG_PATH, LOG_PATH + ".old")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), title, text))
    except Exception:
        pass


_last_err = ["", 0.0]


def _excepthook(tp, val, tb):
    # без своего excepthook PyQt6 при любой ошибке в обработчике молча закрывает программу
    text = "".join(traceback.format_exception(tp, val, tb))
    if text == _last_err[0] and time.time() - _last_err[1] < 30:
        return                                    # одна и та же ошибка каждый кадр — не засоряем журнал
    _last_err[0], _last_err[1] = text, time.time()
    log_error("Необработанная ошибка", text)


sys.excepthook = _excepthook


class Watchdog(threading.Thread):
    """Если главный поток завис (краб не двигается и не слышит мышь) дольше 3 секунд —
    записать в error.log, на какой строке программы он застрял."""

    def __init__(self):
        super().__init__(daemon=True)
        self.beat = time.monotonic()
        self.main_id = threading.main_thread().ident

    def run(self):
        reported = False
        while True:
            time.sleep(1.0)
            lag = time.monotonic() - self.beat
            if lag > 3.0 and not reported:
                reported = True
                frame = sys._current_frames().get(self.main_id)
                stack = "".join(traceback.format_stack(frame)) if frame else "(стек недоступен)"
                log_error("Завис больше чем на %.0f с" % lag, stack)
            elif lag < 1.0 and reported:
                reported = False
                log_error("Отвис", "")


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def load_ai():
    """ИИ-часть: сначала вшитая в exe, иначе pet_ai.py рядом с exe/скриптом. Возвращает (модуль, ошибка)."""
    errors = []
    try:
        import pet_ai
        return pet_ai, ""
    except Exception:
        errors.append(traceback.format_exc())
    for d in dict.fromkeys((app_dir(), os.getcwd())):
        path = os.path.join(d, "pet_ai.py")
        if not os.path.isfile(path):
            continue
        try:
            spec = importlib.util.spec_from_file_location("pet_ai", path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["pet_ai"] = mod
            spec.loader.exec_module(mod)
            return mod, ""
        except Exception:
            sys.modules.pop("pet_ai", None)
            errors.append("%s:\n%s" % (path, traceback.format_exc()))
    full = "\n".join(errors)
    log_error("ИИ-модуль не загрузился", full)
    lines = [l for l in full.strip().splitlines() if l.strip()]
    return None, (lines[-1] if lines else "pet_ai.py не найден")


pet_ai, AI_ERROR = load_ai()
AIBrain = getattr(pet_ai, "AIBrain", None) if pet_ai else None
if pet_ai and not AIBrain:
    AI_ERROR = "в pet_ai.py нет AIBrain — это старая версия файла"

BODY = QColor(203, 124, 93)
DARK = QColor(12, 12, 14)
PINK = QColor(255, 122, 162)


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def sgn(v):
    return 1 if v >= 0 else -1


# ════════════════════════════ Win32 ════════════════════════════
if IS_WIN:
    import winreg
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")
    shell32 = ctypes.WinDLL("shell32")
    HWND, UINT, DWORD = wintypes.HWND, wintypes.UINT, wintypes.DWORD
    WP, LP, VP = wintypes.WPARAM, wintypes.LPARAM, ctypes.c_void_p
    S = wintypes.LPCWSTR

    def _sig(fn, args, res):
        fn.argtypes, fn.restype = args, res

    _sig(user32.FindWindowW, [S, S], HWND)
    _sig(user32.FindWindowExW, [HWND, HWND, S, S], HWND)
    _sig(user32.SendMessageTimeoutW, [HWND, UINT, WP, LP, UINT, UINT, ctypes.POINTER(ctypes.c_size_t)], LP)
    _sig(user32.PostMessageW, [HWND, UINT, WP, LP], wintypes.BOOL)
    _sig(user32.GetWindowThreadProcessId, [HWND, ctypes.POINTER(DWORD)], DWORD)
    _sig(user32.IsWindowVisible, [HWND], wintypes.BOOL)
    _sig(user32.IsIconic, [HWND], wintypes.BOOL)
    _sig(user32.GetWindowLongW, [HWND, ctypes.c_int], ctypes.c_long)
    _sig(user32.SetWindowLongW, [HWND, ctypes.c_int, ctypes.c_long], ctypes.c_long)
    _sig(user32.GetWindowTextLengthW, [HWND], ctypes.c_int)
    _sig(user32.GetClassNameW, [HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int)
    _sig(user32.GetWindowRect, [HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL)
    _sig(user32.ClientToScreen, [HWND, ctypes.POINTER(wintypes.POINT)], wintypes.BOOL)
    _sig(user32.WindowFromPoint, [wintypes.POINT], HWND)
    _sig(user32.GetAncestor, [HWND, UINT], HWND)
    _sig(user32.GetWindow, [HWND, UINT], HWND)
    _sig(user32.GetForegroundWindow, [], HWND)
    _sig(user32.SetWindowPos, [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, UINT], wintypes.BOOL)
    _sig(user32.GetDpiForWindow, [HWND], UINT)
    _sig(kernel32.OpenProcess, [DWORD, wintypes.BOOL, DWORD], VP)
    _sig(kernel32.CloseHandle, [VP], wintypes.BOOL)
    _sig(kernel32.VirtualAllocEx, [VP, VP, ctypes.c_size_t, DWORD, DWORD], VP)
    _sig(kernel32.ReadProcessMemory, [VP, VP, VP, ctypes.c_size_t, VP], wintypes.BOOL)
    _sig(kernel32.WriteProcessMemory, [VP, VP, VP, ctypes.c_size_t, VP], wintypes.BOOL)
    _sig(kernel32.QueryFullProcessImageNameW, [VP, DWORD, wintypes.LPWSTR, ctypes.POINTER(DWORD)], wintypes.BOOL)
    _sig(kernel32.CreateMutexW, [VP, wintypes.BOOL, S], VP)
    _sig(dwmapi.DwmGetWindowAttribute, [HWND, DWORD, VP, DWORD], ctypes.c_long)
    ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, LP)
    _sig(user32.EnumWindows, [ENUMPROC, LP], wintypes.BOOL)
    _sig(user32.GetWindowTextW, [HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int)
    _sig(user32.IsHungAppWindow, [HWND], wintypes.BOOL)
    _sig(kernel32.GetTickCount, [], DWORD)

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", UINT), ("dwTime", DWORD)]

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", DWORD), ("dwMemoryLoad", DWORD)] + \
                   [(n, ctypes.c_ulonglong) for n in ("tp", "ap", "tpf", "apf", "tv", "av", "aev")]

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [("ac", ctypes.c_ubyte), ("flag", ctypes.c_ubyte), ("pct", ctypes.c_ubyte),
                    ("ssf", ctypes.c_ubyte), ("lt", DWORD), ("flt", DWORD)]

    _ULL = ctypes.POINTER(ctypes.c_ulonglong)
    _sig(user32.GetLastInputInfo, [ctypes.POINTER(LASTINPUTINFO)], wintypes.BOOL)
    _sig(kernel32.GetSystemTimes, [_ULL, _ULL, _ULL], wintypes.BOOL)
    _sig(kernel32.GlobalMemoryStatusEx, [ctypes.POINTER(MEMORYSTATUSEX)], wintypes.BOOL)
    _sig(kernel32.GetSystemPowerStatus, [ctypes.POINTER(SYSTEM_POWER_STATUS)], wintypes.BOOL)
    _sig(kernel32.GetLogicalDrives, [], DWORD)
    _sig(kernel32.GetDriveTypeW, [S], UINT)
    _sig(kernel32.GetDiskFreeSpaceExW, [S, _ULL, _ULL, _ULL], wintypes.BOOL)

    def w_text(hwnd):
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def idle_seconds():
        """Сколько секунд хозяин не трогал мышь и клавиатуру."""
        li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
        if not user32.GetLastInputInfo(ctypes.byref(li)):
            return 0.0
        return ((kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0

    def w_class(hwnd):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def w_frame(hwnd):
        r = wintypes.RECT()
        if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(r))
        return r.left, r.top, r.right, r.bottom

    def w_cloaked(hwnd):
        v = DWORD(0)
        dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(v), 4)
        return v.value != 0

    _exe_cache = {}

    def exe_of(hwnd):
        pid = DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in _exe_cache:
            return _exe_cache[pid.value]
        if len(_exe_cache) > 300:
            _exe_cache.clear()
        name = ""
        h = kernel32.OpenProcess(0x1000, False, pid.value)
        if h:
            buf = ctypes.create_unicode_buffer(520)
            n = DWORD(520)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                name = os.path.basename(buf.value).lower()
            kernel32.CloseHandle(h)
        _exe_cache[pid.value] = name
        return name

    def find_listview():
        """SysListView32 рабочего стола (в нём лежат иконки)."""
        defview = None
        prog = user32.FindWindowW("Progman", None)
        if prog:
            defview = user32.FindWindowExW(prog, None, "SHELLDLL_DefView", None)
        if not defview:
            w = None
            while True:
                w = user32.FindWindowExW(None, w, "WorkerW", None)
                if not w:
                    break
                defview = user32.FindWindowExW(w, None, "SHELLDLL_DefView", None)
                if defview:
                    break
        if not defview:
            return None
        return user32.FindWindowExW(defview, None, "SysListView32", None)

    def desktop_host():
        """Окно рабочего стола с иконками (Progman или WorkerW) — над ним кладём слой с рисунками."""
        lv = find_listview()
        return (user32.GetAncestor(lv, 2) or None) if lv else None

    def desktop_root_ok(h, ignore):
        if not h:
            return False
        root = user32.GetAncestor(h, 2) or h
        return root in ignore or w_class(root) in ("Progman", "WorkerW")


else:
    def w_text(hwnd):
        return ""

    def idle_seconds():
        return 0.0


SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                "Windows.UI.Core.CoreWindow", "NotifyIconOverflowWindow"}
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe",
            "browser.exe", "yandex.exe", "arc.exe", "chromium.exe", "zen.exe", "librewolf.exe",
            "waterfox.exe", "iexplore.exe"}


class Plat:
    """Поверхность, по которой он ходит: пол, окно, иконка, «полка» браузера."""
    __slots__ = ("kind", "key", "x1", "x2", "y", "m", "rect", "idx")

    def __init__(self, kind, key, x1, x2, y, m=0, rect=None, idx=None):
        self.kind, self.key, self.x1, self.x2, self.y = kind, key, x1, x2, y
        self.m, self.rect, self.idx = m, rect, idx


def scan_windows(ignore, screens, U):
    """Возвращает (платформы, прямоугольники браузеров, прямоугольники всех окон)."""
    plats, browsers, covers = [], [], []
    if not IS_WIN:
        return plats, browsers, covers

    def exposed(hwnd, x, y):
        h = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        if not h:
            return False
        root = user32.GetAncestor(h, 2) or h
        return root == hwnd or root in ignore

    def cb(hwnd, _):
        try:
            if hwnd in ignore or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            cls = w_class(hwnd)
            if cls in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
                covers.append(w_frame(hwnd))
                return True
            ex = user32.GetWindowLongW(hwnd, -20)
            if ex & 0x80 or ex & 0x20 or user32.GetWindowTextLengthW(hwnd) == 0:
                return True                       # служебные и «прозрачные для мыши» оверлеи — не окна
            if cls in SKIP_CLASSES or w_cloaked(hwnd):
                return True
            l, t, r, b = w_frame(hwnd)
            covers.append((l, t, r, b))
            w, h = r - l, b - t
            if w < 260 or h < 140:
                return True
            cx, cy = (l + r) // 2, (t + b) // 2
            scr = next((s for s in screens if s[0] <= cx < s[2] and s[1] <= cy < s[3]), None)
            if not scr:
                return True
            sl, st, sr, sb = scr
            maximized = l <= sl + 12 and r >= sr - 12 and t <= st + 12
            is_browser = exe_of(hwnd) in BROWSERS
            x1, x2 = max(l, sl), min(r, sr)
            if not maximized and t - st >= 13 * U and exposed(hwnd, (x1 + x2) // 2, t + 3):
                plats.append(Plat("browser_top" if is_browser else "window", ("win", hwnd), x1, x2, t))
            if is_browser and w > 400 and h > 300 and exposed(hwnd, cx, max(t, st) + 3):
                browsers.append((l, t, r, b))
                dpi = user32.GetDpiForWindow(hwnd) or 96
                plats.append(Plat("ledge", ("ledge", hwnd), x1 + 10, x2 - 10, max(t, st) + round(86 * dpi / 96)))
                if b < sb - 12:
                    plats.append(Plat("browser_in", ("bin", hwnd), x1 + 10, x2 - 10, b - 2))
        except Exception:
            pass
        return True

    user32.EnumWindows(ENUMPROC(cb), 0)
    return plats, browsers, covers


class Desktop:
    """Доступ к иконкам рабочего стола через SysListView32 процесса explorer.
    Сдвинутые иконки остаются на новых местах навсегда; исходные места запоминаются в
    %APPDATA%\\Klodik\\icons_home.json, чтобы краб мог сам растолкать их обратно."""

    def __init__(self):
        self.ok = False
        self.flags = []
        self.icon_covers = []
        self.home = {}                    # имя иконки -> исходная позиция (клиентские координаты)
        self.names = {}                   # индекс -> имя (кэш)
        self.mx = threading.RLock()       # общий буфер в explorer: иконки опрашиваются и из фонового потока
        self.home_path = os.path.join(DATA_DIR, "icons_home.json")
        if not IS_WIN:
            return
        try:
            self.lv = find_listview()
            if not self.lv:
                return
            pid = DWORD(0)
            user32.GetWindowThreadProcessId(self.lv, ctypes.byref(pid))
            self.proc = kernel32.OpenProcess(0x0008 | 0x0010 | 0x0020 | 0x0400, False, pid.value)
            if not self.proc:
                return
            self.remote = kernel32.VirtualAllocEx(self.proc, None, 4096, 0x3000, 0x04)
            if not self.remote:
                return
            self.ok = True
            self.load_home()
            self.prepare()
        except Exception:
            log_error("Иконки недоступны", traceback.format_exc())
            self.ok = False

    # --- низкий уровень ---
    def _send(self, msg, w=0, l=0):
        res = ctypes.c_size_t(0)
        ok = user32.SendMessageTimeoutW(self.lv, msg, w, l, 0x2, 150, ctypes.byref(res))
        return res.value if ok else None

    def _write(self, data, off=0):
        kernel32.WriteProcessMemory(self.proc, self.remote + off, data, len(data), None)

    def _read(self, n, off=0):
        buf = ctypes.create_string_buffer(n)
        kernel32.ReadProcessMemory(self.proc, self.remote + off, buf, n, None)
        return buf.raw

    def prepare(self):
        """Выключаем автоупорядочивание и привязку к сетке, иначе иконки не сдвинуть.
        Обратно не включаем: Windows тут же расставила бы иконки заново.
        Возвращает True, если что-то пришлось выключить."""
        fixed = False
        style = user32.GetWindowLongW(self.lv, -16)
        if style & 0x100:
            user32.SetWindowLongW(self.lv, -16, style & ~0x100)
            fixed = True
            if "auto" not in self.flags:
                self.flags.append("auto")
        ext = self._send(0x1037)
        if ext and ext & 0x80000:
            self._send(0x1036, 0x80000, 0)
            fixed = True
            if "snap" not in self.flags:
                self.flags.append("snap")
        return fixed

    def ensure_free(self):
        """Explorer сам включает «Выровнять по сетке» обратно (новый файл на столе, F5, смена экрана).
        Тогда иконка едет рывками по клеточкам. Проверяем перед каждым толчком и при опросе."""
        if not self.ok:
            return False
        try:
            fixed = self.prepare()
        except Exception:
            return False
        if fixed:
            self.refixed = getattr(self, "refixed", 0) + 1
            if self.refixed == 1:
                log_error("Windows снова включила выравнивание значков по сетке", "Выключил, иконки снова едут плавно.")
        return fixed

    # --- чтение ---
    def visible(self):
        return self.ok and bool(user32.IsWindowVisible(self.lv))

    def origin(self):
        pt = wintypes.POINT(0, 0)
        user32.ClientToScreen(self.lv, ctypes.byref(pt))
        return pt.x, pt.y

    def count(self):
        return self._send(0x1004) or 0

    def spacing(self):
        v = self._send(0x1033, 0, 0)
        if v:
            cx, cy = v & 0xFFFF, (v >> 16) & 0xFFFF
            if 30 < cx < 400 and 30 < cy < 400:
                return cx, cy
        return 80, 100

    def _rect(self, i, code):
        with self.mx:
            self._write(struct.pack("<4i", code, 0, 0, 0))
            if not self._send(0x100E, i, self.remote):
                return None
            return struct.unpack("<4i", self._read(16))

    def item_rect(self, i):       # сама картинка иконки
        return self._rect(i, 1)

    def item_bounds(self, i):     # вся ячейка (с подписью)
        return self._rect(i, 0)

    def item_pos(self, i):
        with self.mx:
            if self._send(0x1010, i, self.remote) is None:
                return None
            return struct.unpack("<2i", self._read(8))

    def item_name(self, i):
        """Подпись иконки (LVM_GETITEMTEXTW); explorer 64-битный — структура LVITEMW x64."""
        if i in self.names:
            return self.names[i]
        name = ""
        try:
            with self.mx:
                item = bytearray(88)
                struct.pack_into("<i", item, 8, 0)                       # iSubItem
                struct.pack_into("<Q", item, 24, self.remote + 512)      # pszText
                struct.pack_into("<i", item, 32, 260)                    # cchTextMax
                self._write(bytes(item))
                n = self._send(0x1073, i, self.remote) or 0
                if 0 < n <= 260:
                    ptr = struct.unpack_from("<Q", self._read(32), 24)[0]    # список мог вернуть свой буфер
                    buf = ctypes.create_string_buffer(n * 2)
                    kernel32.ReadProcessMemory(self.proc, ptr or (self.remote + 512), buf, n * 2, None)
                    name = buf.raw.decode("utf-16-le", "ignore")
        except Exception:
            name = ""
        self.names[i] = name
        return name

    def set_pos(self, i, x, y):
        self._send(0x100F, i, ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF))

    def post_pos(self, i, x, y):
        """То же, но не дожидаясь explorer: для кадров анимации, чтобы краб не ждал перерисовки иконки."""
        user32.PostMessageW(self.lv, 0x100F, i, ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF))

    def scan(self, screens, ignore):
        out, covers = self.scan_all(screens, ignore)
        self.icon_covers = covers
        return out

    def scan_all(self, screens, ignore):
        """Опрос всех иконок: (платформы, прямоугольники ячеек). Можно звать из фонового потока."""
        out, covers = [], []
        if not self.visible():
            return out, covers
        n = self.count()
        if len(self.names) and n != getattr(self, "_n", n):
            self.names = {}                       # иконки добавили/удалили — индексы сдвинулись
        self._n = n
        ox, oy = self.origin()
        for i in range(min(n, 150)):
            r = self.item_rect(i)
            if not r:
                continue
            l, t, rr, b = r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy
            if rr - l < 8:
                continue
            cx, cy = (l + rr) // 2, (t + b) // 2
            if not any(s[0] <= cx < s[2] and s[1] <= cy < s[3] for s in screens):
                continue
            bd = self.item_bounds(i)
            if bd:
                covers.append((bd[0] + ox, bd[1] + oy, bd[2] + ox, bd[3] + oy))
            if not desktop_root_ok(user32.WindowFromPoint(wintypes.POINT(cx, cy)), ignore):
                continue
            out.append(Plat("icon", ("icon", i), l, rr, t + int((b - t) * 0.1), 0, rect=(l, t, rr, b), idx=i))
        return out, covers

    def boxes(self):
        """Все иконки: индекс -> [x, y, w, h] в клиентских координатах (для распихивания)."""
        out = {}
        for i in range(min(self.count(), 150)):
            pos, bd = self.item_pos(i), self.item_bounds(i)
            if pos and bd:
                out[i] = [pos[0], pos[1], bd[2] - bd[0], bd[3] - bd[1]]
        return out

    # --- исходные места ---
    def key(self, i):
        return self.item_name(i) or "#%d" % i

    def remember(self, i, pos=None):
        k = self.key(i)
        if k in self.home:
            return
        pos = pos or self.item_pos(i)
        if not pos:
            return
        self.home[k] = list(pos)
        self.save_home()

    def load_home(self):
        try:
            with open(self.home_path, encoding="utf-8") as f:
                self.home = {k: list(v) for k, v in json.load(f).items()}
        except Exception:
            self.home = {}

    def save_home(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(self.home_path, "w", encoding="utf-8") as f:
                json.dump(self.home, f, ensure_ascii=False)
        except Exception:
            pass

    def displaced(self):
        """Иконки не на своих местах: [(индекс, (x, y))]."""
        out, seen = [], set()
        for i in range(min(self.count(), 150)):
            k = self.key(i)
            if k in self.home and k not in seen:
                seen.add(k)
                pos = self.item_pos(i)
                hx, hy = self.home[k]
                if pos and (abs(pos[0] - hx) > 2 or abs(pos[1] - hy) > 2):
                    out.append((i, (hx, hy)))
        return out

    def forget_home(self):
        self.home = {}
        try:
            os.remove(self.home_path)
        except OSError:
            pass

    def restore_now(self):
        """Мгновенно вернуть всё (запасной вариант, без анимации)."""
        for i, (x, y) in self.displaced():
            self.set_pos(i, x, y)
        self.forget_home()

    def shutdown(self):
        pass                                     # иконки остаются там, куда их сдвинули


# ═══════════════════════════ автозапуск ═══════════════════════════
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_cmd():
    if getattr(sys, "frozen", False):
        return '"%s"' % sys.executable
    return '"%s" "%s"' % (sys.executable, os.path.abspath(__file__))


def autostart_enabled():
    if not IS_WIN:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(on):
    if not IS_WIN:
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, autostart_cmd())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


# ═══════════════════════════ рисунки карандашом ═══════════════════════════
def _arc(cx, cy, r, a0, a1, n=28):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def shape_heart():
    pts = []
    for i in range(49):
        t = -math.pi + 2 * math.pi * i / 48
        pts.append((16 * math.sin(t) ** 3 / 17,
                    -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)) / 17))
    return [pts]


def shape_star():
    return [[(math.cos(math.radians(-90 + k * 144)), math.sin(math.radians(-90 + k * 144))) for k in range(6)]]


def shape_sun():
    out = [_arc(0, 0, 0.42, 0, 360)]
    for k in range(8):
        a = math.radians(k * 45)
        out.append([(0.6 * math.cos(a), 0.6 * math.sin(a)), (0.98 * math.cos(a), 0.98 * math.sin(a))])
    return out


def shape_smile():
    return [_arc(0, 0, 0.9, 0, 360, 40), _arc(-0.32, -0.25, 0.07, 0, 360, 8),
            _arc(0.32, -0.25, 0.07, 0, 360, 8), _arc(0, 0.05, 0.52, 20, 160)]


def shape_house():
    return [[(-0.7, 0.8), (-0.7, -0.1), (0, -0.85), (0.7, -0.1), (0.7, 0.8), (-0.7, 0.8)],
            [(-0.15, 0.8), (-0.15, 0.3), (0.15, 0.3), (0.15, 0.8)]]


def shape_flower():
    out = [_arc(0, -0.45, 0.14, 0, 360, 12)]
    for k in range(6):
        a = math.radians(k * 60)
        out.append(_arc(0.34 * math.cos(a), -0.45 + 0.34 * math.sin(a), 0.17, 0, 360, 14))
    out.append([(0, -0.15), (0.03, 0.3), (0, 0.9)])
    out.append(_arc(0.22, 0.45, 0.22, 200, 380, 12))
    return out


def shape_spiral():
    return [[(r * math.cos(a), r * math.sin(a)) for a, r in
             ((i * 0.18, 0.04 + 0.95 * i / 90) for i in range(91))]]


def shape_bolt():
    return [[(0.2, -0.9), (-0.3, 0.05), (0.05, 0.05), (-0.2, 0.9), (0.4, -0.15), (0.05, -0.15), (0.2, -0.9)]]


def shape_asterisk():
    out = []
    for a in (0, 45, 90, 135):
        c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
        out.append([(-0.9 * c, -0.9 * s), (0.9 * c, 0.9 * s)])
    return out


def shape_self():
    body = [(2, 0), (14, 0), (14, 4), (16, 4), (16, 6), (14, 6), (14, 8), (13, 8), (13, 10), (12, 10), (12, 8),
            (11, 8), (11, 10), (10, 10), (10, 8), (6, 8), (6, 10), (5, 10), (5, 8), (4, 8), (4, 10), (3, 10),
            (3, 8), (2, 8), (2, 6), (0, 6), (0, 4), (2, 4), (2, 0)]
    f = lambda pts: [((x - 8) / 8, (y - 5) / 8) for x, y in pts]
    return [f(body), f([(4, 2), (5, 2), (5, 4), (4, 4), (4, 2)]), f([(11, 2), (12, 2), (12, 4), (11, 4), (11, 2)])]


def shape_cloud():
    return [_arc(-0.45, 0.1, 0.35, 90, 270, 14) + _arc(-0.15, -0.25, 0.4, 180, 330, 16) +
            _arc(0.35, -0.15, 0.38, 230, 400, 16) + _arc(0.55, 0.2, 0.3, 270, 450, 12) +
            [(0.55, 0.5), (-0.45, 0.45)]]


def shape_tree():
    crown = _arc(0, -0.35, 0.55, 0, 360, 30)
    return [crown, [(-0.12, 0.2), (-0.12, 0.95)], [(0.12, 0.2), (0.12, 0.95)], [(-0.5, 0.95), (0.5, 0.95)]]


def shape_cat():
    head = [(-0.6, -0.3), (-0.55, -0.85), (-0.25, -0.5), (0.25, -0.5), (0.55, -0.85), (0.6, -0.3)]
    head += _arc(0, -0.25, 0.6, 0, 180, 18)[1:] + [(-0.6, -0.3)]
    return [head, _arc(-0.22, -0.2, 0.06, 0, 360, 8), _arc(0.22, -0.2, 0.06, 0, 360, 8),
            [(-0.08, 0.02), (0, 0.08), (0.08, 0.02)],
            [(-0.25, 0.05), (-0.75, -0.02)], [(-0.25, 0.12), (-0.75, 0.18)],
            [(0.25, 0.05), (0.75, -0.02)], [(0.25, 0.12), (0.75, 0.18)]]


def shape_fish():
    body = _arc(0, 0.2, 0.55, 200, 340, 16) + _arc(0, -0.2, 0.55, 20, 160, 16)
    return [body + [body[0]], [(0.52, 0), (0.95, -0.35), (0.95, 0.35), (0.52, 0)],
            _arc(-0.3, -0.07, 0.06, 0, 360, 8)]


def shape_wave():
    return [[(-0.95 + i * 0.05, 0.25 * math.sin(i * 0.45) - 0.2) for i in range(39)],
            [(-0.95 + i * 0.05, 0.25 * math.sin(i * 0.45 + 1.5) + 0.35) for i in range(39)]]


SHAPES = [shape_heart, shape_star, shape_sun, shape_smile, shape_house, shape_flower, shape_spiral,
          shape_bolt, shape_asterisk, shape_self, shape_self, shape_cloud, shape_tree, shape_cat,
          shape_fish, shape_wave]
PENCIL_COLORS = [(60, 60, 68), (215, 55, 60), (45, 105, 215), (35, 150, 85), (230, 135, 25), (145, 65, 195),
                 (203, 124, 93)]


# ─── цветные рисунки «восковыми карандашами» ───
CRAYON = {
    "red": (222, 52, 48), "orange": (242, 132, 38), "yellow": (238, 196, 30), "green": (58, 168, 72),
    "dgreen": (34, 120, 52), "blue": (48, 106, 220), "sky": (84, 172, 236), "purple": (146, 78, 200),
    "pink": (238, 104, 168), "brown": (138, 84, 44), "black": (38, 38, 44), "gray": (124, 126, 138),
    "claude": (203, 124, 93),
}


def _earc(cx, cy, rx, ry, a0, a1, n=24):
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def _circ(cx, cy, r, n=28):
    return _earc(cx, cy, r, r, -90, 270, n)


def _rect(x1, y1, x2, y2):
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]


def _sun():
    s = [("yellow", _circ(0.5, 0.5, 0.2))]
    for k in range(10):
        a = math.radians(k * 36 + 8)
        s.append(("orange", [(0.5 + 0.28 * math.cos(a), 0.5 + 0.28 * math.sin(a)),
                             (0.5 + 0.44 * math.cos(a), 0.5 + 0.44 * math.sin(a))]))
    s += [("orange", _earc(0.5, 0.5, 0.1, 0.08, 20, 160, 10)),
          ("orange", [(0.43, 0.43), (0.43, 0.47)]), ("orange", [(0.57, 0.43), (0.57, 0.47)])]
    return 1.0, s


def _house():
    return 1.1, [("brown", _rect(0.15, 0.48, 0.95, 0.97)),
                 ("red", [(0.06, 0.52), (0.55, 0.1), (1.04, 0.52)]),
                 ("brown", [(0.48, 0.97), (0.48, 0.7), (0.64, 0.7), (0.64, 0.97)]),
                 ("blue", _rect(0.24, 0.58, 0.38, 0.72)), ("blue", [(0.31, 0.58), (0.31, 0.72)]),
                 ("blue", [(0.24, 0.65), (0.38, 0.65)]),
                 ("brown", [(0.78, 0.33), (0.78, 0.14), (0.88, 0.14), (0.88, 0.41)]),
                 ("gray", [(0.83, 0.1), (0.8, 0.05), (0.86, 0.01), (0.83, -0.04)])]


def _tree():
    crown = [(0.46 + (0.31 + 0.035 * math.sin(7 * t)) * math.cos(t), 0.36 + (0.29 + 0.035 * math.sin(7 * t)) * math.sin(t))
             for t in [i * 2 * math.pi / 56 for i in range(57)]]
    return 0.92, [("brown", [(0.39, 0.99), (0.41, 0.6)]), ("brown", [(0.53, 0.99), (0.51, 0.6)]),
                  ("brown", [(0.46, 0.66), (0.33, 0.52)]), ("green", crown),
                  ("red", _circ(0.36, 0.3, 0.03, 10)), ("red", _circ(0.58, 0.42, 0.03, 10)),
                  ("red", _circ(0.5, 0.2, 0.03, 10))]


def _flower():
    s = [("green", [(0.36, 1.0), (0.38, 0.8), (0.35, 0.6), (0.36, 0.45)]),
         ("green", _earc(0.47, 0.73, 0.11, 0.05, 160, 380, 14))]
    for k in range(6):
        a = math.radians(k * 60)
        s.append(("pink", _circ(0.36 + 0.13 * math.cos(a), 0.3 + 0.13 * math.sin(a), 0.075, 14)))
    s.append(("yellow", _circ(0.36, 0.3, 0.055, 12)))
    return 0.72, s


def _heart():
    pts = []
    for i in range(61):
        t = i * 2 * math.pi / 60
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((0.5 + x * 0.028, 0.47 + y * 0.028))
    return 1.0, [("red", pts), ("pink", _earc(0.32, 0.36, 0.08, 0.07, 190, 290, 8))]


def _star():
    pts = []
    for k in range(11):
        r = 0.46 if k % 2 == 0 else 0.19
        a = math.radians(-90 + k * 36)
        pts.append((0.5 + r * math.cos(a), 0.54 + r * math.sin(a)))
    return 1.0, [("yellow", pts), ("orange", [(0.12, 0.12), (0.2, 0.2)]), ("orange", [(0.86, 0.1), (0.8, 0.18)])]


def _smile():
    return 1.0, [("yellow", _circ(0.5, 0.5, 0.43)), ("black", [(0.38, 0.36), (0.38, 0.46)]),
                 ("black", [(0.62, 0.36), (0.62, 0.46)]), ("black", _earc(0.5, 0.55, 0.2, 0.16, 15, 165, 14)),
                 ("pink", _earc(0.26, 0.6, 0.05, 0.03, 180, 360, 6)), ("pink", _earc(0.74, 0.6, 0.05, 0.03, 180, 360, 6))]


def _cat():
    s = [("orange", _earc(0.55, 0.6, 0.38, 0.32, -90, 270, 34)),
         ("orange", [(0.25, 0.42), (0.27, 0.1), (0.45, 0.31)]), ("orange", [(0.65, 0.31), (0.83, 0.1), (0.85, 0.42)]),
         ("black", _circ(0.42, 0.55, 0.035, 8)), ("black", _circ(0.68, 0.55, 0.035, 8)),
         ("pink", [(0.52, 0.65), (0.58, 0.65), (0.55, 0.69), (0.52, 0.65)]),
         ("black", _earc(0.51, 0.71, 0.04, 0.03, 0, 180, 6)), ("black", _earc(0.59, 0.71, 0.04, 0.03, 0, 180, 6))]
    for dy in (-0.03, 0.02, 0.07):
        s.append(("gray", [(0.35, 0.67), (0.06, 0.64 + dy * 1.6)]))
        s.append(("gray", [(0.75, 0.67), (1.04, 0.64 + dy * 1.6)]))
    return 1.1, s


def _rocket():
    body = [(0.375, 0.02), (0.31, 0.11), (0.265, 0.24), (0.25, 0.4), (0.25, 0.78), (0.5, 0.78),
            (0.5, 0.4), (0.485, 0.24), (0.44, 0.11), (0.375, 0.02)]
    return 0.75, [("gray", body), ("sky", _circ(0.375, 0.38, 0.065, 14)),
                  ("red", [(0.25, 0.58), (0.1, 0.83), (0.25, 0.78)]), ("red", [(0.5, 0.58), (0.65, 0.83), (0.5, 0.78)]),
                  ("orange", [(0.29, 0.8), (0.32, 0.95), (0.375, 0.87), (0.43, 0.97), (0.46, 0.8)]),
                  ("yellow", [(0.08, 0.15), (0.14, 0.15)]), ("yellow", [(0.11, 0.12), (0.11, 0.18)]),
                  ("yellow", [(0.63, 0.3), (0.69, 0.3)]), ("yellow", [(0.66, 0.27), (0.66, 0.33)])]


def _cloud():
    top = (_earc(0.28, 0.52, 0.14, 0.14, 120, 290, 12) + _earc(0.55, 0.42, 0.2, 0.2, 200, 340, 14) +
           _earc(0.86, 0.5, 0.16, 0.16, 220, 360, 12) + _earc(1.0, 0.6, 0.08, 0.08, 270, 420, 8))
    s = [("sky", top + [(0.28, 0.66)])]
    for x in (0.35, 0.55, 0.75, 0.95):
        s.append(("blue", [(x, 0.76), (x - 0.04, 0.88)]))
    return 1.3, s


def _fish():
    return 1.4, [("blue", _earc(0.62, 0.5, 0.38, 0.22, -90, 270, 30)),
                 ("blue", [(0.25, 0.5), (0.06, 0.3), (0.06, 0.7), (0.25, 0.5)]),
                 ("black", _circ(0.86, 0.45, 0.03, 8)), ("sky", _earc(0.58, 0.5, 0.07, 0.15, 270, 450, 10)),
                 ("sky", _circ(1.15, 0.3, 0.04, 10)), ("sky", _circ(1.25, 0.14, 0.055, 10))]


def _boat():
    waves = [(x / 40 * 1.3, 0.93 + 0.025 * math.sin(x * 0.9)) for x in range(41)]
    return 1.3, [("brown", [(0.1, 0.65), (0.25, 0.85), (1.05, 0.85), (1.2, 0.65), (0.1, 0.65)]),
                 ("brown", [(0.66, 0.65), (0.66, 0.05)]), ("red", [(0.66, 0.08), (0.66, 0.58), (0.25, 0.58), (0.66, 0.08)]),
                 ("blue", [(0.66, 0.05), (0.8, 0.09), (0.66, 0.13)]), ("blue", waves)]


def _mountains():
    return 1.5, [("gray", [(0.0, 0.96), (0.4, 0.3), (0.62, 0.6), (0.9, 0.14), (1.25, 0.72), (1.5, 0.96)]),
                 ("sky", [(0.32, 0.42), (0.4, 0.3), (0.48, 0.41)]), ("sky", [(0.82, 0.27), (0.9, 0.14), (0.99, 0.29)]),
                 ("yellow", _circ(1.28, 0.22, 0.1, 18)), ("green", [(0.05, 0.96), (1.45, 0.96)])]


def _snowman():
    return 0.8, [("sky", _circ(0.4, 0.77, 0.2)), ("sky", _circ(0.4, 0.44, 0.14)), ("sky", _circ(0.4, 0.2, 0.1, 20)),
                 ("black", _circ(0.36, 0.18, 0.012, 4)), ("black", _circ(0.44, 0.18, 0.012, 4)),
                 ("orange", [(0.41, 0.21), (0.56, 0.23), (0.41, 0.245)]),
                 ("brown", [(0.27, 0.42), (0.08, 0.3)]), ("brown", [(0.53, 0.42), (0.72, 0.3)]),
                 ("black", _rect(0.33, 0.0, 0.47, 0.09)), ("black", [(0.28, 0.1), (0.52, 0.1)])]


# ─── новые детские рисунки (по картинкам хозяина): штрих — (цвет, точки[, цвет заливки или False]) ───
def _poly(*pts):
    return list(pts) + [pts[0]]


def _rainbow():
    s = []
    for i, col in enumerate(("red", "orange", "yellow", "green", "sky", "blue", "purple")):
        ro, ri = 0.74 - i * 0.075, 0.665 - i * 0.075
        band = _earc(0.8, 0.95, ro, ro, 180, 360, 30) + _earc(0.8, 0.95, ri, ri, 360, 180, 30)
        s.append((col, band + [band[0]], col))
    for cx in (0.13, 1.47):                       # облачка у концов радуги
        s.append(("sky", _earc(cx - 0.06, 0.93, 0.07, 0.06, 90, 270, 8) + _earc(cx, 0.88, 0.08, 0.07, 180, 360, 10) +
                  _earc(cx + 0.07, 0.93, 0.06, 0.05, 270, 450, 8) + [(cx - 0.06, 0.99)], False))
    return 1.6, s


def _car():
    body = _poly((0.08, 0.74), (0.07, 0.52), (0.3, 0.47), (0.44, 0.22), (1.0, 0.22), (1.14, 0.47),
                 (1.42, 0.52), (1.43, 0.74))
    return 1.5, [("blue", body),
                 ("sky", _poly((0.52, 0.29), (0.74, 0.29), (0.74, 0.46), (0.44, 0.46)), "sky"),
                 ("sky", _poly((0.8, 0.29), (0.98, 0.29), (1.08, 0.46), (0.8, 0.46)), "sky"),
                 ("black", _circ(0.38, 0.76, 0.13, 22), "yellow"), ("black", _circ(1.12, 0.76, 0.13, 22), "yellow"),
                 ("orange", _circ(0.38, 0.76, 0.04, 8), False), ("orange", _circ(1.12, 0.76, 0.04, 8), False),
                 ("yellow", _circ(1.36, 0.58, 0.04, 8), "yellow"), ("blue", [(0.77, 0.5), (0.84, 0.5)])]


def _icecream():
    L = lambda y: 0.13 + 0.22 * (y - 0.5) / 0.5      # левый край рожка
    R = lambda y: 0.57 - 0.22 * (y - 0.5) / 0.5
    s = [("pink", _circ(0.35, 0.33, 0.21, 26)), ("red", _circ(0.4, 0.1, 0.05, 10), "red"),
         ("orange", _poly((0.11, 0.5), (0.59, 0.5), (0.35, 1.0)))]
    for a, b in ((0.56, 0.78), (0.66, 0.9), (0.52, 0.64)):
        s.append(("brown", [(L(a), a), (R(b), b)]))
        s.append(("brown", [(R(a), a), (L(b), b)]))
    s.append(("purple", [(0.24, 0.28), (0.27, 0.32)]))
    s.append(("sky", [(0.44, 0.24), (0.47, 0.2)]))
    return 0.7, s


def _gift():
    return 1.0, [("sky", _rect(0.12, 0.42, 0.88, 0.98)), ("blue", _rect(0.06, 0.3, 0.94, 0.44)),
                 ("red", _rect(0.44, 0.44, 0.56, 0.98), "red"), ("red", _rect(0.44, 0.3, 0.56, 0.44), "red"),
                 ("pink", _poly((0.5, 0.3), (0.32, 0.08), (0.2, 0.2), (0.3, 0.28))),
                 ("pink", _poly((0.5, 0.3), (0.68, 0.08), (0.8, 0.2), (0.7, 0.28)))]


def _apple():
    body = []
    for i in range(49):
        t = i * 2 * math.pi / 48
        c = math.cos(t)
        body.append((0.47 + 0.42 * math.sin(t), 0.62 - 0.36 * c + 0.13 * max(c, 0.0) ** 14))
    leaf = _earc(0.64, 0.2, 0.15, 0.06, 180, 360, 10) + _earc(0.64, 0.2, 0.15, 0.06, 0, 180, 10)
    return 0.95, [("red", body), ("brown", [(0.47, 0.38), (0.5, 0.25), (0.55, 0.14)]), ("green", leaf),
                  ("pink", _earc(0.3, 0.55, 0.1, 0.15, 190, 250, 6), False)]


def _butterfly():
    s = []
    for side in (-1, 1):
        x = lambda v: 0.6 + side * v
        s.append(("purple", _earc(x(0.24), 0.36, 0.22, 0.2, -90, 270, 24)))
        s.append(("pink", _earc(x(0.18), 0.7, 0.15, 0.14, -90, 270, 20)))
        s.append(("yellow", _circ(x(0.26), 0.34, 0.05, 10), "yellow"))
        s.append(("orange", _circ(x(0.19), 0.71, 0.035, 8), False))
        s.append(("black", [(x(0.02), 0.3), (x(0.08), 0.15), (x(0.12), 0.07)]))
        s.append(("black", _circ(x(0.13), 0.06, 0.02, 6), False))
    s.append(("brown", _earc(0.6, 0.53, 0.045, 0.27, -90, 270, 20), "brown"))
    return 1.2, s


def _ball():
    s = []
    cols = ("red", "yellow", "blue", "green", "orange", "sky")
    for k, col in enumerate(cols):
        s.append((col, [(0.5, 0.5)] + _earc(0.5, 0.5, 0.45, 0.45, k * 60 - 90, k * 60 - 30, 8) + [(0.5, 0.5)], col))
    s.append(("black", _circ(0.5, 0.5, 0.46, 34), False))
    s.append(("black", _circ(0.5, 0.5, 0.07, 10), "gray"))
    return 1.0, s


def _cube():
    return 1.0, [("yellow", _rect(0.08, 0.34, 0.68, 0.94)),
                 ("orange", _poly((0.08, 0.34), (0.3, 0.1), (0.9, 0.1), (0.68, 0.34))),
                 ("red", _poly((0.68, 0.34), (0.9, 0.1), (0.9, 0.7), (0.68, 0.94))),
                 ("blue", [(0.24, 0.84), (0.38, 0.44), (0.52, 0.84)]), ("blue", [(0.29, 0.7), (0.47, 0.7)]),
                 ("green", [(0.86, 0.26), (0.75, 0.32), (0.75, 0.66), (0.86, 0.6), (0.86, 0.47), (0.75, 0.52)])]


def _cherries():
    leaf = _earc(0.68, 0.12, 0.14, 0.055, 180, 360, 10) + _earc(0.68, 0.12, 0.14, 0.055, 0, 180, 10)
    return 0.9, [("dgreen", [(0.26, 0.6), (0.34, 0.35), (0.54, 0.12)]),
                 ("dgreen", [(0.63, 0.64), (0.6, 0.38), (0.54, 0.12)]), ("green", leaf),
                 ("red", _circ(0.25, 0.76, 0.17, 24)), ("red", _circ(0.64, 0.8, 0.17, 24)),
                 ("pink", _earc(0.2, 0.71, 0.07, 0.07, 190, 260, 5), False),
                 ("pink", _earc(0.59, 0.75, 0.07, 0.07, 190, 260, 5), False)]


def _teddy():
    return 0.9, [("brown", _circ(0.25, 0.16, 0.09, 14)), ("brown", _circ(0.65, 0.16, 0.09, 14)),
                 ("brown", _earc(0.45, 0.76, 0.27, 0.23, -90, 270, 28)),
                 ("brown", _earc(0.14, 0.7, 0.08, 0.13, -90, 270, 14)), ("brown", _earc(0.76, 0.7, 0.08, 0.13, -90, 270, 14)),
                 ("brown", _circ(0.45, 0.36, 0.23, 28)),
                 ("orange", _earc(0.45, 0.45, 0.1, 0.075, -90, 270, 14), "orange"),
                 ("orange", _circ(0.45, 0.78, 0.13, 18), "orange"),
                 ("black", _circ(0.36, 0.31, 0.025, 6), "black"), ("black", _circ(0.54, 0.31, 0.025, 6), "black"),
                 ("black", _earc(0.45, 0.41, 0.035, 0.025, 0, 360, 8), "black"),
                 ("black", _earc(0.45, 0.46, 0.05, 0.03, 20, 160, 8))]


def _book():
    s = []
    for side in (-1, 1):
        x = lambda v: 0.7 + side * v
        s.append(("blue", _poly((x(0.0), 0.3), (x(0.28), 0.17), (x(0.62), 0.25), (x(0.62), 0.86),
                                (x(0.28), 0.79), (x(0.0), 0.92)), "sky"))
        for k in range(4):
            y = 0.37 + k * 0.11
            s.append(("gray", [(x(0.1), y + 0.01), (x(0.5), y - 0.02)]))
    s.append(("red", [(0.7, 0.3), (0.7, 0.92), (0.66, 1.0)]))
    return 1.4, s


def _plane():
    return 1.3, [("purple", _poly((0.06, 0.52), (1.24, 0.1), (0.46, 0.66)), "pink"),
                 ("purple", _poly((0.46, 0.66), (1.24, 0.1), (0.6, 0.92)), "purple"),
                 ("gray", [(0.02, 0.86), (0.1, 0.84)]), ("gray", [(0.17, 0.82), (0.25, 0.8)]),
                 ("gray", [(0.32, 0.79), (0.4, 0.78)])]


def _cake():
    return 1.3, [("orange", _poly((0.1, 0.44), (0.96, 0.44), (0.96, 0.96), (0.1, 0.96)), "yellow"),
                 ("pink", _poly((0.1, 0.44), (0.3, 0.26), (1.22, 0.26), (0.96, 0.44)), "pink"),
                 ("orange", _poly((0.96, 0.44), (1.22, 0.26), (1.22, 0.78), (0.96, 0.96)), "orange"),
                 ("pink", [(0.1, 0.66), (0.96, 0.66)]), ("pink", [(0.1, 0.7), (0.96, 0.7)]),
                 ("red", _circ(0.66, 0.2, 0.07, 12), "red"), ("dgreen", [(0.67, 0.13), (0.72, 0.05)])]


DIGITS = {
    "1": [[(0.1, 0.25), (0.3, 0.0), (0.3, 1.0)]],
    "2": [[(0.0, 0.25), (0.15, 0.02), (0.4, 0.02), (0.5, 0.25), (0.0, 1.0), (0.55, 1.0)]],
    "3": [[(0.0, 0.05), (0.5, 0.05), (0.2, 0.42), (0.45, 0.55), (0.48, 0.85), (0.25, 1.0), (0.0, 0.92)]],
    "4": [[(0.35, 1.0), (0.35, 0.0), (0.0, 0.65), (0.55, 0.65)]],
    "5": [[(0.5, 0.0), (0.05, 0.0), (0.02, 0.45), (0.35, 0.4), (0.5, 0.65), (0.4, 0.95), (0.0, 0.95)]],
    "6": [[(0.45, 0.02), (0.15, 0.25), (0.02, 0.65)] + _earc(0.26, 0.74, 0.24, 0.24, 180, 540, 16)],
}


def _hopscotch():
    s, n = [], 1
    for row in range(4):                              # снизу вверх: 1, 2|3, 4, 5|6
        y1, y2 = 0.98 - (row + 1) * 0.235, 0.98 - row * 0.235
        cells = [(0.15, 0.45)] if row % 2 == 0 else [(0.0, 0.3), (0.3, 0.6)]
        for x1, x2 in cells:
            s.append(("purple", _rect(x1, y1, x2, y2), False))
            for st in DIGITS[str(n)]:
                s.append(("red", [((x1 + x2) / 2 - 0.05 + px * 0.16, y1 + 0.06 + py * 0.12) for px, py in st]))
            n += 1
    return 0.6, s


def _strawberry():
    berry = [(0.4, 0.97)] + _earc(0.4, 0.5, 0.3, 0.2, 165, 375, 18) + [(0.4, 0.97)]
    s = [("red", berry),
         ("green", _poly((0.18, 0.33), (0.26, 0.2), (0.33, 0.29), (0.4, 0.14), (0.47, 0.29), (0.54, 0.2), (0.62, 0.33),
                         (0.4, 0.38)), "green"),
         ("dgreen", [(0.4, 0.16), (0.42, 0.04)])]
    for x, y in ((0.28, 0.5), (0.4, 0.47), (0.52, 0.5), (0.33, 0.63), (0.47, 0.63), (0.4, 0.77)):
        s.append(("yellow", [(x, y), (x + 0.015, y + 0.03)]))
    return 0.8, s


LETTERS = {
    "П": [[(0, 1), (0, 0), (0.45, 0), (0.45, 1)]],
    "Р": [[(0, 1), (0, 0), (0.3, 0), (0.42, 0.08), (0.45, 0.22), (0.42, 0.36), (0.3, 0.45), (0, 0.45)]],
    "И": [[(0, 0), (0, 1), (0.45, 0), (0.45, 1)]],
    "В": [[(0, 1), (0, 0), (0.28, 0), (0.4, 0.08), (0.4, 0.36), (0.28, 0.45), (0, 0.45)],
          [(0.28, 0.45), (0.43, 0.55), (0.45, 0.72), (0.43, 0.9), (0.3, 1), (0, 1)]],
    "Е": [[(0.45, 0), (0, 0), (0, 1), (0.45, 1)], [(0, 0.5), (0.35, 0.5)]],
    "Т": [[(0, 0), (0.5, 0)], [(0.25, 0), (0.25, 1)]],
    "К": [[(0, 0), (0, 1)], [(0.45, 0), (0, 0.55)], [(0.12, 0.45), (0.45, 1)]],
    "Л": [[(0, 1), (0.12, 0.6), (0.2, 0.15), (0.25, 0), (0.45, 0), (0.45, 1)]],
    "О": [_earc(0.225, 0.5, 0.225, 0.5, -90, 270, 24)],
    "Д": [[(-0.04, 1.08), (-0.04, 0.85), (0.5, 0.85), (0.5, 1.08)], [(0.06, 0.85), (0.12, 0.3), (0.17, 0)],
          [(0.17, 0), (0.42, 0), (0.42, 0.85)]],
    "!": [[(0.1, 0), (0.1, 0.7)], _circ(0.1, 0.92, 0.04, 6)],
}


def _word(word):
    def f():
        cols = ["red", "orange", "yellow", "green", "blue", "purple", "pink"]
        s, x = [], 0.06
        for i, ch in enumerate(word):
            for st in LETTERS.get(ch, []):
                s.append((cols[i % len(cols)], [(x + px * 0.8, 0.1 + py * 0.8) for px, py in st]))
            x += 0.5 if ch != "!" else 0.25
        return x + 0.02, s
    return f


# Цветные рисунки (из версии друга): имя -> функция, возвращающая (ширина/высота, [(цвет, точки в 0..1)])
DRAWINGS = {"солнышко": _sun, "домик": _house, "дерево": _tree, "цветок": _flower, "сердечко": _heart,
            "звезда": _star, "смайлик": _smile, "котик": _cat, "ракета": _rocket, "облачко": _cloud,
            "рыбка": _fish, "кораблик": _boat, "горы": _mountains, "снеговик": _snowman,
            "радуга": _rainbow, "машинка": _car, "мороженое": _icecream, "подарок": _gift, "яблоко": _apple,
            "бабочка": _butterfly, "мячик": _ball, "кубик": _cube, "вишенки": _cherries, "мишка": _teddy,
            "книжка": _book, "самолётик": _plane, "тортик": _cake, "классики": _hopscotch, "клубника": _strawberry,
            "ПРИВЕТ": _word("ПРИВЕТ!"), "КЛОД": _word("КЛОД")}


DRAWING_NAMES = tuple(DRAWINGS)


def drawing_parts(name):
    """Цветной рисунок -> (штрихи в координатах «центр 0, высота 1», цвета, заливки, ширина/высота).
    Заливка штриха: цвет, None — «сама решит» (замкнутый и крупный — заштрихует светлее контура), False — нет."""
    aspect, strokes = DRAWINGS[name]()
    out, cols, fills = [], [], []
    for st in strokes:
        col, pts = st[0], st[1]
        if len(pts) > 1:
            out.append([(x - aspect / 2, y - 0.5) for x, y in pts])
            c = CRAYON.get(col, CRAYON["black"])
            cols.append(c)
            f = st[2] if len(st) > 2 else None
            fills.append(False if f is False else CRAYON.get(f, c) if f else lighter(c, 0.3))
    return out, cols, fills, aspect


def drawing_strokes(name):
    out, cols, _, aspect = drawing_parts(name)
    return out, cols, aspect


def lighter(c, k):
    return tuple(int(v + (255 - v) * k) for v in c)


def _area(pts):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2


def closed(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    size = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
    return len(pts) >= 4 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 0.08 * size


def hatch(poly, gap, ang, inset=0.0):
    """Штриховка «как мелком» внутри многоугольника: параллельные линии под углом ang,
    соседние соединяются зигзагом, чтобы карандаш не отрывался. Возвращает список штрихов."""
    ca, sa = math.cos(ang), math.sin(ang)
    rot = [(x * ca + y * sa, -x * sa + y * ca) for x, y in poly]        # линии штриховки — горизонтальные
    ys = [p[1] for p in rot]
    out, chain, prev_n, flip = [], [], 0, False
    y = min(ys) + gap * 0.5
    while y < max(ys):
        xs = []
        for (x1, y1), (x2, y2) in zip(rot, rot[1:] + rot[:1]):
            if (y1 <= y < y2) or (y2 <= y < y1):
                xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        xs.sort()
        segs = [(a + inset, b - inset) for a, b in zip(xs[0::2], xs[1::2]) if b - a > 2 * inset + gap * 0.3]
        if len(segs) == 1 and prev_n == 1 and chain:
            a, b = segs[0]
            chain += [(b, y), (a, y)] if flip else [(a, y), (b, y)]
        else:
            if chain:
                out.append(chain)
            chain = []
            for a, b in segs:
                if len(segs) == 1:
                    chain = [(b, y), (a, y)] if flip else [(a, y), (b, y)]
                else:
                    out.append([(a, y), (b, y)])
        flip = not flip
        prev_n = len(segs)
        y += gap
    if chain:
        out.append(chain)
    return [[(x * ca - y * sa, x * sa + y * ca) for x, y in st] for st in out]


def with_fill(strokes, cols, fills, gap, min_area):
    """Добавляет к замкнутым крупным штрихам штриховку сразу после контура (как рисуют дети).
    Возвращает (штрихи, цвета, номера штрихов-штриховок)."""
    ang = math.radians(random.choice((-1, 1)) * random.uniform(28, 55))
    out, oc, fast = [], [], set()
    for st, c, f in zip(strokes, cols, fills):
        out.append(st)
        oc.append(c)
        if f is False or not closed(st) or _area(st) < min_area:
            continue
        for h in hatch(st, gap, ang + random.uniform(-0.08, 0.08), gap * 0.35):
            fast.add(len(out))
            out.append(h)
            oc.append(f)
    return out, oc, fast


def trace(strokes, step=0.03, fast=()):
    """Штрихи -> точки (x, y, карандаш_прижат, номер_штриха) с лёгкой «дрожью руки».
    Штрихи из fast (штриховка) идут реже: это прямые линии, им много точек не нужно."""
    pts, last = [], None
    wob = random.uniform(0, 6.28)
    span = max(max(abs(x), abs(y)) for s in strokes for x, y in s) or 1.0
    jit = 0.009 * span                            # дрожь пропорциональна размеру рисунка
    for si, s in enumerate(strokes):
        if last is not None:                      # карандаш в воздухе к началу следующего штриха
            n = max(2, int(math.hypot(s[0][0] - last[0], s[0][1] - last[1]) / (step * 2.7)))
            for i in range(1, n + 1):
                k = i / n
                pts.append((last[0] + (s[0][0] - last[0]) * k, last[1] + (s[0][1] - last[1]) * k, False, si))
        pts.append((s[0][0], s[0][1], True, si))
        st = step * 2.4 if si in fast else step
        for a, b in zip(s, s[1:]):
            n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / st))
            for i in range(1, n + 1):
                k = i / n
                wob += 0.35
                j = jit * math.sin(wob) + 0.5 * jit * math.sin(wob * 2.7)
                pts.append((a[0] + (b[0] - a[0]) * k + j, a[1] + (b[1] - a[1]) * k - j, True, si))
        last = s[-1]
    return pts


# ═══════════════════════════ крестики-нолики ═══════════════════════════
TTT_LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))


def ttt_winner(b):
    """("x"/"o", линия) — победа; ("draw", None) — ничья; (None, None) — игра идёт."""
    for line in TTT_LINES:
        a, c, d = line
        if b[a] and b[a] == b[c] == b[d]:
            return b[a], line
    return (None, None) if None in b else ("draw", None)


@functools.lru_cache(maxsize=None)
def _ttt_score(b, turn):
    """Минимакс: оценка позиции для ноликов (краба), +10 — выигрыш (чем быстрее, тем больше)."""
    w, _ = ttt_winner(b)
    if w == "o":
        return 10 + b.count(None)                  # быстрая победа лучше
    if w == "x":
        return -10
    if w == "draw":
        return 0
    nxt = "x" if turn == "o" else "o"
    vals = [_ttt_score(b[:i] + (turn,) + b[i + 1:], nxt) for i in range(9) if b[i] is None]
    return max(vals) if turn == "o" else min(vals)


def ttt_move(board, soft):
    """Ход краба. soft — поддаётся: ходит наугад и не забирает победу, если есть другой ход."""
    b = tuple(board)
    free = [i for i in range(9) if b[i] is None]
    if soft:
        calm = [i for i in free if ttt_winner(b[:i] + ("o",) + b[i + 1:])[0] != "o"]
        return random.choice(calm or free)
    sc = {i: _ttt_score(b[:i] + ("o",) + b[i + 1:], "x") for i in free}
    best = max(sc.values())
    return random.choice([i for i in free if sc[i] >= best - 1e-9])


class TTTPad(QWidget):
    """Невидимая «сетка» поверх нарисованного поля: ловит клики по клеткам и подсвечивает клетку под мышкой."""

    def __init__(self, on_click):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool |
                            Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.on_click, self.hover, self.active, self.busy = on_click, -1, False, set()

    def cell_at(self, pt):
        c, r = int(pt.x() * 3 / max(1, self.width())), int(pt.y() * 3 / max(1, self.height()))
        return r * 3 + c if 0 <= c < 3 and 0 <= r < 3 else -1

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(255, 255, 255, 1))      # почти прозрачно, но клики доходят
        if self.active and self.hover >= 0 and self.hover not in self.busy:
            cw, ch = self.width() / 3, self.height() / 3
            r = QRectF((self.hover % 3) * cw + 6, (self.hover // 3) * ch + 6, cw - 12, ch - 12)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 236, 170, 90))
            p.drawRoundedRect(r, 10, 10)
        p.end()

    def set_hover(self, c):
        if c != self.hover:
            self.hover = c
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.active and c >= 0 and c not in self.busy
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def mouseMoveEvent(self, e):
        self.set_hover(self.cell_at(e.position()))

    def leaveEvent(self, e):
        self.set_hover(-1)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.active:
            c = self.cell_at(e.position())
            if c >= 0 and c not in self.busy:
                self.on_click(c)


class DrawLayer(QWidget):
    """Слой с рисунками на весь рабочий стол. Лежит прямо над обоями — под всеми окнами,
    поэтому окна его закрывают сами. Иконки вырезаны из него, рисунки уходят «за» них.
    Рисунки сохраняются в doodles.json и остаются, пока их не стереть из меню."""
    MAX = 80

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool |
                            Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.path = os.path.join(DATA_DIR, "doodles.json")
        self.doodles, self.clip, self.key, self.cache = [], None, None, None
        self.vx = self.vy = 0
        self.on_show = None
        self.load()
        self.fit()

    # --- геометрия и кэш ---
    def fit(self):
        rs = [s.geometry() for s in QGuiApplication.screens()]
        l, t = min(r.left() for r in rs), min(r.top() for r in rs)
        rr, bb = max(r.left() + r.width() for r in rs), max(r.top() + r.height() for r in rs)
        self.vx, self.vy = l, t
        self.setGeometry(l, t, rr - l, bb - t)
        self.key = None
        self.clip = None
        self.rebuild()

    def rebuild(self):
        self.cache = QImage(max(1, self.width()), max(1, self.height()), QImage.Format.Format_ARGB32_Premultiplied)
        self.cache.fill(0)
        p = QPainter(self.cache)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for d in self.doodles:
            for i, s in enumerate(d["strokes"]):
                for pen, (ox, oy) in self.pens(d, i):
                    p.setPen(pen)
                    if len(s) == 1:
                        p.drawPoint(QPointF(s[0][0] - self.vx + ox, s[0][1] - self.vy + oy))
                    elif len(s) > 1:
                        p.drawPolyline(QPolygonF([QPointF(x - self.vx + ox, y - self.vy + oy) for x, y in s]))
        p.end()
        self.update()

    @staticmethod
    def color_of(d, i):
        cols = d.get("colors")
        return cols[i] if cols and i < len(cols) and cols[i] else d["color"]

    @classmethod
    def pens(cls, d, i):
        """Карандаш штриха i: основная линия, а у цветных — ещё «восковой» светлый след со сдвигом."""
        c, w = QColor(*cls.color_of(d, i)), d["w"]
        pen = QPen(c, w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        out = [(pen, (0.0, 0.0))]
        if d.get("wax"):
            c2 = QColor(c).lighter(140)
            c2.setAlphaF(0.5)
            pen2 = QPen(c2, w * 0.38)
            pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen2.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            out.append((pen2, (w * 0.22, -w * 0.18)))
        return out

    def set_covers(self, rects):
        """rects — то, что лежит над рисунками, но под слоем окон нет: иконки."""
        key = tuple(rects)
        if key == self.key:
            return
        self.key = key
        reg = QRegion(0, 0, self.width(), self.height())
        for l, t, r, b in rects:
            reg = reg.subtracted(QRegion(int(l - self.vx), int(t - self.vy), int(r - l), int(b - t)))
        old, self.clip = self.clip, reg
        if self.doodles and self.isVisible():
            if old is None:
                self.update()
            else:                                  # перерисовываем только то, где иконки сдвинулись
                diff = old.xored(reg)
                if not diff.isEmpty():
                    self.update(diff)

    # --- рисование ---
    def ensure_shown(self):
        if self.doodles and not self.isVisible():
            self.show()
            if self.on_show:
                self.on_show()

    def new_doodle(self, color, w, multi=False):
        d = dict(strokes=[[]], color=list(color), w=round(w, 2))
        if multi:                                   # цветной рисунок: свой цвет у каждого штриха
            d["colors"], d["wax"] = [list(color)], 1
        self.doodles.append(d)
        if len(self.doodles) > self.MAX:
            del self.doodles[0]
            self.rebuild()
        self.ensure_shown()
        return d

    def lift(self, d, color=None):
        if d["strokes"][-1]:
            d["strokes"].append([])
            if "colors" in d:
                d["colors"].append(list(color or d["color"]))
        elif color and "colors" in d:
            d["colors"][-1] = list(color)

    @staticmethod
    def bbox(d):
        pts = [pt for s in d["strokes"] for pt in s]
        if not pts:
            return None
        return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]

    def occupied(self, l, t, r, b, extra=None):
        """Пересекается ли прямоугольник с уже нарисованным (или зарезервированным extra)?"""
        for d in self.doodles:
            if "box" not in d:
                d["box"] = self.bbox(d)
            bx = d["box"]
            if bx and not (r < bx[0] or l > bx[2] or b < bx[1] or t > bx[3]):
                return True
        return False

    def add(self, d, x, y):
        s = d["strokes"][-1]
        pt = (round(x, 1), round(y, 1))
        bx = d.get("box")
        d["box"] = [min(bx[0], pt[0]), min(bx[1], pt[1]), max(bx[2], pt[0]), max(bx[3], pt[1])] if bx else [pt[0], pt[1], pt[0], pt[1]]
        prev = s[-1] if s else pt
        s.append(pt)
        p = QPainter(self.cache)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        a, b = QPointF(prev[0] - self.vx, prev[1] - self.vy), QPointF(pt[0] - self.vx, pt[1] - self.vy)
        for pen, (ox, oy) in self.pens(d, len(d["strokes"]) - 1):
            p.setPen(pen)
            if prev == pt:
                p.drawPoint(a + QPointF(ox, oy))
            else:
                p.drawLine(a + QPointF(ox, oy), b + QPointF(ox, oy))
        p.end()
        m = d["w"] + 3
        self.update(QRectF(a, b).normalized().adjusted(-m, -m, m, m).toAlignedRect())

    def finish(self, d):
        if d in self.doodles and not any(len(s) for s in d["strokes"]):
            self.doodles.remove(d)
        if "colors" in d:
            keep = [i for i, s in enumerate(d["strokes"]) if s]
            d["colors"] = [self.color_of(d, i) for i in keep]
        d["strokes"] = [s for s in d["strokes"] if s]
        self.save()

    def remove(self, ds):
        """Стереть несколько рисунков (поле крестиков-ноликов после игры)."""
        n = len(self.doodles)
        self.doodles = [d for d in self.doodles if all(d is not x for x in ds)]
        if len(self.doodles) != n:
            self.rebuild()
            self.save()
        if not self.doodles:
            self.hide()

    def clear(self):
        self.doodles = []
        self.rebuild()
        self.save()
        self.hide()

    # --- хранение ---
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.doodles = [d for d in data if isinstance(d, dict) and d.get("strokes") and not d.get("tmp")][-self.MAX:]
        except Exception:
            self.doodles = []

    def save(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump([{k: v for k, v in d.items() if k != "box"} for d in self.doodles], f,
                      ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, self.path)
        except Exception:
            log_error("Не сохранились рисунки", traceback.format_exc())

    def paintEvent(self, ev):
        if self.cache is None:
            return
        p = QPainter(self)
        if self.clip is not None:
            p.setClipRegion(self.clip)
        p.setOpacity(0.88)                                  # карандаш, а не маркер
        r = ev.rect()
        p.drawImage(r, self.cache, r)
        p.end()


# ══════════════════ события: Claude Code, уведомления, система (из версии друга) ══════════════════
HOOK_PORT = 47321                       # локальный порт для хуков Claude Code и команды /say
HOOK_CMD = "curl -s -m 2 -X POST --data-binary @- http://127.0.0.1:%d/hook || true" % HOOK_PORT


def hooks_json():
    ent = [{"hooks": [{"type": "command", "command": HOOK_CMD}]}]
    return json.dumps({"hooks": {k: ent for k in ("UserPromptSubmit", "Notification", "Stop")}}, indent=2)


def cc_message(m):
    m = (m or "").strip()
    r = re.match(r"Claude needs your permission to use (.+)", m)
    if r:
        return "Claude просит разрешение: " + r.group(1)
    if "waiting for your input" in m.lower():
        return "Claude ждёт твоего ответа!"
    return ("Claude: " + m)[:140] if m else "Claude зовёт тебя!"


class HookServer:
    """Крошечный HTTP-сервер только на 127.0.0.1: хуки Claude Code шлют сюда события,
    а свои скрипты могут вызвать GET /say?text=... Запросы из браузера (с Origin/Referer) отклоняются,
    чтобы чужая веб-страница не могла говорить голосом краба."""

    def __init__(self, port=HOOK_PORT):
        self.q = queue.Queue()
        self.srv = None
        q = self.q

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _from_browser(self):
                return any(self.headers.get(h) for h in ("Origin", "Referer", "Sec-Fetch-Mode", "Sec-Fetch-Site"))

            def _reply(self, code=204):
                self.send_response(code)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):
                if self._from_browser():
                    return self._reply(403)
                u = urlparse(self.path)
                qs = parse_qs(u.query)
                g = lambda k: (qs.get(k) or [""])[0]
                if u.path == "/say":
                    q.put(("say", g("text")[:300], g("mood")))
                elif u.path == "/event":
                    q.put(("event", g("type"), g("text")[:300]))
                self._reply()

            def do_POST(self):
                if self._from_browser():
                    return self._reply(403)
                n = min(int(self.headers.get("Content-Length") or 0), 1 << 20)
                raw = self.rfile.read(n) if n else b""
                try:
                    d = json.loads(raw.decode("utf-8", "ignore") or "{}")
                except ValueError:
                    d = {}
                if not isinstance(d, dict):
                    d = {}
                if self.path.startswith("/hook"):
                    q.put(("hook", str(d.get("hook_event_name", "")), {"message": str(d.get("message", ""))[:300]}))
                elif self.path.startswith("/say"):
                    q.put(("say", str(d.get("text", ""))[:300], str(d.get("mood", ""))))
                self._reply()

        try:
            self.srv = ThreadingHTTPServer(("127.0.0.1", port), H)
            self.srv.daemon_threads = True
            threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        except OSError:
            self.srv = None

    def shutdown(self):
        if self.srv:
            try:
                self.srv.shutdown()
                self.srv.server_close()
            except Exception:
                pass


APP_NAMES = (("klodik", None), ("claudepet", None), ("python", None), ("claude", "Claude"), ("anthropic", "Claude"),
             ("telegram", "Telegram"), ("whatsapp", "WhatsApp"), ("discord", "Discord"), ("slack", "Slack"),
             ("teams", "Teams"), ("outlook", "Outlook"), ("thunderbird", "Почта"), ("windowscommunicationsapps", "Почта"),
             ("chrome", "Chrome"), ("msedge", "Edge"), ("firefox", "Firefox"), ("yandex", "Яндекс"), ("vk", "VK"),
             ("steam", "Steam"), ("spotify", "Spotify"), ("securityhealth", "Защитник"), ("defender", "Защитник"),
             ("windows.systemtoast", None))
BROWSER_APPS = {"Chrome", "Edge", "Firefox", "Яндекс"}


def app_name(pid):
    s = (pid or "").lower()
    for key, name in APP_NAMES:
        if key in s:
            return name
    toks = [t for t in re.split(r"[\\/!.:_\-\s{}]+", pid or "") if t and not re.fullmatch(
        r"[0-9a-fA-F]{6,}|exe|app|apps|desktop|com|microsoft|windows|store|squirrel|program|files", t, re.I)]
    return toks[-1] if toks else "Уведомление"


class NotifWatcher:
    """Новые всплывающие уведомления Windows — из базы центра уведомлений (wpndatabase.db, только чтение).
    Так краб узнаёт, что ответил Claude. Текст чужих уведомлений он не показывает — только название программы."""

    def __init__(self):
        self.q = queue.Queue()
        self.path = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Notifications",
                                 "wpndatabase.db")
        self.ok = IS_WIN and os.path.isfile(self.path)
        self.last, self.busy, self.fail, self.sig = None, False, 0, None

    def poll_async(self):
        if self.ok and not self.busy:
            self.busy = True
            threading.Thread(target=self._run, daemon=True).start()

    def _rows(self, con):
        if self.last is None:
            self.last = con.execute("SELECT MAX(Id) FROM Notification").fetchone()[0] or 0
            return []
        return con.execute(
            "SELECT n.Id, n.Payload, h.PrimaryId FROM Notification n LEFT JOIN NotificationHandler h "
            "ON h.RecordId = n.HandlerId WHERE n.Id > ? AND n.Type = 'toast' ORDER BY n.Id LIMIT 20",
            (self.last,)).fetchall()

    def _run(self):
        import sqlite3, pathlib, html, tempfile
        try:
            try:
                con = sqlite3.connect(pathlib.Path(self.path).as_uri() + "?mode=ro", uri=True, timeout=2)
                try:
                    rows = self._rows(con)
                finally:
                    con.close()
            except sqlite3.OperationalError:          # база занята — читаем копию, если она изменилась
                tmp = os.path.join(tempfile.gettempdir(), "claudepet_wpn.db")
                sig = tuple((os.path.getsize(self.path + e), os.path.getmtime(self.path + e))
                            for e in ("", "-wal") if os.path.isfile(self.path + e))
                if sig == self.sig and self.last is not None:
                    return
                self.sig = sig
                for ext in ("", "-wal"):
                    if os.path.isfile(self.path + ext):
                        shutil.copyfile(self.path + ext, tmp + ext)
                con = sqlite3.connect(tmp, timeout=2)
                try:
                    rows = self._rows(con)
                finally:
                    con.close()
            for nid, payload, pid in rows:
                self.last = max(self.last, nid)
                s = payload.decode("utf-8", "ignore") if isinstance(payload, (bytes, bytearray)) else str(payload or "")
                texts = [html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
                         for t in re.findall(r"<text[^>]*>(.*?)</text>", s, re.S)]
                texts = [t for t in texts if t]
                name = app_name(pid)
                if name is None or not texts:
                    continue
                claude = name == "Claude" or (name in BROWSER_APPS and any("claude" in t.lower() for t in texts))
                self.q.put((name, texts[:3], claude))
            self.fail = 0
        except Exception:
            self.fail += 1
            if self.fail > 8:
                self.ok = False                       # другая схема базы или нет доступа — тихо выключаемся
        finally:
            self.busy = False


class SysMon:
    """Опрашивает систему (раз в ~2 с) и отдаёт события для реакций краба."""

    def __init__(self):
        self.cpu, self.ram = 0.0, 0
        self._cpu_prev = None
        self.hot_since = None
        self.ac = None
        self.drives = None
        self.net, self._net_now, self._net_busy, self._net_t = None, None, False, 0.0
        self.work_since, self.away = time.time(), 0.0
        self.cool = {}
        self.t_disk = 0.0
        self.hung = 0

    def _once(self, key, cd):
        now = time.time()
        if now < self.cool.get(key, 0):
            return False
        self.cool[key] = now + cd
        return True

    def _probe(self):
        import socket
        ok = False
        for host in ("1.1.1.1", "8.8.8.8", "77.88.8.8"):
            try:
                socket.create_connection((host, 53), 2.5).close()
                ok = True
                break
            except OSError:
                pass
        self._net_now = ok
        self._net_busy = False

    def poll(self):
        ev = []
        if not IS_WIN:
            return ev
        now = time.time()
        try:                                                   # процессор
            i, k, u = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
            if kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u)):
                cur = (i.value, k.value + u.value)
                if self._cpu_prev and cur[1] > self._cpu_prev[1]:
                    load = clamp(1 - (cur[0] - self._cpu_prev[0]) / (cur[1] - self._cpu_prev[1]), 0.0, 1.0)
                    self.cpu = self.cpu * 0.6 + load * 0.4
                self._cpu_prev = cur
            if self.cpu > 0.88:
                self.hot_since = self.hot_since or now
                if now - self.hot_since > 12 and self._once("cpu", 900):
                    ev.append(("cpu_hot", int(self.cpu * 100)))
            else:
                self.hot_since = None
        except Exception:
            pass
        try:                                                   # память
            ms = MEMORYSTATUSEX()
            ms.dwLength = ctypes.sizeof(ms)
            if kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                self.ram = ms.dwMemoryLoad
                if self.ram >= 92 and self._once("ram", 1200):
                    ev.append(("ram_full", self.ram))
        except Exception:
            pass
        try:                                                   # питание
            ps = SYSTEM_POWER_STATUS()
            if kernel32.GetSystemPowerStatus(ctypes.byref(ps)) and ps.flag not in (128, 255) and ps.ac in (0, 1):
                if self.ac is not None and ps.ac != self.ac:
                    ev.append(("ac_on",) if ps.ac else ("ac_off", ps.pct))
                self.ac = ps.ac
                if ps.ac == 0 and ps.pct <= 15 and self._once("batt", 900):
                    ev.append(("batt_low", ps.pct))
        except Exception:
            pass
        try:                                                   # флешки
            mask = kernel32.GetLogicalDrives()
            rem = {chr(65 + n) + ":" for n in range(26) if mask >> n & 1 and n > 1 and
                   kernel32.GetDriveTypeW(chr(65 + n) + ":\\") == 2}
            if self.drives is not None:
                ev += [("usb_in", d) for d in sorted(rem - self.drives)]
                ev += [("usb_out", d) for d in sorted(self.drives - rem)]
            self.drives = rem
        except Exception:
            pass
        if now - self._net_t > 30 and not self._net_busy:     # интернет
            self._net_t, self._net_busy = now, True
            threading.Thread(target=self._probe, daemon=True).start()
        if self._net_now is not None:
            if self.net is not None and self._net_now != self.net:
                ev.append(("net_up",) if self._net_now else ("net_down",))
            self.net = self._net_now
        if now - self.t_disk > 600:                           # место на диске
            self.t_disk = now
            try:
                drv = os.environ.get("SystemDrive", "C:")
                fa, tot, fr = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
                if kernel32.GetDiskFreeSpaceExW(drv + "\\", ctypes.byref(fa), ctypes.byref(tot), ctypes.byref(fr)):
                    gb = fa.value / 2 ** 30
                    if (gb < 8 or fa.value < 0.05 * tot.value) and self._once("disk", 12 * 3600):
                        ev.append(("disk_low", drv, gb))
            except Exception:
                pass
        try:                                                   # зависшее окно
            fg = user32.GetForegroundWindow()
            self.hung = self.hung + 1 if fg and user32.IsHungAppWindow(fg) else 0
            if self.hung >= 2 and self._once("hung", 300):
                ev.append(("hung", (w_text(fg) or "окно")[:40]))
        except Exception:
            pass
        idle = idle_seconds()                                  # отдых и возвращение
        if idle > 300:
            self.work_since = now
            self.away = max(self.away, idle)
        elif idle < 5:
            if self.away > 600 and self._once("back", 600):
                ev.append(("back", int(self.away / 60)))
            self.away = 0.0
        if now - self.work_since > 90 * 60 and self._once("work", 90 * 60):
            ev.append(("long_work", int((now - self.work_since) / 60)))
        return ev


# ═══════════════════════════════ Маскот ═══════════════════════════════
REACH_X, REACH_UP, REACH_DOWN = 70, 55, 160   # дальность прыжка в «пикселях спрайта»
KIND_W = {"floor": 1, "window": 1.5, "icon": 2, "ledge": 3, "browser_top": 3, "browser_in": 3}
LEG_X = (3, 5, 10, 12)

# длительности анимаций «на месте»; какие и когда играть — решает распорядок (Pet.think)
ANIMS = {"wave": 1.8, "dance": 3.6, "stretch": 2.6, "scratch": 2.0, "lookaround": 3.2, "tap": 2.6,
         "sneeze": 1.7, "flex": 2.2, "whistle": 3.2, "shiver": 1.4, "bow": 1.6, "dizzy": 2.4,
         "pant": 2.4, "flinch": 0.7, "admire": 2.2, "shrug": 1.4,
         # из версии друга
         "laptop": 10.0, "read": 9.0, "celebrate": 1.8, "yawn": 2.4, "hiccup": 2.6, "hot": 4.0,
         "heavy": 2.8, "crouch": 0.8}
ANIM_TITLES = {"wave": "Помахать", "dance": "Танцевать", "stretch": "Потянуться и зевнуть",
               "scratch": "Почесаться", "lookaround": "Осмотреться", "tap": "Нетерпеливо топать",
               "sneeze": "Чихнуть", "flex": "Показать мускулы", "whistle": "Насвистывать",
               "shiver": "Дрожать", "bow": "Поклониться", "dizzy": "Закружилась голова",
               "pant": "Отдышаться", "shrug": "Пожать плечами", "laptop": "Покодить на ноутбуке",
               "read": "Почитать книжку", "celebrate": "Отпраздновать", "yawn": "Зевнуть", "hiccup": "Икать"}
MENU_ANIMS = ("wave", "dance", "laptop", "read", "celebrate", "stretch", "yawn", "scratch", "lookaround", "tap",
              "sneeze", "hiccup", "flex", "whistle", "bow", "shrug")
SITTING = ("laptop", "read")

# реплики «от себя» (идея и тексты — из версии друга); можно выключить: Параметры → «Болтать»
PHRASES = {
    "idle": ["Хм…", "Чем займёмся?", "Тут уютно.", "Пойду прогуляюсь.", "Кто раскидал иконки? А, это я.",
             "Классный у тебя рабочий стол.", "Может, нарисовать что-нибудь?", "Тсс… я думаю.",
             "Компилирую мысли…", "Эх, сейчас бы пару токенов.", "Не забывай пить воду!", "Я тут, если что."],
    "throw": ["Уиии!", "Аааа!", "Лечу-у-у!", "Я птица!"],
    "land_hard": ["Ой.", "Ай-ай…", "Мягкая посадка. Почти."],
    "wake": ["Я не сплю! Почти…", "А? Что? Я тут.", "Доброе утро!"],
    "night": ["Уже поздно… пора спать.", "Ты тоже ложись, а?", "Глаза слипаются…"],
    "back": ["С возвращением!", "О, ты тут!", "Я скучал."],
    "draw_start": ["Сейчас нарисую…", "Вдохновение пришло!", "Минуточку, творю."],
    "draw_done": ["Шедевр!", "Повешу в Лувр.", "Как тебе?", "Готово!"],
    "house_start": ["Построю-ка я домик!", "Нужен домик. Из иконок, конечно."],
    "house_done": ["Мой домик!", "Уютненько.", "Ипотека закрыта!"],
    "restore_start": ["Сейчас всё верну!", "Ладно-ладно, убираю…"],
    "restore_done": ["Всё на местах!", "Чистота и порядок."],
    "dizzy": ["Голова кружится…", "Где я?", "Всё плывёт…"],
    "laptop": ["Компилируется…", "Ещё один баг…", "git push --force… шучу.", "Пишу код."],
    "pounce": ["Поймал!", "Ам!", "Попался!"],
    "cc_done": ["Claude Code закончил!", "Готово — можно смотреть!", "Задача выполнена!", "Claude дописал, проверяй!"],
}

# домики: клетки (колонка, ряд), ряд 0 — верхний
HOUSES = [
    [(2, 0), (1, 1), (3, 1), (0, 2), (1, 2), (2, 2), (3, 2), (4, 2), (0, 3), (4, 3), (0, 4), (1, 4), (3, 4), (4, 4)],
    [(1, 0), (0, 1), (1, 1), (2, 1), (0, 2), (2, 2), (0, 3), (2, 3)],
    [(1, 0), (0.5, 1), (1.5, 1), (0, 2), (1, 2), (2, 2)],
    [(0, 0), (0, 1), (0, 2)],
]

PATTERNS = {   # пиксельные значки-эффекты
    "note": (("..XX.", "..X.X", "..X..", "XXX..", "XXX.."), (60, 60, 70)),
    "excl": (("X", "X", "X", "X", ".", "X"), (230, 50, 50)),
    "spark": (("..X..", ".XXX.", "XXXXX", ".XXX.", "..X.."), (255, 210, 60)),
    "star": (("..X..", "..X..", "XXXXX", ".XXX.", ".X.X."), (255, 220, 70)),
    "sweat": (("..X..", ".XXX.", ".XXX.", "..X.."), (110, 190, 255)),
    "dot": (("X",), (255, 255, 255)),
}


class Pet(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self.desk = Desktop()
        self.layer = DrawLayer()
        self.layer.on_show = self.fix_z
        self.ai, self.talking, self.ai_error = None, 0.0, AI_ERROR
        self.push_enabled = cfg.value("push", True, type=bool)
        self.draw_enabled = cfg.value("draw", True, type=bool)
        self.chatter = cfg.value("chatter", True, type=bool)
        self.sys_enabled = cfg.value("sysreact", True, type=bool)
        self.notif_enabled = cfg.value("notif", True, type=bool)
        self.sysmon, self.notif, self.hooks = SysMon(), NotifWatcher(), HookServer()
        self.cc_busy, self.t_shot, self.t_notif = 0.0, 0.0, {}
        self.size_idx = cfg.value("size", 1, type=int)
        self.apply_size()

        # состояние
        self.platforms, self.pmap, self.icon_plats, self.browser_rects = [], {}, [], []
        self.ico_covers, self.ico_gen, self.ico_new, self.ico_busy = [], 0, None, False
        self.state, self.t, self.idle_dur = "idle", 0.0, 1.0
        self.x = self.y = 0.0
        self.vx = self.vy = 0.0
        self.plat = None
        self.after = None
        self.face, self.phase, self.anim = 1, 0.0, 0.0
        self.land_t = self.happy_t = 0.0
        self.hearts, self.fx, self.fx_acc = [], [], 0.0
        self.samples = []
        self.dragging = False
        self.press = None
        now = time.time()
        self.last_push, self.last_build, self.last_draw = now - 20, now - 400, now - 30
        self.t_startle = self.t_greet = self.t_click = 0.0
        self.t_modal = None
        self.dog = Watchdog()
        self.dog.start()
        # распорядок: план из нескольких связанных действий + бодрость
        self.plan, self.scene, self.scene_t = [], "", {}
        self.energy = 0.85
        self.restore_q = []
        self.free = None                       # свободные от окон и иконок куски обоев (QRegion)
        self.dt = 0.016
        self.hidden_fs = False
        self.j, self.ju, self.pu, self.tx, self.speed, self.dur = {}, 0.0, {}, 0, 0, 0
        self.moon = False
        self.an, self.sneezed = "", False
        self.dizzy = False
        self.build = None
        self.art = None
        self.dw = None
        self.ttt, self.pad = None, None                  # партия в крестики-нолики и её «сетка» для кликов
        self.ttt_offer = cfg.value("ttt", True, type=bool)
        self.next_ttt = time.time() + random.uniform(35, 60) * 60
        self.pencil, self.pencil_col = None, None
        self.mark, self.mark_t, self.aflag = "", 0.0, False
        self.t_chatter, self.night_said = now, ""
        self.cur_still, self.last_pounce, self.shake, self.last_svx = 0.0, now, [], 0.0
        self.look_ovr = None
        self.lk = [0.0, 0.0]
        self.cur_prev, self.cur_d, self.dwell = (0, 0), 1e9, 0.0
        self.scr_key = None
        # поза
        self.L, self.cuts, self.legdx, self.al, self.ar = 0.0, [0] * 4, [0] * 4, (0, 0), (0, 0)
        self.hide_arm, self.bdx, self.eye, self.mouth = 0, 0.0, "open", 0
        self.sx, self.sy, self.rot, self.prop = 1.0, 1.0, 0.0, None
        self.sm = dict(L=0.0, bdx=0.0, sx=1.0, sy=1.0, rot=0.0, a0=0.0, a1=0.0, b0=0.0, b1=0.0)

        self.build_menu()
        self.build_tray()
        self.show()
        self.own = int(self.winId())
        QApplication.clipboard().dataChanged.connect(self.on_clipboard)
        if AIBrain:
            try:
                self.ai = AIBrain(self, cfg)
            except Exception:
                log_error("ИИ-модуль упал при запуске", traceback.format_exc())
                self.ai_error = traceback.format_exc().strip().splitlines()[-1]
        if not self.ai:
            QTimer.singleShot(2500, lambda: self.notify(
                "ИИ-модуль не загрузился: %s. Подробности: «Папка с журналом» в меню." % self.ai_error[:120]))
        self.layer.ensure_shown()

        self.refresh_platforms(True)
        scr = self.screen_rects()
        pl, pt, pr, pb = scr[0]
        self.x, self.y = (pl + pr) / 2 + random.uniform(-200, 200), pt   # эффектно падает сверху
        self.start_fall()

        self.last = time.perf_counter()
        self.t_win = self.t_ico = self.t_sys = self.last
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)

    # ───────────── настройки ─────────────
    def apply_size(self):
        ph = QGuiApplication.primaryScreen().geometry().height()
        self.U = max(3, round(ph / 180 * (0.75, 1.0, 1.5)[self.size_idx]))
        self.setFixedSize(40 * self.U, 34 * self.U)

    def set_size(self, i):
        self.size_idx = i
        self.cfg.setValue("size", i)
        self.apply_size()
        self.refresh_platforms(True)

    def screen_rects(self):
        out = []
        for s in QGuiApplication.screens():
            g = s.availableGeometry()
            out.append((g.left(), g.top(), g.left() + g.width(), g.top() + g.height()))
        return out

    def ignore(self):
        s = {self.own}
        try:
            s.add(int(self.layer.winId()))
            if self.pad:
                s.add(int(self.pad.winId()))
        except Exception:
            pass
        return s

    # ───────────── меню и трей ─────────────
    def build_menu(self):
        m = QMenu()
        self.menu = m

        def act(menu, text, fn, checkable=False):
            a = QAction(text, menu)
            a.setCheckable(checkable)
            a.triggered.connect((lambda c=False: fn(c)) if checkable else (lambda c=False: fn()))
            menu.addAction(a)
            return a

        self.a_sleep = act(m, "Спать", self.cmd_sleep)
        act(m, "Ко мне", self.cmd_come)
        act(m, "В браузер", self.cmd_browser)
        m.addSeparator()
        act(m, "Поговорить с Клодиком  (клик / Ctrl+Alt+Пробел)", self.cmd_chat)
        act(m, "Что у меня на экране?", self.cmd_look)
        self.m_model = m.addMenu("Модель")
        grp = QActionGroup(self.m_model)
        self.a_main = act(self.m_model, "Основная", lambda c: self.set_slot("main"), True)
        self.a_light = act(self.m_model, "Лёгкая", lambda c: self.set_slot("light"), True)
        grp.addAction(self.a_main)
        grp.addAction(self.a_light)
        self.a_vision = act(m, "Следить за экраном (ИИ)", self.set_vision, True)
        act(m, "Настройки ИИ…", self.cmd_ai_settings)
        self.a_power = act(m, "Выключить ИИ (выгрузить модели из памяти)", self.cmd_power)
        m.addSeparator()
        dm = m.addMenu("Нарисовать")
        act(dm, "Что-нибудь", self.cmd_draw)
        dm.addSeparator()
        for name in DRAWING_NAMES:
            act(dm, name.capitalize() if not name.isupper() else "Надпись «%s»" % name,
                lambda n=name: self.cmd_draw(n))
        act(m, "Сыграть в крестики-нолики", self.cmd_ttt)
        act(m, "Построить домик из иконок", self.cmd_build)
        act(m, "Толкнуть иконку", self.cmd_push)
        act(m, "Вернуть иконки на место", self.cmd_restore)
        sub = m.addMenu("Трюки")
        for name in MENU_ANIMS:
            act(sub, ANIM_TITLES[name], lambda n=name: self.cmd_anim(n))
        act(sub, "Сальто назад", lambda: self.cmd_flip(1))
        act(sub, "Сальто вперёд", lambda: self.cmd_flip(-1))
        act(sub, "Прыжки «звёздочкой»", self.cmd_jacks)
        act(sub, "Лунная походка", self.cmd_moon)
        m.addSeparator()
        opt = m.addMenu("Параметры")
        self.a_push = act(opt, "Разрешить двигать иконки", self.set_push, True)
        self.a_draw = act(opt, "Разрешить рисовать", self.set_draw, True)
        self.a_ttt = act(opt, "Иногда предлагать крестики-нолики", self.set_ttt_offer, True)
        self.a_shy = act(opt, "Пугаться резкой мышки", self.set_shy, True)
        self.a_chatter = act(opt, "Болтать сам по себе", self.set_chatter, True)
        cs = opt.addMenu("Claude и система")
        self.a_notif = act(cs, "Реагировать на уведомления Windows (ответ Claude и др.)", self.set_notif, True)
        self.a_sys = act(cs, "Реагировать на систему: процессор, память, флешки, интернет", self.set_sys, True)
        cs.addSeparator()
        act(cs, "Скопировать хуки для Claude Code", self.cmd_copy_hooks)
        self.a_hookinfo = act(cs, "", lambda: None)
        self.a_hookinfo.setEnabled(False)
        sz = opt.addMenu("Размер")
        for i, n in enumerate(("Маленький", "Средний", "Большой")):
            act(sz, n, lambda i=i: self.set_size(i))
        self.a_auto = act(opt, "Автозапуск с Windows", self.set_auto, True)
        opt.addSeparator()
        act(opt, "Вернуть иконки мгновенно", self.restore_icons)
        act(opt, "Папка с журналом и данными", self.open_data_dir)
        act(m, "Стереть рисунки", self.layer.clear)
        m.addSeparator()
        act(m, "Выход", QApplication.quit)
        m.aboutToShow.connect(self.menu_show)

    def menu_show(self):
        self.menu_pos = QCursor.pos()
        self.a_push.setChecked(self.push_enabled)
        self.a_draw.setChecked(self.draw_enabled)
        self.a_ttt.setChecked(self.ttt_offer)
        self.a_shy.setChecked(self.cfg.value("shy", True, type=bool))
        self.a_auto.setChecked(autostart_enabled())
        self.a_vision.setChecked(bool(self.ai and self.ai.vision_on()))
        self.a_chatter.setChecked(self.chatter)
        self.a_notif.setChecked(self.notif_enabled)
        self.a_notif.setEnabled(self.notif.ok)
        self.a_sys.setChecked(self.sys_enabled)
        self.a_hookinfo.setText(("Жду Claude Code на 127.0.0.1:%d" % HOOK_PORT) if self.hooks.srv else
                                "Порт %d занят — хуки не работают" % HOOK_PORT)
        on = bool(self.ai and self.ai.ai_on())
        self.a_power.setText("Выключить ИИ (выгрузить модели из памяти)" if on else "Включить ИИ")
        self.a_power.setEnabled(bool(self.ai))
        self.a_sleep.setText("Разбудить" if self.state == "sleep" else "Спать")
        self.m_model.setEnabled(bool(self.ai))
        if self.ai:
            names = self.ai.slot_names()
            self.a_main.setText("Основная: " + (names["main"] or "не выбрана"))
            self.a_light.setText("Лёгкая: " + (names["light"] or "не выбрана"))
            (self.a_main if self.ai.slot() == "main" else self.a_light).setChecked(True)

    def build_tray(self):
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        for r in ((4, 2, 24, 16), (0, 10, 4, 4), (28, 10, 4, 4), (6, 18, 2, 5), (10, 18, 2, 5), (20, 18, 2, 5), (24, 18, 2, 5)):
            p.fillRect(*r, BODY)
        p.fillRect(9, 6, 2, 4, DARK)
        p.fillRect(21, 6, 2, 4, DARK)
        p.end()
        self.tray = QSystemTrayIcon(QIcon(pm))
        self.tray.setToolTip("Klodik")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.on_tray)
        self.tray.show()

    def on_tray(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.cmd_chat()

    # ───────────── ИИ ─────────────
    def cmd_chat(self):
        if self.ai:
            self.ai.open_chat()
        else:
            QMessageBox.warning(None, "Klodik", "ИИ-модуль не загрузился:\n%s\n\nПолный текст ошибки — в файле\n%s\n\n"
                                "Проверьте, что при сборке рядом с klodik.py лежал pet_ai.py (именно с таким "
                                "именем), и пересоберите build.bat." % (self.ai_error, LOG_PATH))

    def cmd_look(self):
        if self.ai:
            self.ai.look_now()
        else:
            self.cmd_chat()

    def cmd_power(self):
        if self.ai:
            self.ai.toggle_power()

    def cmd_ai_settings(self):
        if self.ai:
            self.ai.open_settings()
        else:
            self.cmd_chat()

    def set_vision(self, on):
        if self.ai:
            self.ai.set_vision(on)

    def set_slot(self, slot):
        if self.ai:
            self.ai.set_slot(slot)

    def speak(self, text, anim=None):
        """Реплика в облачке + шевелит ртом + (по настроению) анимация."""
        self.talking = clamp(1.5 + len(text) * 0.05, 2.0, 14.0)
        if self.ai:
            self.ai.say(text)
        if anim in ANIMS and self.can_cmd() and self.state != "sleep":
            self.interrupt()
            self.start_anim(anim, ANIMS[anim])

    # ───────────── реплики, реакции, события ─────────────
    def chat_busy_ui(self):
        return bool(self.ai and self.ai.chat_open())

    def say_text(self, text, secs=None):
        if not text or self.hidden_fs or not self.ai:
            return
        self.talking = clamp(1.5 + len(text) * 0.05, 2.0, 14.0)
        self.ai.say(text, secs)

    def say_phrase(self, kind, prob=1.0, force=False):
        """Случайная фраза «от себя». Пока открыт чат — молчит, чтобы не мешать разговору."""
        if (self.chatter or force) and random.random() < prob and not self.chat_busy_ui():
            self.say_text(random.choice(PHRASES[kind]))

    def say_phrase_text(self, text):
        if self.chatter and not self.chat_busy_ui():
            self.say_text(text)

    def emote(self, mark, dur=1.2):
        self.mark, self.mark_t = mark, dur

    def free_for_reaction(self):
        return (self.can_cmd() and not self.build and not self.restore_q and self.state != "draw"
                and not self.dragging and self.state != "sleep")

    def react(self, anim=None, dur=None, text=None, mark=None, force_text=False):
        if text and (self.chatter or force_text):
            self.say_text(text)
        if mark:
            self.emote(mark, 1.4)
        if anim and self.free_for_reaction():
            self.after, self.plan = None, []
            if anim == "happy":
                self.start_happy()
            elif anim == "hops":
                self.act_hops(3)
            else:
                self.start_anim(anim, dur or ANIMS.get(anim, 2.0))

    def poll_events(self):
        batch = []
        for _ in range(20):
            try:
                batch.append(self.notif.q.get_nowait())
            except queue.Empty:
                break
        if batch and not self.hidden_fs:            # пачкой пришло несколько — важнее всего Claude
            self.on_notif(next((n for n in batch if n[2]), batch[-1]))
        for _ in range(10):
            try:
                ev = self.hooks.q.get_nowait()
            except queue.Empty:
                break
            try:
                self.on_hook(ev)
            except Exception:
                log_error("Ошибка в реакции на хук", traceback.format_exc())
        if self.cc_busy and time.time() - self.cc_busy > 1200:
            self.cc_busy = 0.0                      # Stop так и не пришёл

    def on_hook(self, ev):
        """События Claude Code (хуки) и команда /say."""
        kind, a, b = ev
        if kind == "say":
            return self.react("happy" if b in ("happy", "love") else None, text=a, force_text=True)
        name = a
        if kind == "event":
            name = {"busy": "UserPromptSubmit", "start": "UserPromptSubmit", "stop": "Stop", "done": "Stop",
                    "wait": "Notification", "notify": "Notification"}.get(a.lower(), a)
            b = {"message": b} if b else {}
        d = b if isinstance(b, dict) else {}
        if name == "UserPromptSubmit":
            self.cc_busy = time.time()
            if self.free_for_reaction() and not (self.state == "anim" and self.an == "laptop"):
                self.after, self.plan = None, []
                self.start_anim("laptop", random.uniform(10, 18))
        elif name == "Stop":
            self.cc_busy = 0.0
            self.react("celebrate", 1.8, random.choice(PHRASES["cc_done"]), force_text=True)
        elif name == "Notification":
            self.react("wave", 2.4, cc_message(d.get("message", "")), "!", force_text=True)

    def on_notif(self, ev):
        """Всплывающее уведомление Windows. Про Claude — радуется; про остальное — только название программы."""
        app, texts, is_claude = ev
        if not self.notif_enabled:
            return
        if is_claude:
            title = texts[0] if texts else ""
            body = texts[1] if len(texts) > 1 else ""
            msg = " ".join((body or title).split())
            text = ("Claude ответил: " + msg[:100]) if msg and msg.lower() != "claude" else "Claude ответил!"
            return self.react("celebrate", 1.8, text, "!", force_text=True)
        now = time.time()
        if now - self.t_notif.get(app, 0) < 90:     # не дёргаться на каждое сообщение в чате
            return
        self.t_notif[app] = now
        self.react("admire", 1.6, "%s: новое уведомление" % app, "!")
        if self.state == "anim" and self.an == "admire":
            self.face, self.look_ovr = 1, (1.0, 0.7)     # уведомления всплывают справа внизу

    def on_sys(self, ev):
        if not self.sys_enabled or self.hidden_fs:
            return
        k, R = ev[0], self.react
        if k == "cpu_hot":
            R("hot", 4.0, "Процессор на %d%%… жарко!" % ev[1])
        elif k == "ram_full":
            R("heavy", 2.8, "Память забита на %d%%. Тяжело!" % ev[1])
        elif k == "ac_on":
            R("celebrate", 1.4, "Зарядка! Ням.")
        elif k == "ac_off":
            R("lookaround", 2.4, "Работаем от батареи (%d%%)." % ev[1])
        elif k == "batt_low":
            R("yawn", 2.4, "Батарея %d%%… засыпаю. Где зарядка?" % ev[1], force_text=True)
        elif k == "usb_in":
            R("hops", 0, "О, флешка %s!" % ev[1], "!")
        elif k == "usb_out":
            R("wave", 1.8, "Пока, флешка %s." % ev[1])
        elif k == "net_down":
            R("lookaround", 2.6, "Интернет пропал!", "?", force_text=True)
        elif k == "net_up":
            R("happy", 0, "Интернет вернулся!")
        elif k == "disk_low":
            R("scratch", 2.4, "На диске %s осталось %.0f ГБ." % (ev[1], ev[2]), "!", force_text=True)
        elif k == "hung":
            R("tap", 2.6, "«%s» не отвечает…" % ev[1], "?")
        elif k == "long_work":
            R("stretch", 2.4, "Ты за компом уже %d мин — разомнёмся?" % ev[1])
        elif k == "back":
            R("wave", 2.0, random.choice(PHRASES["back"]))

    def on_clipboard(self):
        if not self.sys_enabled or time.time() - self.t_shot < 15 or self.hidden_fs:
            return
        try:
            md = QApplication.clipboard().mimeData()
            if md is not None and md.hasImage():
                self.t_shot = time.time()
                self.react("celebrate", 1.3, random.choice(("Чииз!", "Я получился?", "Скриншот! Я в кадре?")))
        except Exception:
            pass

    def describe_doing(self):
        s, n = self.state, self.an
        if s == "sleep":
            return "спишь"
        if s == "draw":
            return "рисуешь карандашом на обоях"
        if s == "push":
            return "толкаешь иконку"
        if s == "anim" and n in ("laptop", "read", "dance"):
            return {"laptop": "печатаешь на своём маленьком ноутбуке", "read": "читаешь книжку",
                    "dance": "танцуешь"}[n]
        kind = self.plat.kind if self.plat else ""
        where = {"floor": "на панели задач", "window": "на крыше окна", "icon": "на иконке",
                 "ledge": "в браузере", "browser_top": "на крыше браузера", "browser_in": "в браузере"}.get(kind, "")
        return ("гуляешь " if s == "walk" else "сидишь ") + where if where else "отдыхаешь"

    def screen_context(self, geo):
        """Для зрения: окна на мониторе (заголовок, программа, активное ли), простой хозяина, чем занят краб."""
        out = dict(doing=self.describe_doing())
        if not IS_WIN:
            return out
        out["idle"] = int(idle_seconds())
        fg = user32.GetForegroundWindow()
        fg = (user32.GetAncestor(fg, 2) or fg) if fg else None
        me, wins = os.getpid(), []
        gl, gt, gr, gb = geo.left(), geo.top(), geo.left() + geo.width(), geo.top() + geo.height()

        def cb(hwnd, _):
            try:
                if len(wins) >= 10:
                    return False
                if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                    return True
                pid = DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == me or user32.GetWindowLongW(hwnd, -20) & 0x80:
                    return True
                title = w_text(hwnd).strip()
                if not title or w_class(hwnd) in SKIP_CLASSES or w_cloaked(hwnd):
                    return True
                l, t, r, b = w_frame(hwnd)
                cx, cy = (l + r) // 2, (t + b) // 2
                if r - l < 200 or b - t < 100 or not (gl <= cx < gr and gt <= cy < gb):
                    return True
                wins.append((title, exe_of(hwnd), hwnd == fg))
            except Exception:
                pass
            return True

        user32.EnumWindows(ENUMPROC(cb), 0)
        out["windows"] = wins
        return out

    def show_menu(self, pos):
        self.menu.exec(pos)

    def set_push(self, on):
        self.push_enabled = on
        self.cfg.setValue("push", on)

    def set_draw(self, on):
        self.draw_enabled = on
        self.cfg.setValue("draw", on)

    def set_ttt_offer(self, on):
        self.ttt_offer = on
        self.cfg.setValue("ttt", on)

    def set_shy(self, on):
        self.cfg.setValue("shy", on)

    def set_chatter(self, on):
        self.chatter = on
        self.cfg.setValue("chatter", on)

    def set_notif(self, on):
        self.notif_enabled = on
        self.cfg.setValue("notif", on)

    def set_sys(self, on):
        self.sys_enabled = on
        self.cfg.setValue("sysreact", on)

    def cmd_copy_hooks(self):
        QGuiApplication.clipboard().setText(hooks_json())
        self.speak_short("Скопировал! Вставь в %USERPROFILE%\\.claude\\settings.json — и я буду знать, "
                         "когда Claude Code работает и когда закончил.")

    def set_auto(self, on):
        try:
            set_autostart(on)
        except OSError:
            pass

    def restore_icons(self):
        if self.desk.ok:
            self.restore_q = []
            self.desk.restore_now()

    def open_data_dir(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        if IS_WIN:
            os.startfile(DATA_DIR)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(DATA_DIR))

    def notify(self, text):
        self.tray.showMessage("Klodik", text)

    def shutdown(self):
        if self.ai:
            try:
                self.ai.shutdown()
            except Exception:
                log_error("Ошибка при выходе (ИИ)", traceback.format_exc())
        self.desk.shutdown()
        self.hooks.shutdown()
        self.layer.save()
        self.layer.hide()
        self.tray.hide()

    # ───────────── команды из меню ─────────────
    def can_cmd(self):
        return self.state in ("idle", "walk", "sleep", "anim", "draw") and self.plat is not None

    def interrupt(self):
        """Бросить текущий план (команда пользователя важнее распорядка)."""
        self.after, self.plan, self.build, self.restore_q = None, [], None, []
        if self.state == "draw":
            self.stop_draw()

    def attend(self):
        """Хозяин заговорил: бросить свои прогулки (но не его поручения) и остаться рядом."""
        if self.restore_q or self.build or self.state in ("draw", "drag", "fall", "jump", "push"):
            return
        self.after, self.plan = None, []
        if self.state == "walk" and self.plat is not None:
            self.start_idle(random.uniform(2.0, 4.0))

    def cmd_sleep(self):
        if self.state == "sleep":
            self.wake_up()
        elif self.can_cmd():
            self.interrupt()
            self.go_sleep(random.uniform(25, 60))

    def cmd_come(self):
        if not self.can_cmd():
            return
        pos = getattr(self, "menu_pos", QCursor.pos())
        p = self.platform_below(pos.x(), pos.y()) or self.nearest_floor(pos.x())
        if not p:
            return
        self.interrupt()
        px = clamp(pos.x(), p.x1 + p.m, p.x2 - p.m) if p.x2 - p.x1 > 2 * p.m else (p.x1 + p.x2) / 2
        self.goto(p.key, done=lambda: self.start_walk(px, after=self.start_happy))

    def cmd_browser(self):
        if self.can_cmd():
            self.interrupt()
            self.act_visit_browser()

    def cmd_push(self):
        if self.can_cmd() and self.desk.ok:
            self.interrupt()
            self.act_push()

    def cmd_build(self):
        if self.can_cmd() and self.desk.ok:
            self.interrupt()
            self.act_build(force=True)

    def cmd_restore(self):
        if not self.desk.ok:
            return
        q = self.desk.displaced()
        if not q:
            self.desk.forget_home()
            self.notify("Все иконки и так на своих местах.")
            return
        if not self.can_cmd():
            return
        self.interrupt()
        q.sort(key=lambda it: it[1][1], reverse=True)          # сначала нижние — чтобы не мешали друг другу
        self.restore_q = q
        self.say_phrase("restore_start", 0.8)
        self.restore_next()

    def restore_next(self):
        if not self.restore_q:
            if not self.desk.displaced():
                self.desk.forget_home()
                self.say_phrase("restore_done", 0.8)
            self.refresh_platforms(True)
            return self.start_fall() if self.plat is None else self.start_happy()
        idx, tgt = self.restore_q.pop(0)
        self.start_icon_job(idx, tgt, 20, after=self.restore_next, quick=True)

    def cmd_draw(self, subject=None):
        if self.can_cmd():
            self.interrupt()
            self.plan_art(force=True, subject=subject)

    def cmd_anim(self, name):
        if self.can_cmd():
            self.interrupt()
            self.start_anim(name, ANIMS[name])

    def cmd_flip(self, sign):
        if self.can_cmd():
            self.interrupt()
            self.act_flip(sign)

    def cmd_jacks(self):
        if self.can_cmd():
            self.interrupt()
            self.act_jacks()

    def cmd_moon(self):
        if self.can_cmd():
            self.interrupt()
            self.act_moon()

    PET_ACTIONS = ("wave", "dance", "stretch", "scratch", "lookaround", "tap", "sneeze", "flex", "whistle", "bow",
                   "shrug", "laptop", "read", "celebrate", "yawn", "hiccup", "flip", "jacks", "moonwalk", "happy",
                   "sleep", "wake", "draw", "push_icon", "build_house", "restore_icons", "tictactoe")
    DRAWING_NAMES = DRAWING_NAMES

    def do_action(self, name, subject=None):
        """Действие по просьбе ИИ (инструмент pet_action). Возвращает текст для модели."""
        if name == "wake":
            if self.state == "sleep":
                self.wake_up()
            return "Проснулся."
        if not self.can_cmd():
            return "Сейчас не может: он в прыжке, падает или его несут мышкой."
        if name in ANIMS:
            self.cmd_anim(name)
        elif name == "flip":
            self.cmd_flip(random.choice((1, -1)))
        elif name == "jacks":
            self.cmd_jacks()
        elif name == "moonwalk":
            self.cmd_moon()
        elif name == "happy":
            self.interrupt()
            self.start_happy()
        elif name == "sleep":
            self.interrupt()
            self.go_sleep(random.uniform(25, 60))
        elif name == "draw":
            subject = subject if subject in DRAWINGS else None
            self.cmd_draw(subject)
            return "Пошёл к свободному месту на обоях рисовать%s; рисунок появится через несколько секунд." % (
                (" (" + subject + ")") if subject else "")
        elif name == "tictactoe":
            if self.ttt:
                return "Вы уже играете: поле нарисовано, хозяин ходит крестиками."
            self.cmd_ttt()
            return ("Пошёл рисовать поле для крестиков-ноликов на обоях. Хозяин ходит крестиками: кликает по клетке, "
                    "краб отвечает ноликами.")
        elif name == "push_icon":
            if not self.desk.ok:
                return "Иконки рабочего стола недоступны."
            self.cmd_push()
        elif name == "build_house":
            self.cmd_build()
        elif name == "restore_icons":
            self.cmd_restore()
        else:
            return "Неизвестное действие: " + name
        return "Готово: " + name

    # ───────────── платформы ─────────────
    def refresh_platforms(self, icons=False):
        U, scr = self.U, self.screen_rects()
        ign = self.ignore() if hasattr(self, "own") else set()
        plats = [Plat("floor", ("floor", i), l, r, b, 8 * U) for i, (l, t, r, b) in enumerate(scr)]
        wins, self.browser_rects, covers = scan_windows(ign, scr, U)
        plats += wins
        if icons and self.desk.ok:
            self.ico_gen += 1                     # опрос из фона, начатый раньше, уже устарел
            self.icon_plats, self.ico_covers = self.desk.scan_all(scr, ign)
            self.t_ico = time.perf_counter()
        else:
            got = self.ico_new
            if got and got[0] == self.ico_gen:
                self.ico_new = None
                self.icon_plats, self.ico_covers = got[1], got[2]
        plats += self.icon_plats
        self.platforms = plats
        self.pmap = {p.key: p for p in plats}
        self.layer.set_covers(list(self.ico_covers))
        free = QRegion()
        for l, t, r, b in scr:
            free = free.united(QRegion(int(l), int(t), int(r - l), int(b - t)))
        for l, t, r, b in covers + list(self.ico_covers):
            free = free.subtracted(QRegion(int(l), int(t), int(r - l), int(b - t)))
        self.free = free

    def scan_icons_async(self):
        """Опрос иконок в фоновом потоке: если explorer занят, ждёт поток, а не краб.
        Раньше опрос раз в секунду шёл в главном цикле и подвешивал анимацию."""
        if self.ico_busy or not self.desk.ok:
            return
        self.ico_busy = True
        self.t_ico = time.perf_counter()
        gen, d, scr = self.ico_gen, self.desk, self.screen_rects()
        ign = self.ignore() if hasattr(self, "own") else set()

        def work():
            try:
                d.ensure_free()
                plats, covers = d.scan_all(scr, ign)
                self.ico_new = (gen, plats, covers)
            except Exception:
                log_error("Опрос иконок", traceback.format_exc())
            finally:
                self.ico_busy = False

        threading.Thread(target=work, daemon=True).start()

    def is_free(self, l, t, r, b):
        """Прямоугольник целиком на видимых обоях (не под окном и не на иконке)?"""
        if self.free is None:
            return True
        return QRegion(int(l), int(t), int(r - l), int(b - t)).subtracted(self.free).isEmpty()

    def platform_below(self, x, y):
        best = None
        for p in self.platforms:
            if p.x1 <= x <= p.x2 and p.y >= y - 1 and (best is None or p.y < best.y):
                best = p
        return best

    def nearest_floor(self, x):
        fl = [p for p in self.platforms if p.kind == "floor"]
        return min(fl, key=lambda p: max(0, p.x1 - x, x - p.x2)) if fl else None

    def reach_ok(self, p):
        gap = max(0, p.x1 - self.x, self.x - p.x2)
        up = self.y - p.y
        U = self.U
        return gap <= REACH_X * U and -REACH_DOWN * U <= up <= REACH_UP * U

    def pick_x(self, p):
        U = self.U
        lo, hi = p.x1 + p.m, p.x2 - p.m
        if lo > hi:
            lo = hi = (p.x1 + p.x2) / 2
        near = clamp(self.x, lo, hi)
        return clamp(near + random.uniform(-8 * U, 8 * U), lo, hi)

    def in_browser(self):
        return any(l <= self.x <= r and t <= self.y - 3 * self.U <= b for l, t, r, b in self.browser_rects)

    def follow(self):
        """Ехать вместе с платформой (окно двигают — он едет). Пропала — падает."""
        if self.plat is None:
            self.start_fall()
            return False
        p = self.pmap.get(self.plat.key)
        U = self.U
        if p is None or self.x < p.x1 - 3 * U or self.x > p.x2 + 3 * U:
            if self.state == "draw":
                self.stop_draw()
            self.plan = []
            self.start_fall()
            return False
        self.plat, self.y = p, p.y
        return True

    # ───────────── базовые действия ─────────────
    def finish(self):
        cb, self.after = self.after, None
        cb() if cb else self.start_idle()

    def start_idle(self, dur=None):
        self.state, self.t = "idle", 0.0
        dur = dur if dur is not None else random.uniform(2.0, 5.0)
        if self.plan:                                   # внутри плана паузы короткие
            dur = min(dur, random.uniform(0.5, 1.1))
        self.idle_dur = dur

    def start_sleep(self, dur):
        self.state, self.t, self.dur = "sleep", 0.0, dur
        self.look_ovr = None

    def go_sleep(self, dur):
        """Зевнуть, потянуться — и спать."""
        self.start_anim("stretch", ANIMS["stretch"], after=lambda: self.start_sleep(dur))

    def wake_up(self):
        self.energy = max(self.energy, 0.6)
        self.start_anim("stretch", ANIMS["stretch"])

    def start_fall(self, vx=0.0, vy=0.0):
        self.state, self.t, self.plat = "fall", 0.0, None
        self.vx, self.vy = vx, vy

    def start_walk(self, tx, speed=None, after=None, moon=False):
        self.after = after
        self.state, self.t = "walk", 0.0
        self.tx, self.moon = tx, moon
        self.speed = speed or 11 * self.U
        self.face = 1 if tx >= self.x else -1

    def start_anim(self, name, dur, after=None):
        self.after = after
        self.state, self.t, self.an, self.dur = "anim", 0.0, name, dur
        self.fx_acc, self.sneezed, self.look_ovr, self.aflag = 0.0, False, None, False
        if self.plat is None:
            return self.start_fall()
        if name == "laptop":
            self.say_phrase("laptop", 0.25)

    def start_jump(self, tx, ty, key=None, h=None, T=None, crouch=0.14, after=None,
                   spin=0, jacks=False, far=False):
        U = self.U
        dx, dy = tx - self.x, ty - self.y
        dist = math.hypot(dx, dy * 0.5)
        T = T or (clamp(dist / (80 * U), 0.5, 1.5) if far else clamp(dist / (55 * U), 0.42, 1.15))
        h = h if h is not None else 7 * U + 0.5 * max(0, -dy) + 0.06 * abs(dx)
        self.after = after
        self.state, self.t, self.ju = "jump", 0.0, 0.0
        self.j = dict(x0=self.x, y0=self.y, x1=tx, y1=ty, key=key, T=T, h=h, crouch=crouch,
                      spin=spin, jacks=jacks)
        self.plat = None
        if abs(dx) > U:
            self.face = 1 if dx > 0 else -1

    def start_happy(self):
        self.happy_t = 1.6
        for _ in range(3):
            self.hearts.append([random.uniform(-4, 4) * self.U, -11 * self.U, -random.uniform(0, 0.4)])
        if self.state == "sleep":
            self.wake_up()
        elif self.state in ("idle", "walk") and self.plat:
            self.after = None
            self.start_jump(self.x, self.y, self.plat.key, h=5 * self.U, T=0.4, crouch=0.08, after=self.start_idle)

    def add_fx(self, kind, dx, dy, vx=0.0, vy=0.0, life=1.0, txt="", col=None):
        if len(self.fx) < 120:
            self.fx.append(dict(k=kind, x=dx, y=dy, vx=vx, vy=vy, age=0.0, life=life, txt=txt, col=col))

    def goto(self, key, done=None, steps=0):
        """Добраться до платформы серией прыжков/шагов."""
        U, cur, tgt = self.U, self.plat, self.pmap.get(key)

        def end():
            done() if done else self.start_idle()

        if cur is None or tgt is None or steps > 14 or cur.key == key:
            return end()

        def d(p):
            return max(0, tgt.x1 - p.x2, p.x1 - tgt.x2) + 0.6 * abs(p.y - tgt.y)

        best, bd = None, d(cur) - U
        for p in self.platforms:
            if p.key != cur.key and self.reach_ok(p) and d(p) < bd:
                best, bd = p, d(p)
        if best:
            self.start_jump(self.pick_x(best), best.y, best.key,
                            after=lambda: self.goto(key, done, steps + 1))
            return
        lo, hi = cur.x1 + cur.m, cur.x2 - cur.m
        direction = 1 if (tgt.x1 + tgt.x2) / 2 > self.x else -1
        nx = clamp(self.x + direction * 25 * U, lo, hi)
        if abs(nx - self.x) < 2 * U:
            return end()
        self.start_walk(nx, after=lambda: self.goto(key, done, steps + 1))

    # ───────────── «мозг»: распорядок дня ─────────────
    # Вместо случайных несвязанных трюков он выбирает «занятие» — короткий сценарий из
    # нескольких логично связанных шагов. Бодрость тратится на игры и восстанавливается сном.
    SCENES = {      # имя: (базовый вес, затраты бодрости, пауза до повтора, сек)
        "stroll": (5.0, 0.02, 0), "explore": (3.0, 0.04, 20), "fidget": (2.0, 0.0, 25),
        "play": (1.6, 0.16, 60), "workout": (0.8, 0.2, 150), "art": (1.1, 0.06, 150),
        "icons": (1.3, 0.07, 45), "build": (0.35, 0.22, 600), "browser": (1.4, 0.04, 60),
        "screen": (0.5, 0.04, 420), "rest": (0.5, 0.0, 240),
        "work": (0.9, 0.03, 200), "read": (0.6, 0.0, 300),
    }

    def think(self):
        if self.ttt:                                   # идёт партия — всё остальное подождёт
            return self.ttt_think()
        # внимание: открыт чат или курсор рядом — никуда не уходит, смотрит на хозяина
        chatting = bool(self.ai and self.ai.chat_open())
        if self.ttt_due(chatting):
            return self.ttt_start(offer=True)
        if chatting or self.cur_d < 24 * self.U:
            self.plan = []
            if not chatting and random.random() < 0.25:
                return self.start_anim("wave" if random.random() < 0.3 else "whistle", 1.8)
            return self.start_idle(random.uniform(1.5, 3.0))
        if self.plan:
            step = self.plan.pop(0)
            return step()
        p, now = self.plat, time.time()
        self.energy = clamp(self.energy - 0.01, 0.0, 1.0)
        lt = time.localtime()
        hour = lt.tm_hour
        tired = (1 - self.energy) + (0.35 if hour >= 23 or hour < 6 else 0.0)
        night = time.strftime("%Y%m%d", time.localtime(now - 6 * 3600))
        if (hour >= 23 or hour < 5) and self.night_said != night:
            self.night_said = night                                # раз за ночь
            self.say_phrase("night")
        elif now - self.t_chatter > random.uniform(300, 900):
            self.t_chatter = now
            self.say_phrase("idle", 0.6)
        if self.cc_busy and random.random() < 0.6:           # Claude Code работает — и он «кодит» рядом
            return self.start_anim("laptop", random.uniform(8, 15))
        if self.energy < 0.12:
            return self.run_scene("rest")
        have_icons = self.push_enabled and self.desk.ok and len(self.icon_plats) > 0
        ok = {
            "stroll": True, "explore": any(self.reach_ok(q) and q.key != p.key for q in self.platforms),
            "fidget": True, "play": self.energy > 0.35, "workout": self.energy > 0.55,
            "art": self.draw_enabled, "icons": have_icons and now - self.last_push > 30,
            "build": have_icons and len(self.icon_plats) >= 3 and now - self.last_build > 480,
            "browser": not self.in_browser() and any(q.kind in ("ledge", "browser_top", "browser_in")
                                                     for q in self.platforms),
            "screen": len([q for q in self.platforms if q.kind == "floor"]) > 1 and (
                not self.on_cursor_screen() or random.random() < 0.3),
            "rest": True, "work": True, "read": True,
        }
        names, weights = [], []
        for name, (w, cost, cool) in self.SCENES.items():
            if not ok[name] or name == self.scene or now - self.scene_t.get(name, -1e9) < cool:
                continue
            if name == "rest":
                w *= 0.2 + 5 * max(0.0, tired - 0.3)
            elif cost >= 0.1:
                w *= self.energy
            names.append(name)
            weights.append(max(w, 0.01))
        if not names:
            return self.start_idle()
        self.run_scene(random.choices(names, weights)[0])

    def run_scene(self, name):
        self.scene = name
        self.scene_t[name] = time.time()
        self.energy = clamp(self.energy - self.SCENES[name][1], 0.0, 1.0)
        S = self.start_anim
        A = lambda n: (lambda: S(n, ANIMS[n]))
        plans = {
            "stroll": [self.act_walk, A("lookaround")] + ([self.act_walk] if random.random() < 0.5 else []),
            "explore": [self.act_jump, A("lookaround")],
            "fidget": [A(random.choice(("whistle", "tap", "scratch", "whistle", "sneeze", "hiccup") +
                                       (("yawn", "yawn") if time.localtime().tm_hour >= 22 else ("yawn",))))],
            "play": random.choice([[self.act_hops, lambda: self.act_flip(1), A("dance")],
                                   [self.act_zoom, self.act_hops, A("pant")],
                                   [A("dance"), self.act_moon, A("bow")],
                                   [lambda: self.act_flip(-1), self.act_hops, A("dance")]]),
            "workout": [A("stretch"), self.act_jacks, A("flex"), A("pant")],
            "art": [lambda: self.plan_art()],
            "icons": [self.act_push, A("lookaround"), A(random.choice(("whistle", "flex", "shrug")))],
            "build": [lambda: self.act_build()],
            "browser": [self.act_visit_browser, A("lookaround")],
            "screen": [self.act_visit_screen, A("wave")],
            "rest": [lambda: self.go_sleep(15 + 40 * (1 - self.energy))],
            "work": [lambda: S("laptop", random.uniform(8, 14)), A("stretch")],
            "read": [lambda: S("read", random.uniform(7, 12)), A("lookaround")],
        }
        steps = plans[name]
        self.plan = list(steps[1:])
        steps[0]()

    def act_walk(self):
        p, U = self.plat, self.U
        lo, hi = p.x1 + p.m, p.x2 - p.m
        if hi - lo < 2 * U:
            return self.start_idle()
        d = random.uniform(8, 40) * U * random.choice((-1, 1))
        tx = clamp(self.x + d, lo, hi)
        if abs(tx - self.x) < 3 * U:
            tx = clamp(self.x - d, lo, hi)
        self.start_walk(tx, speed=random.uniform(9, 12) * U)

    def act_moon(self):
        p, U = self.plat, self.U
        lo, hi = p.x1 + p.m, p.x2 - p.m
        if hi - lo < 12 * U:
            return self.start_idle()
        tx = clamp(self.x + random.choice((-1, 1)) * random.uniform(10, 25) * U, lo, hi)
        self.start_walk(tx, speed=8 * U, moon=True)

    def act_jump(self):
        cands = [q for q in self.platforms if q.key != self.plat.key and self.reach_ok(q)]
        if not cands:
            return self.act_walk()
        q = random.choices(cands, [KIND_W.get(c.kind, 1) for c in cands])[0]
        self.start_jump(self.pick_x(q), q.y, q.key)

    def act_flip(self, sign):
        U, p = self.U, self.plat
        lo, hi = p.x1 + p.m, max(p.x1 + p.m, p.x2 - p.m)
        tx = clamp(self.x + random.uniform(-5 * U, 5 * U), lo, hi)
        self.start_jump(tx, self.y, p.key, h=10 * U, T=0.75, crouch=0.15, spin=360 * sign * self.face)

    def act_hops(self, n=None, jacks=False):
        n = n if n is not None else random.randint(2, 4)
        if n <= 0 or self.plat is None:
            return self.start_idle()
        U, p = self.U, self.plat
        lo, hi = p.x1 + p.m, p.x2 - p.m
        tx = clamp(self.x + random.uniform(-5 * U, 5 * U), lo, max(lo, hi))
        self.start_jump(tx, self.y, p.key, h=random.uniform(3, 6) * U, T=0.38, crouch=0.07, jacks=jacks,
                        after=lambda: self.act_hops(n - 1, jacks))

    def act_jacks(self):
        self.act_hops(random.randint(4, 6), jacks=True)

    def act_zoom(self, n=None):
        n = n if n is not None else random.randint(2, 4)
        p = self.plat
        if n <= 0 or p is None:
            return self.start_idle()
        lo, hi = p.x1 + p.m, p.x2 - p.m
        if hi - lo < 4 * self.U:
            return self.start_idle()
        self.start_walk(random.uniform(lo, hi), speed=34 * self.U, after=lambda: self.act_zoom(n - 1))

    def act_visit_browser(self):
        c = [q for q in self.platforms if q.kind in ("ledge", "browser_top", "browser_in")]
        if not c:
            return self.start_idle()
        self.goto(random.choice(c).key)

    def screen_of(self, x, y):
        return next((i for i, s in enumerate(self.screen_rects()) if s[0] <= x < s[2] and s[1] <= y < s[3]), -1)

    def on_cursor_screen(self):
        c = QCursor.pos()
        return self.screen_of(self.x, self.y - 2) == self.screen_of(c.x(), c.y())

    def act_visit_screen(self):
        """Сходить на другой монитор. Если он не там, где курсор, — вернуться к хозяину."""
        fl = [q for q in self.platforms if q.kind == "floor" and q.key != self.plat.key]
        if not fl:
            return self.start_idle()
        c = QCursor.pos()
        home = [q for q in fl if self.screen_of((q.x1 + q.x2) / 2, q.y - 2) == self.screen_of(c.x(), c.y())]
        if home:
            self.speak_short("Иду к тебе!")
            return self.goto(home[0].key)
        self.speak_short("Сбегаю на соседний монитор 👉")
        self.goto(random.choice(fl).key)

    def startle(self, away):
        """Мягкий испуг: вздрогнул и отступил на шаг. Без прыжков через весь экран."""
        p, U = self.plat, self.U
        self.add_fx("excl", 0, -13 * U, life=0.8)
        self.after, self.plan = None, []
        self.face = -away
        tx = clamp(self.x + away * 4 * U, p.x1 + p.m, max(p.x1 + p.m, p.x2 - p.m))
        self.start_anim("flinch", ANIMS["flinch"], after=lambda: self.start_walk(
            tx, speed=14 * U, after=lambda: self.start_idle(random.uniform(1.0, 2.0))))

    # ───────────── рисуем карандашом ─────────────
    def find_spot(self, p, near=None, wfac=1.0):
        """Свободное место на обоях над платформой p: (cx, cy, S, W) — центр, полувысота, полуширина."""
        U = self.U
        lo, hi = p.x1 + p.m + 2 * U, p.x2 - p.m - 2 * U
        big = 1.15 if wfac > 1.01 or self.art and not self.art.get("mono") else 1.0   # цветные рисунки чуть крупнее
        for _ in range(24):
            S = random.uniform(6, 9) * U * big
            W = S * wfac
            if hi - lo < 2 * W + 14 * U:
                continue
            if near is not None and random.random() < 0.7:
                cx = near + random.choice((-1, 1)) * random.uniform(W + 6 * U, W + 30 * U)
            else:
                cx = random.uniform(lo + W + 7 * U, hi - W - 7 * U)
            cx = clamp(cx, lo + W + 7 * U, hi - W - 7 * U)
            cy = p.y - S - random.uniform(1.5, 3.5) * U
            box = (cx - W - 2 * U, cy - S - 2 * U, cx + W + 2 * U, cy + S + 2 * U)
            if self.is_free(*box) and not self.layer.occupied(*box):
                return cx, cy, S, W
        return None

    def pick_art(self, subject=None):
        """Что рисовать: цветной рисунок (чаще) или простой контур одним карандашом."""
        name = subject if subject in DRAWINGS else None
        if not name and random.random() < 0.72:
            names = list(DRAWINGS)
            name = random.choices(names, [0.35 if n.isupper() else 1.0 for n in names])[0]
        if name:
            strokes, cols, fills, aspect = drawing_parts(name)
            return dict(name=name, strokes=strokes, cols=cols, fills=fills, k=2.0, step=0.015, wfac=max(1.0, aspect),
                        mono=False)
        strokes = random.choice(SHAPES)()
        c = random.choice(PENCIL_COLORS)                 # простой рисунок: контур одним карандашом,
        f = lighter(random.choice([v for v in CRAYON.values() if v != c]) if random.random() < 0.4 else c, 0.45)
        return dict(name="", strokes=strokes, cols=[c] * len(strokes), fills=[f] * len(strokes),   # а внутри — штриховка
                    k=1.0, step=0.03, wfac=1.0, mono=True)

    def plan_art(self, force=False, subject=None):
        """Выбрать, что и где рисовать (любой экран, пол или крыша окна), дойти туда и нарисовать."""
        self.last_draw = time.time()
        if not self.draw_enabled and not force:
            return self.start_idle()
        U, here = self.U, self.plat
        my_scr = self.screen_of(self.x, self.y - 2)
        for attempt in range(3):
            self.art = self.pick_art(subject if attempt == 0 else None)
            cands = []
            for q in self.platforms:
                if q.kind in ("floor", "window", "browser_top") and q.x2 - q.x1 > 40 * U:
                    if force and self.screen_of((q.x1 + q.x2) / 2, q.y - 2) != my_scr:
                        continue                   # по просьбе — рисует тут, у вас на глазах
                    if self.find_spot(q, self.x if q is here else None, self.art["wfac"]):
                        w = (12.0 if force else 3.0) if q is here else 1.0
                        cands.append((q, w))
            if cands:
                break
        if not cands:
            self.art = None
            if force:
                self.speak_short("Негде рисовать: свободные обои заняты окнами или рисунками")
            return self.start_anim("shrug", ANIMS["shrug"])
        q = random.choices([c[0] for c in cands], [c[1] for c in cands])[0]
        self.goto(q.key, done=self.walk_to_draw)

    def walk_to_draw(self):
        p = self.plat
        if p is None:
            return self.start_fall()
        if not self.art:
            self.art = self.pick_art()
        spot = self.find_spot(p, self.x, self.art["wfac"])
        if not spot:
            return self.start_anim("shrug", ANIMS["shrug"])
        cx, cy, S, W = spot
        d = 1 if cx > self.x else -1                   # с какой стороны от рисунка он стоит
        U = self.U
        sx = clamp(cx - d * (W + 5 * U), p.x1 + p.m, p.x2 - p.m)
        self.start_walk(sx, after=lambda: self.act_draw(spot, d))

    def speak_short(self, text):
        if self.ai:
            self.ai.say(text, 3.5)
        else:
            self.notify(text)

    def act_draw(self, spot, d):
        p = self.plat
        if p is None or self.pmap.get(p.key) is None:
            return self.start_fall()
        cx, cy, S, W = spot
        if not self.is_free(cx - W, cy - S, cx + W, cy + S):
            return self.start_anim("shrug", ANIMS["shrug"])
        art = self.art or self.pick_art()
        self.art = None
        k = art["k"] * S
        w = max(2.0, 0.38 * self.U) if art["mono"] else max(2.5, 0.55 * self.U)
        strokes, cols, fast = with_fill(art["strokes"], art["cols"], art["fills"], 1.7 * w / k, 30 * (w / k) ** 2)
        self.start_strokes(strokes, cols, cx, cy, k, d, w, art["step"], fast=fast, wax=not art["mono"],
                           name=art["name"], speed=75 if art["mono"] else 95)
        self.say_phrase("draw_start", 0.35)

    def start_strokes(self, strokes, cols, cx, cy, k, d, w, step, fast=(), wax=True, name="", speed=90, done=None, tmp=False):
        """Нарисовать штрихи карандашом: (cx, cy) — центр, k — пикселей на единицу, d — с какой стороны стоит.
        done — что делать после (иначе любуется рисунком)."""
        doodle = self.layer.new_doodle(cols[0], w, multi=True)
        if not wax:
            doodle.pop("wax", None)
        if tmp:
            doodle["tmp"] = 1                         # игровое поле: стирается после игры
        self.fix_z()
        pts = trace(strokes, step, fast)
        speed = max(speed, len(pts) / 11.0)            # большой рисунок — бойчее, не дольше ~10 секунд
        self.dw = dict(pts=pts, i=0, prog=0.0, cx=cx, cy=cy, k=k, dir=d, doodle=doodle,
                       end=0.0, cols=cols, fast=fast, name=name, speed=speed, done=done)
        self.pencil_col = QColor(*cols[0])
        self.state, self.t, self.face = "draw", 0.0, d
        self.after = None
        return doodle

    def stop_draw(self):
        if self.dw:
            self.layer.finish(self.dw["doodle"])
        self.dw = None
        self.pencil = self.look_ovr = None

    def st_draw(self, dt):
        if not self.follow():
            return
        dw, U, p = self.dw, self.U, self.plat
        pts, k = dw["pts"], dw["k"]
        first = pts[0]
        ftip = (dw["cx"] + first[0] * k, dw["cy"] + first[1] * k)
        if self.t < 0.5:                                # достаёт карандаш и тянется к листу
            shoulder = (self.x + dw["dir"] * 6 * U, self.y - 5 * U)
            k = self.t / 0.5
            k = k * k * (3 - 2 * k)
            tip = (shoulder[0] + (ftip[0] - shoulder[0]) * k, shoulder[1] + (ftip[1] - shoulder[1]) * k)
        else:
            if dw["i"] < len(pts):
                dw["prog"] += dw["speed"] * dt * (2.0 if pts[dw["i"]][3] in dw["fast"] else 1.0)
                while dw["prog"] >= 1 and dw["i"] < len(pts):
                    dw["prog"] -= 1
                    x, y, down, si = pts[dw["i"]]
                    dw["i"] += 1
                    wx, wy = dw["cx"] + x * k, dw["cy"] + y * k
                    dw["tip"] = (wx, wy)
                    if down:
                        self.layer.add(dw["doodle"], wx, wy)
                    else:
                        col = dw["cols"][si] if dw["cols"] else None
                        self.layer.lift(dw["doodle"], col)
                        if col:
                            self.pencil_col = QColor(*col)       # взял карандаш другого цвета
            else:
                dw["end"] += dt
            tip = dw.get("tip", ftip)
        # шагает вдоль рисунка, чтобы рука доставала до кончика карандаша
        want = clamp(tip[0] - dw["dir"] * 7 * U, p.x1 + p.m, p.x2 - p.m)
        step = 16 * U * dt
        if abs(want - self.x) > 1.5 * U:
            mv = clamp(want - self.x, -step, step)
            self.x += mv
            self.phase += abs(mv) / (3 * U)
            dw["moving"] = True
        else:
            dw["moving"] = False
        dw["cur"] = tip
        self.pencil = tip
        self.face = dw["dir"]
        self.look_ovr = (clamp((tip[0] - self.x) / (10 * U), -1, 1), clamp((tip[1] - (self.y - 7 * U)) / (8 * U), -1, 1))
        if dw["end"] > 0.4 and dw.get("done"):
            self.stop_draw()
            return dw["done"]()
        if dw["end"] > 0.4:
            spot = (dw["cx"], dw["cy"])
            self.stop_draw()
            back = clamp(self.x - self.face * 6 * U, p.x1 + p.m, p.x2 - p.m)
            self.last_draw = time.time()

            name = dw.get("name", "")

            def admire():
                self.start_anim("admire", ANIMS["admire"], after=self.start_happy)
                if name and not name.isupper() and random.random() < 0.4:
                    self.say_phrase_text("Это %s!" % name)
                else:
                    self.say_phrase("draw_done", 0.5)
                self.face = 1 if spot[0] > self.x else -1
                self.look_ovr = (clamp((spot[0] - self.x) / (10 * U), -1, 1), -0.6)

            self.start_walk(back, speed=8 * U, after=admire)

    # ───────────── крестики-нолики ─────────────
    TTT_WIN = ["Я выиграл! Ещё разок?", "Три в ряд! Победа!", "Ха, попался! Сыграем ещё?"]
    TTT_LOSE = ["Ты выиграл! Молодец!", "Ого, сдаюсь!", "Ты сильный игрок!"]
    TTT_DRAW = ["Ничья! Хорошая была игра.", "Ничья. Ты тоже не промах!"]

    def ttt_due(self, chatting):
        """Пора предложить сыграть: примерно раз в час, когда хозяин рядом, но не печатает и не в игре/фильме."""
        now = time.time()
        if not self.ttt_offer or now < self.next_ttt or chatting or self.hidden_fs or self.plat is None:
            return False
        if self.state == "sleep" or self.build or self.restore_q:
            return False
        idle = idle_seconds()
        if not (8 < idle < 300):
            self.next_ttt = now + 60                      # печатает или отошёл — спросим позже
            return False
        return True

    def cmd_ttt(self):
        if self.ttt:
            return self.say_text("Мы уже играем! Твой ход." if self.ttt["phase"] == "user" else "Мы уже играем!")
        if self.can_cmd():
            self.interrupt()
            self.ttt_start(offer=False)

    def ttt_spot(self, p, strict=True):
        """Место для поля над платформой p: (cx, cy, S) — центр и полуразмер."""
        U = self.U
        S = 11 * U
        lo, hi = p.x1 + p.m + 2 * U, p.x2 - p.m - 2 * U
        if hi - lo < 2 * S + 14 * U:
            return None
        for _ in range(24):
            if p is self.plat and random.random() < 0.7:
                cx = self.x + random.choice((-1, 1)) * random.uniform(S + 8 * U, S + 30 * U)
            else:
                cx = random.uniform(lo + S + 7 * U, hi - S - 7 * U)
            cx = clamp(cx, lo + S + 7 * U, hi - S - 7 * U)
            cy = p.y - S - 2.5 * U
            box = (cx - S - 2 * U, cy - S - 2 * U, cx + S + 2 * U, cy + S + 2 * U)
            if self.is_free(*box) and (not strict or not self.layer.occupied(*box)):
                return cx, cy, S
        return None

    def ttt_start(self, offer):
        self.next_ttt = time.time() + random.uniform(50, 70) * 60
        my_scr = self.screen_of(self.x, self.y - 2)
        cands = [q for q in self.platforms if q.kind in ("floor", "window", "browser_top")
                 and self.screen_of((q.x1 + q.x2) / 2, q.y - 2) == my_scr]
        cands.sort(key=lambda q: (q is not self.plat, abs((q.x1 + q.x2) / 2 - self.x) + abs(q.y - self.y)))
        spot, where = None, None
        for strict in (True, False):                   # всё изрисовано — можно и поверх рисунков
            for q in cands:
                spot = self.ttt_spot(q, strict)
                if spot:
                    where = q
                    break
            if spot:
                break
        if not spot:
            if not offer:
                self.speak_short("Негде нарисовать поле: обои закрыты окнами")
                return self.start_anim("shrug", ANIMS["shrug"])
            return self.start_idle()
        cx, cy, S = spot
        self.plan, self.after = [], None
        self.ttt = dict(phase="walk", key=where.key, cx=cx, cy=cy, S=S, board=[None] * 9, docs=[], offer=offer,
                        soft=random.random() < 0.5, t=time.time(), grid=random.choice(("purple", "blue", "brown")))
        self.say_text("Сыграем в крестики-нолики? Сейчас нарисую поле!" if offer else "Давай! Сейчас нарисую поле.")
        self.goto(where.key, done=self.ttt_walk)

    def ttt_walk(self):
        g, U = self.ttt, self.U
        if not g:
            return self.start_idle()
        if self.plat is None or self.plat.key != g["key"]:
            return self.ttt_end("Не добрался до поля… в другой раз!")
        d = 1 if g["cx"] > self.x else -1
        sx = clamp(g["cx"] - d * (g["S"] + 5 * U), self.plat.x1 + self.plat.m, self.plat.x2 - self.plat.m)
        self.start_walk(sx, after=self.ttt_draw_grid)

    def ttt_pen(self):
        return max(2.5, 0.6 * self.U)

    def ttt_draw_grid(self):
        g = self.ttt
        if not g:
            return self.start_idle()
        if self.plat is None or self.plat.key != g["key"]:
            return self.ttt_end("Поле потерялось…")
        g["phase"] = "grid"
        t = 1 / 3
        strokes = [[(-t, -0.97), (-t, 0.97)], [(t, -0.97), (t, 0.97)], [(-0.97, -t), (0.97, -t)], [(-0.97, t), (0.97, t)]]
        d = 1 if g["cx"] > self.x else -1
        col = CRAYON[g["grid"]]
        g["docs"].append(self.start_strokes(strokes, [col] * 4, g["cx"], g["cy"], g["S"], d, self.ttt_pen(), 0.03,
                                            speed=80, done=self.ttt_ready, tmp=True))

    def ttt_ready(self):
        g = self.ttt
        if not g:
            return self.start_idle()
        g["phase"], g["t"], g["nudged"] = "user", time.time(), False
        if self.pad is None:
            self.pad = TTTPad(self.ttt_click)
        S = g["S"]
        self.pad.setGeometry(int(g["cx"] - S), int(g["cy"] - S), int(2 * S), int(2 * S))
        self.pad.busy = set()
        self.pad.active = True
        self.pad.show()
        self.fix_z()
        self.say_text("Ты — крестики, ходи первым: кликни по клетке!")
        self.ttt_look()
        if not self.ttt_step_aside():
            self.start_idle(1.0)

    def ttt_cell(self, i):
        """Центр клетки i в единицах поля (поле от -1 до 1)."""
        return -2 / 3 + (i % 3) * 2 / 3, -2 / 3 + (i // 3) * 2 / 3

    def ttt_side(self):
        """Куда отойти, чтобы не загораживать поле: сбоку от него, с той стороны, где ближе и есть место."""
        g, p, U = self.ttt, self.plat, self.U
        lo, hi = p.x1 + p.m, p.x2 - p.m
        off = g["S"] + 10 * U
        sides = sorted((g["cx"] - off, g["cx"] + off), key=lambda x: abs(x - self.x))
        for x in sides:
            if lo <= x <= hi:
                return x
        return clamp(sides[0], lo, hi)

    def ttt_step_aside(self):
        """Стоит перед полем — отходит в сторону. True, если пошёл."""
        g = self.ttt
        if not g or self.plat is None or abs(self.x - g["cx"]) >= g["S"] + 9 * self.U:
            return False
        self.start_walk(self.ttt_side(), after=lambda: (self.ttt_look(), self.start_idle(0.5)))
        return True

    def ttt_look(self):
        g = self.ttt
        if g:
            self.face = 1 if g["cx"] > self.x else -1
            self.look_ovr = (clamp((g["cx"] - self.x) / (10 * self.U), -1, 1), -0.5)

    def ttt_click(self, i):
        g = self.ttt
        if not g or g["phase"] != "user" or g["board"][i]:
            return
        g["board"][i] = "x"
        self.pad.busy.add(i)
        self.pad.active = False
        self.pad.set_hover(-1)
        self.pad.update()
        cx, cy = self.ttt_cell(i)                         # крестик хозяина появляется сразу, «мелком»
        r = 0.2
        strokes = [[(cx - r, cy - r), (cx + r, cy + r)], [(cx + r, cy - r), (cx - r, cy + r)]]
        S = g["S"]
        doodle = self.layer.new_doodle(CRAYON["blue"], self.ttt_pen(), multi=True)
        doodle["tmp"] = 1
        for x, y, down, si in trace(strokes, 0.03):
            if down:
                self.layer.add(doodle, g["cx"] + x * S, g["cy"] + y * S)
            else:
                self.layer.lift(doodle, CRAYON["blue"])
        self.layer.finish(doodle)
        g["docs"].append(doodle)
        self.fix_z()
        w, line = ttt_winner(g["board"])
        if w:
            return self.ttt_over(w, line)
        g["phase"], g["t"], g["delay"] = "crab", time.time(), random.uniform(0.6, 1.4)
        if self.state == "idle" and self.plat is not None:
            self.emote("?", 0.8)
            self.start_idle(g["delay"])

    def ttt_think(self):
        g, now = self.ttt, time.time()
        if g["key"] not in self.pmap:
            return self.ttt_end("Ой, поле закрыли окном. Доиграем потом!")
        if g["phase"] in ("grid", "line"):                  # рисование поля или линии прервали
            return self.ttt_end()
        if g["phase"] == "drawing":                       # нолик не дорисовал — сходит заново
            g["board"][g["cell"]] = None
            self.layer.remove([g["docs"].pop()])
            g["phase"], g["t"], g["delay"] = "crab", now, 0.3
        if self.plat is None or self.plat.key != g["key"]:
            if now - g["t"] > 60:
                return self.ttt_end("Ладно, доиграем в другой раз!")
            return self.goto(g["key"], done=self.ttt_back)
        self.ttt_look()
        if g["phase"] == "walk":
            return self.ttt_walk()
        if g["phase"] in ("user", "over") and self.ttt_step_aside():
            return
        if g["phase"] == "user":
            if now - g["t"] > 75:
                return self.ttt_end("Ладно, доиграем в другой раз!" if any(g["board"]) else
                                    "Не хочешь? Ну ладно, в другой раз.")
            if now - g["t"] > 25 and not g["nudged"]:
                g["nudged"] = True
                self.say_text("Твой ход!" if any(g["board"]) else "Ну что, сыграем? Кликни по клетке!")
                return self.start_anim("tap", ANIMS["tap"])
            return self.start_idle(1.0)
        if g["phase"] == "crab":
            wait = g["delay"] - (now - g["t"])
            if wait > 0:
                return self.start_idle(wait)
            return self.ttt_crab_move()
        if g["phase"] == "over":
            if now - g["t"] > 5:
                self.ttt_end()
                return self.start_happy()
        return self.start_idle(1.0)

    def ttt_back(self):
        if not self.ttt:
            return self.start_idle()
        if self.plat is None or self.plat.key != self.ttt["key"]:
            return self.ttt_end("Не добрался до поля… доиграем потом!")
        return self.ttt_think()

    def ttt_crab_move(self):
        g = self.ttt
        i = ttt_move(g["board"], g["soft"])
        g["board"][i], g["cell"], g["phase"] = "o", i, "drawing"
        cx, cy = self.ttt_cell(i)
        circle = _earc(cx, cy, 0.21, 0.23, -100, 265, 22)
        d = 1 if g["cx"] + cx * g["S"] > self.x else -1
        g["docs"].append(self.start_strokes([circle], [CRAYON["red"]], g["cx"], g["cy"], g["S"], d, self.ttt_pen(),
                                            0.03, speed=70, done=self.ttt_after_crab, tmp=True))

    def ttt_after_crab(self):
        g = self.ttt
        if not g:
            return self.start_idle()
        if self.pad:
            self.pad.busy.add(g["cell"])
        w, line = ttt_winner(g["board"])
        if w:
            return self.ttt_over(w, line)
        g["phase"], g["t"], g["nudged"] = "user", time.time(), False
        if self.pad:
            self.pad.active = True
            self.pad.update()
        self.ttt_look()
        if not self.ttt_step_aside():
            self.start_idle(1.0)

    def ttt_over(self, w, line):
        g = self.ttt
        if self.pad:
            self.pad.active = False
            self.pad.update()
        if not line:
            return self.ttt_react(w)
        (ax, ay), (bx, by) = self.ttt_cell(line[0]), self.ttt_cell(line[2])
        ex, ey = (bx - ax) * 0.2, (by - ay) * 0.2
        g["phase"] = "line"
        d = 1 if g["cx"] > self.x else -1
        col = CRAYON["red"] if w == "o" else CRAYON["blue"]
        g["docs"].append(self.start_strokes([[(ax - ex, ay - ey), (bx + ex, by + ey)]], [col], g["cx"], g["cy"],
                                            g["S"], d, self.ttt_pen(), 0.03, speed=70,
                                            done=lambda: self.ttt_react(w), tmp=True))

    def ttt_react(self, w):
        g = self.ttt
        if not g:
            return self.start_idle()
        g["phase"], g["t"] = "over", time.time()
        g["result"] = w
        self.ttt_look()
        if w == "o":
            self.say_text(random.choice(self.TTT_WIN))
            self.start_anim("celebrate", ANIMS["celebrate"])
        elif w == "x":
            self.say_text(random.choice(self.TTT_LOSE))
            for _ in range(3):
                self.hearts.append([random.uniform(-4, 4) * self.U, -11 * self.U, random.uniform(-0.3, 0.0)])
            self.start_anim("bow", ANIMS["bow"])
        else:
            self.say_text(random.choice(self.TTT_DRAW))
            self.start_anim("shrug", ANIMS["shrug"])

    def ttt_end(self, text=None):
        """Конец партии: поле стирается, остальные рисунки остаются."""
        g = self.ttt
        self.ttt = None
        if self.pad:
            self.pad.active = False
            self.pad.hide()
        if g:
            if self.dw and any(self.dw["doodle"] is d for d in g["docs"]):
                self.stop_draw()
            self.layer.remove(g["docs"])
        self.look_ovr = None
        self.next_ttt = max(self.next_ttt, time.time() + random.uniform(50, 70) * 60)
        if text:
            self.say_text(text)
        if self.state in ("idle", "draw") and self.plat is not None:
            self.start_idle(random.uniform(1.0, 2.0))

    def ttt_pad_check(self):
        """Поле закрыли окном — прячем «сетку», чтобы она не перехватывала клики в чужом окне."""
        g, pad = self.ttt, self.pad
        if not pad:
            return
        S = g["S"] if g else 0
        vis = bool(g) and g["phase"] in ("user", "crab", "drawing", "line") and not self.hidden_fs and \
            self.is_free(g["cx"] - S, g["cy"] - S, g["cx"] + S, g["cy"] + S)
        if vis != pad.isVisible():
            pad.setVisible(vis)

    # ───────────── двигаем иконки во все стороны ─────────────
    def random_target(self, idx):
        """Куда толкнуть иконку: по одному из 8 направлений, но так, чтобы по пути и на новом месте
        она ни на кого не наехала. Остальные иконки не трогаются."""
        d, U = self.desk, self.U
        pos, bd = d.item_pos(idx), d.item_bounds(idx)
        if not pos or not bd:
            return None
        ox, oy = d.origin()
        bw, bh = bd[2] - bd[0], bd[3] - bd[1]
        cx, cy = (bd[0] + bd[2]) // 2 + ox, (bd[1] + bd[3]) // 2 + oy
        scr = next((s for s in self.screen_rects() if s[0] <= cx < s[2] and s[1] <= cy < s[3]), None)
        if not scr:
            return None
        minx, maxx = scr[0] - ox + 4, scr[2] - ox - bw - 4
        miny, maxy = scr[1] - oy + 4, scr[3] - oy - bh - 2
        others = [b for i, b in d.boxes().items() if i != idx]
        gap = 6

        def hits(x, y):
            return any(not (x >= b[0] + b[2] + gap or x + bw + gap <= b[0] or
                            y >= b[1] + b[3] + gap or y + bh + gap <= b[1]) for b in others)

        opts = []
        for ang in range(0, 360, 45):
            nx, ny = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            lim = 24 * U
            if nx > 0.01:
                lim = min(lim, (maxx - pos[0]) / nx)
            elif nx < -0.01:
                lim = min(lim, (pos[0] - minx) / -nx)
            if ny > 0.01:
                lim = min(lim, (maxy - pos[1]) / ny)
            elif ny < -0.01:
                lim = min(lim, (pos[1] - miny) / -ny)
            free, t = 0.0, 4.0
            while t <= lim:                                  # идём по пути, пока не упрёмся в соседа
                if hits(pos[0] + nx * t, pos[1] + ny * t):
                    break
                free = t
                t += 4.0
            if free >= 6 * U:
                opts.append((nx, ny, free))
        if not opts:
            return None
        nx, ny, free = random.choice(opts)
        D = random.uniform(6 * U, free)
        return int(pos[0] + nx * D), int(pos[1] + ny * D)

    def act_push(self, idx=None):
        icons = list(self.icon_plats)
        if not icons or not self.desk.ok or not self.push_enabled:
            return self.start_idle()
        if idx is None:
            icons.sort(key=lambda q: abs((q.x1 + q.x2) / 2 - self.x) + abs(q.y - self.y))
            idx = random.choice(icons[:6]).idx
        tgt = self.random_target(idx)
        if not tgt:                                   # вокруг тесно — пробуем другую иконку рядом
            for q in icons[:6]:
                if q.idx != idx:
                    tgt = self.random_target(q.idx)
                    if tgt:
                        idx = q.idx
                        break
        if not tgt:
            return self.start_anim("shrug", ANIMS["shrug"])
        self.start_icon_job(idx, tgt, 9)

    def job_end(self, cb):
        if cb:
            cb()
        else:
            self.start_fall()

    def start_icon_job(self, idx, tgt, speed, after=None, quick=False):
        """Допрыгать до иконки, встать с нужной стороны и толкнуть её в точку tgt (клиентские координаты)."""
        d, U = self.desk, self.U
        pos, ic, bd = d.item_pos(idx), d.item_rect(idx), d.item_bounds(idx)
        if not (pos and ic and bd):
            return self.job_end(after)
        d.ensure_free()
        vx, vy = tgt[0] - pos[0], tgt[1] - pos[1]
        D = math.hypot(vx, vy)
        if D < 3 * U:
            return self.job_end(after)
        nx, ny = vx / D, vy / D
        ox, oy = d.origin()
        L, T, R, B = ic[0] + ox, ic[1] + oy, ic[2] + ox, ic[3] + oy
        bb = bd[3] + oy
        fl = self.nearest_floor((L + R) / 2)
        mode = "side"
        if abs(nx) < 0.55:
            if ny < 0 and fl and bb + 10 * U <= fl.y:
                mode = "up"
            elif ny > 0:
                mode = "down"
        if mode == "side":
            spot = (L - 8 * U if nx >= 0 else R + 8 * U, B - 2)
        elif mode == "up":
            spot = ((L + R) / 2, bb + 10 * U)
        else:
            spot = ((L + R) / 2, T)
        job = dict(idx=idx, mode=mode, nx=nx, ny=ny, D=D, bx=pos[0], by=pos[1], spot=spot,
                   dur=D / (speed * U), quick=quick, after=after, last=0.0, done=False)
        d.remember(idx, pos)
        self.start_jump(spot[0], spot[1], None, far=True, after=lambda: self.run_push(job))

    def run_push(self, job):
        self.state, self.t, self.pu = "push", 0.0, job
        self.plat = None
        self.face = sgn(job["nx"])

    def st_push(self, dt):
        pu, U = self.pu, self.U
        wind = 0.3
        if self.t < wind:
            return
        k = (self.t - wind) / pu["dur"]
        if k < 1:
            e = k * k * (3 - 2 * k)
            dist = pu["D"] * e
            ip = (int(round(pu["bx"] + pu["nx"] * dist)), int(round(pu["by"] + pu["ny"] * dist)))
            if ip != pu.get("ip"):                 # не ждём explorer на каждом кадре
                pu["ip"] = ip
                self.desk.post_pos(pu["idx"], ip[0], ip[1])
            self.x = pu["spot"][0] + pu["nx"] * dist
            self.y = pu["spot"][1] + pu["ny"] * dist
            self.phase += abs(dist - pu["last"]) / (3 * U)
            pu["last"] = dist
            return
        rest = 0.15 if pu["quick"] else 0.6
        if self.t < wind + pu["dur"] + rest:       # отдышался
            if not pu["done"]:
                pu["done"] = True
                self.desk.ensure_free()
                fx, fy = pu["bx"] + pu["nx"] * pu["D"], pu["by"] + pu["ny"] * pu["D"]
                self.desk.post_pos(pu["idx"], fx, fy)  # последним в очереди explorer тоже будет конечное место
                self.desk.set_pos(pu["idx"], fx, fy)
                now = self.desk.item_pos(pu["idx"])
                if now and abs(now[0] - pu["bx"]) < 2 and abs(now[1] - pu["by"]) < 2 and pu["D"] > 8:
                    self.push_enabled = False
                    self.build = None
                    pu["after"] = None
                    self.notify("Иконки не двигаются. Выключите на рабочем столе: ПКМ → Вид → "
                                "«Автоматическое расположение значков», потом включите двигание иконок в меню.")
            return
        self.last_push = time.time()
        cb = pu["after"]
        if cb:
            cb()
        else:
            self.refresh_platforms(True)
            self.start_fall()

    # ───────────── строим домик ─────────────
    def act_build(self, force=False):
        d, U = self.desk, self.U
        icons = list(self.icon_plats)
        if not (d.ok and (self.push_enabled or force) and len(icons) >= 3):
            if force:
                self.speak_short("Для домика нужно хотя бы 3 иконки на виду")
            return self.start_idle()
        self.last_build = time.time()
        cw, ch = d.spacing()
        scr = self.screen_rects()
        sl, st, sr, sb = min(scr, key=lambda s: max(0, s[0] - self.x, self.x - s[2]))
        tpl = None
        for cells in HOUSES:
            if len(cells) > len(icons):
                continue
            cols, rows = max(c for c, r in cells) + 1, max(r for c, r in cells) + 1
            if rows * ch <= (sb - st) * 0.85 and cols * cw <= (sr - sl) * 0.7:
                tpl = cells
                break
        if not tpl:
            return self.start_idle()
        w, h = (max(c for c, r in tpl) + 1) * cw, (max(r for c, r in tpl) + 1) * ch
        sx = random.uniform(sl + (sr - sl - w) * 0.2, sl + (sr - sl - w) * 0.8)
        sy = sb - h - 4
        ox, oy = d.origin()
        jobs, free = [], icons[:]
        for c, r in sorted(tpl, key=lambda cr: (-cr[1], cr[0])):      # снизу вверх
            gx, gy = sx + c * cw, sy + r * ch
            pick = min(free, key=lambda q: math.hypot(q.rect[0] - gx, q.rect[1] - gy))
            free.remove(pick)
            jobs.append((pick.idx, (int(gx - ox), int(gy - oy)), r))
        self.build = dict(jobs=jobs, k=0, apex=min(jobs, key=lambda j: j[2])[0], force=force)
        self.say_phrase("house_start", 0.6)
        self.build_next()

    def build_next(self):
        b = self.build
        if not b or not (self.push_enabled or b.get("force")):
            self.build = None
            return self.start_fall()
        if b["k"] >= len(b["jobs"]):
            return self.finish_build()
        idx, tgt, _ = b["jobs"][b["k"]]
        b["k"] += 1
        self.start_icon_job(idx, tgt, 16, after=self.build_next, quick=True)

    def finish_build(self):
        apex = self.build["apex"]
        self.build = None
        self.refresh_platforms(True)
        p = self.pmap.get(("icon", apex))
        if p:
            self.say_phrase("house_done", 0.7)
            self.start_jump((p.x1 + p.x2) / 2, p.y, p.key, far=True,
                            after=lambda: self.start_anim("celebrate", 2.0))
        else:
            self.start_fall()

    # ───────────── главный цикл ─────────────
    def tick(self):
        self.dog.beat = time.monotonic()
        now = time.perf_counter()
        dt = min(now - self.last, 0.05)
        self.last = now
        self.dt = dt
        if now - self.t_sys > 2.0:
            self.t_sys = now
            self.system_checks()
        self.poll_events()
        if self.hidden_fs:
            if self.ttt:
                self.ttt_end()
            return
        if now - self.t_win > 0.4:
            self.t_win = now
            if now - self.t_ico > 1.0 and self.state != "push" and not self.build:
                self.scan_icons_async()               # иконку двигаем мы — не опрашиваем
            self.refresh_platforms(False)
            self.ttt_pad_check()
        self.anim += dt
        self.t += dt
        self.land_t = max(0.0, self.land_t - dt)
        self.happy_t = max(0.0, self.happy_t - dt)
        self.talking = max(0.0, self.talking - dt)
        self.mark_t = max(0.0, self.mark_t - dt)
        for h in self.hearts:
            h[1] -= 5 * self.U * dt
            h[2] += dt
        self.hearts = [h for h in self.hearts if h[2] < 1.4]
        for f in self.fx:
            f["x"] += f["vx"] * dt
            f["y"] += f["vy"] * dt
            f["age"] += dt
        self.fx = [f for f in self.fx if f["age"] < f["life"]]
        self.watch_cursor(dt, now)
        getattr(self, "st_" + self.state)(dt)
        self.update_look(dt)
        self.pose()
        self.move(int(self.x - self.width() / 2), int(self.y - self.height()))
        if self.ai:
            self.ai.follow()
        self.update()

    def watch_cursor(self, dt, now):
        c, U = QCursor.pos(), self.U
        v = math.hypot(c.x() - self.cur_prev[0], c.y() - self.cur_prev[1]) / max(dt, 1e-3)
        self.cur_prev = (c.x(), c.y())
        dx, dy = c.x() - self.x, c.y() - (self.y - 5 * U)
        self.cur_d = math.hypot(dx, dy)
        calm = self.state in ("idle", "walk") and self.plat is not None
        if (calm and self.cur_d < 14 * U and v > 4500 and now - self.t_startle > 45 and
                self.cfg.value("shy", True, type=bool) and random.random() < 0.5):
            self.t_startle = now
            return self.startle(-sgn(dx))
        self.dwell = self.dwell + dt if (self.cur_d < 16 * U and v < 80) else 0.0
        self.cur_still = self.cur_still + dt if v < 25 else 0.0
        if self.dwell > 1.6 and self.state == "idle" and now - self.t_greet > 25:
            self.t_greet, self.dwell = now, 0.0
            self.face = sgn(dx)
            self.start_anim("wave", 1.8)
            return
        # курсор замер прямо над головой — присесть и прыгнуть на него (редко, по-котячьи)
        if (calm and self.state == "idle" and abs(dx) < 22 * U and -30 * U < dy < -9 * U and self.cur_still > 1.2
                and now - self.last_pounce > 90 and not self.chat_busy_ui() and random.random() < dt * 0.4):
            self.last_pounce = now
            self.face = sgn(dx)
            self.start_anim("crouch", ANIMS["crouch"], after=self.pounce)

    def pounce(self):
        c, U = QCursor.pos(), self.U
        tx, ty = c.x(), c.y() + 9 * U
        if math.hypot(tx - self.x, ty - self.y) > 45 * U or self.plat is None:
            return self.start_idle()
        self.start_jump(tx, ty, None, h=3 * U, T=0.42, crouch=0.05, after=self.pounce_land)

    def pounce_land(self):
        c, U = QCursor.pos(), self.U
        if abs(c.x() - self.x) < 8 * U and abs(c.y() - (self.y - 5 * U)) < 8 * U:
            self.say_phrase("pounce", 0.7)
            self.happy_t = 1.2
            self.hearts.append([0.0, -11 * U, 0.0])
        else:
            self.emote("?", 1.0)
        self.start_fall()

    def update_look(self, dt):
        """Глаза следят за курсором, когда он рядом; иначе смотрят по ходу движения."""
        U = self.U
        if self.look_ovr is not None:
            tgt = self.look_ovr
        elif self.state in ("sleep",):
            tgt = (0, 0)
        else:
            c = QCursor.pos()
            dx, dy = c.x() - self.x, c.y() - (self.y - 7 * U)
            if math.hypot(dx, dy) < 70 * U:
                tgt = (clamp(dx / (14 * U), -1, 1), clamp(dy / (10 * U), -1, 1))
            elif self.state in ("walk", "jump"):
                tgt = (self.face * 0.8, 0)
            else:
                tgt = (0, 0)
        k = 1 - math.exp(-14 * dt)
        self.lk[0] += (tgt[0] - self.lk[0]) * k
        self.lk[1] += (tgt[1] - self.lk[1]) * k

    def fix_z(self):
        """Питомец — поверх всех окон; слой с рисунками — прямо над обоями, под всеми окнами."""
        if not IS_WIN:
            return
        flags = 0x13                                   # NOSIZE | NOMOVE | NOACTIVATE
        user32.SetWindowPos(self.own, wintypes.HWND(-1), 0, 0, 0, 0, flags)
        if not self.layer.isVisible():
            return
        lay = int(self.layer.winId())
        host = desktop_host()
        if not host:
            return
        above = user32.GetWindow(host, 3)              # окно прямо над рабочим столом
        if above == lay:
            return
        if not above or user32.GetWindowLongW(above, -20) & 0x8:
            user32.SetWindowPos(lay, wintypes.HWND(-2), 0, 0, 0, 0, flags)   # обычных окон нет вовсе
        else:
            user32.SetWindowPos(lay, above, 0, 0, 0, 0, flags)               # встать сразу под ним

    def system_checks(self):
        key = tuple(self.screen_rects())
        if key != self.scr_key:
            self.scr_key = key
            self.layer.fit()
        modal = QApplication.activeModalWidget()      # открытое окно-вопрос блокирует клики по крабу
        if modal is None:
            self.t_modal = None
        elif self.t_modal is None:
            self.t_modal = time.monotonic()
        elif self.t_modal > 0 and time.monotonic() - self.t_modal > 30:
            self.t_modal = -1.0
            log_error("Открыто окно «%s» — пока оно не закрыто, краб не реагирует на мышь" % modal.windowTitle(),
                      "видно: %s, место: %s" % (modal.isVisible(), modal.geometry().getRect()))
            modal.raise_()
            modal.activateWindow()
        if not IS_WIN:
            return
        if self.notif_enabled:
            self.notif.poll_async()
        try:
            for ev in self.sysmon.poll():
                self.on_sys(ev)
        except Exception:
            log_error("Ошибка в реакции на систему", traceback.format_exc())
        self.fix_z()
        fs, why = self.fullscreen_app()
        if fs and not self.hidden_fs:
            self.hidden_fs = True
            log_error("Прячусь: полноэкранное окно", why)
            self.hide()
            if self.ai:
                self.ai.hide_all()
        elif not fs and self.hidden_fs:
            self.hidden_fs = False
            self.show()
            self.fix_z()

    def fullscreen_app(self):
        """Прятаться только от настоящей полноэкранной игры/видео на ТОМ ЖЕ мониторе, где сидит краб.
        Свои окна (слой с рисунками, облачко, чат), рабочий стол и панель задач не считаются."""
        st = ctypes.c_int(0)
        if shell32.SHQueryUserNotificationState(ctypes.byref(st)) != 0 or st.value not in (2, 3, 4):
            return False, ""
        fg = user32.GetForegroundWindow()
        if not fg:
            return False, ""
        pid = DWORD(0)
        user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        if pid.value == os.getpid():
            return False, ""
        cls = w_class(fg)
        if cls in SKIP_CLASSES:
            return False, ""
        l, t, r, b = w_frame(fg)
        for g in (s.geometry() for s in QGuiApplication.screens()):
            sl, st_, sr, sb = g.left(), g.top(), g.left() + g.width(), g.top() + g.height()
            if sl <= self.x < sr and st_ <= self.y - 1 <= sb:
                covers = l <= sl and t <= st_ and r >= sr and b >= sb
                return covers, "состояние %d, окно %s (%s) %s" % (st.value, cls, exe_of(fg), (l, t, r, b))
        return False, ""

    # ───────────── состояния ─────────────
    def st_idle(self, dt):
        if self.follow() and self.t >= self.idle_dur:
            self.think()

    def st_sleep(self, dt):
        self.energy = min(1.0, self.energy + dt / 35)
        if self.follow() and self.t >= self.dur:
            self.wake_up()

    def st_walk(self, dt):
        if not self.follow():
            return
        d, step = self.tx - self.x, self.speed * dt
        self.phase += step / (3 * self.U)
        if abs(d) <= step:
            self.x = self.tx
            self.finish()
        else:
            self.x += math.copysign(step, d)
            self.face = (-1 if self.moon else 1) * (1 if d > 0 else -1)

    def st_anim(self, dt):
        if not self.follow():
            return
        n, t, U, d = self.an, self.t, self.U, self.dur
        self.fx_acc += dt
        if n in ("dance", "whistle") and self.fx_acc > 0.3:
            self.fx_acc = 0
            self.add_fx("note", random.uniform(-7, 7) * U, -11 * U, random.uniform(-1, 1) * U, -4 * U, 1.3)
        elif n == "flex" and self.fx_acc > 0.22:
            self.fx_acc = 0
            self.add_fx("spark", random.uniform(-9, 9) * U, random.uniform(-12, -3) * U, 0, -1 * U, 0.6)
        elif n == "dizzy" and self.fx_acc > 0.12:
            self.fx_acc = 0
            a = self.anim * 5
            self.add_fx("star", 5 * U * math.cos(a), -11 * U + 1.2 * U * math.sin(a), 0, 0, 0.5)
        elif n == "shiver" and self.fx_acc > 0.35:
            self.fx_acc = 0
            self.add_fx("sweat", random.choice((-1, 1)) * 5 * U, -9 * U, 0, 2 * U, 0.7)
        elif n == "sneeze" and not self.sneezed and t >= 0.55 * d:
            self.sneezed = True
            self.emote("Апчхи!", 1.0)
            for _ in range(10):
                self.add_fx("dot", self.face * 2 * U, -6 * U, self.face * random.uniform(8, 22) * U,
                            random.uniform(-6, 3) * U, 0.5)
        elif n == "laptop":
            if random.random() < dt * 1.5:
                self.add_fx("txt", self.face * random.uniform(10, 14) * U, -8 * U, random.uniform(-1, 1) * U, -4 * U,
                            1.1, txt=random.choice(("{ }", "</>", ";", "()", "=>", "#")), col=(70, 200, 120))
            if not self.aflag and t > d * 0.75:
                self.aflag = True
                self.emote(random.choice(("!", "✓", "?")), 1.2)
            self.look_ovr = (0.9 * self.face, 0.5)
        elif n == "read":
            self.look_ovr = (0.35 * math.sin(self.anim * 0.9), 0.7)
        elif n == "celebrate" and random.random() < dt * 9:
            self.add_fx("spark", random.uniform(-9, 9) * U, random.uniform(-17, -8) * U, 0, -2 * U, 0.6)
        elif n == "hiccup" and int(t / 0.8) != int((t - self.dt) / 0.8):
            self.emote("ик!", 0.5)
        elif n in ("hot", "heavy") and self.fx_acc > 0.4:
            self.fx_acc = 0
            self.add_fx("sweat", self.face * 6 * U, -11 * U, self.face * 1.5 * U, 4 * U, 0.8)
        elif n == "crouch":
            c = QCursor.pos()
            self.look_ovr = (clamp((c.x() - self.x) / (14 * U), -1, 1), -1)
        elif n == "lookaround":
            self.look_ovr = ((-1, 0) if t < 0.8 else (1, 0) if t < 1.6 else (0, -1) if t < 2.2 else (0, 0))
        elif n == "scratch":
            self.look_ovr = (self.face * 0.6, -0.5)
        if t >= d:
            self.look_ovr = None
            self.finish()

    def st_jump(self, dt):
        j = self.j
        if self.t < j["crouch"]:
            return
        u = (self.t - j["crouch"]) / j["T"]
        if u >= 1:
            self.x, self.y = j["x1"], j["y1"]
            p = self.pmap.get(j["key"]) if j["key"] else None
            self.plat = p
            if p:
                self.y = p.y
                if p.x2 - p.x1 > 2 * p.m:
                    self.x = clamp(self.x, p.x1 + p.m, p.x2 - p.m)
            self.land_t = 0.18
            self.finish()
            return
        self.ju = u
        self.x = j["x0"] + (j["x1"] - j["x0"]) * u
        self.y = j["y0"] + (j["y1"] - j["y0"]) * u - 4 * j["h"] * u * (1 - u)

    def st_fall(self, dt):
        U = self.U
        self.vy = min(self.vy + 380 * U * dt, 260 * U)
        nx, ny = self.x + self.vx * dt, self.y + self.vy * dt
        scr = self.screen_rects()
        vl, vr = min(s[0] for s in scr), max(s[2] for s in scr)
        if nx < vl + 4 * U:
            nx, self.vx = vl + 4 * U, abs(self.vx) * 0.5
        elif nx > vr - 4 * U:
            nx, self.vx = vr - 4 * U, -abs(self.vx) * 0.5
        if self.vy > 0:
            best = None
            for p in self.platforms:
                if p.x1 <= nx <= p.x2 and self.y - 1 <= p.y <= ny and (best is None or p.y < best.y):
                    best = p
            if best:
                if best.x2 - best.x1 > 2 * best.m:
                    nx = clamp(nx, best.x1 + best.m, best.x2 - best.m)
                self.land_t = 0.2
                hard = self.vy > 220 * U
                self.x, self.y, self.plat, self.vx, self.vy = nx, best.y, best, 0.0, 0.0
                if self.dizzy:
                    self.dizzy = False
                    self.start_anim("dizzy", 2.4)
                    self.say_phrase("dizzy", 0.6)
                else:
                    self.start_idle(0.5)
                    if hard:
                        self.say_phrase("land_hard", 0.3)
                return
        self.x, self.y = nx, ny
        if ny > max(s[3] for s in scr) + 300:        # улетел мимо экранов — вернуть на пол
            f = self.nearest_floor(nx)
            if f:
                self.x, self.y, self.plat, self.vy = clamp(nx, f.x1 + f.m, f.x2 - f.m), f.y, f, 0.0
                self.start_idle(0.5)

    def st_drag(self, dt):
        pass

    # ───────────── поза ─────────────
    def walk_legs(self):
        cuts = [0, 0, 0, 0]
        if self.phase % 2 < 1:
            cuts[0] = cuts[2] = 1
        else:
            cuts[1] = cuts[3] = 1
        return cuts, (0.5 if self.phase % 1 < 0.5 else 0.0)

    def pose(self):
        s, a, t = self.state, self.anim, self.t
        L, cuts, legdx, al, ar = 0.0, [0, 0, 0, 0], [0, 0, 0, 0], (0, 0), (0, 0)
        hide, bdx, eye, mouth, sx, sy, rot = 0, 0.0, "open", 0, 1.0, 1.0, 0.0
        if s == "idle":
            k = math.sin(a * 2.2) * 0.015
            sx, sy = 1 - k, 1 + k
            if a % 3.7 < 0.11:
                eye = "closed"
            elif self.cur_d < 14 * self.U:
                eye = "wide"
        elif s == "walk":
            cuts, L = self.walk_legs()
            if a % 3.7 < 0.11:
                eye = "closed"
        elif s == "jump":
            j = self.j
            if self.t < j["crouch"]:
                sx, sy = 1.15, 0.8
            else:
                u = self.ju
                L, cuts = 1.0, ([2] * 4 if u < 0.5 else [1] * 4)
                al = ar = (-2, 0)
                st = 0.18 * abs(1 - 2 * u)
                sx, sy = 1 - st * 0.6, 1 + st
                if j["spin"]:
                    rot = j["spin"] * (u * u * (3 - 2 * u))
                    eye = "chev"
                if j["jacks"]:
                    legdx = [-1.2, -0.6, 0.6, 1.2]
                    al, ar = (-3, 1), (-3, 1)
                    eye = "chev"
        elif s in ("fall", "drag"):
            n = int(a * 12)
            cuts = [(n + i) % 2 for i in range(4)]
            al = ar = (-2, 0)
            eye = "wide"
            sx, sy = 0.93, 1.1
        elif s == "push":
            pu = self.pu
            cuts, L = self.walk_legs()
            eye = "chev"
            if pu["mode"] == "side":
                bdx = sgn(pu["nx"]) * (0.5 + 0.5 * math.sin(a * 14))
                if pu["nx"] >= 0:
                    ar = (0, 1)
                else:
                    al = (0, 1)
            elif pu["mode"] == "up":
                al = ar = (-2, 0)
                sy = 1 + 0.03 * math.sin(a * 14)
            else:
                al = ar = (1, 0)
                L = 1.0 if math.sin(a * 12) > 0 else 0.0
                cuts = [1] * 4 if L else [0] * 4
        elif s == "sleep":
            eye, cuts = "closed", [1] * 4
            k = math.sin(a * 1.6) * 0.02
            sx, sy = 1.05 - k, 0.9 + k
        elif s == "draw":
            dw = self.dw or {}
            if dw.get("moving"):
                cuts, L = self.walk_legs()
            if a % 3.7 < 0.11:
                eye = "closed"
            hide = dw.get("dir", 0)
            tip = dw.get("cur")
            if tip:                                   # тянется вверх к высоким частям рисунка
                k = clamp((self.y - 9 * self.U - tip[1]) / (10 * self.U), 0.0, 1.0)
                sy, sx = 1 + 0.12 * k, 1 - 0.04 * k
            if 0 < self.t < 0.5:
                eye = "chev" if self.t < 0.25 else eye
        elif s == "anim":
            (L, cuts, legdx, al, ar, hide, bdx, eye, mouth, sx, sy, rot) = self.pose_anim(t, a)
        if self.land_t > 0:
            k = self.land_t / 0.18
            sx, sy = sx * (1 + 0.25 * k), sy * (1 - 0.25 * k)
            if k > 0.3:
                eye = "chev"
        if self.happy_t > 0 and s in ("idle", "walk"):
            eye = "happy"
            wave = int(a * 8) % 2
            al, ar = (-2 if wave else 0, 0), (0 if wave else -2, 0)
        if self.talking > 0 and mouth == 0 and s != "sleep":
            mouth = 1 + int(a * 9) % 2
        # плавные переходы: непрерывные параметры позы догоняют цель, а не прыгают
        sm, k = self.sm, 1 - math.exp(-18 * self.dt)
        snap = s == "jump" and self.j.get("spin")
        for name, val in (("L", L), ("bdx", bdx), ("sx", sx), ("sy", sy), ("a0", al[0]), ("a1", al[1]),
                          ("b0", ar[0]), ("b1", ar[1])):
            sm[name] += (val - sm[name]) * k
        if snap or s in ("drag", "fall"):
            sm["rot"] = rot
        else:
            sm["rot"] += (rot - sm["rot"]) * min(1.0, k * 1.3)
        self.L, self.cuts, self.legdx = sm["L"], cuts, legdx
        self.al, self.ar = (sm["a0"], sm["a1"]), (sm["b0"], sm["b1"])
        self.hide_arm, self.bdx, self.eye, self.mouth = hide, sm["bdx"], eye, mouth
        self.prop = self.an if s == "anim" and self.an in SITTING else None
        self.sx, self.sy, self.rot = sm["sx"], sm["sy"], sm["rot"]

    def pose_anim(self, t, a):
        n, d, f = self.an, self.dur, self.face
        u = min(t / d, 1.0)
        L, cuts, legdx, al, ar, hide, bdx, eye, mouth, sx, sy, rot = 0.0, [0] * 4, [0] * 4, (0, 0), (0, 0), 0, 0.0, "open", 0, 1.0, 1.0, 0.0
        if n == "wave":
            w = -4.6 + 1.1 * math.sin(t * 14)
            if f > 0:
                ar = (w, 0)
            else:
                al = (w, 0)
            L = 0.5 * abs(math.sin(t * 8))
            eye = "happy"
        elif n == "dance":
            b = int(t * 6) % 2
            cuts = [b, 1 - b, b, 1 - b]
            L = 0.5 * (1 - b)
            al, ar = (-2 if b else 0, 0), (0 if b else -2, 0)
            bdx, rot = 0.6 * math.sin(t * 6), 5 * math.sin(t * 6)
            sx = 1 + 0.04 * math.sin(t * 12)
            eye = "chev"
        elif n == "stretch":
            k = min(u / 0.35, 1.0) if u < 0.65 else max(0.0, 1 - (u - 0.65) / 0.1)
            al = ar = (-3, 0) if k > 0.1 else (0, 0)
            sy, sx = 1 + 0.12 * k, 1 - 0.05 * k
            eye = "closed"
            mouth = 2 if 0.15 < u < 0.6 else 0
            if u > 0.75:
                bdx, eye = 0.4 * math.sin(t * 40) * (1 - u) * 4, "open"
        elif n == "scratch":
            w = -3 + 0.5 * math.sin(t * 30)
            if f > 0:
                ar = (w, 0)
            else:
                al = (w, 0)
            rot, eye = -5 * f, "half"
        elif n == "lookaround":
            cuts = [1] * 4
            sy = 0.96 + 0.01 * math.sin(a * 3)
        elif n == "tap":
            cuts[1] = int(t * 8) % 2
            eye, rot = "half", -3
        elif n == "sneeze":
            if u < 0.55:
                k = u / 0.55
                sy, L, eye, mouth, bdx = 1 + 0.1 * k, 0.5 * k, "closed", 1 + (k > 0.6), -0.6 * f * k
            else:
                k = 1 - (u - 0.55) / 0.45
                sx, sy, eye, mouth = 1 + 0.25 * k, 1 - 0.2 * k, "chev", 2
        elif n == "flex":
            e = int(t * 5) % 2
            al = ar = (-2, e)
            sy = 1 + 0.04 * e
            eye = "chev"
        elif n == "whistle":
            eye, mouth = "open", 1
            bdx = 0.3 * math.sin(t * 5)
            L = 0.5 if math.sin(t * 5) > 0.5 else 0.0
        elif n == "shiver":
            bdx, eye, sy = 0.4 * math.sin(t * 50), "wide", 0.97
        elif n == "dizzy":
            bdx, rot, eye = 0.9 * math.sin(t * 3), 8 * math.sin(t * 3), "x"
        elif n == "bow":
            rot = 25 * f * math.sin(u * math.pi)
            eye = "closed"
        elif n == "pant":                              # отдышка после игры
            k = 0.5 + 0.5 * math.sin(t * 11)
            sy, sx = 0.96 + 0.05 * k, 1.02 - 0.02 * k
            mouth, eye = 2 if k > 0.5 else 1, "half"
            al = ar = (1, 0)
        elif n == "flinch":                            # вздрогнул
            k = math.sin(min(u, 1) * math.pi)
            sx, sy, eye = 1 - 0.08 * k, 1 + 0.1 * k, "wide"
            al = ar = (-2 * k, 0)
            bdx = -0.5 * f * k
        elif n == "admire":                            # любуется своим рисунком
            rot = -4 * f * math.sin(u * math.pi)
            eye = "happy" if u > 0.5 else "open"
            if u > 0.55:
                if f > 0:
                    ar = (-2, 0)
                else:
                    al = (-2, 0)
        elif n == "shrug":
            k = math.sin(min(u, 1) * math.pi)
            al = ar = (-1.5 * k, 0)
            sy, eye, mouth = 1 - 0.04 * k, "half", 1 if k > 0.5 else 0
        elif n == "laptop":                            # сидит и стучит по клавишам своего ноутбука
            L = -2.0
            tap = int(a * 9) % 2
            arm = (0.6 * tap, 1.6)
            if f > 0:
                ar, al = arm, (1, 0)
            else:
                al, ar = arm, (1, 0)
            sx = 1 + 0.01 * math.sin(a * 2)
            eye = "half"
            if self.mark_t > 0 and self.mark == "✓":
                eye, mouth = "happy", 1
            elif self.mark_t > 0 and self.mark == "!":
                eye = "wide"
        elif n == "read":                              # сидит с книжкой
            L = -2.0
            al = ar = (1.6, -0.6)
            eye = "half" if d - t > 1 else "open"
        elif n == "celebrate":                         # прыгает от радости, лапки вверх
            ph = (t % 0.5) / 0.5
            L = 2.5 * math.sin(ph * math.pi)
            al = ar = (-3.5, 0)
            eye, mouth = "happy", 2
        elif n == "yawn":
            up = min(1.0, u * 2.2) * (1 - max(0.0, min(1.0, (u - 0.75) * 4)))
            al = ar = (-3 * up, 0)
            sy = 1 + 0.08 * up
            eye = "closed"
            mouth = 2 if 0.2 < u < 0.75 else (1 if u < 0.85 else 0)
        elif n == "hiccup":
            ph = (t % 0.8) / 0.8
            if ph < 0.18:
                L, eye = 1.5 * math.sin(ph / 0.18 * math.pi), "wide"
        elif n == "hot":                               # жарко: обмахивается лапкой
            fan = int(a * 10) % 2
            if f > 0:
                ar = (-2.5 + fan, 1)
            else:
                al = (-2.5 + fan, 1)
            eye, mouth = "half", 2 if int(a * 2) % 2 else 1
            sy = 0.96 + 0.02 * math.sin(a * 3)
        elif n == "heavy":                             # тяжело: еле держит
            sx, sy = 1.16 + 0.03 * math.sin(a * 30), 0.8
            bdx = 0.25 * math.sin(a * 40)
            al = ar = (-3, 0)
            eye, mouth = "chev", 1
        elif n == "crouch":                            # приготовился прыгнуть на курсор
            sx, sy = 1.12, 0.84
            bdx = 0.35 * math.sin(a * 22)
            eye, cuts = "wide", [1] * 4
        return L, cuts, legdx, al, ar, hide, bdx, eye, mouth, sx, sy, rot

    # ───────────── рисование ─────────────
    def sprite(self):
        """Тело краба в отдельной картинке: прямоугольники выровнены по целым пикселям,
        поэтому при наклоне и сжатии нет щелей и «рваных» краёв."""
        U = self.U
        iw, ih, ax, ay = 26 * U, 24 * U, 13 * U, 20 * U        # якорь (ax, ay) = точка (8, 10) спрайта
        img = getattr(self, "_img", None)
        if img is None or img.width() != iw:
            img = self._img = QImage(iw, ih, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)

        def R(x, y, w, h, c=BODY):
            x0, y0 = round((x - 8) * U + ax), round((y - 10) * U + ay)
            x1, y1 = round((x - 8 + w) * U + ax), round((y - 10 + h) * U + ay)
            if x1 > x0 and y1 > y0:
                p.fillRect(QRect(x0, y0, x1 - x0, y1 - y0), c)

        L, bdx = self.L, self.bdx
        for i, lx in enumerate(LEG_X):
            ln = 2 + L - self.cuts[i]
            if ln > 0.05:
                R(lx + self.legdx[i], 8 - L, 1, ln)
        R(2 + bdx, -L, 12, 8)
        if self.prop == "read":                        # книжка в лапках
            R(3.4 + bdx, 3.7 - L, 9.2, 4.3, QColor(52, 96, 190))
            R(3.4 + bdx, 3.7 - L, 9.2, 0.6, QColor(250, 248, 240))
            R(7.8 + bdx, 3.7 - L, 0.4, 4.3, QColor(30, 60, 130))
            ph = (self.anim * 0.7) % 3
            if ph < 0.3:                               # перелистывает страницу
                R(8.2 + bdx, 3.1 - L, 3.6 * (1 - ph / 0.3), 0.6, QColor(250, 248, 240))
        if self.hide_arm != -1:
            R(0 + bdx - self.al[1], 4 - L + self.al[0], 2 + self.al[1], 2)
        if self.hide_arm != 1:
            R(14 + bdx, 4 - L + self.ar[0], 2 + self.ar[1], 2)
        lx = round(self.lk[0] * 2) / 2
        ly = round(self.lk[1] * 2) / 2
        e = self.eye
        if e in ("open", "wide", "half"):
            h = {"open": 2, "wide": 3, "half": 1}[e]
            y0 = {"open": 2, "wide": 1.5, "half": 2.6}[e]
            for x in (4, 11):
                R(x + lx + bdx, y0 - L + ly * 0.8, 1, h, DARK)
        elif e == "closed":
            for x in (4, 11):
                R(x - 0.5 + bdx, 3.1 - L, 2, 0.6, DARK)
        else:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pen = QPen(DARK, 0.75 * U)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            cy = 3 - L
            for cx, sg in ((4.5 + bdx, 1), (11.5 + bdx, -1)):
                path = QPainterPath()
                if e == "chev":                      # «> <»
                    path.moveTo((cx - sg * 0.8 - 8) * U + ax, (cy - 1.1 - 10) * U + ay)
                    path.lineTo((cx + sg * 0.8 - 8) * U + ax, (cy - 10) * U + ay)
                    path.lineTo((cx - sg * 0.8 - 8) * U + ax, (cy + 1.1 - 10) * U + ay)
                elif e == "happy":                   # «^ ^» — довольные глазки
                    path.moveTo((cx - 0.95 - 8) * U + ax, (cy + 0.6 - 10) * U + ay)
                    path.lineTo((cx - 8) * U + ax, (cy - 0.6 - 10) * U + ay)
                    path.lineTo((cx + 0.95 - 8) * U + ax, (cy + 0.6 - 10) * U + ay)
                else:                                # «x x»
                    for q in (1, -1):
                        path.moveTo((cx - 0.9 - 8) * U + ax, (cy - q * 1.0 - 10) * U + ay)
                        path.lineTo((cx + 0.9 - 8) * U + ax, (cy + q * 1.0 - 10) * U + ay)
                p.drawPath(path)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        if self.mouth:
            if self.mouth == 1:
                R(7 + bdx, 5.2 - L, 2, 0.9, DARK)
            else:
                R(6.5 + bdx, 4.8 - L, 3, 2, DARK)
        p.end()
        return img, ax, ay

    def paintEvent(self, ev):
        p = QPainter(self)
        U, W, H = self.U, self.width(), self.height()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.state not in ("fall", "drag", "jump"):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 50))
            sw = 14 * U * clamp(self.sx, 0.8, 1.3)
            p.drawEllipse(QRectF(W / 2 - sw / 2, H - U, sw, U))
        img, ax, ay = self.sprite()
        p.translate(W / 2, H)
        if abs(self.rot) > 0.05:
            p.translate(0, -5 * U)
            p.rotate(self.rot)
            p.translate(0, 5 * U)
        if abs(self.sx - 1) > 0.003 or abs(self.sy - 1) > 0.003:
            p.scale(self.sx, self.sy)
        smooth = abs(self.rot) > 0.05 or abs(self.sx - 1) > 0.003 or abs(self.sy - 1) > 0.003
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
        p.drawImage(QPointF(-ax, -ay), img)
        p.resetTransform()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        if self.prop == "laptop":
            self.paint_laptop(p, W, H)

        p.translate(W / 2, H)
        if self.pencil:                               # рука с карандашом
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            tx, ty = self.pencil[0] - self.x, self.pencil[1] - self.y
            d = self.dw["dir"] if self.dw else 1
            sh = (d * 6 * U, -5 * U)
            ln = max(math.hypot(tx - sh[0], ty - sh[1]), 1.0)
            ux, uy = (tx - sh[0]) / ln, (ty - sh[1]) / ln
            hl = max(0.0, ln - 4 * U)
            hand = (sh[0] + ux * hl, sh[1] + uy * hl)
            pen = QPen(BODY, 1.9 * U)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            p.drawLine(QPointF(*sh), QPointF(*hand))
            p.save()
            p.translate(tx, ty)
            p.rotate(math.degrees(math.atan2(uy, ux)))
            p.setPen(Qt.PenStyle.NoPen)
            p.fillRect(QRectF(-5.6 * U, -0.55 * U, 0.7 * U, 1.1 * U), QColor(232, 120, 138))     # ластик
            p.fillRect(QRectF(-4.9 * U, -0.55 * U, 3.9 * U, 1.1 * U), self.pencil_col or QColor(242, 193, 78))
            p.fillRect(QRectF(-1.0 * U, -0.55 * U, 0.7 * U, 1.1 * U), QColor(235, 215, 180))     # дерево
            p.fillRect(QRectF(-0.3 * U, -0.3 * U, 0.4 * U, 0.6 * U), QColor(40, 40, 45))         # грифель
            p.restore()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for f in self.fx:                             # значки-эффекты
            if f["k"] == "txt":                       # «{ }», «</>» над ноутбуком
                c = QColor(*(f["col"] or (60, 60, 70)))
                c.setAlphaF(clamp(1.6 * (1 - f["age"] / f["life"]), 0, 1))
                fnt = QFont("Consolas")
                fnt.setPixelSize(int(2.2 * U))
                fnt.setBold(True)
                p.setFont(fnt)
                sh = QColor(255, 255, 255, int(200 * c.alphaF()))
                p.setPen(sh)
                p.drawText(QPointF(f["x"] + 1, f["y"] + 1), f["txt"])
                p.setPen(c)
                p.drawText(QPointF(f["x"], f["y"]), f["txt"])
                continue
            rows, col = PATTERNS[f["k"]]
            c = QColor(*col)
            c.setAlphaF(clamp(2.2 * (1 - f["age"] / f["life"]), 0, 1))
            sc = U * (0.9 if f["k"] in ("excl", "spark", "star") else 0.6 if f["k"] != "dot" else 0.5)
            for ry, row in enumerate(rows):
                for rx, ch in enumerate(row):
                    if ch == "X":
                        p.fillRect(QRectF(f["x"] + rx * sc, f["y"] + ry * sc, sc, sc), c)
        p.resetTransform()
        heart = ("01010", "11111", "11111", "01110", "00100")
        for dx, dy, age in self.hearts:
            if age < 0:
                continue
            c = QColor(PINK)
            c.setAlphaF(clamp(1.4 - age, 0, 1))
            for ry, row in enumerate(heart):
                for rx, ch in enumerate(row):
                    if ch == "1":
                        p.fillRect(QRectF(W / 2 + dx + rx * U * 0.55, H + dy + ry * U * 0.55, U * 0.56, U * 0.56), c)
        if self.mark_t > 0 and self.mark:             # значок над головой: «!», «?», «✓», «ик!»
            pop = min(1.0, (1.4 - self.mark_t) * 8) if self.mark_t < 1.4 else 1.0
            fm = QFont("Segoe UI")
            fm.setBold(True)
            fm.setPixelSize(max(8, int(3.0 * U * (0.6 + 0.4 * pop))))
            p.setFont(fm)
            tw = QFontMetrics(fm).horizontalAdvance(self.mark)
            mx, my = W / 2 - tw / 2, H - (13.5 + max(0.0, self.L)) * U
            p.setPen(QColor(40, 30, 28))
            for ddx, ddy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                p.drawText(QPointF(mx + ddx, my + ddy), self.mark)
            p.setPen(QColor(255, 255, 255))
            p.drawText(QPointF(mx, my), self.mark)
        if self.state == "sleep":
            fnt = QFont("Consolas")
            fnt.setPixelSize(int(2.4 * U))
            fnt.setBold(True)
            p.setFont(fnt)
            for k in range(3):
                ph = (self.anim * 0.6 + k / 3) % 1
                zx, zy = W / 2 + 4 * U + ph * 4 * U, H - 10 * U - ph * 6 * U
                p.setPen(QColor(0, 0, 0, int(160 * (1 - ph))))
                p.drawText(int(zx + 1), int(zy + 1), "z")
                p.setPen(QColor(255, 255, 255, int(255 * (1 - ph))))
                p.drawText(int(zx), int(zy), "z")
        p.end()

    def paint_laptop(self, p, W, H):
        """Маленький ноутбук перед крабом (со стороны, куда он смотрит)."""
        U, f = self.U, self.face
        X = lambda x: W / 2 + f * (x - 8) * U          # координаты спрайта -> окно, зеркально по взгляду
        Y = lambda y: H + (y - 10) * U
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        dark, glow = QColor(70, 72, 82), QColor(140, 220, 255, 220)
        base = QRectF(min(X(16.4), X(23.0)), Y(9.3), abs(X(23.0) - X(16.4)), 0.7 * U)
        p.fillRect(base, dark)
        p.setBrush(dark)
        p.drawPolygon(QPolygonF([QPointF(X(22.2), Y(9.3)), QPointF(X(23.5), Y(4.2)),
                                 QPointF(X(24.3), Y(4.4)), QPointF(X(23.0), Y(9.3))]))
        p.setBrush(glow)
        p.drawPolygon(QPolygonF([QPointF(X(21.75), Y(9.1)), QPointF(X(22.85), Y(4.75)),
                                 QPointF(X(23.25), Y(4.85)), QPointF(X(22.15), Y(9.1))]))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    # ───────────── мышь ─────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.press = e.globalPosition().toPoint()
            self.dragging = False
        elif e.button() == Qt.MouseButton.RightButton:
            self.show_menu(e.globalPosition().toPoint())
        elif e.button() == Qt.MouseButton.MiddleButton:
            self.cmd_chat()

    def mouseMoveEvent(self, e):
        if not (e.buttons() & Qt.MouseButton.LeftButton) or self.press is None:
            return
        gp = e.globalPosition().toPoint()
        if not self.dragging and (gp - self.press).manhattanLength() > 8:
            self.dragging = True
            self.interrupt()
            self.pencil = self.look_ovr = None
            self.last_push = time.time()
            self.state, self.plat, self.samples, self.shake, self.last_svx = "drag", None, [], [], 0.0
        if self.dragging:
            self.x, self.y = gp.x(), gp.y() + 9 * self.U
            now = time.perf_counter()
            self.samples = [s for s in self.samples if now - s[0] < 0.12] + [(now, self.x, self.y)]
            if len(self.samples) >= 2:                # трясут из стороны в сторону — закружится голова
                a, b = self.samples[-2], self.samples[-1]
                svx = (b[1] - a[1]) / max(b[0] - a[0], 1e-3)
                if abs(svx) > 500 and self.last_svx and sgn(svx) != sgn(self.last_svx):
                    self.shake = [t for t in self.shake if now - t < 1.2] + [now]
                    if len(self.shake) >= 4 and not self.dizzy:
                        self.dizzy = True
                        self.emote("@_@", 1.0)
                if abs(svx) > 500:
                    self.last_svx = svx

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if not self.dragging:
            now = time.monotonic()
            if now - self.t_click < 0.45:             # двойной клик не должен открыть и тут же закрыть чат
                return
            self.t_click = now
            if self.ai:                               # клик по крабу — поговорить с ним
                self.hearts.append([random.uniform(-3, 3) * self.U, -11 * self.U, 0.0])
                if self.state == "sleep":
                    self.wake_up()
                    self.say_phrase("wake", 0.5)
                self.ai.toggle_chat()
            elif self.state in ("idle", "walk", "sleep", "anim"):
                self.after, self.plan = None, []
                self.start_happy()
            return
        self.dragging = False
        vx = vy = 0.0
        if len(self.samples) >= 2:
            a, b = self.samples[0], self.samples[-1]
            dt = max(b[0] - a[0], 0.016)
            vx, vy = clamp((b[1] - a[1]) / dt, -2500, 2500), clamp((b[2] - a[2]) / dt, -2500, 2500)
        speed = math.hypot(vx, vy)
        self.dizzy = self.dizzy or speed > 1500
        if speed > 1600:
            self.say_phrase("throw", 0.5)
        if self.platform_below(self.x, self.y) is None:
            f = self.nearest_floor(self.x)
            if f:
                self.start_jump(clamp(self.x, f.x1 + f.m, f.x2 - f.m), f.y, f.key, after=self.start_idle)
                return
        self.start_fall(vx, vy)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.mousePressEvent(e)                   # быстрый второй клик — как обычный клик                                          # двойной клик ничего не делает (клик — открыть чат)


# ═══════════════════════════════ запуск ═══════════════════════════════
def make_icon():
    app = QApplication(sys.argv)
    pm = QPixmap(256, 256)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    u = 14
    ox, oy = 16, 60
    for x, y, w, h in ((2, 0, 12, 8), (0, 4, 2, 2), (14, 4, 2, 2), (3, 8, 1, 2), (5, 8, 1, 2), (10, 8, 1, 2), (12, 8, 1, 2)):
        p.fillRect(ox + x * u, oy + y * u, w * u, h * u, BODY)
    p.fillRect(ox + 4 * u, oy + 2 * u, u, 2 * u, DARK)
    p.fillRect(ox + 11 * u, oy + 2 * u, u, 2 * u, DARK)
    p.end()
    pm.save("icon.ico")


SERVER_NAME = "KlodikSingleton"
OLD_SERVERS = ("ClaudePetSingleton-v3",)          # прежнее имя: его тоже просим закрыться


def take_over(app):
    """Если уже запущена копия v3 — попросить её закрыться (новый запуск = свежая версия).
    Старую v2 так закрыть нельзя: тогда подсказываем, как её выключить."""
    for name in (SERVER_NAME,) + OLD_SERVERS:
        sock = QLocalSocket()
        sock.connectToServer(name)
        if not sock.waitForConnected(400):
            continue
        sock.write(b"quit")
        sock.flush()
        sock.waitForBytesWritten(400)
        sock.disconnectFromServer()
        for _ in range(40):                       # ждём до 4 с, пока старая копия выйдет
            time.sleep(0.1)
            probe = QLocalSocket()
            probe.connectToServer(name)
            if not probe.waitForConnected(100):
                break
            probe.abort()
    if IS_WIN:
        global _mutex
        for _ in range(30):
            _mutex = kernel32.CreateMutexW(None, False, "Local\\KlodikSingleton")
            if ctypes.get_last_error() != 183:
                break
            kernel32.CloseHandle(_mutex)
            time.sleep(0.1)
        else:
            QMessageBox.information(None, "Klodik",
                                    "Уже работает другая копия Klodik (краб в трее у часов).\n"
                                    "Закройте её: правый клик по крабу → «Выход», затем запустите эту снова.")
            return False
    server = QLocalServer(app)
    QLocalServer.removeServer(SERVER_NAME)
    if server.listen(SERVER_NAME):
        def on_conn():
            c = server.nextPendingConnection()
            if c is None:
                return
            c.waitForReadyRead(300)
            if bytes(c.readAll()).startswith(b"quit"):
                QTimer.singleShot(0, app.quit)
        server.newConnection.connect(on_conn)
        app._single = server
    return True


def migrate_old_name(cfg):
    """До v4.4 краб назывался ClaudePet. Один раз переносим его рисунки, память, чаты и настройки на новое имя;
    старые файлы не трогаем (остаются как резервная копия)."""
    try:
        if os.path.isdir(OLD_DATA_DIR) and not os.path.exists(os.path.join(DATA_DIR, ".migrated")):
            os.makedirs(DATA_DIR, exist_ok=True)
            for name in os.listdir(OLD_DATA_DIR):
                src, dst = os.path.join(OLD_DATA_DIR, name), os.path.join(DATA_DIR, name)
                if os.path.exists(dst):
                    continue
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            with open(os.path.join(DATA_DIR, ".migrated"), "w", encoding="utf-8") as f:
                f.write("из %s\n" % OLD_DATA_DIR)
        if not cfg.allKeys():
            old = QSettings(OLD_NAME, OLD_NAME)
            for k in old.allKeys():
                cfg.setValue(k, old.value(k))
            cfg.sync()
        if IS_WIN:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_ALL_ACCESS) as k:
                try:
                    winreg.QueryValueEx(k, OLD_NAME)
                except OSError:
                    return
                winreg.DeleteValue(k, OLD_NAME)          # старый автозапуск указывал на ClaudePet.exe
            if getattr(sys, "frozen", False):
                set_autostart(True)
    except Exception:
        log_error("Перенос настроек со старого имени", traceback.format_exc())


def main():
    if "--make-icon" in sys.argv:
        return make_icon()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Klodik")
    if not take_over(app):
        return
    cfg = QSettings(APP_NAME, APP_NAME)
    migrate_old_name(cfg)
    if IS_WIN and getattr(sys, "frozen", False):
        try:
            if not cfg.value("inited", False, type=bool):
                set_autostart(True)             # по умолчанию — автозапуск включён
                cfg.setValue("inited", True)
            elif autostart_enabled():
                set_autostart(True)             # обновить путь, если exe перенесли
        except OSError:
            pass
    try:
        pet = Pet(cfg)
    except Exception:
        log_error("Питомец не запустился", traceback.format_exc())
        QMessageBox.critical(None, "Klodik", "Не удалось запустить питомца.\nПодробности в файле:\n" + LOG_PATH)
        return
    app.aboutToQuit.connect(pet.shutdown)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
