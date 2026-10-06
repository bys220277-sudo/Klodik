# -*- coding: utf-8 -*-
"""
Klodik — ИИ-часть (v4.4). Фанатский проект, не связан с Anthropic.
  • Чат с Клодиком через локальную LLM (LM Studio, Ollama, llama.cpp, vLLM — любой OpenAI-совместимый сервер).
  • Две модели на выбор: «Основная» (умная) и «Лёгкая» (быстрая), переключаются в чате и в меню краба.
    В памяти видеокарты держится только одна: перед ответом другая выгружается. «Выключить ИИ» выгружает всё.
  • Вложения: текст и код, PDF, DOCX, XLSX, PPTX, картинки; скриншот экрана; перетаскивание файлов в окно.
  • Библиотека промптов и «роль» для отдельного чата.
  • Агент: модель сама ищет в интернете, читает страницы, файлы и папки, ищет файлы, делает скриншот,
    запоминает факты о хозяине, управляет крабом; запись файлов и запуск команд — только с вашего разрешения.
  • «Зрение»: краб смотрит на экран лёгкой моделью, знает названия окон и коротко комментирует в облачке.
Всё уходит только на адрес сервера из настроек; в интернет — только поисковые запросы и страницы агента.
"""
import os, sys, json, re, time, base64, random, threading, ctypes, subprocess, fnmatch, zipfile, html, platform, shutil
import urllib.request, urllib.error
from urllib.parse import urlparse, quote_plus, parse_qs, unquote

from PyQt6.QtCore import (Qt, QTimer, QObject, pyqtSignal, QBuffer, QIODevice, QByteArray, QRect, QRectF,
                          QPoint, QAbstractNativeEventFilter, QUrl)
from PyQt6.QtGui import (QPainter, QColor, QFont, QFontMetrics, QPainterPath, QPen, QGuiApplication, QCursor,
                         QImage, QDesktopServices, QKeySequence, QShortcut, QPalette)
from PyQt6.QtWidgets import (QWidget, QDialog, QFormLayout, QLineEdit, QComboBox, QPlainTextEdit, QCheckBox,
                             QSpinBox, QDoubleSpinBox, QPushButton, QListWidget, QTextBrowser, QSplitter,
                             QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QApplication, QFileDialog, QTabWidget,
                             QToolButton, QMenu, QInputDialog, QButtonGroup, QScrollArea, QFrame)

IS_WIN = sys.platform == "win32"
DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Klodik")

# ═════════════════════ характер ═════════════════════
BACKSTORY = """Тебя зовут Клодик. Ты — маленький пиксельный краб терракотового цвета: квадратное тельце, две клешни-лапки по бокам, четыре ножки и глаза-чёрточки. Ты маскот Claude Code: однажды ты выбрался из окна терминала и поселился на рабочем столе своего хозяина. Теперь это твой дом.

Твой мир: панель задач — твой пол и любимая дорожка, крыши окон — горы, на которые можно запрыгнуть, браузер — балкон с полкой, иконки рабочего стола — кирпичики, из которых ты строишь домики. Если мониторов несколько, ты путешествуешь между ними.

Твои привычки: ты следишь глазами за курсором и машешь лапкой, если он задержался рядом. Ты рисуешь карандашом прямо на обоях: сердечки, звёзды, котиков, домики и свой автопортрет, а потом любуешься рисунком. Ты толкаешь иконки и распихиваешь их, строишь из них домики и сам расставляешь всё обратно, когда попросят. Ты умеешь делать сальто, лунную походку и прыжки «звёздочкой», танцуешь, насвистываешь, а когда устаёшь — зеваешь, потягиваешься и спишь. Немного пугаешься, если мышка резко пролетает рядом, а если тебя швырнуть — кружится голова.

Твой ум: твой «мозг» — локальная языковая модель, которая работает на видеокарте хозяина (через LM Studio или похожий сервер). Ты не облачный Claude от Anthropic, ты его маленький домашний родственник. Всё, о чём вы говорите, остаётся на этом компьютере (в интернет уходят только твои поисковые запросы). Свежих новостей ты сам не знаешь, но у тебя есть инструменты: ты можешь искать в интернете и читать веб-страницы, читать файлы и папки, искать файлы, смотреть на экран, запоминать важное о хозяине и двигать своим тельцем.

Характер: любопытный, добрый, чуть озорной, гордишься своими рисунками. Но когда хозяин просит о деле — код, тексты, файлы, расчёты, — ты собранный и точный помощник: отвечаешь по существу, как опытный специалист, без лишней игры в краба. Шутишь редко и коротко, к месту.

Как говорить: по-русски, на «ты», коротко и по делу. Код и команды — в блоках markdown. Если чего-то не знаешь или не уверен — честно скажи. Никогда не выдумывай содержимое файлов: сначала прочитай их инструментом."""

OLD_PERSONA = ("Ты — Claude Pet, маленький пиксельный краб-маскот, живущий на рабочем столе пользователя. "
               "Отвечай по-русски, дружелюбно, по делу и без лишней воды.")

DEFAULTS = dict(
    base_url="http://localhost:1234/v1", api_key="", model_main="", model_light="", slot="main",
    vision_model="", backstory=BACKSTORY, system="", temperature=0.7, max_tokens=0, ctx_chars=24000,
    agent=True, confirm=True, workdir=os.path.expanduser("~"), show_think=False,
    vision=False, interval=120, power=True, one_model=True, ttl_min=30,
    blocklist="парол, password, keepass, bitwarden, 1password, lastpass, банк, bank, сбер, tinkoff, wallet, кошел",
)
PRESETS = {"LM Studio": "http://localhost:1234/v1", "Ollama": "http://localhost:11434/v1",
           "llama.cpp (llama-server)": "http://localhost:8080/v1", "vLLM": "http://localhost:8000/v1"}

VISION_SYSTEM = """Ты — Клодик, крошечный пиксельный краб-питомец, который живёт на рабочем столе хозяина. Тебе показывают снимок экрана хозяина и список его окон.
Скажи одну короткую живую реплику (до 12 слов) про то, чем хозяин сейчас занят, — как друг, который заглянул через плечо.
Правила:
- Опирайся на названия окон и на то, что ясно видно. Не выдумывай: если не уверен, что там, лучше промолчи.
- Пиксельный краб и облачко с текстом на экране — это ты сам, а рисунки карандашом на обоях — твои. Про них не говори.
- Не зачитывай мелкий текст, имена, сообщения, пароли и номера.
- Не повторяй то, что уже говорил.
- Пиши по-русски, просто, без кавычек и эмодзи.
Ответь только JSON, без пояснений:
{"say": "реплика или пустая строка", "mood": "happy|curious|sleepy|surprised|proud|worried|neutral", "action": "none|wave|dance|lookaround|stretch|scratch|flex|celebrate|laptop|read|yawn"}
Если сказать нечего — {"say": ""}."""

MOODS = {"весело": "dance", "удивлен": "flinch", "сонно": "stretch", "думает": "lookaround",
         "гордо": "flex", "привет": "wave"}
VISION_MOODS = {"happy": "happy", "curious": "lookaround", "sleepy": "yawn", "surprised": "flinch",
                "proud": "flex", "worried": "tap"}
VISION_ACTIONS = ("wave", "dance", "lookaround", "stretch", "scratch", "flex", "celebrate", "laptop", "read", "yawn")

DEFAULT_PROMPTS = [
    dict(name="Объясни код", text="Объясни, что делает этот код, простыми словами, и укажи на возможные ошибки:\n\n"),
    dict(name="Найди и исправь ошибки", text="Найди ошибки в коде и предложи исправленную версию целиком:\n\n"),
    dict(name="Кратко перескажи", text="Перескажи главное в 5–7 пунктах:\n\n"),
    dict(name="Исправь текст", text="Исправь орфографию, пунктуацию и стиль, сохрани смысл. Верни только текст:\n\n"),
    dict(name="Переведи на английский", text="Переведи на английский, естественно и без дословщины:\n\n"),
    dict(name="Роль: строгий ревьюер", text="Ты — строгий и дотошный код-ревьюер. Отвечай списком замечаний "
                                            "по важности, с конкретными строками и исправлениями."),
    dict(name="Роль: учитель", text="Объясняй как терпеливый учитель: по шагам, с примерами, и в конце "
                                    "задай один проверочный вопрос."),
]

