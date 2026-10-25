# -*- coding: utf-8 -*-
"""Щотижневе оновлення даних для дашборду і банку ідей.

    python build.py reels_analysis.csv data.js            -> перезапише data.js
    python build.py reels_analysis.csv data.js -o new.js  -> запише в new.js

reels_analysis.csv — таблиця з тетраді «Разбор хитов 5000».
data.js — поточний файл даних із сайту (у ньому вже є обкладинки, теми, історія).
"""
import csv, json, re, sys, math, base64, io, datetime as dt
from collections import Counter, defaultdict
from statistics import median

HIT = 5000          # поріг «понад 5 000»
OUT = 3             # «виліт»: у 3+ рази більше за медіану акаунта
AD_RATE = 0.4       # лайків менше 0,4% від переглядів -> схоже на рекламу
NEW_ACCOUNT_MIN = 20  # автор з такою кількістю рилсів у таблиці вважається новим відстежуваним акаунтом
COLS = ["code", "account", "group", "date", "views", "x_median", "over_5k", "detail", "likes", "comments",
        "like_rate", "promoted", "topic", "hook", "cta", "caption", "url", "thumb", "duration_s",
        "v_hook", "v_strength", "v_cta", "v_frame", "v_overlay", "v_subs", "v_goal", "v_speech", "v_first"]

RU = {
 "Хук": ("v_hook", {"Провокационное заявление или личная позиция автора": "Провокація, позиція", "Вопрос или загадка к зрителю": "Питання до глядача", "Боль или проблема зрителя": "Біль глядача", "Обещание пользы или результата": "Обіцянка користі", "Юмор, сценка или тренд": "Гумор, сценка, тренд", "Явного хука нет": "Без явного хука", "Действие в кадре без слов": "Дія в кадрі без слів", "Новость или объявление": "Новина, оголошення", "Цифра, факт, норма или развенчание мифа": "Цифра, факт або міф", "Личная история или случай из практики": "Історія з практики"}),
 "Призыв": ("v_cta", {"Комментарий": "Коментар", "Подписаться": "Підписатися", "Запись или директ": "Запис або директ", "Нет призыва": "Без заклику", "Кодовое слово": "Кодове слово", "Сохранить или переслать": "Зберегти, переслати", "Ссылка": "Посилання", "Покупка": "Покупка"}),
 "Первый кадр": ("v_frame", {"Человек в сцене": "Людина в сцені", "Руки или процесс": "Руки, процес", "Специалист с ребёнком": "Фахівець з дитиною", "Лицо в камеру": "Обличчя в камеру", "Текст на экране": "Текст на екрані", "Другое": "Інше", "Место без людей": "Місце без людей"}),
 "Задача": ("v_goal", {"Польза": "Користь", "Прогрев": "Прогрів", "Продажа": "Продаж", "Охват": "Охоплення"}),
 "Речь": ("v_speech", {"Речь с первой секунды": "З першої секунди", "Речь начинается позже": "Пізніше", "Нет речи": "Без мови"}),
 "Роль первой фразы": ("v_first", {"Хук": "Хук", "Другое": "Інше", "Польза": "Користь", "Проблема или контекст": "Проблема, контекст", "Эмоция или история": "Емоція, історія", "Призыв": "Заклик"}),
 "Плашка-заголовок": ("v_overlay", {"True": "Є", "False": "Немає"}),
 "Субтитры": ("v_subs", {"True": "Є", "False": "Немає"}),
}
THUMB_COLS = ["Обкладинка", "displayUrl", "thumbnailUrl", "thumbnail", "Thumbnail"]


def num(x):
    try:
        v = float(str(x).replace(",", "."))
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def fmt(v, nd=0):
    if v is None: return ""
    return str(int(round(v))) if nd == 0 else str(round(v, nd))


def code_of(url):
    m = re.search(r"/(?:p|reel|reels|tv)/([^/?#]+)", url or "")
    return m.group(1) if m else ""


# ---------- правила за підписом ----------
def strip_tags(t):
    return re.sub(r"#[\wЀ-ӿ.]+", "", t or "").strip()

def first_line(t):
    t = strip_tags(t)
    for ln in t.splitlines():
        if ln.strip(): return ln.strip()
    return ""

def hook_rule(cap):
    s = first_line(cap).lower()
    if not s: return "Без тексту"
    if re.search(r"міф|не про |це не ", s): return "Міф, «це не про…»"
    if "?" in s: return "Питання"
    if re.match(r"^\W*\d", s) or re.search(r"\b\d+\s+(ознак|причин|способ|поради|порад|вправ|ігор|кроків|помил)", s): return "Цифра або список"
    if re.search(r"запрошу|набір|старт|оголош|розклад|відкрит|акці|знижк|розіграш", s): return "Оголошення"
    if re.search(r"не говорить|не розмовля|переживає|хвилю|не вимовля|не слуха|істерик", s): return "Біль батьків"
    if re.match(r"^\W*(я|ми|мій|моя|моє|наш|наша|наше)\b", s): return "Особисте, «я/ми»"
    return "Твердження"

