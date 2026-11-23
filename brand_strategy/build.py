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


# ---------------------------------------------------------------- AUDIT (real Instagram ma'lumotlari)
def hbar(items, total, w=470, row=17, lab=120, maxv=None, fmt=lambda v, t: f"{v} · {v/t*100:.0f}%"):
    maxv = maxv or max(v for _, v in items)
    scale = (w - lab - 80) / maxv
    out = [f'<svg viewBox="0 0 {w} {len(items)*row+4}" class="chart" role="img">']
    for i, (name, v) in enumerate(items):
        y = i * row + 2
        out.append(f'<text x="0" y="{y+10}" class="cl">{html.escape(name, quote=False)}</text>')
        out.append(f'<rect x="{lab}" y="{y+1}" width="{max(v*scale,1):.1f}" height="11" fill="#111"/>')
        out.append(f'<text x="{lab+v*scale+5:.1f}" y="{y+10}" class="cv">{fmt(v, total)}</text>')
    out.append("</svg>")
    return "".join(out)


def spark(vals, w=470, h=60):
    n, mx = len(vals), max(max(vals), 1)
    bw = w / n
    out = [f'<svg viewBox="0 0 {w} {h+14}" class="chart" role="img">',
           f'<line x1="0" x2="{w}" y1="{h}" y2="{h}" stroke="#bbb"/>']
    for i, v in enumerate(vals):
        bh = v / mx * (h - 12)
        out.append(f'<rect x="{i*bw+1:.1f}" y="{h-bh:.1f}" width="{bw-2:.1f}" height="{bh:.1f}" fill="#111"/>')
        if v:
            out.append(f'<text x="{i*bw+bw/2:.1f}" y="{h-bh-2:.1f}" class="cv" text-anchor="middle">{v}</text>')
    out.append(f'<text x="0" y="{h+11}" class="cv g">23-okt</text><text x="{w}" y="{h+11}" class="cv g" text-anchor="end">21-noy</text></svg>')
    return "".join(out)


def n(x):
    return f"{x:,}".replace(",", "\u00a0")