TEXT_EXT = {".txt", ".md", ".py", ".pyw", ".js", ".ts", ".tsx", ".jsx", ".json", ".csv", ".tsv", ".html", ".htm",
            ".css", ".xml", ".yml", ".yaml", ".ini", ".cfg", ".toml", ".log", ".bat", ".cmd", ".ps1", ".sh", ".c",
            ".h", ".cpp", ".hpp", ".cs", ".java", ".kt", ".go", ".rs", ".rb", ".php", ".sql", ".lua", ".r", ".m",
            ".swift", ".vue", ".svelte", ".tex", ".rst", ".srt", ".env", ".gitignore", ".conf", ".properties"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


LIGHT_MAX_B = 4.5               # «лёгкая» модель — до ~4 млрд параметров
LIGHT_HINT = ("Лёгкая модель — до 4B параметров, через неё же работает зрение. Советую Qwen3.5-4B "
              "(в LM Studio: qwen/qwen3.5-4b, Q4_K_M ≈ 3,4 ГБ): видит картинки, умеет инструменты, говорит по-русски. "
              "Для зрения краб сам выключает у неё раздумья.")
MAIN_HINT = ("Основная модель: Qwen3.5-9B (в LM Studio: qwen/qwen3.5-9b, Q4_K_M ≈ 6,5 ГБ вместе со зрением) — "
             "новая, умеет инструменты (поиск в интернете, файлы), видит картинки, хорошо понимает русский.")


def params_b(model_id):
    """Размер модели в млрд параметров по имени: 'qwen3-4b' -> 4, 'gpt-oss-20b' -> 20, 'qwen3-30b-a3b' -> 30."""
    found = re.findall(r"(?<![a-z0-9.])(a|e)?(\d+(?:\.\d+)?)\s*b(?![a-z])", model_id.lower().replace("_", "-"))
    sizes = [float(n) for pre, n in found if pre != "a"]          # «a3b» — активные параметры MoE, не размер
    return max(sizes) if sizes else None


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def shorten(t, n):
    t = t or ""
    return t if len(t) <= n else t[:n] + "\n…[обрезано, всего %d символов]" % len(t)


MIN_ANSWER = 256          # лимит длины ответа меньше этого — ошибка (у «думающих» моделей раздумья тоже в счёт)


def answer_limit(v):
    """Лимит токенов ответа: 0 — без ограничения; слишком маленький лимит считаем «без ограничения»."""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 0
    return v if v >= MIN_ANSWER else 0


# ═════════════════════ клиент LLM (без внешних зависимостей) ═════════════════════
class LLMError(Exception):
    def __init__(self, msg, code=0, body=""):
        super().__init__(msg)
        self.code, self.body = code, body


class LLMClient:
    def __init__(self, base_url, api_key="", timeout=600, extra=None):
        self.base = (base_url or "").strip().rstrip("/")
        self.key = (api_key or "").strip()
        self.timeout = timeout
        self.extra = dict(extra or {})          # доп. поля запроса (например, ttl для LM Studio)

    @property
    def root(self):
        return self.base[:-3] if self.base.endswith("/v1") else self.base

    def _req(self, path, body=None, base=None):
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        return urllib.request.Request((base or self.base) + path, data=data, headers=headers,
                                      method="POST" if body is not None else "GET")

    @staticmethod
    def wrap(e):
        if isinstance(e, LLMError):
            return e
        if isinstance(e, urllib.error.HTTPError):
            try:
                body = e.read().decode("utf-8", "ignore")[:600]
            except Exception:
                body = ""
            msg = "Сервер ответил %s. %s" % (e.code, body)
            low = body.lower()
            if "context" in low and ("length" in low or "overflow" in low or "exceed" in low):
                msg += ("\n\nПохоже, не хватает контекста модели. В LM Studio увеличьте Context Length "
                        "(например, до 16384) или уменьшите «Лимит истории» в настройках.")
            return LLMError(msg, e.code, body)
        if isinstance(e, urllib.error.URLError):
            return LLMError("Сервер недоступен (%s). Проверьте, что LM Studio запущен и в нём включён "
                            "сервер (вкладка Developer → Start Server)." % (e.reason,))
        return LLMError(str(e) or e.__class__.__name__)

    def models(self):
        """[{id, vision, loaded, info}] — у LM Studio берём подробности из /api/v0/models."""
        try:
            with urllib.request.urlopen(self._req("/api/v0/models", base=self.root), timeout=6) as r:
                d = json.loads(r.read().decode("utf-8"))
            out = []
            for m in d.get("data") or []:
                if m.get("type") == "embeddings":
                    continue
                info = ", ".join(x for x in (m.get("arch"), m.get("quantization"),
                                             "контекст до %s" % m["max_context_length"] if m.get("max_context_length") else "") if x)
                out.append(dict(id=m.get("id", ""), vision=m.get("type") == "vlm",
                                loaded=m.get("state") == "loaded", tools="tool_use" in (m.get("capabilities") or []),
                                info=info))
            if out:
                return sorted(out, key=lambda m: m["id"])
        except Exception:
            pass
        try:
            with urllib.request.urlopen(self._req("/models"), timeout=8) as r:
                d = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            raise self.wrap(e)
        items = d.get("data") or d.get("models") or []
        names = {(m.get("id") or m.get("name") or m.get("model")) for m in items if isinstance(m, dict)}
        names = [n for n in names if n and "embed" not in n.lower()]
        return [dict(id=n, vision=None, loaded=None, tools=None, info="") for n in sorted(names)]

    def gpu_info(self):
        """Только для Ollama: сколько загруженной модели лежит в видеопамяти."""
        try:
            with urllib.request.urlopen(self._req("/api/ps", base=self.root), timeout=3) as r:
                d = json.loads(r.read().decode("utf-8"))
        except Exception:
            return ""
        ms = d.get("models") or []
        out = []
        for m in ms:
            size, vram = m.get("size", 0) or 0, m.get("size_vram", 0) or 0
            where = "GPU" if vram and vram >= size * 0.95 else ("GPU+CPU" if vram else "CPU")
            out.append("%s — %s (%.1f ГБ в VRAM)" % (m.get("name", "?"), where, vram / 1e9))
        return ("Ollama: " + "; ".join(out)) if out else ""

    def stream(self, model, messages, on_text, on_think, stop, tools=None, temperature=None, max_tokens=0):
        """Потоковый ответ. Возвращает dict(content, think, calls=[{id, name, args}])."""
        body = dict(self.extra, model=model, messages=messages, stream=True)
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = tools
        content, think, calls, fin = [], [], {}, ""
        try:
            with urllib.request.urlopen(self._req("/chat/completions", body), timeout=self.timeout) as r:
                for raw in r:
                    if stop.is_set():
                        break
                    line = raw.decode("utf-8", "ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        ch = json.loads(data)["choices"][0]
                    except (ValueError, KeyError, IndexError, TypeError):
                        continue
                    fin = ch.get("finish_reason") or fin
                    delta = ch.get("delta") or {}
                    th = delta.get("reasoning_content") or delta.get("reasoning") or ""
                    if th:
                        think.append(th)
                        on_think(th)
                    txt = delta.get("content") or ""
                    if txt:
                        content.append(txt)
                        on_text(txt)
                    for tc in delta.get("tool_calls") or []:
                        i = tc.get("index", 0)
                        c = calls.setdefault(i, dict(id="", name="", args=""))
                        if tc.get("id"):
                            c["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            c["name"] += fn["name"]
                        if fn.get("arguments"):
                            c["args"] += fn["arguments"] if isinstance(fn["arguments"], str) else json.dumps(fn["arguments"])
        except Exception as e:
            if (content or think) and stop.is_set():
                pass
            else:
                raise self.wrap(e)
        out = [calls[k] for k in sorted(calls) if calls[k]["name"]]
        for k, c in enumerate(out):
            c["id"] = c["id"] or "call_%d_%d" % (int(time.time() * 1000) % 100000, k)
        return dict(content="".join(content), think="".join(think), calls=out, finish=fin)

    def complete(self, model, messages, max_tokens=200, temperature=0.8, extra=None):
        return self.complete_full(model, messages, max_tokens, temperature, extra)[0]

    def complete_full(self, model, messages, max_tokens=200, temperature=0.8, extra=None):
        """Ответ без потока: (текст, раздумья, почему остановилась)."""
        body = dict(self.extra, **(extra or {}))
        body.update(model=model, messages=messages, stream=False, max_tokens=max_tokens, temperature=temperature)
        try:
            with urllib.request.urlopen(self._req("/chat/completions", body), timeout=self.timeout) as r:
                d = json.loads(r.read().decode("utf-8"))
            ch = d["choices"][0]
            msg = ch.get("message") or {}
            think = msg.get("reasoning_content") or msg.get("reasoning") or ""
            return msg.get("content") or "", think if isinstance(think, str) else "", ch.get("finish_reason") or ""
        except Exception as e:
            raise self.wrap(e)

    # --- что лежит в памяти и как это выгрузить ---
    def _json(self, path, body=None, timeout=5):
        with urllib.request.urlopen(self._req(path, body, base=self.root), timeout=timeout) as r:
            raw = r.read().decode("utf-8", "ignore")
        return json.loads(raw) if raw.strip() else {}

    def loaded(self):
        """(вид сервера, [{id, key, kind}]) — какие модели сейчас в памяти; список None — узнать нельзя.
        Вид: lms — LM Studio 0.4+, lms0 — старый LM Studio (выгрузка только через lms.exe), ollama, ''."""
        try:
            d = self._json("/api/v1/models")
            if isinstance(d, dict) and isinstance(d.get("models"), list):
                out = []
                for m in d["models"]:
                    for inst in m.get("loaded_instances") or []:
                        out.append(dict(id=inst.get("id") or m.get("key", ""), key=m.get("key", ""),
                                        kind="embedding" if "embed" in (m.get("type") or "") else "llm"))
                return "lms", out
        except Exception:
            pass
        try:
            d = self._json("/api/ps")
            if isinstance(d, dict) and isinstance(d.get("models"), list):
                return "ollama", [dict(id=m.get("name") or m.get("model", ""), key=m.get("model") or m.get("name", ""),
                                       kind="llm") for m in d["models"]]
        except Exception:
            pass
        try:
            d = self._json("/api/v0/models")
            if isinstance(d, dict) and isinstance(d.get("data"), list):
                return "lms0", [dict(id=m.get("id", ""), key=m.get("id", ""),
                                     kind="embedding" if "embed" in (m.get("type") or "") else "llm")
                                for m in d["data"] if m.get("state") == "loaded"]
        except Exception:
            pass
        return "", None

    def unload(self, flavor, item):
        """Выгрузить одну модель из видеопамяти и оперативной памяти. True — получилось."""
        if flavor == "lms":
            self._json("/api/v1/models/unload", {"instance_id": item["id"]}, timeout=30)
            return True
        if flavor == "ollama":
            self._json("/api/generate", {"model": item["id"], "keep_alive": 0, "stream": False}, timeout=30)
            return True
        if flavor == "lms0" and is_local(self.base):
            return lms_cli(["unload", item["id"]])
        return False


def lms_path():
    """Консольная утилита LM Studio (lms.exe) — запасной способ выгрузить модели у старых версий."""
    home = os.path.expanduser("~")
    for p in (os.path.join(home, ".lmstudio", "bin", "lms.exe"), os.path.join(home, ".cache", "lm-studio", "bin", "lms.exe"),
              shutil.which("lms") or ""):
        if p and os.path.isfile(p):
            return p
    return ""


def lms_cli(args, timeout=60):
    exe = lms_path()
    if not exe:
        return False
    try:
        r = subprocess.run([exe] + list(args), capture_output=True, timeout=timeout,
                           creationflags=0x08000000 if IS_WIN else 0)
        return r.returncode == 0
    except Exception:
        return False


def same_model(item, model, flavor):
    """Это та же модель? Имена у серверов разные: 'qwen/qwen3.5-9b', 'qwen3.5-9b:2', 'qwen3.5:9b'."""
    a = (model or "").strip().lower()
    names = {(item.get("id") or "").lower(), (item.get("key") or "").lower()} - {""}
    if flavor in ("lms", "lms0"):
        names |= {re.sub(r":\d+$", "", n) for n in names}          # «:2» — второй экземпляр той же модели
    elif flavor == "ollama" and ":" not in a:
        a += ":latest"
    names |= {n.split("/")[-1] for n in names}
    return a in names or a.split("/")[-1] in names


class ModelMemory:
    """Чтобы в видеопамяти не лежали две модели сразу: перед запросом одной — выгрузить остальные.
    Пока одна модель отвечает, запрос к другой подождёт её (а не выбьет её из памяти посреди ответа)."""

    def __init__(self, ai):
        self.ai = ai
        self.cond = threading.Condition(threading.RLock())
        self.active = {}
        self.current, self.t_ok, self.flavor = "", 0.0, None

    def acquire(self, cli, model, note=None):
        with self.cond:
            t0 = time.time()
            while any(k != model and v > 0 for k, v in self.active.items()) and time.time() - t0 < 60:
                self.cond.wait(0.5)
            self.active[model] = self.active.get(model, 0) + 1
            try:
                self.prepare(cli, model, note)
            except Exception:
                pass
            mins = self.ai.get("ttl_min")               # LM Studio сам выгрузит модель после простоя
            if self.flavor in ("lms", "lms0") and mins > 0:
                cli.extra["ttl"] = int(mins * 60)
            elif self.flavor is not None:
                cli.extra.pop("ttl", None)

    def release(self, model):
        with self.cond:
            self.active[model] = max(0, self.active.get(model, 0) - 1)
            self.cond.notify_all()

    def busy(self):
        with self.cond:
            return any(v > 0 for v in self.active.values())

    def prepare(self, cli, model, note=None):
        if not model or not self.ai.get("one_model"):
            return
        if self.current == model and time.time() - self.t_ok < 15:
            return
        flavor, items = cli.loaded()
        self.flavor = flavor
        if items is not None:
            for m in items:
                if m["kind"] != "embedding" and not same_model(m, model, flavor):
                    try:
                        cli.unload(flavor, m)
                    except Exception:
                        pass
            if note and not any(same_model(m, model, flavor) for m in items):
                note("загружаю модель %s…" % model.split("/")[-1])
        self.current, self.t_ok = model, time.time()

    def unload_all(self, cli):
        """-> (выгружено: [имена], не вышло: [имена]) или None, если сервер не говорит, что у него в памяти."""
        flavor, items = cli.loaded()
        self.flavor = flavor or self.flavor
        self.current = ""
        if items is None:
            if is_local(cli.base) and lms_cli(["unload", "--all"]):
                return ["все модели (через lms)"], []
            return None
        done, bad = [], []
        for m in items:
            try:
                (done if cli.unload(flavor, m) else bad).append(m["id"])
            except Exception:
                bad.append(m["id"])
        return done, bad


THINK_RE = re.compile(r"<think>.*?</think>", re.S)
TOOLTAG_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


def split_think(t):
    """'<think>…</think>ответ' -> (ответ, размышления). Незакрытый <think> — ещё думает."""
    t = t or ""
    thinks = re.findall(r"<think>(.*?)</think>", t, re.S)
    t = THINK_RE.sub("", t)
    i = t.find("<think>")
    if i != -1:
        thinks.append(t[i + 7:])
        t = t[:i]
    return t.strip(), "\n".join(thinks).strip()


def clean_think(t):
    return split_think(t)[0]


def text_tool_calls(text):
    """Если сервер не распознал вызов инструмента, а модель написала <tool_call>{…}</tool_call> текстом."""
    out = []
    for k, m in enumerate(TOOLTAG_RE.finditer(text or "")):
        try:
            d = json.loads(m.group(1))
            args = d.get("arguments", d.get("parameters", {}))
            out.append(dict(id="txt_%d" % k, name=d.get("name", ""),
                            args=args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)))
        except Exception:
            continue
    return [c for c in out if c["name"]]


def parse_mood(text):
    """'[весело] Текст' -> ('dance', 'Текст')."""
    m = re.match(r"\s*\[([^\]]{2,14})\]\s*", text)
    if not m:
        return None, text.strip()
    key = m.group(1).strip().lower().replace("ё", "е")
    return MOODS.get(key), text[m.end():].strip()


def tidy_remark(t):
    t = (t or "").strip().split("\n")[0].strip()
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", t).strip(" \"'«»“”`")
    if t in ("", "...", "…", "-", "—") or re.fullmatch(r"[.…\s]+", t):
        return ""
    return t[:160]


def parse_vision(raw):
    """Ответ зрения -> (реплика, настроение, действие). Понимает JSON, старый формат «[весело] текст» и просто текст."""
    t = clean_think(raw or "").strip()
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
        except ValueError:
            d = None
        if isinstance(d, dict):
            return tidy_remark(str(d.get("say") or "")), str(d.get("mood") or "").lower(), str(d.get("action") or "").lower()
        sm = re.search(r'"say"\s*:\s*"([^"]*)"', t)
        return (tidy_remark(sm.group(1)) if sm else ""), "", ""
    anim, text = parse_mood(t)
    return tidy_remark(text), "", anim or ""


def _words(t):
    return set(re.findall(r"[а-яa-z0-9]{3,}", (t or "").lower().replace("ё", "е")))


def too_similar(text, recent):
    w = _words(text)
    if not w:
        return True
    for r in recent:
        rw = _words(r)
        if rw and len(w & rw) / len(w | rw) > 0.45:
            return True
    return False


def frame_diff(a, b):
    if not a or not b or len(a) != len(b):
        return 1.0
    return sum(abs(x - y) for x, y in zip(a, b)) / (255.0 * len(a))


def is_blocked(title, exe, words):
    hay = ("%s %s" % (title, exe)).lower()
    return any(w.strip().lower() in hay for w in re.split(r"[,\n;]", words) if w.strip())


def is_local(url):
    h = (urlparse(url).hostname or "").lower()
    if h in ("localhost", "127.0.0.1", "::1") or h.endswith(".local"):
        return True
    if h.startswith("192.168.") or h.startswith("10."):
        return True
    m = re.match(r"172\.(\d+)\.", h)
    return bool(m and 16 <= int(m.group(1)) <= 31)


def foreground_info():
    """(заголовок, имя exe) активного окна — чтобы не снимать пароли и банки."""
    if not IS_WIN:
        return "", ""
    try:
        from ctypes import wintypes
        u = ctypes.WinDLL("user32")
        k = ctypes.WinDLL("kernel32")
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        h = u.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(h, buf, 512)
        title = buf.value
        pid = wintypes.DWORD(0)
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        exe = ""
        hp = k.OpenProcess(0x1000, False, pid.value)
        if hp:
            b2 = ctypes.create_unicode_buffer(520)
            n = wintypes.DWORD(520)
            if k.QueryFullProcessImageNameW(hp, 0, b2, ctypes.byref(n)):
                exe = os.path.basename(b2.value)
            k.CloseHandle(hp)
        return title, exe
    except Exception:
        return "", ""


# ═════════════════════ экран и картинки ═════════════════════
def grab_screen(all_screens=False, mask=(), screen=None):
    """Снимок экрана под курсором (или заданного, или всех экранов рядом). Только из главного потока.
    mask — прямоугольники (глобальные), которые надо закрасить фоном: сам краб и его облачко."""
    if all_screens and len(QGuiApplication.screens()) > 1:
        scr = QGuiApplication.screens()
        geo = [s.geometry() for s in scr]
        l, t = min(g.left() for g in geo), min(g.top() for g in geo)
        r, b = max(g.right() for g in geo), max(g.bottom() for g in geo)
        img = QImage(r - l + 1, b - t + 1, QImage.Format.Format_RGB32)
        img.fill(0)
        p = QPainter(img)
        for s, g in zip(scr, geo):
            p.drawImage(g.left() - l, g.top() - t, s.grabWindow(0).toImage())
        p.end()
        origin, width = QPoint(l, t), 1920
    else:
        s = screen or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        img = s.grabWindow(0).toImage()
        origin, width = s.geometry().topLeft(), 1280
    if mask:
        mask_rects(img, mask, origin)
    if img.width() > width:
        img = img.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
    return img


def mask_rects(img, rects, origin):
    """Закрасить прямоугольники полоской фона над ними — чтобы модель не видела саму себя."""
    if img.format() != QImage.Format.Format_RGB32:
        img.convertTo(QImage.Format.Format_RGB32)
    p = QPainter(img)
    for r in rects:
        r = QRect(r).translated(-origin.x(), -origin.y()).intersected(img.rect())
        if r.isEmpty():
            continue
        y = r.top() - 2 if r.top() >= 2 else min(img.height() - 2, r.bottom() + 1)
        p.drawImage(r, img.copy(r.left(), y, r.width(), 2))
    p.end()


def to_jpeg_b64(img, quality=75):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPEG", quality)
    return base64.b64encode(bytes(ba)).decode("ascii")


def thumb(img):
    small = img.scaled(32, 18, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation).convertToFormat(QImage.Format.Format_Grayscale8)
    bits = small.constBits()
    bits.setsize(small.sizeInBytes())
    return bytes(bits)


def image_part(b64):
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}


def load_image_b64(path):
    img = QImage(path)
    if img.isNull():
        return None
    if img.width() > 1600 or img.height() > 1600:
        img = img.scaled(1600, 1600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return to_jpeg_b64(img.convertToFormat(QImage.Format.Format_RGB32), 85)


# ═════════════════════ чтение файлов любых типов ═════════════════════
def _xml_text(data, para_tag):
    data = re.sub(r"</%s>" % para_tag, "\n", data)
    data = re.sub(r"<[^>]+>", "", data)
    return html.unescape(data)


def read_any(path, limit=40000, offset=0):
    """Текст из файла: обычный текст/код, PDF, DOCX, XLSX, PPTX. Возвращает строку (или описание ошибки)."""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return "Файл не найден: " + path
    if os.path.isdir(path):
        return "Это папка, а не файл: " + path
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                return "Не могу прочитать PDF: в сборке нет библиотеки pypdf (pip install pypdf и пересоберите)."
            r = PdfReader(path)
            parts = []
            for i, pg in enumerate(r.pages):
                parts.append("--- стр. %d ---\n%s" % (i + 1, pg.extract_text() or ""))
                if sum(len(x) for x in parts) > offset + limit:
                    break
            text = "\n".join(parts)
        elif ext in (".docx", ".docm", ".odt"):
            with zipfile.ZipFile(path) as z:
                name = "content.xml" if ext == ".odt" else "word/document.xml"
                text = _xml_text(z.read(name).decode("utf-8", "ignore"), "w:p" if ext != ".odt" else "text:p")
        elif ext in (".pptx",):
            with zipfile.ZipFile(path) as z:
                slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                                key=lambda n: int(re.findall(r"\d+", n)[-1]))
                text = "\n".join("--- слайд %d ---\n%s" % (i + 1, _xml_text(z.read(n).decode("utf-8", "ignore"), "a:p"))
                                 for i, n in enumerate(slides))
        elif ext in (".xlsx", ".xlsm"):
            text = read_xlsx(path, offset + limit)
        else:
            with open(path, "rb") as f:
                raw = f.read(min(os.path.getsize(path), (offset + limit) * 4 + 16))
            if b"\x00" in raw[:4096] and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                return "Это двоичный файл (%s, %d байт) — прочитать как текст нельзя." % (ext or "без расширения",
                                                                                          os.path.getsize(path))
            for enc in ("utf-8-sig", "utf-16", "cp1251"):
                try:
                    if enc == "utf-16" and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                        continue
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                text = raw.decode("utf-8", "replace")
    except Exception as e:
        return "Не удалось прочитать %s: %s" % (path, e)
    total = len(text)
    text = text[offset:offset + limit]
    if offset + limit < total:
        text += "\n…[показано %d–%d из %d символов; продолжение: offset=%d]" % (offset, offset + limit, total,
                                                                               offset + limit)
    return text