def cta_rule(cap):
    s = (cap or "").lower()
    if re.search(r"кодов|слово\s*[«\"“']|напиши\w*\s+[«\"“']?\+|пиши\w*\s+[«\"“']", s): return "Кодове слово"
    if re.search(r"посилання|в шапці|у шапці|лінк|link|біо", s): return "Посилання"
    if re.search(r"збереж|перешл|надішл\w* (подруз|друг|мам)", s): return "Зберегти, переслати"
    if re.search(r"запис|директ|дірект|direct|телефону|дзвоні|консультац", s): return "Запис або директ"
    if re.search(r"коментар|напиши|пишіть|поділіться", s): return "Коментар"
    if re.search(r"підпиш|підписуй", s): return "Підписатися"
    return "Без заклику"

TOPIC_RULES = [
    ("Розіграші й подарунки", r"розіграш|подарун|гайд у подарунок|безкоштовн\w* гайд"),
    ("Курси й заходи для колег", r"колег|логопед(ам|ів)\b|супервіз|курс для|вебінар|конференц|педагог(ам|ів)|chill"),
    ("Звуки й вимова", r"звук|артикуля|вимов|язич|гімнастик|автоматиз|постанов"),
    ("Школа: читання, письмо, увага", r"школ|читан|письм|дисграф|дислекс|уваг|концентр|першоклас"),
    ("Запуск мовлення, РАС, ЗПР", r"запуск|\bрас\b|\bзпр\b|аутиз|перші слова|не говорить|мовчун"),
    ("Ознаки й вікові норми", r"ознак|норм[аиу]\b|сигнал|у \d+ рок|в \d+ рок|коли час|коли звертатис"),
    ("Гумор і тренди", r"гумор|тренд|😂|🤣|жиза|так і живемо"),
    ("Поведінка й емоції", r"поведін|емоці|істерик|каприз|гаджет|мультик"),
    ("Особисте, команда, відгуки", r"дякуємо|команд|відгук|довір|річниц|день народж"),
    ("Послуги: запис, як проходять заняття", r"запис|запрошуємо|консультац|діагностик|як проходить|наші заняття|вільні місця"),
    ("Показ занять, ігри, вправи", r"гра\b|ігри|іграшк|вправ|розпаков|вдома з дитиною"),
]

TOK = re.compile(r"[a-zа-яіїєґ']{3,}")
def toks(t):
    return [w[:6] for w in TOK.findall(strip_tags(t).lower())]

class TopicNB:
    def __init__(self, rows):
        self.cnt = defaultdict(Counter); self.prior = Counter(); self.vocab = set()
        for r in rows:
            t = r.get("topic")
            if not t or t == "Без підпису" or not r.get("caption"): continue
            self.prior[t] += 1
            for w in toks(r["caption"]): self.cnt[t][w] += 1; self.vocab.add(w)
        self.tot = {t: sum(c.values()) for t, c in self.cnt.items()}
    def __call__(self, cap):
        ws = toks(cap)
        if not ws: return "Без підпису"
        s = strip_tags(cap).lower()
        for topic, rx in TOPIC_RULES:
            if re.search(rx, s): return topic
        if not self.prior: return "Інше"
        N, V = sum(self.prior.values()), len(self.vocab) + 1
        best = max(self.prior, key=lambda t: math.log(self.prior[t] / N) + sum(math.log((self.cnt[t][w] + 1) / (self.tot[t] + V)) for w in ws))
        return best


# ---------- обкладинки ----------
def fetch_thumb(url):
    try:
        import urllib.request
        from PIL import Image
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        img = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=15).read())).convert("RGB")
        img.thumbnail((96, 170))
        buf = io.BytesIO(); img.save(buf, "JPEG", quality=62)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


# ---------- читання ----------
def load_old(path):
    if path.endswith(".csv"):
        return {"rows": list(csv.DictReader(open(path, encoding="utf-8-sig")))}
    txt = open(path, encoding="utf-8").read()
    return json.loads(txt[txt.index("{"): txt.rindex("}") + 1])


