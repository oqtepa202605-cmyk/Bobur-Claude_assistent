"""BOBUR — 30 kunlik strategiya PDF quruvchisi.

Ishlatish:  python3 build.py   ->  out/strategy.html, so'ng render.js PDF yasaydi.
Matnlarda oddiy ' belgisi yoziladi; oxirida o‘, g‘ va ’ belgilariga aylantiriladi.
"""
import datetime as dt
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "content"))
from w1 import DAYS as D1  # noqa: E402
from w2 import DAYS as D2  # noqa: E402
from w3 import DAYS as D3  # noqa: E402
from w4 import DAYS as D4  # noqa: E402

DAYS = D1 + D2 + D3 + D4
START = dt.date(2026, 11, 23)
OYLAR = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust",
         "sentabr", "oktabr", "noyabr", "dekabr"]
HAFTA = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]


def date_of(n):
    d = START + dt.timedelta(days=n - 1)
    return f"{d.day}-{OYLAR[d.month - 1]}", HAFTA[d.weekday()]


def e(s):
    """HTML-escape + qatorlarni <br> ga aylantirish."""
    return html.escape(s, quote=False).replace("\n", "<br>")


def ul(items, cls=""):
    return f'<ul class="{cls}">' + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>"


# ---------------------------------------------------------------- KUN SAHIFASI
def day_page(d):
    date, wd = date_of(d["n"])
    is_reel = d.get("reel") is not None
    tag = f'Reels #{d["reel"]}' if is_reel else d["type"]
    h = [f'<section class="day" id="day{d["n"]}">']
    h.append(f'''<div class="dayhead">
      <div class="daynum"><span>KUN</span>{d["n"]:02d}</div>
      <div class="daymeta"><div class="date">{date} · {wd}</div>
      <div class="chips"><span class="chip dark">{e(tag)}</span><span class="chip">{e(d["pillar"])}</span></div>
      <h3>{e(d["title"])}</h3></div></div>''')
    h.append('<div class="todo"><div class="lbl">BUGUN BAJARILADI</div>' + ul(d["tasks"], "check") + "</div>")
    h.append(f'''<div class="two"><div class="box"><div class="lbl">Maqsad</div><p>{e(d["goal"])}</p></div>
      <div class="box"><div class="lbl">Mijoz va brendga foydasi</div><p>{e(d["benefit"])}</p></div></div>''')

    if is_reel:
        h.append(f'<div class="hook"><div class="lbl">HOOK · 1–3 soniya</div><p>{e(d["hook"])}</p></div>')
        h.append(f'''<div class="two"><div class="box"><div class="lbl">Nima ko'rsataman</div><p>{e(d["show"])}</p></div>
          <div class="box"><div class="lbl">Nima haqida gapiraman</div><p>{e(d["talk"])}</p></div></div>''')
        rows = "".join(f'<tr><td class="t">{e(t)}</td><td>{e(s)}</td></tr>' for t, s in d["scenes"])
        h.append(f'<div class="lbl sec">Ssenariy · kadrlar</div><table class="scenes"><tr><th>Vaqt</th><th>Kadr</th></tr>{rows}</table>')
        h.append('<div class="speech"><div class="lbl">GAPIRISH MATNI (kameraga o\'qiladi)</div>'
                 + "".join(f"<p>{e(p)}</p>" for p in d["speech"]) + "</div>")
        h.append(f'''<div class="two"><div class="box"><div class="lbl">Kamera</div><p>{e(d["camera"])}</p></div>
          <div class="box"><div class="lbl">Olinadigan kadrlar</div>{ul(d["shots"])}</div></div>''')
        h.append(f'<div class="box"><div class="lbl">Montaj va subtitr</div>{ul(d["edit"])}</div>')
        h.append(f'<div class="kv"><span>Davomiylik</span><b>{e(d["duration"])}</b></div>')
    else:
        h.append(f'<div class="box"><div class="lbl">Slaydlar / suratlar</div>{ul(d["slides"], "num")}</div>')

    h.append(f'<div class="caption"><div class="lbl">TAYYOR CAPTION</div><p>{e(d["caption"])}</p></div>')
    h.append(f'<div class="kv"><span>CTA</span><b>{e(d["cta"])}</b></div>')
    s = d["story"]
    inter = "interaktiv" in s["sticker"].lower()
    h.append(f'''<div class="two"><div class="box story"><div class="lbl">STORY{" · INTERAKTIV" if inter else ""}</div>
        <p>{e(s["idea"])}</p><p class="quote">{e(s["text"])}</p><p class="small">Stiker: {e(s["sticker"])}</p></div>
      <div class="box tg"><div class="lbl">TELEGRAM</div><p><b>{e(d["tg"]["title"])}</b></p><p>{e(d["tg"]["text"])}</p>
        <p class="small">Media: {e(d["tg"]["media"])}</p><p class="small">Murojaat: {e(d["tg"]["cta"])}</p></div></div>''')
    if d.get("weekly"):
        h.append('<div class="note">Bugun — haftalik tahlil kuni: 13-bo\'limdagi jadvalni to\'ldiring (20 daqiqa).</div>')
    h.append("</section>")
    return "\n".join(h)