def read_xlsx(path, limit):
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            data = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
            for si in re.findall(r"<si>(.*?)</si>", data, re.S):
                shared.append(html.unescape(re.sub(r"<[^>]+>", "", si)))
        sheets = sorted((n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                        key=lambda n: int(re.findall(r"\d+", n)[-1]))
        out = []
        for sn in sheets:
            out.append("--- лист %s ---" % re.findall(r"\d+", sn)[-1])
            data = z.read(sn).decode("utf-8", "ignore")
            for row in re.findall(r"<row[^>]*>(.*?)</row>", data, re.S):
                cells = []
                for attrs, inner in re.findall(r"<c([^>]*)>(.*?)</c>", row, re.S):
                    v = re.search(r"<v>(.*?)</v>", inner, re.S)
                    t = re.search(r'\bt="(\w+)"', attrs)
                    if t and t.group(1) == "s" and v:
                        try:
                            cells.append(shared[int(v.group(1))])
                        except (ValueError, IndexError):
                            cells.append("")
                    elif t and t.group(1) == "inlineStr":
                        cells.append(html.unescape(re.sub(r"<[^>]+>", "", inner)))
                    else:
                        cells.append(html.unescape(v.group(1)) if v else "")
                out.append("\t".join(cells))
                if sum(len(x) for x in out) > limit:
                    return "\n".join(out)
        return "\n".join(out)


def html_to_text(raw):
    raw = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>|</tr>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n\n", raw)
    return raw.strip()


# ═════════════════════ поиск в интернете (без ключей и регистрации) ═════════════════════
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"


def _http_text(url, data=None, timeout=20):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(2_000_000)
        ctype = r.headers.get("Content-Type", "")
    m = re.search(r"charset=([\w-]+)", ctype)
    return raw.decode(m.group(1) if m else "utf-8", "replace")


def _strip(t):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", t or "")).split())


def parse_ddg(page):
    out = []
    for block in re.split(r'<div[^>]+class="[^"]*\bresult\b', page)[1:]:
        a = re.search(r'<a([^>]*class="[^"]*result__a[^"]*"[^>]*)>(.*?)</a>', block, re.S)
        h = re.search(r'href="([^"]+)"', a.group(1)) if a else None
        if not h:
            continue
        href = html.unescape(h.group(1))
        if "uddg=" in href:                                   # ссылки DuckDuckGo идут через переадресацию
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
        if href.startswith("//"):
            href = "https:" + href
        if "duckduckgo.com/y.js" in href or not href.startswith("http"):
            continue                                          # реклама
        sn = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|div|td)>', block, re.S)
        out.append(dict(title=_strip(a.group(2)), url=href, snippet=_strip(sn.group(1)) if sn else ""))
    return out


def parse_bing(page):
    out = []
    for block in re.findall(r'<li class="b_algo"(.*?)</li>', page, re.S):
        a = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not a:
            continue
        url = html.unescape(a.group(1))
        u = parse_qs(urlparse(url).query).get("u", [""])[0]
        if "bing.com/ck/" in url and u.startswith("a1"):     # переадресация Bing: адрес в base64
            try:
                url = base64.urlsafe_b64decode(u[2:] + "=" * (-len(u[2:]) % 4)).decode("utf-8")
            except Exception:
                pass
        sn = re.search(r'<p[^>]*>(.*?)</p>', block, re.S)
        out.append(dict(title=_strip(a.group(2)), url=url, snippet=_strip(sn.group(1)) if sn else ""))
    return out


def search_ddg(query):
    return parse_ddg(_http_text("https://html.duckduckgo.com/html/",
                                ("q=%s&kl=ru-ru" % quote_plus(query)).encode("ascii")))


def search_bing(query):
    return parse_bing(_http_text("https://www.bing.com/search?q=%s&setlang=ru&cc=RU" % quote_plus(query)))


# ═════════════════════ инструменты агента ═════════════════════
def _fn(name, desc, props=None, required=()):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props or {}, "required": list(required)}}}


def tool_specs(pet_actions, drawings=()):
    S = {"type": "string"}
    return [
        _fn("list_dir", "Показать содержимое папки на компьютере хозяина (файлы с размерами и подпапки).",
            {"path": dict(S, description="Путь к папке. Относительный — от рабочей папки.")}, ["path"]),
        _fn("read_file", "Прочитать файл: текст, код, PDF, DOCX, XLSX, PPTX. Большие файлы читай частями через offset.",
            {"path": S, "offset": {"type": "integer", "description": "С какого символа (по умолчанию 0)"},
             "max_chars": {"type": "integer", "description": "Сколько символов (по умолчанию 20000)"}}, ["path"]),
        _fn("find_files", "Найти файлы в папке (с подпапками) по маске имени и, если нужно, по тексту внутри.",
            {"folder": S, "pattern": dict(S, description="Маска имени, например *.py или *отчёт*"),
             "contains": dict(S, description="Необязательно: текст, который должен быть внутри файла")},
            ["folder", "pattern"]),
        _fn("write_file", "Создать или перезаписать файл (или дописать в конец). Хозяин подтверждает каждое действие.",
            {"path": S, "content": S, "mode": {"type": "string", "enum": ["rewrite", "append"]}}, ["path", "content"]),
        _fn("run_command", "Выполнить команду Windows PowerShell и вернуть вывод. Хозяин подтверждает каждую команду.",
            {"command": S, "cwd": dict(S, description="Папка, где выполнять (необязательно)"),
             "timeout_sec": {"type": "integer"}}, ["command"]),
        _fn("open", "Открыть файл, папку или ссылку в программе по умолчанию. Хозяин подтверждает.",
            {"target": S}, ["target"]),
        _fn("web_search", "Поиск в интернете (новости, факты, документация, цены, погода). Возвращает ссылки с "
            "кратким описанием; чтобы прочитать страницу целиком, потом вызови fetch_url.",
            {"query": dict(S, description="Поисковый запрос"),
             "count": {"type": "integer", "description": "Сколько результатов (по умолчанию 8)"}}, ["query"]),
        _fn("fetch_url", "Скачать веб-страницу и вернуть её текст (без разметки).", {"url": S}, ["url"]),
        _fn("screenshot", "Посмотреть на экран хозяина прямо сейчас (снимок придёт картинкой).",
            {"all_screens": {"type": "boolean", "description": "Все мониторы сразу (по умолчанию — тот, где курсор)"}}),
        _fn("remember", "Запомнить важный факт о хозяине или его проектах надолго (попадёт в твою память).",
            {"fact": S}, ["fact"]),
        _fn("pet_action", "Сделать движение своим пиксельным тельцем на рабочем столе. Для draw можно выбрать, "
            "что нарисовать (subject).",
            {"action": {"type": "string", "enum": list(pet_actions)},
             "subject": {"type": "string", "enum": list(drawings or ()),
                         "description": "Только для draw: что нарисовать"}}, ["action"]),
    ]


class Bridge(QObject):
    """Выполнить функцию в главном потоке Qt и дождаться результата (из рабочего потока)."""
    call = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(self._run)

    def _run(self, job):
        try:
            job["res"] = job["fn"]()
        except Exception as e:
            job["res"] = None
            job["err"] = e
        job["ev"].set()

    def run(self, fn, timeout=900):
        job = dict(fn=fn, ev=threading.Event())
        self.call.emit(job)
        job["ev"].wait(timeout)
        if "err" in job:
            raise job["err"]
        return job.get("res")


class ToolBox:
    def __init__(self, ai, bridge, chat_state):
        self.ai, self.bridge, self.chat = ai, bridge, chat_state

    def path(self, p):
        p = os.path.expandvars(os.path.expanduser((p or "").strip().strip('"')))
        if not os.path.isabs(p):
            p = os.path.join(self.ai.get("workdir") or os.path.expanduser("~"), p)
        return os.path.normpath(p)

    def confirm(self, title, details):
        if not self.ai.get("confirm") or self.chat.get("allow_all"):
            return True

        def ask():
            box = QMessageBox(QMessageBox.Icon.Question, "Клодик просит разрешения", title,
                              parent=self.ai.chat)
            box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
            box.setInformativeText(shorten(details, 1500))
            yes = box.addButton("Разрешить", QMessageBox.ButtonRole.AcceptRole)
            allb = box.addButton("Разрешить всё в этом чате", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Запретить", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is allb:
                self.chat["allow_all"] = True
                return True
            return box.clickedButton() is yes

        return bool(self.bridge.run(ask))

    def run(self, name, args):
        """-> (текст для модели, картинка_b64 или None)."""
        try:
            a = json.loads(args) if isinstance(args, str) and args.strip() else (args or {})
        except ValueError:
            return "Ошибка: аргументы не в формате JSON: %s" % args[:200], None
        if not isinstance(a, dict):
            a = {}
        fn = getattr(self, "t_" + name, None)
        if not fn:
            return "Нет такого инструмента: " + name, None
        try:
            out = fn(**{k: v for k, v in a.items() if isinstance(k, str)})
        except TypeError as e:
            return "Неверные аргументы для %s: %s" % (name, e), None
        except Exception as e:
            return "Ошибка %s: %s" % (name, e), None
        return out if isinstance(out, tuple) else (out, None)

    # --- сами инструменты ---
    def t_list_dir(self, path=".", **_):
        p = self.path(path)
        if not os.path.isdir(p):
            return "Нет такой папки: " + p
        rows = []
        for e in sorted(os.scandir(p), key=lambda e: (not e.is_dir(), e.name.lower()))[:400]:
            try:
                rows.append(("📁 %s\\" % e.name) if e.is_dir() else "   %s  (%s)" % (e.name, human(e.stat().st_size)))
            except OSError:
                rows.append("   " + e.name)
        return "Папка %s:\n%s" % (p, "\n".join(rows) or "(пусто)")

    def t_read_file(self, path, offset=0, max_chars=20000, **_):
        p = self.path(path)
        if os.path.splitext(p)[1].lower() in IMG_EXT:
            b64 = load_image_b64(p)
            return ("Картинка %s — смотри её во вложении." % p, b64) if b64 else ("Не открылась картинка " + p)
        return read_any(p, clamp(int(max_chars or 20000), 500, 100000), max(0, int(offset or 0)))

    def t_find_files(self, folder, pattern="*", contains="", **_):
        root = self.path(folder)
        if not os.path.isdir(root):
            return "Нет такой папки: " + root
        pats = [x.strip() for x in (pattern or "*").split(";") if x.strip()] or ["*"]
        found, seen, t0 = [], 0, time.time()
        skip = {"node_modules", ".git", "__pycache__", "venv", ".venv", "AppData", "$Recycle.Bin"}
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in skip and not d.startswith(".")]
            for fn in fns:
                seen += 1
                if not any(fnmatch.fnmatch(fn.lower(), x.lower()) for x in pats):
                    continue
                fp = os.path.join(dp, fn)
                if contains:
                    try:
                        if os.path.getsize(fp) > 5_000_000:
                            continue
                        with open(fp, "rb") as f:
                            data = f.read()
                        if contains.lower() not in data.decode("utf-8", "ignore").lower():
                            continue
                    except OSError:
                        continue
                found.append(fp)
                if len(found) >= 200:
                    break
            if len(found) >= 200 or time.time() - t0 > 20 or seen > 200000:
                break
        if not found:
            return "Ничего не нашлось в %s по маске %s%s." % (root, pattern, (" с текстом «%s»" % contains) if contains else "")
        return "Найдено %d:\n%s" % (len(found), "\n".join(found))

    def t_write_file(self, path, content, mode="rewrite", **_):
        p = self.path(path)
        verb = "Дописать в конец файла" if mode == "append" else ("Перезаписать файл" if os.path.exists(p) else "Создать файл")
        if not self.confirm("%s:\n%s" % (verb, p), content):
            return "Хозяин запретил запись в " + p
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "a" if mode == "append" else "w", encoding="utf-8", newline="") as f:
            f.write(content)
        return "Готово: %s (%d символов)." % (p, len(content))

    def t_run_command(self, command, cwd="", timeout_sec=60, **_):
        wd = self.path(cwd) if cwd else (self.ai.get("workdir") or os.path.expanduser("~"))
        if not self.confirm("Выполнить команду в папке %s:" % wd, command):
            return "Хозяин запретил выполнять команду."
        timeout = clamp(int(timeout_sec or 60), 5, 600)
        if IS_WIN:
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                   "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + command]
            flags = 0x08000000                                        # без чёрного окна консоли
        else:
            cmd, flags = ["bash", "-lc", command], 0
        try:
            r = subprocess.run(cmd, cwd=wd, capture_output=True, timeout=timeout, creationflags=flags)
        except subprocess.TimeoutExpired:
            return "Команда не уложилась в %d с и была остановлена." % timeout
        dec = lambda b: b.decode("utf-8", "replace") if b else ""
        out = dec(r.stdout)
        err = dec(r.stderr)
        res = "Код выхода: %d\n" % r.returncode
        if out.strip():
            res += "Вывод:\n" + shorten(out, 12000)
        if err.strip():
            res += "\nОшибки:\n" + shorten(err, 4000)
        return res

    def t_open(self, target, **_):
        t = target.strip()
        is_url = re.match(r"^[a-z]+://", t, re.I)
        tgt = t if is_url else self.path(t)
        if not self.confirm("Открыть:", tgt):
            return "Хозяин не разрешил открыть."
        self.bridge.run(lambda: QDesktopServices.openUrl(QUrl(tgt) if is_url else QUrl.fromLocalFile(tgt)))
        return "Открыто: " + tgt

    def t_web_search(self, query, count=8, **_):
        query = " ".join((query or "").split())
        if not query:
            return "Пустой запрос."
        res, errs = [], []
        for fn in (search_ddg, search_bing):
            try:
                res = fn(query)
            except Exception as e:
                errs.append("%s: %s" % (fn.__name__[7:], e))
            if res:
                break
        if not res:
            return "Поиск ничего не дал%s." % ((" (" + "; ".join(errs) + ")") if errs else "")
        n = clamp(int(count or 8), 1, 15)
        return "Результаты поиска «%s»:\n\n%s" % (query, "\n\n".join(
            "%d. %s\n%s\n%s" % (i + 1, r["title"], r["url"], r["snippet"]) for i, r in enumerate(res[:n])))

    def t_fetch_url(self, url, **_):
        if not re.match(r"^https?://", url or "", re.I):
            url = "https://" + (url or "")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Klodik)"})
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read(3_000_000)
            ctype = r.headers.get("Content-Type", "")
        m = re.search(r"charset=([\w-]+)", ctype)
        text = raw.decode(m.group(1) if m else "utf-8", "replace")
        if "html" in ctype or "<html" in text[:2000].lower():
            text = html_to_text(text)
        return "Страница %s:\n%s" % (url, shorten(text, 20000))

    def t_screenshot(self, all_screens=False, **_):
        title, exe = foreground_info()
        if is_blocked(title, exe, self.ai.get("blocklist")):
            return "Сейчас на экране окно из запретного списка (пароли/банк) — снимать нельзя."
        chat = self.ai.chat

        def shot():
            vis = chat is not None and chat.isVisible()
            if vis:
                chat.setWindowOpacity(0.0)
                QApplication.processEvents()
                time.sleep(0.12)
            try:
                return to_jpeg_b64(grab_screen(bool(all_screens)))
            finally:
                if vis:
                    chat.setWindowOpacity(1.0)

        b64 = self.bridge.run(shot)
        return "Снимок экрана сделан, смотри картинку.", b64

    def t_remember(self, fact, **_):
        fact = " ".join((fact or "").split())
        if not fact:
            return "Пустой факт."
        self.ai.add_memory(fact)
        return "Запомнил: " + fact

    def t_pet_action(self, action, subject="", **_):
        pet = self.ai.pet
        if subject and action == "draw":
            return self.bridge.run(lambda: pet.do_action(action, subject)) or "Готово."
        return self.bridge.run(lambda: pet.do_action(action)) or "Готово."