def audit_html():
    from audit_data import (FETCHED, PERIOD, PROFILE, DAILY, GENDER_AGE, CITIES,
                            TASHKENT_REGION, ABROAD)
    P = PROFILE
    total = sum(GENDER_AGE.values())
    g = {k: sum(v for kk, v in GENDER_AGE.items() if kk[0] == k) for k in "FMU"}
    ages = ["13-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
    age = [(a, sum(v for kk, v in GENDER_AGE.items() if kk.endswith("." + a))) for a in ages]
    known = g["F"] + g["M"]
    c_total = sum(CITIES.values())
    tsh = CITIES["Toshkent"]
    tsh_reg = sum(CITIES[c] for c in TASHKENT_REGION)
    abroad = sum(CITIES[c] for c in ABROAD)
    regions = c_total - tsh - tsh_reg - abroad
    top = sorted(CITIES.items(), key=lambda x: -x[1])[:12]
    reach, views = sum(DAILY["reach"]), sum(DAILY["views"])
    newf = sum(DAILY["new_followers"])
    a2534 = dict(age)["25-34"]
    a1824 = dict(age)["18-24"]
    a3544 = dict(age)["35-44"]
    bio = html.escape(P["biography"], quote=False).replace("\n", "<br>")
    return f'''
<section class="chapter" id="audit">
  <div class="chapter-head"><div class="no">A</div><div><h2>Audit: @{P["username"]}</h2><div class="sub">Instagram API ma'lumotlari · olingan sana: {FETCHED} · davr: {PERIOD}</div></div></div>
  <div class="warn"><b>Manba va cheklov.</b> Quyidagi raqamlar akkauntingizga ulangan Windsor.ai orqali Instagram API'dan olingan — taxmin emas. Ammo tarif faqat oxirgi 30 kun ma'lumotini beradi: profildagi 3 ta postning o'zi (mavzusi, ko'rishlar, saqlashlar) bu davrga kirmagani uchun ko'rilmadi. Shuning uchun postlaringiz mazmuni haqida xulosa yozilmagan.</div>
  <h3>Profil — hozirgi holat</h3>
  <table>
    <tr><td style="width:32%">Username</td><td><b>@{P["username"]}</b></td></tr>
    <tr><td>Name</td><td>{html.escape(P["name"])}</td></tr>
    <tr><td>Bio</td><td class="biotxt">{bio}</td></tr>
    <tr><td>Havola</td><td>{P["website"]}</td></tr>
    <tr><td>Obunachilar / obunalar</td><td><b>{n(P["followers"])}</b> / {P["follows"]}</td></tr>
    <tr><td>Postlar soni</td><td><b>{P["media"]}</b></td></tr>
  </table>
  <div class="three">
    <div class="stat"><b>{n(P["followers"])}</b><span class="small">obunachi</span></div>
    <div class="stat"><b>{P["media"]}</b><span class="small">post profilda</span></div>
    <div class="stat"><b>{reach}</b><span class="small">qamrov, 30 kun (kunlik yig'indi)</span></div>
  </div>
  <h3>Oxirgi 30 kun faolligi</h3>
  <p>Ko'rishlar (views) kunlar bo'yicha — jami <b>{views}</b>. Shu davrda: yangi post — <b>{DAILY["posts_in_period"]}</b>, yangi obunachi — <b>{newf}</b>, layk — {DAILY["likes"]}, izoh — {DAILY["comments"]}, saqlash — {DAILY["saves"]}, ulashish — {DAILY["shares"]}, profil tugmalari bosilishi — {DAILY["profile_links_taps"]}.</p>
  {spark(DAILY["views"])}
  <div class="note"><b>Xulosa:</b> akkaunt «uxlab yotgan» holatda. {n(P["followers"])} obunachi bor, lekin 30 kun ichida yangi kontent chiqmagani uchun Instagram ularga deyarli hech narsa ko'rsatmagan. Bu yomon yangilik emas: strategiya «noldan» emas, tayyor obunachilar bazasidan boshlanadi. Lekin obunachilarning bir qismi faol bo'lmasligi mumkin — birinchi Reels'lar asosan obunachi bo'lmaganlarga tarqalishini kuting.</div>

  <h3>Auditoriya: yosh</h3>
  <p class="small">{n(total)} obunachi bo'yicha (Instagram jins/yosh ma'lumoti).</p>
  {hbar(age, total)}
  <h3>Auditoriya: jins</h3>
  <p>Jinsi ko'rsatilgan {known} obunachidan <b>{g["M"]/known*100:.0f}% erkak</b>, {g["F"]/known*100:.0f}% ayol. Qolgan {n(g["U"])} ({g["U"]/total*100:.0f}%) obunachining jinsi Instagram'da ko'rsatilmagan — shuning uchun bu nisbat taxminiy.</p>
  <h3>Auditoriya: shaharlar (top-12)</h3>
  <p class="small">API {len(CITIES)} ta shahar bo'yicha {n(c_total)} obunachini ko'rsatdi; foizlar shu songa nisbatan.</p>
  {hbar(top, c_total)}
  <table class="keep">
    <tr><th>Hudud</th><th>Obunachi</th><th>Ulush</th></tr>
    <tr><td>Toshkent shahri</td><td>{tsh}</td><td>{tsh/c_total*100:.0f}%</td></tr>
    <tr><td>Toshkent viloyati (Salar, O'rtaovul, Chirchiq, Qibray, Yangiyo'l)</td><td>{tsh_reg}</td><td>{tsh_reg/c_total*100:.0f}%</td></tr>
    <tr><td>Boshqa viloyatlar</td><td>{regions}</td><td>{regions/c_total*100:.0f}%</td></tr>
    <tr><td>Xorij (Moskva, Bishkek, Dushanbe)</td><td>{abroad}</td><td>{abroad/c_total*100:.0f}%</td></tr>
  </table>

  <h3>Nima yaxshi</h3>
  <ul>
    <li><b>Ism + kasb</b> Name maydonida: «Bobur Hayitov | Arxitektor» — qidiruvda topiladi va ishonch beradi.</li>
    <li><b>«5 yillik tajriba»</b> — aniq, tekshiriladigan ishonch belgisi.</li>
    <li><b>Aniq CTA:</b> «Bepul konsultatsiya uchun Direct'ga yozing».</li>
    <li><b>Asosiy auditoriya to'g'ri yoshda:</b> 25–34 yosh — {a2534/total*100:.0f}%, 35–44 — {a3544/total*100:.0f}%. Bu uy-joy olayotgan, ta'mir va qurilish qilayotgan yosh — sizning mijozingiz.</li>
  </ul>
  <h3>Kamchiliklar va ularning yechimi</h3>
  <table>
    <tr><th>Kamchilik</th><th>Nima uchun muhim</th><th>Yechim (strategiyada)</th></tr>
    <tr><td><b>Profilda atigi {P["media"]} ta post</b></td><td>Profilga kirgan odam portfolio ko'rmaydi va yozmasdan chiqib ketadi.</td><td>9-kungacha profil to'rida 9 ta post (3 qator) bo'ladi. Ilk postlar — render/real va oldin/keyin.</td></tr>
    <tr><td><b>30 kunda yangi kontent yo'q</b></td><td>Algoritm akkauntni «faol emas» deb hisoblaydi.</td><td>Har kuni Story va har 1–2 kunda Reels.</td></tr>
    <tr><td><b>Bio'da maxsus Unicode «qalin» shrift</b></td><td>Qidiruvda so'z sifatida o'qilmaydi, ayrim telefonlarda kvadratcha bo'lib ko'rinadi.</td><td>Oddiy harflar bilan yangi bio — 6-bo'lim.</td></tr>
    <tr><td><b>Bio'da shahar va jarayon yo'q</b></td><td>Mijoz siz uning shahrida ishlaysizmi va nima olishini bilmaydi.</td><td>«Toshkent» + «Reja → 3D → chizma → nazorat».</td></tr>
    <tr><td><b>Havola faqat shaxsiy Telegram'ga</b></td><td>Foydali kontent uchun kanal yo'q — obunachini «ushlab qoladigan» joy kerak.</td><td>Telegram kanal + shaxsiy havola (5 ta havola imkoniyati).</td></tr>
    <tr><td><b>18–24 yosh — {a1824/total*100:.0f}%</b></td><td>Bu qismning ko'pi talaba va yosh mutaxassislar bo'lishi mumkin — ular mijoz emas.</td><td>Kontent fokusi — uy egalari. Dasturlar haqidagi videolar soni cheklangan (10%).</td></tr>
  </table>
  <h3>Strategiyaga kiritilgan o'zgarishlar</h3>
  <ol>
    <li><b>Viloyatlar uchun onlayn xizmat.</b> Obunachilarning {regions/c_total*100:.0f}% qismi Toshkentdan tashqarida. Masofadan loyiha (o'lchovni mijoz yoki usta qiladi, siz reja, 3D va chizma berasiz) — alohida taklif. Uni 25-kun videosi va DM ssenariylarida ishlating, «Xizmatlar» highlights'iga qo'shing.</li>
    <li><b>Xorijdagi vatandoshlar</b> ({abroad} obunachi — Moskva, Bishkek, Dushanbe): kichik, lekin mantiqiy segment — chet elda ishlab, O'zbekistonda uy qurayotganlar. Bu taxmin: DM'da qayerdan yozishayotganini kuzatib tekshiring.</li>
    <li><b>Eksteryer ham bor.</b> Bio'ingizda «Eksteryer» yozilgan — 15-kun (keys), 22-kun (oldin/keyin) va 29-kun («Chiziqdan hayotga») videolarini fasad yoki xususiy uy loyihasi bilan ham qilish mumkin.</li>
    <li><b>«Bepul konsultatsiya»</b> — barcha CTA va DM ssenariylarida bir xil ishlatildi (bio'dagi va'dangizga mos).</li>
    <li><b>Telegram:</b> barcha CTA'larda @HayitovBobur ko'rsatildi.</li>
    <li><b>KPI'ning 0-kun ustuni</b> real raqamlar bilan to'ldirildi (14-bo'lim).</li>
  </ol>
</section>'''


# ---------------------------------------------------------------- MATN BO'LIMLARI
STATIC = (ROOT / "sections.html").read_text(encoding="utf-8")


def build():
    reels = sum(1 for d in DAYS if d.get("reel"))
    inter = sum(1 for d in DAYS if "interaktiv" in d["story"]["sticker"].lower())
    body = STATIC
    body = body.replace("{{AUDIT}}", audit_html())
    pages = {}
    pf = ROOT / "out" / "toc_pages.json"
    if pf.exists():
        import json
        pages = json.loads(pf.read_text())
    body = re.sub(r'(<a href="#(\w+)"><span>.*?</span>)(</a>)',
                  lambda m: f'{m.group(1)}<span class="pg">{pages.get(m.group(2), "")}</span>{m.group(3)}', body)
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