# ---------------------------------------------------------------- GRAFIKLAR
PILLARS = [  # nom, foydalanuvchi taklifi, tavsiya
    ("A · Real ishlar", 35, 35),
    ("B · Foydali ma'lumotlar", 20, 20),
    ("C · Muammo va yechim", 15, 15),
    ("D · Jonli videolar", 15, 10),
    ("E · Trend va kreativ", 10, 10),
    ("F · Shaxsiy brend", 5, 10),
]


def pillar_chart():
    w, row, lab = 470, 30, 150
    scale = (w - lab - 40) / 40
    out = [f'<svg viewBox="0 0 {w} {len(PILLARS)*row+34}" class="chart" role="img" aria-label="Kontent ustunlari foizlari">']
    for i, (name, a, b) in enumerate(PILLARS):
        y = i * row + 6
        out.append(f'<text x="0" y="{y+13}" class="cl">{html.escape(name, quote=False)}</text>')
        out.append(f'<rect x="{lab}" y="{y}" width="{a*scale:.1f}" height="9" fill="#c9c9c9"/>')
        out.append(f'<rect x="{lab}" y="{y+11}" width="{b*scale:.1f}" height="9" fill="#111"/>')
        out.append(f'<text x="{lab+b*scale+5:.1f}" y="{y+19}" class="cv">{b}%</text>')
        if a != b:
            out.append(f'<text x="{lab+a*scale+5:.1f}" y="{y+8}" class="cv g">{a}%</text>')
    y = len(PILLARS) * row + 16
    out.append(f'<rect x="{lab}" y="{y}" width="10" height="8" fill="#c9c9c9"/><text x="{lab+14}" y="{y+8}" class="cv g">Dastlabki taklif</text>')
    out.append(f'<rect x="{lab+110}" y="{y}" width="10" height="8" fill="#111"/><text x="{lab+124}" y="{y+8}" class="cv">Tavsiya etilgan</text>')
    out.append("</svg>")
    return "".join(out)


def week_chart():
    weeks = [(1, 7), (8, 14), (15, 21), (22, 30)]
    data = []
    for a, b in weeks:
        ds = [d for d in DAYS if a <= d["n"] <= b]
        r = sum(1 for d in ds if d.get("reel"))
        c = sum(1 for d in ds if d["type"] == "Carousel")
        f = sum(1 for d in ds if d["type"].startswith("Foto"))
        data.append((r, c, f))
    w, h, base = 470, 185, 152
    bw, gap, unit = 60, 50, 14
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="Haftalar bo\'yicha kontent">']
    for k in range(0, 11, 2):
        y = base - k * unit
        out.append(f'<line x1="30" x2="{w}" y1="{y}" y2="{y}" stroke="#e5e5e5"/><text x="20" y="{y+3}" class="cv g" text-anchor="end">{k}</text>')
    cols = ["#111", "#7a7a7a", "#c9c9c9"]
    for i, vals in enumerate(data):
        x = 50 + i * (bw + gap)
        y = base
        for v, c in zip(vals, cols):
            if v:
                y -= v * unit
                out.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{v*unit-1.5}" fill="{c}"/>')
        out.append(f'<text x="{x+bw/2}" y="{y-4}" class="cv" text-anchor="middle">{sum(vals)}</text>')
        out.append(f'<text x="{x+bw/2}" y="{base+14}" class="cv" text-anchor="middle">{i+1}-hafta</text>')
    lx = 50
    for lbl, c in zip(["Reels", "Carousel", "Foto"], cols):
        out.append(f'<rect x="{lx}" y="{h-10}" width="10" height="8" fill="{c}"/><text x="{lx+14}" y="{h-3}" class="cv">{lbl}</text>')
        lx += 90
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- JADVALLAR
def calendar_table():
    rows = []
    for d in DAYS:
        date, wd = date_of(d["n"])
        tag = f'Reels #{d["reel"]}' if d.get("reel") else d["type"]
        inter = "●" if "interaktiv" in d["story"]["sticker"].lower() else ""
        rows.append(f'<tr><td class="t"><a href="#day{d["n"]}">{d["n"]}</a></td><td class="t">{date}<br><span class="small">{wd[:3]}</span></td>'
                    f'<td><b>{e(tag)}</b><br><span class="small">{e(d["pillar"])}</span></td><td>{e(d["title"])}</td><td class="c">{inter}</td></tr>')
    return ('<table class="cal"><tr><th>Kun</th><th>Sana</th><th>Tur / ustun</th><th>Mavzu</th><th>Int.</th></tr>'
            + "".join(rows) + "</table>")