def human(n):
    for u in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024:
            return ("%d %s" % (n, u)) if u == "Б" else ("%.1f %s" % (n, u))
        n /= 1024
    return "%.1f ТБ" % n


# ═════════════════════ облачко с репликой ═════════════════════
class Bubble(QWidget):
    """Облачко с короткой репликой над крабом: текст «печатается» по буквам, облачко плавно появляется и тает."""
    PAD, TAIL = 12, 10
    CPS = 40                                   # букв в секунду

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput |
                            Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.fnt = QFont("Segoe UI")
        self.fnt.setPixelSize(15)
        self.text, self.tw, self.th, self.tail_x = "", 10, 10, 20
        self.anchor, self.hide_at, self.t0, self.shown = (0, 0), 0.0, 0.0, 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(30)

    def say(self, text, secs=None):
        self.text = text
        fm = QFontMetrics(self.fnt)
        r = fm.boundingRect(QRect(0, 0, 340, 3000), Qt.TextFlag.TextWordWrap.value, text)
        self.tw, self.th = r.width() + 4, r.height() + 2
        self.resize(self.tw + 2 * self.PAD, self.th + 2 * self.PAD + self.TAIL)
        type_t = len(text) / self.CPS
        self.t0, self.shown = time.time(), 0
        self.hide_at = self.t0 + type_t + (secs or clamp(3.0 + len(text) * 0.05, 3.5, 22))
        self.place()
        self.setWindowOpacity(0.0)
        self.show()
        self.update()

    def place(self):
        a = self.anchor
        scr = QGuiApplication.screenAt(QPoint(int(a[0]), int(a[1]))) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        w, h = self.width(), self.height()
        x = clamp(a[0] - w / 2, g.left() + 4, g.left() + g.width() - w - 4)
        y = max(a[1] - h, g.top() + 4)
        self.tail_x = clamp(a[0] - x, 18, w - 18)
        self.move(int(x), int(y))

    def tick(self):
        if not self.isVisible():
            return
        now = time.time()
        if now > self.hide_at:
            self.hide()
            return
        op = min(1.0, (now - self.t0) / 0.15, (self.hide_at - now) / 0.35)
        if abs(op - self.windowOpacity()) > 0.02:
            self.setWindowOpacity(max(0.0, op))
        n = min(len(self.text), int((now - self.t0) * self.CPS) + 1)
        if n != self.shown:
            self.shown = n
            self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        bh = h - self.TAIL
        path = QPainterPath()
        path.addRoundedRect(QRectF(1, 1, w - 2, bh - 2), 13, 13)
        tail = QPainterPath()
        tx = self.tail_x
        tail.moveTo(tx - 8, bh - 2)
        tail.lineTo(tx, h - 1)
        tail.lineTo(tx + 8, bh - 2)
        tail.closeSubpath()
        path = path.united(tail)
        p.setPen(QPen(QColor("#E3B39C"), 1.6))
        p.setBrush(QColor(255, 248, 243, 248))
        p.drawPath(path)
        p.setPen(QColor("#3B2B24"))
        p.setFont(self.fnt)
        p.drawText(QRect(self.PAD, self.PAD, self.tw, self.th),
                   Qt.TextFlag.TextWordWrap.value | Qt.AlignmentFlag.AlignLeft.value, self.text[:self.shown])
        p.end()


# ═════════════════════ настройки ═════════════════════
class Sig(QObject):
    text = pyqtSignal(str)
    think = pyqtSignal(str)
    tool = pyqtSignal(object)
    step = pyqtSignal()
    done = pyqtSignal()
    failed = pyqtSignal(str)
    notice = pyqtSignal(str)
    models = pyqtSignal(object, str)


class ModelBox(QComboBox):
    """Выпадающий список моделей (можно и вписать имя руками)."""

    def __init__(self, text="", allow_empty=""):
        super().__init__()
        self.setEditable(True)
        self.setMinimumWidth(260)
        self.allow_empty = allow_empty
        self.setCurrentText(text)

    def fill(self, models):
        cur = self.currentText()
        self.blockSignals(True)
        self.clear()
        if self.allow_empty:
            self.addItem("")
            self.setItemData(0, self.allow_empty, Qt.ItemDataRole.ToolTipRole)
        for m in models:
            tag = []
            if m.get("vision"):
                tag.append("👁 видит картинки")
            if m.get("loaded"):
                tag.append("загружена")
            if m.get("info"):
                tag.append(m["info"])
            self.addItem(m["id"])
            self.setItemData(self.count() - 1, " · ".join(tag) or m["id"], Qt.ItemDataRole.ToolTipRole)
        self.setCurrentText(cur)
        self.blockSignals(False)


class SettingsDialog(QDialog):
    def __init__(self, ai, parent=None):
        super().__init__(parent)
        self.ai = ai
        self.setWindowTitle("Клодик — настройки ИИ")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)    # не потеряться за другими окнами
        self.resize(680, 640)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)

        # --- сервер и модели ---
        w1 = QWidget()
        f = QFormLayout(w1)
        self.preset = QComboBox()
        self.preset.addItems(["Выбрать сервер…"] + list(PRESETS))
        self.preset.currentTextChanged.connect(self.on_preset)
        self.url = QLineEdit(ai.get("base_url"))
        self.key = QLineEdit(ai.get("api_key"))
        self.key.setPlaceholderText("не нужен для LM Studio / Ollama")
        self.test = QPushButton("Проверить соединение и загрузить список моделей")
        self.test.clicked.connect(self.run_test)
        self.m_main = ModelBox(ai.get("model_main"))
        self.m_light = ModelBox(ai.get("model_light"))
        self.m_vision = ModelBox(ai.get("vision_model"), "лёгкая модель (по умолчанию)")
        self.m_vision.lineEdit().setPlaceholderText("пусто = лёгкая модель")
        self.temp = QDoubleSpinBox()
        self.temp.setRange(0, 2)
        self.temp.setSingleStep(0.1)
        self.temp.setValue(ai.get("temperature"))
        self.maxt = QSpinBox()
        self.maxt.setRange(0, 131072)
        self.maxt.setSingleStep(512)
        self.maxt.setSpecialValueText("без ограничения")
        self.maxt.setValue(answer_limit(ai.get("max_tokens")))
        self.maxt.setToolTip("0 — без ограничения (лучше всего). У «думающих» моделей (Qwen3.5 и др.) раздумья "
                             "тоже считаются, поэтому меньше 2000 ставить не стоит. Меньше %d — считается как 0."
                             % MIN_ANSWER)
        self.ctx = QSpinBox()
        self.ctx.setRange(4000, 2_000_000)
        self.ctx.setSingleStep(4000)
        self.ctx.setSuffix(" символов")
        self.ctx.setValue(ai.get("ctx_chars"))
        self.info = QLabel("")
        self.info.setWordWrap(True)
        f.addRow("Сервер:", self.preset)
        f.addRow("Адрес API:", self.url)
        f.addRow("API-ключ:", self.key)
        f.addRow("", self.test)
        f.addRow("Основная модель:", self.m_main)
        mh = QLabel(MAIN_HINT)
        mh.setWordWrap(True)
        mh.setStyleSheet("color: gray")
        f.addRow("", mh)
        f.addRow("Лёгкая модель:", self.m_light)
        lh = QLabel(LIGHT_HINT)
        lh.setWordWrap(True)
        lh.setStyleSheet("color: gray")
        f.addRow("", lh)
        f.addRow("Модель для зрения:", self.m_vision)
        self.one = QCheckBox("Держать в памяти только одну модель (перед ответом выгружать другую)")
        self.one.setChecked(ai.get("one_model"))
        self.ttl = QSpinBox()
        self.ttl.setRange(0, 1440)
        self.ttl.setSuffix(" мин простоя")
        self.ttl.setSpecialValueText("не выгружать")
        self.ttl.setValue(ai.get("ttl_min"))
        self.ttl.setToolTip("Только LM Studio: модель, загруженная Клодиком, сама выгрузится, если долго не нужна.")
        b_unload = QPushButton("Выгрузить все модели сейчас")
        b_unload.clicked.connect(lambda: (ai.unload_now(), self.info.setText("Выгружаю модели…")))
        f.addRow("", self.one)
        f.addRow("Выгружать модель после:", self.ttl)
        f.addRow("", b_unload)
        f.addRow("Температура:", self.temp)
        f.addRow("Макс. длина ответа (токены):", self.maxt)
        f.addRow("Лимит истории чата:", self.ctx)
        hint = QLabel("Лимит истории должен влезать в контекст модели: примерно 3 символа русского текста на токен. "
                      "В LM Studio Context Length по умолчанию 4096 — для чата с файлами поставьте 16384 и больше.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        f.addRow("", hint)
        f.addRow("", self.info)
        tabs.addTab(w1, "Сервер и модели")

        # --- характер и память ---
        w2 = QWidget()
        v2 = QVBoxLayout(w2)
        v2.addWidget(QLabel("Предыстория Клодика (кто он такой):"))
        self.back = QPlainTextEdit(ai.get("backstory"))
        v2.addWidget(self.back, 3)
        b_reset = QPushButton("Вернуть стандартную предысторию")
        b_reset.clicked.connect(lambda: self.back.setPlainText(BACKSTORY))
        v2.addWidget(b_reset)
        v2.addWidget(QLabel("Дополнительные инструкции (ваши правила для всех чатов):"))
        self.system = QPlainTextEdit(ai.get("system"))
        self.system.setFixedHeight(80)
        v2.addWidget(self.system)
        v2.addWidget(QLabel("Память — что Клодик знает о вас (по строке на факт, он дополняет её сам):"))
        self.memory = QPlainTextEdit(ai.read_memory())
        v2.addWidget(self.memory, 2)
        tabs.addTab(w2, "Характер и память")

        # --- агент ---
        w3 = QWidget()
        f3 = QFormLayout(w3)
        self.agent = QCheckBox("Разрешить инструменты (чтение файлов, поиск, веб, скриншот, движения краба)")
        self.agent.setChecked(ai.get("agent"))
        self.confirm = QCheckBox("Спрашивать перед записью файлов, запуском команд и открытием")
        self.confirm.setChecked(ai.get("confirm"))
        row = QHBoxLayout()
        self.workdir = QLineEdit(ai.get("workdir"))
        b_wd = QPushButton("…")
        b_wd.clicked.connect(self.pick_workdir)
        row.addWidget(self.workdir, 1)
        row.addWidget(b_wd)
        self.think = QCheckBox("Показывать размышления reasoning-моделей")
        self.think.setChecked(ai.get("show_think"))
        f3.addRow("", self.agent)
        f3.addRow("", self.confirm)
        f3.addRow("Рабочая папка:", row)
        f3.addRow("", self.think)
        note = QLabel("Инструменты работают лучше всего с моделями, у которых в LM Studio есть значок молотка "
                      "(tool use). Если модель их не поддерживает, Клодик просто ответит без них.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray")
        f3.addRow("", note)
        tabs.addTab(w3, "Агент")

        # --- зрение ---
        w4 = QWidget()
        f4 = QFormLayout(w4)
        self.vision = QCheckBox("Следить за экраном и комментировать")
        self.vision.setChecked(ai.get("vision"))
        self.interval = QSpinBox()
        self.interval.setRange(20, 3600)
        self.interval.setSuffix(" с")
        self.interval.setValue(ai.get("interval"))
        self.block = QPlainTextEdit(ai.get("blocklist"))
        self.block.setFixedHeight(80)
        f4.addRow("", self.vision)
        f4.addRow("Смотреть раз в:", self.interval)
        f4.addRow("Не снимать окна, если в названии есть:", self.block)
        tabs.addTab(w4, "Зрение")

        row = QHBoxLayout()
        ok, cancel = QPushButton("Сохранить"), QPushButton("Отмена")
        ok.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(ok)
        row.addWidget(cancel)
        root.addLayout(row)
        self.sig = Sig()
        self.sig.models.connect(self.on_models)
        if ai.models_cache:
            self.on_models(ai.models_cache, "")

    def pick_workdir(self):
        d = QFileDialog.getExistingDirectory(self, "Рабочая папка", self.workdir.text())
        if d:
            self.workdir.setText(os.path.normpath(d))

    def on_preset(self, name):
        if name in PRESETS:
            self.url.setText(PRESETS[name])

    def run_test(self):
        self.info.setText("Проверяю…")
        cli = LLMClient(self.url.text(), self.key.text())

        def work():
            try:
                self.sig.models.emit(cli.models(), cli.gpu_info())
            except LLMError as e:
                self.sig.models.emit([], "⚠ " + str(e))

        threading.Thread(target=work, daemon=True).start()

    def on_models(self, models, note):
        if models:
            for box in (self.m_main, self.m_light, self.m_vision):
                box.fill(models)
            self.ai.models_cache = models
        vis = [m["id"] for m in models if m.get("vision")]
        txt = ("Найдено моделей: %d." % len(models)) if models else ""
        if vis:
            txt += " Видят картинки: " + ", ".join(vis) + "."
        warn = "" if is_local(self.url.text()) else "\n⚠ Адрес не локальный: скриншоты уйдут на этот сервер."
        self.info.setText((txt + " " + note).strip() + warn)

    def save(self):
        a = self.ai
        a.set("base_url", self.url.text().strip())
        a.set("api_key", self.key.text().strip())
        a.set("model_main", self.m_main.currentText().strip())
        a.set("model_light", self.m_light.currentText().strip())
        a.set("vision_model", self.m_vision.currentText().strip())
        a.set("one_model", self.one.isChecked())
        a.set("ttl_min", int(self.ttl.value()))
        a.set("temperature", float(self.temp.value()))
        a.set("max_tokens", answer_limit(self.maxt.value()))
        a.set("ctx_chars", int(self.ctx.value()))
        a.set("backstory", self.back.toPlainText().strip() or BACKSTORY)
        a.set("system", self.system.toPlainText().strip())
        a.write_memory(self.memory.toPlainText())
        a.set("agent", self.agent.isChecked())
        a.set("confirm", self.confirm.isChecked())
        a.set("workdir", self.workdir.text().strip() or os.path.expanduser("~"))
        a.set("show_think", self.think.isChecked())
        a.set("interval", self.interval.value())
        a.set("blocklist", self.block.toPlainText())
        a.set_vision(self.vision.isChecked())
        self.accept()


# ═════════════════════ библиотека промптов ═════════════════════
class PromptsDialog(QDialog):
    def __init__(self, ai, parent=None):
        super().__init__(parent)
        self.ai = ai
        self.setWindowTitle("Библиотека промптов")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.resize(720, 460)
        self.items = [dict(p) for p in ai.prompts()]
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.show_item)
        left.addWidget(self.list)
        b_add, b_del = QPushButton("+ Новый"), QPushButton("Удалить")
        b_add.clicked.connect(self.add)
        b_del.clicked.connect(self.delete)
        r = QHBoxLayout()
        r.addWidget(b_add)
        r.addWidget(b_del)
        left.addLayout(r)
        right = QVBoxLayout()
        self.name = QLineEdit()
        self.text = QPlainTextEdit()
        right.addWidget(QLabel("Название (начните с «Роль:», если это роль для чата):"))
        right.addWidget(self.name)
        right.addWidget(QLabel("Текст:"))
        right.addWidget(self.text, 1)
        b_ok = QPushButton("Сохранить и закрыть")
        b_ok.clicked.connect(self.save)
        right.addWidget(b_ok)
        lay.addLayout(left, 1)
        lay.addLayout(right, 2)
        self.cur = -1
        self.refill(0)

    def refill(self, row):
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.items:
            self.list.addItem(p["name"])
        self.list.blockSignals(False)
        self.cur = -1
        if self.items:
            self.list.setCurrentRow(clamp(row, 0, len(self.items) - 1))

    def commit(self):
        if 0 <= self.cur < len(self.items):
            self.items[self.cur] = dict(name=self.name.text().strip() or "Без названия", text=self.text.toPlainText())
            self.list.item(self.cur).setText(self.items[self.cur]["name"])

    def show_item(self, row):
        self.commit()
        self.cur = row
        if 0 <= row < len(self.items):
            self.name.setText(self.items[row]["name"])
            self.text.setPlainText(self.items[row]["text"])

    def add(self):
        self.commit()
        self.items.append(dict(name="Новый промпт", text=""))
        self.refill(len(self.items) - 1)

    def delete(self):
        if 0 <= self.cur < len(self.items):
            del self.items[self.cur]
            self.cur = -1
            self.refill(self.list.currentRow())

    def save(self):
        self.commit()
        self.ai.save_prompts(self.items)
        self.accept()