def build(new_csv, old_path, out_path):
    old = load_old(old_path)
    rows = {r["code"]: {c: r.get(c, "") or "" for c in COLS} for r in old["rows"]}
    groups = {}
    for r in rows.values(): groups.setdefault(r["account"], r["group"] or "Конкурент")
    nb = TopicNB(rows.values())

    new = list(csv.DictReader(open(new_csv, encoding="utf-8-sig")))
    if not new or "Ссылка" not in new[0]:
        sys.exit("Це не та таблиця: немає колонки «Ссылка».")
    thumb_col = next((c for c in THUMB_COLS if c in new[0]), None)
    per_author = Counter(r["Автор"] for r in new)
    for a, n in per_author.items():
        if a not in groups and n >= NEW_ACCOUNT_MIN: groups[a] = "Конкурент"

    added = updated = skipped = 0
    caps = {}
    for s in new:
        c = code_of(s["Ссылка"])
        if not c: continue
        r = rows.get(c)
        if r is None:
            if s["Автор"] not in groups: skipped += 1; continue
            r = {k: "" for k in COLS}; r.update(code=c, account=s["Автор"], group=groups[s["Автор"]]); rows[c] = r; added += 1
        else:
            updated += 1
        r["url"] = r["url"] or "https://www.instagram.com/%s/reel/%s/" % (r["account"], c)
        if s.get("Дата"): r["date"] = s["Дата"][:10]
        v = num(s.get("Просмотры"))
        if v is not None and v > 0: r["views"] = fmt(v)
        d = num(s.get("Длительность, с"))
        if d: r["duration_s"] = fmt(d, 1)
        cap = (s.get("Подпись") or "").strip()
        likes, com = num(s.get("Лайки")), num(s.get("Комментарии"))
        if likes is not None: r["likes"] = fmt(likes)
        if com is not None: r["comments"] = fmt(com)
        views = num(r["views"]) or 0
        if likes is not None and views: r["like_rate"] = fmt(100 * likes / views, 2)
        need_detail = r["detail"] != "так" and (c not in old_codes(old) or views >= HIT)
        if need_detail:
            r.update(detail="так", caption=re.sub(r"\s+", " ", cap)[:220], topic=nb(cap), hook=hook_rule(cap), cta=cta_rule(cap))
        if r["detail"] == "так" and r["like_rate"]:
            r["promoted"] = "так" if float(r["like_rate"]) < AD_RATE else "ні"
        if s.get("Хук"):
            for src, (dst, m) in RU.items():
                if s.get(src): r[dst] = m.get(s[src], s[src])
            st = num(s.get("Сила хука (0–2)"))
            if st is not None: r["v_strength"] = "Сильний" if st >= 1 else "Середній" if st >= 0.6 else "Слабкий"
        caps[c] = cap
        if thumb_col and not r["thumb"] and s.get(thumb_col) and views >= HIT:
            r["thumb"] = fetch_thumb(s[thumb_col])

    # медіана акаунта і похідні
    today = max(dt.date.fromisoformat(r["date"]) for r in rows.values() if r["date"])
    young = lambda r: (today - dt.date.fromisoformat(r["date"])).days < 7
    by = defaultdict(list)
    for r in rows.values():
        if r["views"] and not young(r): by[r["account"]].append(float(r["views"]))
    med = {a: median(v) for a, v in by.items() if v}
    for r in rows.values():
        v = num(r["views"]) or 0
        r["over_5k"] = "так" if v >= HIT else "ні"
        r["x_median"] = fmt(v / med[r["account"]], 2) if r["account"] in med and med[r["account"]] and not young(r) else ""

    # органічні вильоти нижче 5 000 теж розбираємо за підписом
    for c, r in rows.items():
        x = num(r["x_median"])
        if r["detail"] != "так" and x is not None and x >= OUT and c in caps:
            cap = caps[c]
            r.update(detail="так", caption=re.sub(r"\s+", " ", cap)[:220], topic=nb(cap), hook=hook_rule(cap), cta=cta_rule(cap))
            if r["like_rate"]: r["promoted"] = "так" if float(r["like_rate"]) < AD_RATE else "ні"

    out = sorted(rows.values(), key=lambda r: r["date"], reverse=True)
    data = {"updated": dt.date.today().isoformat(), "last_reel": today.isoformat(), "accounts": len(groups),
            "groups": groups, "rows": out}
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("window.REELS_DATA=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
    hits = sum(1 for r in out if r["over_5k"] == "так")
    print("Готово: %d рилсів, %d акаунтів, нових %d, оновлено %d, пропущено колаборацій %d, понад 5 000: %d, обкладинок: %d"
          % (len(out), len(groups), added, updated, skipped, hits, sum(1 for r in out if r["thumb"])))
    if not thumb_col:
        print("Підказка: у таблиці немає колонки «Обкладинка», тож нові хіти будуть без картинки.")


_OLD = None
def old_codes(old):
    global _OLD
    if _OLD is None: _OLD = {r["code"] for r in old["rows"]}
    return _OLD


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2: sys.exit(__doc__)
    out = a[a.index("-o") + 1] if "-o" in a else a[1]
    build(a[0], a[1], out)