def stories_table():
    rows = "".join(
        f'<tr><td class="t">{d["n"]}</td><td>{e(d["story"]["idea"])}<br><span class="quote">{e(d["story"]["text"])}</span></td>'
        f'<td class="small">{e(d["story"]["sticker"])}</td></tr>' for d in DAYS)
    return f'<table class="cal"><tr><th>Kun</th><th>Story g\'oyasi va matni</th><th>Stiker</th></tr>{rows}</table>'


def tg_table():
    rows = "".join(
        f'<tr><td class="t">{d["n"]}</td><td><b>{e(d["tg"]["title"])}</b><br><span class="small">{e(d["tg"]["media"])}</span></td>'
        f'<td class="small">{e(d["tg"]["cta"])}</td></tr>' for d in DAYS)
    return f'<table class="cal"><tr><th>Kun</th><th>Sarlavha · media</th><th>Murojaat</th></tr>{rows}</table>'


def week_table(n):
    metrics = ["Reels ko'rishlar (jami)", "Reach (qamrov)", "Saqlashlar (Saves)", "Ulashishlar (Shares)",
               "Izohlar", "Profilga kirishlar", "Yangi obunachilar", "Direct murojaatlar",
               "Potensial mijozlar", "Konsultatsiyalar", "Telegram: yangi obunachilar", "Telegram: o'rtacha ko'rish"]
    rows = "".join(f"<tr><td>{e(m)}</td><td></td><td></td><td></td></tr>" for m in metrics)
    return (f'<div class="wk"><div class="lbl">{n}-HAFTA · kunlar {[ "1–7","8–14","15–21","22–30"][n-1]}</div>'
            '<table class="fill"><tr><th>Ko\'rsatkich</th><th>Shu hafta</th><th>O\'tgan hafta</th><th>Farq</th></tr>'
            + rows + '</table><div class="fillines"><div>Eng yaxshi video va nima uchun:</div><div>Eng zaif video va nima uchun:</div>'
            '<div>Keyingi haftada nimani o\'zgartiraman:</div></div></div>')


def reel_score_table():
    rows = "".join(
        f'<tr><td class="t">#{d["reel"]}</td><td>{e(d["title"])}</td><td></td><td></td><td></td><td></td><td></td></tr>'
        for d in DAYS if d.get("reel"))
    return ('<table class="fill sm"><tr><th>№</th><th>Video</th><th>Ko\'rish</th><th>Saves</th><th>Shares</th><th>Profilga</th><th>DM</th></tr>'
            + rows + "</table>")


# ---------------------------------------------------------------- MATN BO'LIMLARI
STATIC = (ROOT / "sections.html").read_text(encoding="utf-8")


def build():
    reels = sum(1 for d in DAYS if d.get("reel"))
    inter = sum(1 for d in DAYS if "interaktiv" in d["story"]["sticker"].lower())
    body = STATIC
    body = body.replace("{{PILLAR_CHART}}", pillar_chart())
    body = body.replace("{{WEEK_CHART}}", week_chart())
    body = body.replace("{{CALENDAR}}", calendar_table())
    body = body.replace("{{DAYS}}", "\n".join(day_page(d) for d in DAYS))
    body = body.replace("{{STORIES}}", stories_table())
    body = body.replace("{{TELEGRAM}}", tg_table())
    body = body.replace("{{WEEKS}}", "".join(week_table(i) for i in range(1, 5)))
    body = body.replace("{{REELSCORE}}", reel_score_table())
    body = body.replace("{{REELS}}", str(reels)).replace("{{INTER}}", str(inter))
    s, _ = date_of(1)
    f, _ = date_of(30)
    body = body.replace("{{START}}", s + " 2026").replace("{{END}}", f + " 2026")
    css = (ROOT / "style.css").read_text(encoding="utf-8")
    doc = f'<!doctype html><html lang="uz"><head><meta charset="utf-8"><title>BOBUR — 30 kunlik strategiya</title><style>{css}</style></head><body>{body}</body></html>'
    # O'zbek imlosi: o' g' -> o‘ g‘ ; qolgan ' -> ’ (tutuq belgisi)
    doc = re.sub(r"([oOgG])'", "\\1\u2018", doc)
    doc = doc.replace("'", "\u2019")
    assert "{{" not in doc, re.findall(r"\{\{\w+\}\}", doc)
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    (out / "strategy.html").write_text(doc, encoding="utf-8")
    print(f"OK: {len(DAYS)} kun, {reels} Reels, {inter} interaktiv Story")


if __name__ == "__main__":
    build()