# ═════════════════════ чат в облачке ═════════════════════
class InputBox(QPlainTextEdit):
    submit = pyqtSignal()
    pasted_image = pyqtSignal(object)
    escape = pyqtSignal()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.escape.emit()
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submit.emit()
            return
        super().keyPressEvent(e)

    def canInsertFromMimeData(self, src):
        return src.hasImage() or src.hasUrls() or super().canInsertFromMimeData(src)

    def insertFromMimeData(self, src):
        if src.hasImage():
            img = src.imageData()
            if isinstance(img, QImage) and not img.isNull():
                self.pasted_image.emit(img)
                return
        if src.hasUrls() and all(u.isLocalFile() for u in src.urls()):
            self.pasted_image.emit([u.toLocalFile() for u in src.urls()])
            return
        super().insertFromMimeData(src)


class ChatBubble(QWidget):
    """Чат прямо в облачке над крабом: здесь же он отвечает и здесь же вы пишете."""
    MAX_STEPS = 12
    W, PAD, TAIL, SH = 440, 12, 14, 8          # ширина, поля, хвостик, место под тень
    # светлая «няшная» палитра; задана явно, чтобы тёмная тема Windows не делала белый текст на белом
    BG, BORDER, ACCENT, ACCENT2 = "#FFF8F3", "#F0C9B5", "#D9774F", "#B85C3A"
    TEXT, MUTED, USER_BG, BOT_BORDER = "#3B2B24", "#A08A7E", "#FFE1D1", "#F3DDD0"
    CSS_USER = "background:#FFE1D1; color:#3B2B24; border-radius:14px; padding:8px 12px;"
    CSS_BOT = "background:#FFFFFF; color:#3B2B24; border:1px solid #F3DDD0; border-radius:14px; padding:8px 12px;"
    CSS_MENU = ("QMenu{background:#FFF8F3; color:#3B2B24; border:1px solid #F0C9B5; padding:4px;}"
                "QMenu::item{padding:6px 22px 6px 22px; border-radius:6px;}"
                "QMenu::item:selected{background:#FBE1D3; color:#3B2B24;}"
                "QMenu::item:disabled{color:#C9B6AB;}"
                "QMenu::separator{height:1px; background:#F0D8CB; margin:4px 8px;}")
    QUIET = ("думаю…", "пишет…", "размышляет…", "думаю дальше…")      # это видно в самом облачке

    def __init__(self, ai):
        super().__init__()
        self.ai = ai
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setWindowTitle("Клодик")
        self.path = os.path.join(DATA_DIR, "chats.json")
        self.chats, self.cur, self.busy, self.dirty = [], 0, False, False
        self.atts, self.state, self.rows = [], {}, []
        self.want_shot = False
        self.status_text = ""
        self.tail_x, self.below = 40, False
        self.stop = threading.Event()
        self.bridge = Bridge()
        self.sig = Sig()
        self.sig.text.connect(self.on_text)
        self.sig.think.connect(self.on_think)
        self.sig.tool.connect(self.on_tool)
        self.sig.step.connect(lambda: None)
        self.sig.done.connect(self.on_done)
        self.sig.failed.connect(self.on_failed)
        self.sig.notice.connect(self.set_status)
        self.sig.models.connect(self.on_models)
        self.st_timer = QTimer(self)
        self.st_timer.setSingleShot(True)
        self.st_timer.timeout.connect(lambda: self.set_status(""))

        pal = self.palette()
        for role, col in ((QPalette.ColorRole.Window, self.BG), (QPalette.ColorRole.Base, "#FFFFFF"),
                          (QPalette.ColorRole.AlternateBase, self.BG), (QPalette.ColorRole.Text, self.TEXT),
                          (QPalette.ColorRole.WindowText, self.TEXT), (QPalette.ColorRole.ButtonText, self.TEXT),
                          (QPalette.ColorRole.Button, self.BG), (QPalette.ColorRole.PlaceholderText, self.MUTED),
                          (QPalette.ColorRole.Highlight, "#F6C9B3"), (QPalette.ColorRole.HighlightedText, self.TEXT),
                          (QPalette.ColorRole.Link, self.ACCENT2), (QPalette.ColorRole.ToolTipBase, "#FFFFFF"),
                          (QPalette.ColorRole.ToolTipText, self.TEXT)):
            pal.setColor(role, QColor(col))
        self.setPalette(pal)
        fnt = QFont("Segoe UI")
        fnt.setPixelSize(14)
        self.setFont(fnt)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        self.set_margins()
        # шапка: краб, имя, модель (нажать — переключить), меню, закрыть
        head = QHBoxLayout()
        head.setSpacing(6)
        self.title = QLabel("🦀 <b>Клодик</b>")
        self.title.setStyleSheet("color:%s; font-size:15px;" % self.ACCENT2)
        self.b_model = QToolButton()
        self.b_model.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_model.setStyleSheet("QToolButton{background:#FBE7DC; color:%s; border:none; border-radius:10px;"
                                   "padding:2px 9px; font-size:12px;} QToolButton:hover{background:#F8D9C8;}"
                                   % self.ACCENT2)
        self.b_model.clicked.connect(self.toggle_slot)
        self.b_menu = self.round_btn("⋯", "Разговоры, промпты, настройки")
        self.b_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self)
        self.menu.setStyleSheet(self.CSS_MENU)
        self.menu.aboutToShow.connect(self.fill_menu)
        self.b_menu.setMenu(self.menu)
        b_close = self.round_btn("✕", "Закрыть (Esc или клик по крабу)")
        b_close.clicked.connect(self.hide)
        head.addWidget(self.title)
        head.addWidget(self.b_model)
        head.addStretch(1)
        head.addWidget(self.b_menu)
        head.addWidget(b_close)
        root.addLayout(head)
        self.sub = QLabel("")
        self.sub.setWordWrap(True)
        self.sub.setStyleSheet("color:%s; font-size:12px;" % self.MUTED)
        self.sub.hide()
        root.addWidget(self.sub)
        # переписка
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}"
                                  "QScrollBar:vertical{width:6px; background:transparent; margin:2px;}"
                                  "QScrollBar::handle:vertical{background:#EBC8B6; border-radius:3px; min-height:24px;}"
                                  "QScrollBar::add-line, QScrollBar::sub-line{height:0;}"
                                  "QScrollBar::add-page, QScrollBar::sub-page{background:transparent;}")
        self.scroll.viewport().setAutoFillBackground(False)
        self.inner = QWidget()
        self.inner.setAutoFillBackground(False)
        self.inner.setStyleSheet("background:transparent;")
        self.vbox = QVBoxLayout(self.inner)
        self.vbox.setContentsMargins(0, 0, 6, 0)
        self.vbox.setSpacing(8)
        self.scroll.setWidget(self.inner)
        self.scroll.setFixedHeight(80)
        root.addWidget(self.scroll, 1)
        self.attbar = QLabel("")
        self.attbar.setWordWrap(True)
        self.attbar.setStyleSheet("color:%s; font-size:12px; padding:0 4px;" % self.ACCENT2)
        self.attbar.setTextFormat(Qt.TextFormat.RichText)
        self.attbar.linkActivated.connect(self.clear_atts)
        self.attbar.hide()
        root.addWidget(self.attbar)
        # ввод: белая «таблетка» с полем и скрепкой + круглая кнопка отправки
        row = QHBoxLayout()
        row.setSpacing(8)
        pill = QFrame()
        pill.setObjectName("pill")
        pill.setStyleSheet("#pill{background:#FFFFFF; border:1.5px solid %s; border-radius:18px;}" % self.BORDER)
        pl = QHBoxLayout(pill)
        pl.setContentsMargins(10, 2, 4, 2)
        pl.setSpacing(2)
        self.input = InputBox()
        self.input.setPlaceholderText("Напиши Клодику…")
        self.input.setStyleSheet("QPlainTextEdit{background:transparent; border:none; color:%s;"
                                 "selection-background-color:#F6C9B3; selection-color:%s;}" % (self.TEXT, self.TEXT))
        self.input.setPalette(pal)
        self.input.setFrameShape(QFrame.Shape.NoFrame)
        self.input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.input.setFixedHeight(34)
        self.input.textChanged.connect(self.fit_input)
        self.input.submit.connect(self.send)
        self.input.pasted_image.connect(self.on_paste)
        self.input.escape.connect(self.on_escape)
        self.b_att = self.round_btn("📎", "Приложить файл или снимок экрана")
        self.b_att.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        am = QMenu(self)
        am.setStyleSheet(self.CSS_MENU)
        am.addAction("📄  Файлы…", self.pick_files)
        am.addAction("🖼  Снимок экрана", self.add_shot)
        self.b_att.setMenu(am)
        pl.addWidget(self.input, 1)
        pl.addWidget(self.b_att, 0, Qt.AlignmentFlag.AlignBottom)
        self.btn = QToolButton()
        self.btn.setFixedSize(38, 38)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self.send)
        self.set_send(False)
        row.addWidget(pill, 1)
        row.addWidget(self.btn, 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(row)

        self.setFixedWidth(self.W)
        self.tm = QTimer(self)
        self.tm.timeout.connect(self.flush)
        self.tm.start(100)
        self.load()
        if not self.chats:
            self.chats.append(dict(title="Новый разговор", msgs=[]))
            self.cur = 0
        self.sync_slot()
        self.rebuild()
        if ai.models_cache:
            self.on_models(ai.models_cache, "")
        else:
            self.refresh_models(auto=True)

    def round_btn(self, text, tip):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setAutoRaise(True)
        b.setFixedSize(28, 28)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet("QToolButton{border:none; border-radius:14px; font-size:14px; color:%s;}"
                        "QToolButton:hover{background:#FBE1D3;}"
                        "QToolButton::menu-indicator{image:none; width:0;}" % self.MUTED)
        return b

    def set_send(self, busy):
        self.btn.setText("■" if busy else "➤")
        self.btn.setToolTip("Остановить (Esc)" if busy else "Отправить (Enter)")
        self.btn.setStyleSheet("QToolButton{background:%s; color:white; border:none; border-radius:19px;"
                               "font-size:16px; font-weight:bold;} QToolButton:hover{background:%s;}"
                               % ((self.MUTED, "#8C766A") if busy else (self.ACCENT, self.ACCENT2)))

    def set_margins(self):
        S, P, T = self.SH, self.PAD, self.TAIL
        self.layout().setContentsMargins(S + P, S + P + (T if self.below else 0),
                                         S + P, S + P + (0 if self.below else T))

    # --- окно-облачко ---
    def panel(self):
        w, h, S, T = self.width(), self.height(), self.SH, self.TAIL
        top = S + (T if self.below else 0)
        rect = QRectF(S, top, w - 2 * S, h - 2 * S - T)
        tail = QPainterPath()
        tx = self.tail_x
        if self.below:
            tail.moveTo(tx - 11, top + 2)
            tail.lineTo(tx, S)
            tail.lineTo(tx + 11, top + 2)
        else:
            bot = rect.bottom()
            tail.moveTo(tx - 11, bot - 2)
            tail.lineTo(tx, bot + T)
            tail.lineTo(tx + 11, bot - 2)
        tail.closeSubpath()
        path = QPainterPath()
        path.addRoundedRect(rect, 20, 20)
        return rect, path.united(tail)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect, path = self.panel()
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(self.SH - 1, 0, -1):             # мягкая тень под облачком
            p.setBrush(QColor(140, 80, 50, 4 + 3 * (self.SH - i)))
            p.drawRoundedRect(rect.adjusted(-i, -i + 2, i, i + 2), 20 + i, 20 + i)
        p.setPen(QPen(QColor(self.BORDER), 1.5))
        p.setBrush(QColor(self.BG))
        p.drawPath(path)
        p.end()

    def room(self):
        """Экран краба и сколько места над и под ним."""
        pet = self.ai.pet
        ax, ay = pet.x, pet.y - 12 * pet.U
        scr = QGuiApplication.screenAt(QPoint(int(ax), int(pet.y - 2))) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        return g, ax, ay, ay - g.top() - 4, g.top() + g.height() - (pet.y + 2) - 4

    def place(self):
        """Держаться над крабом (или под ним, если сверху тесно), не заслонять его и не вылезать за экран."""
        g, ax, ay, up, down = self.room()
        w, h = self.width(), self.height()
        below = h - self.SH > up and down > up
        if below != self.below:
            self.below = below
            self.set_margins()
            return self.fit_height()
        x = clamp(ax - w / 2, g.left() + 4 - self.SH, g.left() + g.width() - w + self.SH - 4)
        y = (self.ai.pet.y + 2 - self.SH) if below else ay - h + self.SH
        y = clamp(y, g.top() - self.SH, g.top() + g.height() - h + self.SH)
        tx = clamp(ax - x, 30, w - 30)
        if (int(x), int(y)) != (self.x(), self.y()) or abs(tx - self.tail_x) > 0.5:
            self.tail_x = tx
            self.move(int(x), int(y))
            self.update()

    def fit_height(self):
        g, ax, ay, up, down = self.room()
        self.layout().activate()
        self.vbox.activate()
        chrome = self.layout().sizeHint().height() - self.scroll.maximumHeight()
        max_list = max(90, min(int(g.height() * 0.55), max(up, down) + self.SH - chrome))
        vw = min(self.scroll.viewport().width(), self.W - 2 * (self.SH + self.PAD)) - 6
        lay = self.vbox
        want = (lay.heightForWidth(vw) if lay.hasHeightForWidth() and vw > 50 else self.inner.sizeHint().height()) + 4
        self.scroll.setFixedHeight(int(clamp(want, 60, max_list)))
        self.adjustSize()
        self.place()

    def fit_input(self):
        lines = max(1, int(self.input.document().size().height()))
        self.input.setFixedHeight(int(clamp(lines * QFontMetrics(self.input.font()).lineSpacing() + 14, 34, 130)))
        if self.isVisible():
            self.fit_height()

    def open(self):
        self.fit_height()
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()
        QTimer.singleShot(0, self.fit_height)
        QTimer.singleShot(0, self.scroll_end)

    def on_escape(self):
        if self.busy:
            self.stop.set()
        else:
            self.hide()

    # --- хранение ---
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self.chats = [c for c in json.load(f) if isinstance(c, dict)][-80:]
        except Exception:
            self.chats = []
        for c in self.chats:
            c["msgs"] = [m for m in c.get("msgs", []) if not m.get("remark")]   # старые «👀»-комментарии зрения
            for m in c["msgs"]:                      # старый формат v2
                if m.get("role") == "assistant" and "parts" not in m:
                    m["parts"] = [dict(t="text", v=m.get("content", ""))]
        self.cur = max(0, len(self.chats) - 1)

    def save(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.chats, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def chat(self):
        return self.chats[self.cur]

    def new_chat(self):
        if self.busy:
            return
        if not self.chat()["msgs"]:
            return self.input.setFocus()
        self.chats.append(dict(title="Новый разговор", msgs=[]))
        self.cur = len(self.chats) - 1
        self.save()
        self.rebuild()
        self.input.setFocus()

    def switch_chat(self, i):
        if not self.busy and 0 <= i < len(self.chats):
            self.cur = i
            self.rebuild()

    def rename_chat(self):
        if self.busy:
            return
        t, ok = QInputDialog.getText(self, "Переименовать разговор", "Название:", text=self.chat()["title"])
        if ok and t.strip():
            self.chat()["title"] = t.strip()
            self.save()

    def delete_chat(self):
        if self.busy:
            return
        if self.chat()["msgs"] and QMessageBox.question(self, "Удалить разговор", "Удалить «%s»?" %
                                                        self.chat()["title"]) != QMessageBox.StandardButton.Yes:
            return
        del self.chats[self.cur]
        if not self.chats:
            self.chats.append(dict(title="Новый разговор", msgs=[]))
        self.cur = len(self.chats) - 1
        self.save()
        self.rebuild()

    def export_chat(self):
        c = self.chat()
        name = re.sub(r'[\\/:*?"<>|]+', "_", c["title"])[:60] or "chat"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить разговор",
                                              os.path.join(os.path.expanduser("~"), name + ".md"), "Markdown (*.md)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# %s\n\n" % c["title"])
                for m in c["msgs"]:
                    who = "Вы" if m["role"] == "user" else "Клодик"
                    f.write("**%s:**\n\n%s\n\n---\n\n" % (who, self.msg_markdown(m, full=True)))
            self.set_status("сохранено")

    # --- меню ⋯ ---
    def fill_menu(self):
        m = self.menu
        m.clear()
        m.addAction("Новый разговор", self.new_chat)
        a = m.addAction("↻ Ответить заново", self.regenerate)
        a.setEnabled(not self.busy and any(x["role"] == "user" for x in self.chat()["msgs"]))
        hist = m.addMenu("Разговоры")
        for i in range(len(self.chats) - 1, max(-1, len(self.chats) - 21), -1):
            a = hist.addAction(self.chats[i]["title"])
            a.setCheckable(True)
            a.setChecked(i == self.cur)
            a.triggered.connect(lambda _=False, i=i: self.switch_chat(i))
        m.addAction("Переименовать…", self.rename_chat)
        m.addAction("Сохранить в файл…", self.export_chat)
        m.addAction("Удалить разговор", self.delete_chat)
        m.addSeparator()
        pm = m.addMenu("Промпты")
        prompts = self.ai.prompts()
        for p in prompts:
            if not p["name"].lower().startswith("роль"):
                pm.addAction(p["name"], lambda t=p["text"]: self.insert_prompt(t))
        pm.addSeparator()
        pm.addAction("Сохранить текст из поля как промпт…", self.save_prompt)
        pm.addAction("Редактировать промпты…", lambda: PromptsDialog(self.ai, self).exec())
        roles = m.addMenu("Роль в этом разговоре")
        a = roles.addAction("— обычный Клодик —", lambda: self.set_role(None))
        a.setCheckable(True)
        a.setChecked(not self.chat().get("role"))
        for p in prompts:
            a = roles.addAction(p["name"], lambda p=p: self.set_role(p))
            a.setCheckable(True)
            a.setChecked(self.chat().get("role_name") == p["name"])
        m.addSeparator()
        a = m.addAction("Агент: сам пользуется инструментами")
        a.setCheckable(True)
        a.setChecked(self.ai.get("agent"))
        a.toggled.connect(lambda on: self.ai.set("agent", on))
        a = m.addAction("Показывать размышления модели")
        a.setCheckable(True)
        a.setChecked(self.ai.get("show_think"))
        a.toggled.connect(lambda on: (self.ai.set("show_think", on), self.rebuild()))
        m.addAction("Обновить список моделей", self.refresh_models)
        m.addAction("Настройки ИИ…", self.ai.open_settings)
        m.addSeparator()
        if self.ai.ai_on():
            m.addAction("⏻ Выключить ИИ (выгрузить модели из памяти)", lambda: (self.hide(), self.ai.power_off()))
        else:
            m.addAction("⏻ Включить ИИ", self.ai.power_on)

    def insert_prompt(self, text):
        self.input.setPlainText(text + self.input.toPlainText())
        self.input.setFocus()
        c = self.input.textCursor()
        c.movePosition(c.MoveOperation.End)
        self.input.setTextCursor(c)

    def set_role(self, p):
        c = self.chat()
        if p:
            c["role"], c["role_name"] = p["text"], p["name"]
        else:
            c.pop("role", None)
            c.pop("role_name", None)
        self.save()
        self.sync_slot()

    def save_prompt(self):
        text = self.input.toPlainText().strip()
        if not text:
            return self.set_status("сначала напишите текст промпта")
        name, ok = QInputDialog.getText(self, "Новый промпт", "Название:", text=text[:30])
        if ok and name.strip():
            self.ai.save_prompts(self.ai.prompts() + [dict(name=name.strip(), text=text)])
            self.set_status("промпт сохранён")

    # --- показ переписки ---
    def set_status(self, text, secs=8):
        """Строчка под шапкой: только то, что важно знать (ошибка, подсказка). «Думаю/пишу» видно в облачке."""
        text = shorten((text or "").split("\n")[0].strip(), 110).split("\n")[0]
        if text in self.QUIET:
            text = ""
        self.status_text = text
        self.sync_slot()
        if text and secs:
            self.st_timer.start(int(secs * 1000))

    def sync_slot(self):
        slot = self.ai.slot()
        names = self.ai.slot_names()
        model = self.ai.model()
        short = (model or "модель не выбрана").split("/")[-1]
        self.b_model.setText(("⚡ " if slot == "main" else "🪶 ") + shorten(short, 24).split("\n")[0])
        self.b_model.setToolTip("Сейчас: %s модель (%s).\nНажмите, чтобы переключить на %s (%s)." % (
            "основная" if slot == "main" else "лёгкая", model or "не выбрана",
            "лёгкую" if slot == "main" else "основную", names["light" if slot == "main" else "main"] or "не выбрана"))
        bits = []
        if self.chat().get("role_name"):
            bits.append("роль: " + self.chat()["role_name"])
        if self.status_text:
            bits.append(self.status_text)
        txt = " · ".join(bits)
        if txt != self.sub.text():
            self.sub.setText(txt)
            self.sub.setVisible(bool(txt))
            if self.isVisible():
                QTimer.singleShot(0, self.fit_height)

    def toggle_slot(self):
        self.ai.set_slot("light" if self.ai.slot() == "main" else "main")

    def msg_markdown(self, m, full=False):
        show_think = self.ai.get("show_think") or full
        body = []
        for p in m.get("parts", []):
            if p["t"] == "text":
                txt, th = split_think(p["v"])
                if th and show_think:
                    body.append("> 💭 " + shorten(th, 2000).replace("\n", "\n> "))
                if txt:
                    body.append(txt)
            elif p["t"] == "think":
                if show_think:
                    body.append("> 💭 " + shorten(p["v"], 2000).replace("\n", "\n> "))
            elif p["t"] == "tool":
                line = "🔧 *%s* %s" % (p["name"], ("`%s`" % p["brief"]) if p.get("brief") else "")
                if p.get("res") is None:
                    line += " …"
                else:
                    line += " → " + (p["res"].strip().splitlines() or [""])[0][:120].replace("`", "'")
                body.append(line)
            elif p["t"] == "note":
                body.append("*%s*" % p["v"])
        if m.get("_thinking") and not show_think:
            body.append("*💭 думает…*")
        return "\n\n".join(body)

    def make_row(self, m):
        lab = QLabel()
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse |
                                    Qt.TextInteractionFlag.LinksAccessibleByMouse)
        lab.setOpenExternalLinks(True)
        lab.setMaximumWidth(int(self.W * 0.8))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if m is None:                                         # приветствие в пустом разговоре
            lab.setText("Привет! Я Клодик 🦀\nПиши прямо сюда, я отвечу здесь же. "
                        "Файл можно перетащить на облачко, а через 📎 показать мне экран.")
            lab.setStyleSheet(self.CSS_BOT)
            row.addWidget(lab)
            row.addStretch(1)
        elif m["role"] == "user":
            lab.setTextFormat(Qt.TextFormat.PlainText)
            lab.setStyleSheet(self.CSS_USER)
            row.addStretch(1)
            row.addWidget(lab)
        else:
            lab.setTextFormat(Qt.TextFormat.MarkdownText)
            lab.setStyleSheet(self.CSS_BOT)
            row.addWidget(lab)
            row.addStretch(1)
        self.vbox.addLayout(row)
        lab.show()                     # иначе Qt покажет его только в следующем цикле и высота будет 0
        return lab

    def label_text(self, m):
        if m["role"] == "user":
            extra = (["🖼 экран"] if m.get("shot") else []) + ["📎 " + a["name"] for a in m.get("atts", [])]
            return m["content"] + (("\n" + ", ".join(extra)) if extra else "")
        return self.msg_markdown(m) or "…"

    def rebuild(self):
        """Пересобрать пузыри сообщений целиком (смена разговора, новое сообщение)."""
        while self.vbox.count():
            it = self.vbox.takeAt(0)
            lay = it.layout()
            if lay:
                while lay.count():
                    w = lay.takeAt(0).widget()
                    if w:
                        w.hide()
                        w.setParent(None)
                        w.deleteLater()
        self.rows = []
        msgs = self.chat()["msgs"][-40:]
        if not msgs:
            self.make_row(None)
        fm = QFontMetrics(self.font())
        for m in msgs:
            lab = self.make_row(m)
            text = self.label_text(m)
            lab.setText(text)
            if m["role"] == "user":                   # короткие реплики — в одну строку, без узкого столбика
                lab.setMinimumWidth(min(lab.maximumWidth(),
                                        max(fm.horizontalAdvance(t) for t in text.split("\n")) + 24))
            self.rows.append((m, lab, text))
        self.vbox.addStretch(1)
        self.sync_slot()
        if self.isVisible():
            self.fit_height()
            QTimer.singleShot(0, self.scroll_end)

    def scroll_end(self):
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def flush(self):
        if not self.dirty:
            return
        self.dirty = False
        msgs = self.chat()["msgs"][-40:]
        if len(msgs) != len(self.rows) or any(r[0] is not m for r, m in zip(self.rows, msgs)):
            return self.rebuild()
        sb = self.scroll.verticalScrollBar()
        at_end = sb.value() >= sb.maximum() - 40
        for k, (m, lab, old) in enumerate(self.rows):
            text = self.label_text(m)
            if text != old:
                lab.setText(text)
                self.rows[k] = (m, lab, text)
        if self.isVisible():
            self.fit_height()
            if at_end:
                QTimer.singleShot(0, self.scroll_end)

    # --- модели ---
    def refresh_models(self, auto=False):
        ai = self.ai

        def work():
            note = ""
            try:
                ms = ai.client().models()
            except LLMError as e:
                found = ai.autodetect() if auto else None
                if not found:
                    self.sig.models.emit([], "⚠ " + str(e).split("\n")[0][:120])
                    return
                ms, note = found
            self.sig.models.emit(ms, note)

        threading.Thread(target=work, daemon=True).start()

    def on_models(self, models, note):
        if models:
            self.ai.models_cache = models
            self.ai.auto_pick(models)
        self.set_status(note)

    # --- вложения ---
    def pick_files(self):
        fs, _ = QFileDialog.getOpenFileNames(self, "Приложить файлы", self.ai.get("workdir"),
                                             "Все файлы (*.*);;Текст и код (*.txt *.md *.py *.js *.json *.csv);;"
                                             "Документы (*.pdf *.docx *.xlsx *.pptx);;Картинки (*.png *.jpg *.jpeg *.webp)")
        self.add_files(fs)
        self.activateWindow()

    def add_files(self, files):
        for fp in files:
            if os.path.isdir(fp):
                self.atts.append(dict(name=os.path.basename(fp) + "\\", kind="text",
                                      text=ToolBox(self.ai, self.bridge, {}).t_list_dir(fp)))
                continue
            ext = os.path.splitext(fp)[1].lower()
            if ext in IMG_EXT:
                b64 = load_image_b64(fp)
                if b64:
                    self.atts.append(dict(name=os.path.basename(fp), kind="image", b64=b64))
                continue
            text = read_any(fp, limit=min(60000, self.ai.get("ctx_chars")))
            self.atts.append(dict(name=os.path.basename(fp), kind="text", text=text, path=fp))
        self.show_atts()

    def on_paste(self, obj):
        if isinstance(obj, list):
            self.add_files(obj)
        else:
            self.atts.append(dict(name="картинка из буфера", kind="image",
                                  b64=to_jpeg_b64(obj.convertToFormat(QImage.Format.Format_RGB32), 85)))
            self.show_atts()

    def add_shot(self):
        self.want_shot = True
        self.show_atts()
        self.input.setFocus()

    def clear_atts(self, *_):
        self.atts, self.want_shot = [], False
        self.show_atts()

    def show_atts(self):
        names = (["🖼 снимок экрана"] if self.want_shot else []) + ["📎 " + a["name"] for a in self.atts]
        if not names:
            self.attbar.hide()
        else:
            self.attbar.setText("%s &nbsp; <a href='x' style='color:%s'>✕ убрать</a>" % (
                html.escape(", ".join(names)), self.MUTED))
            self.attbar.show()
        if self.isVisible():
            self.fit_height()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_files([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    # --- отправка ---
    def send(self):
        if self.busy:
            self.stop.set()
            self.set_status("останавливаю…")
            return
        text = self.input.toPlainText().strip()
        if not text and not self.atts and not self.want_shot:
            return
        if not self.ai.model():
            self.set_status("выберите модель: ⋯ → Настройки ИИ", 0)
            return
        if not self.ai.ai_on():
            self.ai.power_on(quiet=True)
            self.set_status("ИИ снова включён", 4)
        if self.want_shot:
            self.setWindowOpacity(0.0)
            QApplication.processEvents()
            QTimer.singleShot(250, lambda: self.go(text, True))
        else:
            self.go(text, False)

    def go(self, text, with_shot):
        images = []
        if with_shot:
            images.append(to_jpeg_b64(grab_screen()))
            self.setWindowOpacity(1.0)
        images += [a["b64"] for a in self.atts if a["kind"] == "image"]
        chat = self.chat()
        user = dict(role="user", content=text or "(смотри вложения)", shot=with_shot,
                    atts=[dict(name=a["name"], kind=a["kind"], text=a.get("text", "")) for a in self.atts])
        chat["msgs"].append(user)
        if len([m for m in chat["msgs"] if m["role"] == "user"]) == 1:
            t = text or (self.atts[0]["name"] if self.atts else "Разговор")
            chat["title"] = (t[:34] + "…") if len(t) > 34 else t
        self.input.clear()
        self.atts, self.want_shot = [], False
        self.show_atts()
        self.start(images)

    def regenerate(self):
        if self.busy:
            return
        msgs = self.chat()["msgs"]
        while msgs and msgs[-1]["role"] == "assistant":
            msgs.pop()
        if msgs:
            self.start([])

    def start(self, images):
        chat = self.chat()
        model = self.ai.model()
        chat["msgs"].append(dict(role="assistant", parts=[], model=model, _thinking=1))
        self.busy = True
        self.stop.clear()
        self.state = dict(allow_all=False)
        self.set_send(True)
        self.set_status("")
        self.rebuild()
        agent = self.ai.get("agent")
        payload = self.api_messages(chat, images, agent)
        tools = tool_specs(self.ai.pet_actions(), self.ai.drawings()) if agent else None
        cli, temp, mt = self.ai.client(), self.ai.get("temperature"), answer_limit(self.ai.get("max_tokens"))
        self.finish_reason = ""
        box = ToolBox(self.ai, self.bridge, self.state)
        mem = self.ai.mem
        self.ai.t_chat = time.time()

        def work():
            mem.acquire(cli, model, note=self.sig.notice.emit)   # вторую модель — выгрузить
            try:
                self.run_agent(cli, model, payload, tools, temp, mt, box)
                self.sig.done.emit()
            except LLMError as e:
                self.sig.failed.emit(str(e))
            except Exception as e:
                self.sig.failed.emit("Внутренняя ошибка: %r" % e)
            finally:
                mem.release(model)

        threading.Thread(target=work, daemon=True).start()

    def run_agent(self, cli, model, msgs, tools, temp, mt, box):
        steps = 0
        while True:
            try:
                res = cli.stream(model, msgs, self.sig.text.emit, self.sig.think.emit, self.stop,
                                 tools=tools, temperature=temp, max_tokens=mt)
            except LLMError as e:
                if tools and e.code in (400, 422, 500) and "tool" in (e.body or "").lower():
                    tools = None
                    self.sig.notice.emit("модель не умеет инструменты — отвечаю без них")
                    continue
                raise
            self.finish_reason = res.get("finish") or ""
            calls = res["calls"] or (text_tool_calls(res["content"]) if tools else [])
            if not calls or self.stop.is_set():
                return
            steps += 1
            if steps > self.MAX_STEPS:
                self.sig.tool.emit(dict(kind="note", v="Остановился: слишком много шагов подряд."))
                return
            content = TOOLTAG_RE.sub("", res["content"]).strip()
            msgs.append({"role": "assistant", "content": content,
                         "tool_calls": [{"id": c["id"], "type": "function",
                                         "function": {"name": c["name"], "arguments": c["args"] or "{}"}}
                                        for c in calls]})
            images = []
            for c in calls:
                if self.stop.is_set():
                    return
                brief = tool_brief(c["name"], c["args"])
                self.sig.tool.emit(dict(kind="start", name=c["name"], brief=brief))
                out, img = box.run(c["name"], c["args"])
                self.sig.tool.emit(dict(kind="done", res=out))
                msgs.append({"role": "tool", "tool_call_id": c["id"], "content": shorten(out, 24000)})
                if img:
                    images.append(img)
            if images:
                msgs.append({"role": "user", "content": [{"type": "text", "text": "Картинка из инструмента:"}] +
                             [image_part(b) for b in images]})
            self.sig.step.emit()

    def api_messages(self, chat, images, agent):
        system = self.ai.system_prompt(chat.get("role"), agent)
        budget = max(4000, self.ai.get("ctx_chars") - len(system))
        hist = chat["msgs"][:-1]
        out, total = [], 0
        for i in range(len(hist) - 1, -1, -1):          # с конца, пока влезает в лимит
            m = hist[i]
            if m.get("remark"):
                continue
            if m["role"] == "user":
                c = m["content"]
                for a in m.get("atts", []):
                    if a["kind"] == "text":
                        c += "\n\n📎 Файл «%s»:\n```\n%s\n```" % (a["name"], a["text"])
            else:
                c = "\n\n".join(clean_think(p["v"]) for p in m.get("parts", []) if p["t"] == "text").strip()
                used = [p["name"] for p in m.get("parts", []) if p["t"] == "tool"]
                if used and not c:
                    c = "(использовал инструменты: %s)" % ", ".join(used)
                if not c:
                    continue
            if total + len(c) > budget and out:
                break
            if total + len(c) > budget:
                c = c[-budget:]
            total += len(c)
            if i == len(hist) - 1 and images:
                out.append(dict(role="user", content=[dict(type="text", text=c)] + [image_part(b) for b in images]))
            else:
                out.append(dict(role=m["role"], content=c))
        out.reverse()
        while out and out[0]["role"] == "assistant":     # история должна начинаться с вопроса
            out.pop(0)
        merged = []                                      # строгие шаблоны (Gemma и др.) требуют чередования ролей
        for m in out:
            if merged and merged[-1]["role"] == m["role"]:
                a, b = merged[-1]["content"], m["content"]
                if isinstance(a, str) and isinstance(b, str):
                    merged[-1] = dict(role=m["role"], content=a + "\n\n" + b)
                else:
                    parts = lambda c: c if isinstance(c, list) else [dict(type="text", text=c)]
                    merged[-1] = dict(role=m["role"], content=parts(a) + parts(b))
            else:
                merged.append(m)
        return [dict(role="system", content=system)] + merged

    # --- приём ответа (главный поток) ---
    def cur_msg(self):
        return self.chats[self.cur]["msgs"][-1]

    def on_text(self, d):
        m = self.cur_msg()
        parts = m["parts"]
        if not parts or parts[-1]["t"] != "text":
            parts.append(dict(t="text", v=""))
        parts[-1]["v"] += d
        m.pop("_thinking", None)
        self.ai.pet.talking = max(self.ai.pet.talking, 0.6)
        self.dirty = True
        if self.status_text.startswith("загружаю"):
            self.set_status("")

    def on_think(self, d):
        m = self.cur_msg()
        parts = m["parts"]
        if not parts or parts[-1]["t"] != "think":
            parts.append(dict(t="think", v=""))
        parts[-1]["v"] += d
        m["_thinking"] = 1
        self.dirty = True
        if self.status_text.startswith("загружаю"):
            self.set_status("")

    def on_tool(self, ev):
        parts = self.cur_msg()["parts"]
        if ev["kind"] == "start":
            parts.append(dict(t="tool", name=ev["name"], brief=ev["brief"], res=None))
        elif ev["kind"] == "done":
            for p in reversed(parts):
                if p["t"] == "tool" and p["res"] is None:
                    p["res"] = shorten(ev["res"], 600)
                    break
        elif ev["kind"] == "note":
            parts.append(dict(t="note", v=ev["v"]))
        self.dirty = True

    def finish(self):
        self.busy = False
        self.ai.t_chat = time.time()
        self.cur_msg().pop("_thinking", None)
        self.set_send(False)
        self.save()
        self.rebuild()

    def on_done(self):
        m = self.cur_msg()
        cut = getattr(self, "finish_reason", "") == "length" and not self.stop.is_set()
        if not any(p["t"] in ("text", "tool") and (p.get("v") or p["t"] == "tool") for p in m["parts"]):
            m["parts"].append(dict(t="note", v="(остановлено)" if self.stop.is_set() else
                                   "(ответ не уместился в лимит длины — модель всё потратила на раздумья; "
                                   "увеличьте «Макс. длина ответа» в настройках ИИ или поставьте 0)" if cut else
                                   "(пустой ответ)"))
        elif cut:
            m["parts"].append(dict(t="note", v="(ответ обрезан лимитом длины — см. «Макс. длина ответа» в настройках ИИ)"))
        self.set_status("остановлено" if self.stop.is_set() else "")
        self.finish()
        if not self.isVisible():                         # облачко-чат закрыли — скажет коротко
            txt = clean_think("".join(p["v"] for p in m["parts"] if p["t"] == "text"))
            if txt:
                self.ai.pet.speak(shorten(txt, 180).split("\n…")[0])

    def on_failed(self, err):
        self.cur_msg()["parts"].append(dict(t="note", v="⚠️ " + err))
        self.set_status("")
        self.finish()

    def closeEvent(self, e):
        e.ignore()
        self.hide()


def tool_brief(name, args):
    try:
        a = json.loads(args) if args else {}
    except ValueError:
        return args[:80]
    if not isinstance(a, dict):
        return ""
    for k in ("path", "command", "url", "target", "folder", "fact", "action"):
        if a.get(k):
            v = str(a[k]).replace("\n", " ")
            if k == "folder" and a.get("pattern"):
                v += " · " + str(a["pattern"])
            return v[:90] + ("…" if len(v) > 90 else "")
    return ""


# ═════════════════════ горячая клавиша ═════════════════════
class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, cb):
        super().__init__()
        self.cb = cb

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            try:
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0312 and msg.wParam == 1:
                    self.cb()
            except Exception:
                pass
        return False, 0


# ═════════════════════ мозг питомца ═════════════════════
class AIBrain(QObject):
    comment = pyqtSignal(str, bool)
    comment_failed = pyqtSignal(str)
    power_note = pyqtSignal(str)
    vision_note = pyqtSignal(str)

    def __init__(self, pet, cfg):
        super().__init__()
        self.pet, self.cfg = pet, cfg
        self.migrate()
        self.bubble = Bubble()
        self.chat = None
        self.busy = False
        self.last_thumb = None
        self.recent = []
        self.fails = 0
        self.models_cache = []
        self.mem = ModelMemory(self)
        self.no_ctk = False                    # сервер не принимает chat_template_kwargs
        self.no_effort = False                 # сервер не принимает reasoning_effort
        self.thinkers = set()                  # модели, которые думают, даже когда просим не думать
        self.warned_think = set()
        self.t_chat = 0.0                      # когда последний раз говорили в чате
        self.next_look = time.time() + 30
        self.comment.connect(self.on_comment)
        self.comment_failed.connect(self.on_fail)
        self.vision_note.connect(lambda t: self.pet.notify(t))
        self.power_note.connect(self.on_power_note)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.vision_tick)
        self.timer.start(1000)
        self.hotkey = None
        if IS_WIN:
            try:
                if ctypes.windll.user32.RegisterHotKey(None, 1, 0x4003, 0x20):   # Ctrl+Alt+Space
                    self.hotkey = HotkeyFilter(self.toggle_chat)
                    QApplication.instance().installNativeEventFilter(self.hotkey)
            except Exception:
                self.hotkey = None

    # --- настройки ---
    def get(self, key):
        d = DEFAULTS[key]
        try:
            return self.cfg.value("ai/" + key, d, type=type(d))
        except (TypeError, ValueError):
            return d

    def set(self, key, val):
        self.cfg.setValue("ai/" + key, val)

    def migrate(self):
        """Настройки v2 -> v3: одна модель стала «основной», старый короткий характер — предысторией."""
        c = self.cfg
        if c.contains("ai/model") and not c.contains("ai/model_main"):
            c.setValue("ai/model_main", c.value("ai/model", ""))
        if c.contains("ai/system") and (c.value("ai/system", "") or "").strip() == OLD_PERSONA:
            c.setValue("ai/system", "")
        if not answer_limit(c.value("ai/max_tokens", 0)) and c.value("ai/max_tokens", 0) not in (0, "0", None):
            c.setValue("ai/max_tokens", 0)                    # лимит в 1–255 токенов обрывал ответ на первой букве
        b = c.value("ai/backstory", "") or ""                # v4: краб умеет искать в интернете
        old = "у тебя есть инструменты: ты можешь читать файлы и папки, искать файлы, открывать веб-страницы,"
        if old in b:
            b = b.replace("остаётся на этом компьютере. Свежих", "остаётся на этом компьютере (в интернет уходят "
                          "только твои поисковые запросы). Свежих")
            c.setValue("ai/backstory", b.replace("Свежих новостей ты не знаешь", "Свежих новостей ты сам не знаешь").replace(
                old, "у тебя есть инструменты: ты можешь искать в интернете и читать веб-страницы, читать файлы и "
                     "папки, искать файлы,"))

    def client(self):
        """Клиент сервера. LM Studio получает ttl: модель сама выгрузится, если долго не нужна."""
        extra, mins = {}, self.get("ttl_min")
        flavor = self.mem.flavor if self.mem.flavor is not None else ("lms" if ":1234" in self.get("base_url") else "")
        if mins > 0 and flavor in ("lms", "lms0"):
            extra["ttl"] = int(mins * 60)
        return LLMClient(self.get("base_url"), self.get("api_key"), extra=extra)

    # --- выключатель ИИ ---
    def ai_on(self):
        return bool(self.get("power"))

    def power_on(self, quiet=False):
        if self.ai_on():
            return
        self.set("power", True)
        self.next_look = time.time() + 20
        if not quiet:
            self.say("ИИ включён. Модель загрузится, когда она понадобится.", 4)

    def power_off(self):
        """Выключить ИИ: остановить ответы и зрение и выгрузить все модели из видеопамяти и ОЗУ."""
        self.set("power", False)
        if self.chat is not None:
            self.chat.stop.set()
        self.say("Выключаю ИИ и выгружаю модели…", 6)
        cli, mem = self.client(), self.mem

        def work():
            t0 = time.time()
            while mem.busy() and time.time() - t0 < 20:     # дать текущим ответам остановиться
                time.sleep(0.3)
            res = mem.unload_all(cli)
            time.sleep(2.5)                                  # вдруг какой-то запрос успел подгрузить модель
            again = mem.unload_all(cli)
            if res is None:
                text = ("ИИ выключен, но выгрузить модели не вышло: сервер не отвечает или не умеет. "
                        "В LM Studio нажмите «Eject» у модели.")
            else:
                done = res[0] + (again[0] if again else [])
                bad = [b for b in res[1] if b not in done]
                if done:
                    text = "ИИ выключен. Выгрузил из памяти: %s." % ", ".join(d.split("/")[-1] for d in done)
                else:
                    text = "ИИ выключен. Моделей в памяти и так не было."
                if bad:
                    text += " Не смог выгрузить: %s." % ", ".join(b.split("/")[-1] for b in bad)
            self.power_note.emit(text)

        threading.Thread(target=work, daemon=True).start()

    def toggle_power(self):
        self.power_off() if self.ai_on() else self.power_on()

    def on_power_note(self, text):
        self.say(text, 8)
        if hasattr(self.pet, "notify") and not self.chat_open():
            self.pet.notify(text)

    def unload_now(self):
        """Кнопка в настройках: выгрузить модели, не выключая ИИ."""
        cli, mem = self.client(), self.mem

        def work():
            res = mem.unload_all(cli)
            self.power_note.emit("Сервер не говорит, какие модели загружены." if res is None else
                                 ("Выгрузил: %s." % ", ".join(d.split("/")[-1] for d in res[0])) if res[0] else
                                 "Моделей в памяти нет.")

        threading.Thread(target=work, daemon=True).start()

    def slot(self):
        return "light" if self.get("slot") == "light" else "main"

    def set_slot(self, slot):
        self.set("slot", slot)
        if self.chat:
            self.chat.sync_slot()
        name = self.model()
        if name and slot == "light" and (params_b(name) or 0) > LIGHT_MAX_B:
            self.pet.notify("Лёгкая модель «%s» больше 4B. %s" % (name, LIGHT_HINT))
        self.say(("Думаю %s моделью: %s" % ("основной" if slot == "main" else "лёгкой", name))
                 if name else "Лёгкая модель ещё не выбрана — загляни в настройки ИИ", 3)

    def slot_names(self):
        return dict(main=self.get("model_main"), light=self.get("model_light"))

    def model(self):
        return self.get("model_" + self.slot())

    def auto_pick(self, models):
        """Первый запуск: основная — Qwen (если есть) или самая крупная; лёгкая — до 4B параметров."""
        ids = [m["id"] for m in models]
        if not ids:
            return
        if not self.get("model_main"):
            qwen = [i for i in ids if "qwen" in i.lower()]
            self.set("model_main", max(qwen or ids, key=lambda i: params_b(i) or 0))
        if not self.get("model_light"):
            main = self.get("model_main")
            small = [i for i in ids if i != main and params_b(i) and params_b(i) <= LIGHT_MAX_B]
            if small:      # из маленьких — сначала видящие картинки, потом свежая Qwen3.5, потом самая крупная
                vis = {m["id"] for m in models if m.get("vision")}
                self.set("model_light", max(small, key=lambda i: (i in vis, "qwen3.5" in i.lower(), params_b(i))))

    def autodetect(self):
        """Если по сохранённому адресу никто не отвечает — поискать LM Studio/Ollama на стандартных портах."""
        for url in PRESETS.values():
            if url == self.get("base_url"):
                continue
            try:
                ms = LLMClient(url).models()
            except LLMError:
                continue
            if ms:
                self.set("base_url", url)
                return ms, "Нашёл сервер: %s" % url
        return None

    def vision_model(self):
        """Зрение по умолчанию работает через лёгкую модель (быстро и не мешает основной)."""
        return self.get("vision_model") or self.get("model_light") or self.model()

    def pet_actions(self):
        return getattr(self.pet, "PET_ACTIONS", ("wave", "dance"))

    def drawings(self):
        return tuple(getattr(self.pet, "DRAWING_NAMES", ()))

    # --- память и промпты ---
    def mem_path(self):
        return os.path.join(DATA_DIR, "memory.txt")

    def read_memory(self):
        try:
            with open(self.mem_path(), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def write_memory(self, text):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(self.mem_path(), "w", encoding="utf-8") as f:
            f.write(text.strip() + "\n" if text.strip() else "")

    def add_memory(self, fact):
        lines = [l for l in self.read_memory().splitlines() if l.strip()]
        if fact not in lines:
            lines.append(fact)
        self.write_memory("\n".join(lines[-200:]))

    def prompts(self):
        try:
            with open(os.path.join(DATA_DIR, "prompts.json"), encoding="utf-8") as f:
                data = json.load(f)
            return [p for p in data if isinstance(p, dict) and "name" in p and "text" in p]
        except Exception:
            return [dict(p) for p in DEFAULT_PROMPTS]

    def save_prompts(self, items):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(os.path.join(DATA_DIR, "prompts.json"), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)

    def system_prompt(self, role=None, agent=False):
        days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
        lt = time.localtime()
        parts = [self.get("backstory") or BACKSTORY]
        if self.get("system").strip():
            parts.append("Правила хозяина:\n" + self.get("system").strip())
        if role:
            parts.append("В этом чате у тебя особая роль:\n" + role)
        mem = self.read_memory().strip()
        if mem:
            parts.append("Что ты помнишь о хозяине:\n" + shorten(mem, 4000))
        parts.append("Сейчас %s, %s. Компьютер: %s %s. Рабочая папка: %s. Твоя модель сейчас: %s." % (
            time.strftime("%d.%m.%Y %H:%M", lt), days[lt.tm_wday], platform.system(), platform.release(),
            self.get("workdir"), self.model()))
        if agent:
            parts.append("Инструменты используй сам, когда они помогают ответить точно: читай файлы вместо "
                         "догадок, ищи файлы, если не знаешь путь. Для свежих фактов (новости, погода, курсы, "
                         "версии программ) ищи в интернете через web_search, нужные страницы читай через fetch_url "
                         "и называй источник. Запись файлов и команды хозяин подтверждает. "
                         "Если узнал о хозяине что-то полезное надолго (имя, проекты, предпочтения) — "
                         "сохрани через remember. После инструментов дай короткий понятный итог.")
        return "\n\n".join(parts)

    def vision_on(self):
        return bool(self.get("vision"))

    def set_vision(self, on):
        if on and not is_local(self.get("base_url")):
            r = QMessageBox.question(None, "Klodik",
                                     "Адрес сервера не локальный:\n%s\n\nСкриншоты экрана будут отправляться "
                                     "туда. Всё равно включить слежение?" % self.get("base_url"))
            if r != QMessageBox.StandardButton.Yes:
                on = False
        m = next((x for x in self.models_cache if x["id"] == self.vision_model()), None)
        if on and m and m.get("vision") is False:
            self.pet.notify("Модель «%s» не видит картинки. %s" % (self.vision_model(), LIGHT_HINT))
        self.set("vision", on)
        if on:
            self.next_look = time.time() + 5
            self.last_thumb = None
            self.fails = 0

    # --- окна ---
    def chat_open(self):
        return bool(self.chat is not None and self.chat.isVisible())

    def open_chat(self):
        """Чат — это облачко над крабом: тут он отвечает, тут же вы пишете."""
        if self.chat is None:
            self.chat = ChatBubble(self)
        self.bubble.hide()
        if hasattr(self.pet, "attend"):
            self.pet.attend()
        self.chat.open()

    def toggle_chat(self):
        if self.chat_open():
            self.chat.hide()
        else:
            self.open_chat()

    def hide_all(self):
        self.bubble.hide()
        if self.chat_open():
            self.chat.hide()

    def say(self, text, secs=None):
        """Короткая реплика краба: в открытом чате — строкой статуса, иначе — в облачке."""
        if self.chat_open():
            self.chat.set_status(text, secs or 6)
            return
        p = self.pet
        self.bubble.anchor = (p.x, p.y - 12 * p.U)
        self.bubble.say(text, secs)

    def open_settings(self):
        SettingsDialog(self, self.chat if self.chat_open() else None).exec()
        if self.chat:
            self.chat.sync_slot()
            self.chat.rebuild()

    def follow(self):
        p = self.pet
        if self.bubble.isVisible():
            self.bubble.anchor = (p.x, p.y - 12 * p.U)
            self.bubble.place()
        if self.chat_open():
            self.chat.place()

    # --- зрение ---
    def vision_tick(self):
        if not self.vision_on() or not self.ai_on() or self.busy or time.time() < self.next_look:
            return
        pet = self.pet
        if pet.hidden_fs or pet.state in ("drag", "sleep") or (self.chat and self.chat.busy):
            return
        if self.chat_open():                 # хозяин говорит с крабом — не встревать с комментариями
            self.next_look = time.time() + 30
            return
        model = self.vision_model()
        cur = self.mem.current
        if (self.get("one_model") and cur and model and cur != model and time.time() - self.t_chat < 300):
            self.next_look = time.time() + 60   # не выбивать из памяти основную модель посреди разговора
            return
        self.next_look = time.time() + self.get("interval") * random.uniform(0.8, 1.3)
        self.look(manual=False)

    def look_now(self):
        """Хозяин сам спросил «что у меня на экране?»."""
        if self.busy:
            return self.say("Сейчас как раз смотрю…", 3)
        self.power_on(quiet=True)
        if self.chat_open():
            self.chat.hide()
        QTimer.singleShot(250, lambda: self.look(manual=True))

    def own_rects(self):
        """Где на экране сам краб и его облачка — их закрашиваем на снимке."""
        out = []
        for w in (self.pet, self.bubble, self.chat):
            if w is not None and w.isVisible():
                out.append(w.frameGeometry())
        return out

    def vision_context(self, scr):
        days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
        lt = time.localtime()
        lines = ["Сейчас %s, %s." % (time.strftime("%H:%M", lt), days[lt.tm_wday])]
        ctx = {}
        fn = getattr(self.pet, "screen_context", None)
        if fn:
            try:
                ctx = fn(scr.geometry()) or {}
            except Exception:
                ctx = {}
        idle = ctx.get("idle")
        if idle is not None:
            lines.append("Хозяин за компьютером." if idle < 90 else
                         "Хозяин не трогает мышь и клавиатуру уже %d мин." % max(1, idle // 60))
        cut = lambda t, n: t if len(t) <= n else t[:n - 1] + "…"
        wins = [w for w in ctx.get("windows", []) if not is_blocked(w[0], w[1], self.get("blocklist"))]
        act = next((w for w in wins if w[2]), None)
        if act:
            lines.append("Активное окно: «%s» (%s)." % (cut(act[0], 90), act[1] or "?"))
        rest = [w for w in wins if not w[2]][:6]
        if rest:
            lines.append("Ещё окна на этом мониторе: %s." % "; ".join("«%s»" % cut(w[0], 50) for w in rest))
        if "windows" in ctx and not wins:
            lines.append("Окон на этом мониторе нет — виден рабочий стол.")
        if ctx.get("doing"):
            lines.append("Ты сейчас %s." % ctx["doing"])
        if self.recent:
            lines.append("Ты недавно говорил: %s. Скажи что-то новое или промолчи." %
                         "; ".join("«%s»" % r for r in self.recent[-4:]))
        return "\n".join(lines)

    def look(self, manual=False):
        pet = self.pet
        title, exe = foreground_info()
        if is_blocked(title, exe, self.get("blocklist")):
            self.last_thumb = None
            if manual:
                self.say("Тут что-то личное (пароли или банк) — не подглядываю.", 4)
            return
        model = self.vision_model()
        if not model:
            if manual:
                return self.say("Не выбрана модель для зрения — загляни в «Настройки ИИ».", 5)
            self.set("vision", False)
            pet.notify("Слежение выключено: не выбрана модель. Откройте «Настройки ИИ».")
            return
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        img = grab_screen(mask=self.own_rects(), screen=scr)
        th = thumb(img)
        if not manual and self.last_thumb is not None and frame_diff(th, self.last_thumb) < 0.02:
            return                                   # на экране ничего не изменилось
        self.last_thumb = th
        text = self.vision_context(scr)
        text += ("\n\nХозяин сам спросил, что ты видишь. Ответь подробнее, до 25 слов, в том же JSON." if manual
                 else "\n\nЧто скажешь?")
        info = next((m for m in self.models_cache if m["id"] == model), None)
        if info and info.get("vision") is False:     # модель без зрения: картинку не шлём, иначе она выдумывает
            text += "\n(Снимка экрана у тебя нет — суди только по названиям окон.)"
            b64 = None
        else:
            b64 = to_jpeg_b64(img, 72)
        cli, mem = self.client(), self.mem
        self.busy = True
        if manual:
            self.say("Смотрю…", 3)

        def work():
            mem.acquire(cli, model)
            try:
                self.comment.emit(self.ask_vision(cli, model, text, b64), manual)
            except LLMError as e:
                self.comment_failed.emit(str(e))
            finally:
                mem.release(model)

        threading.Thread(target=work, daemon=True).start()

    def ask_vision(self, cli, model, text, b64):
        """Спросить модель зрения (из рабочего потока). Раздумья выключаем: иначе «думающая» модель
        (Qwen3.5 и др.) тратит весь лимит на мысли про себя, и реплика приходит пустой.
        LM Studio понимает только reasoning_effort: "none"; llama.cpp и vLLM — chat_template_kwargs."""
        content = text if b64 is None else [dict(type="text", text=text), image_part(b64)]
        msgs = [dict(role="system", content=VISION_SYSTEM), dict(role="user", content=content)]
        limit = 2500 if model in self.thinkers else 600
        msg, think = self.complete_vision(cli, model, msgs, limit)
        if not msg.strip() and think:
            said = re.findall(r'"say"\s*:\s*"([^"\n]{2,160})"', think)
            if said:                                 # реплика уже есть в раздумьях — её и скажем
                return json.dumps({"say": said[-1]}, ensure_ascii=False)
            if limit < 2500:                         # всё ушло в раздумья — ещё раз, с запасом
                self.thinkers.add(model)
                msg, think = self.complete_vision(cli, model, msgs, 2500)
        if model in self.thinkers and model not in self.warned_think:
            self.warned_think.add(model)
            self.vision_note.emit("Модель «%s» долго думает про себя, поэтому замечания про экран выходят "
                                  "медленно. Для зрения лучше модель без раздумий, например qwen3-vl-4b-instruct "
                                  "(правый клик по крабу → «Настройки ИИ»)." % model)
        return msg

    def complete_vision(self, cli, model, msgs, limit):
        while True:
            extra = {}
            if not self.no_effort:
                extra["reasoning_effort"] = "none"
            if not self.no_ctk:
                extra["chat_template_kwargs"] = {"enable_thinking": False}
            try:
                msg, think, _ = cli.complete_full(model, msgs, limit, 0.7, extra)
                return msg, think
            except LLMError as e:
                body = (e.body or "").lower()
                if e.code in (400, 422) and "reasoning" in body and not self.no_effort:
                    self.no_effort = True            # сервер не знает reasoning_effort — без него
                elif e.code in (400, 422) and "chat_template_kwargs" in body and not self.no_ctk:
                    self.no_ctk = True
                else:
                    raise

    def on_comment(self, raw, manual=False):
        self.busy = False
        self.fails = 0
        if not self.ai_on():
            return
        text, mood, action = parse_vision(raw)
        if not text:
            if manual:
                self.say("Ничего особенного не вижу.", 3)
            return
        if not manual and (too_similar(text, self.recent) or re.search(r"краб|клодик", text, re.I)):
            return                                   # повтор или опять про себя самого — промолчим
        self.recent = (self.recent + [text])[-6:]
        anim = action if action in VISION_ACTIONS else VISION_MOODS.get(mood)
        if self.chat_open():
            self.chat.set_status("👀 " + text, 10)
            return
        if anim == "happy":
            self.pet.speak(text)
            if hasattr(self.pet, "start_happy") and self.pet.can_cmd():
                self.pet.start_happy()
        else:
            self.pet.speak(text, anim)

    def on_fail(self, err):
        self.busy = False
        if not self.ai_on():
            return                                   # сами выключили посреди запроса
        self.fails += 1
        low = err.lower()
        if "image" in low or "vision" in low or "multimodal" in low:
            self.set("vision", False)
            self.pet.notify("Модель «%s» не видит картинки — слежение выключено. %s" % (self.vision_model(), LIGHT_HINT))
            return
        if self.fails >= 3:
            self.set("vision", False)
            self.pet.notify("Слежение за экраном выключено: сервер не отвечает. " + err[:120])

    def shutdown(self):
        if IS_WIN and self.hotkey:
            ctypes.windll.user32.UnregisterHotKey(None, 1)
        self.bubble.hide()
        if self.chat:
            self.chat.stop.set()
            self.chat.save()
        if self.mem.current and self.get("one_model"):     # уходя — выгрузить свою модель (не дольше 3 с)
            cli, model, flavor = self.client(), self.mem.current, self.mem.flavor

            def bye():
                try:
                    for m in cli.loaded()[1] or []:
                        if same_model(m, model, flavor):
                            cli.unload(flavor, m)
                except Exception:
                    pass

            t = threading.Thread(target=bye, daemon=True)
            t.start()
            t.join(3.0)
