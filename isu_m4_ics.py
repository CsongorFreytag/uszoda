#!/usr/bin/env python3
"""ISU műkorcsolya (Grand Prix + bajnokságok) M4 Sport közvetítései -> isu_m4.ics.

Források:
  * ISU eseménylista (isu-skating.com) - melyik versenyek érdekesek
  * results.isu.org "Time Schedule" - a programok eredeti (helyi) kezdési ideje
  * M4 Sport műsorújság (m4sport.hu/musor) - mikor megy adásban
Az M4 adás típusa: Élő (az ISU kezdéshez közel), Csúsztatott (első, nem élő adás),
Ismétlés (minden további adás). Ha az ISU időbeosztás még nem elérhető, az első adás
"Közvetítés" címkét kap, a többi "Ismétlés".
Csak a Python standard könyvtárát használja.

Használat:  python isu_m4_ics.py [kimeneti.ics]
"""
import re
import sys
import html
import json
import hashlib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ISU_URL = "https://isu-skating.com/en/events/?month=All&season=2026%2F2027&event_level=ISU"
RESULTS_URL = "https://results.isu.org/results/season{season}/{code}/"
M4_URL = "https://m4sport.hu/wp-content/plugins/hms-global-widgets/widgets/programGuide/programGuideInterface.php"
M4_CHANNEL = ("30", "m4", "M4 Sport")  # id, rövid kód, név
LIVE_URL = "https://mediaklikk.hu/elo/mtv4live"
SHOW_URL = "https://mediaklikk.hu/musor/mukorcsolya-es-jegtanc-grand-prix"
OUT = sys.argv[1] if len(sys.argv) > 1 else "isu_m4.ics"

LIVE_WINDOW = timedelta(minutes=90)  # ennyivel az ISU kezdés körül még "élő"
DAYS_BEFORE, DAYS_AFTER = 1, 6        # az esemény körül ennyi napot nézünk az M4 műsorban
M4_PAST, M4_FUTURE = 60, 20           # az M4 műsorújság ennyi napra vissza / előre érhető el

KIND = {"live": "Élő", "delayed": "Csúsztatott", "repeat": "Ismétlés", "unknown": "Közvetítés"}
UA = {"User-Agent": "Mozilla/5.0"}


def http(url, data=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


# ---------------------------------------------------------------- ISU
def isu_events():
    """Műkorcsolya Grand Prix + bajnokság események (Junior GP nélkül)."""
    page = http(ISU_URL)
    i = page.find('initialData\\":')
    if i < 0:
        sys.exit("Az ISU eseménylista szerkezete megváltozott.")
    s = page[i + len('initialData\\":'):].replace('\\"', '"').replace("\\\\", "\\")
    data, _ = json.JSONDecoder().raw_decode(s)
    out = []
    for e in data["data"]:
        if e["discipline_id"] != 1 or "Junior Grand Prix" in e["event_sub_type_name"]:
            continue
        e["start"] = parse_utc(e["from_date_utc"])
        e["end"] = parse_utc(e["to_date_utc"])
        out.append(e)
    return out


def parse_utc(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


SEGMENTS = {"Short Program": "SP", "Rhythm Dance": "RD", "Free Skating": "FS", "Free Dance": "FS"}
CATEGORIES = {"Men": "M", "Women": "W", "Pairs": "P", "Ice Dance": "D"}


def isu_schedule(event):
    """-> {(kategória, szegmens): (kezdés UTC-ben, helyi idő szerint)}; None, ha még nincs időbeosztás."""
    season = event["season"].replace("/", "")[2:4] + event["season"][-2:]
    try:
        page = http(RESULTS_URL.format(season=season, code=event["odf_code"]))
    except urllib.error.HTTPError:
        return None
    m = re.search(r"\(Local Time, UTC\s*([^)]*)\)", page)
    if not m:
        return None
    m = re.search(r"([+-])(\d\d):(\d\d)", html.unescape(m.group(1)))
    if not m:
        return None
    offset = timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
    if m.group(1) == "-":
        offset = -offset
    sched, day = {}, None
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) != 4:
            continue
        if re.fullmatch(r"\d\d\.\d\d\.\d{4}", cells[0]):
            day = datetime.strptime(cells[0], "%d.%m.%Y")
        elif day and re.fullmatch(r"\d\d:\d\d:\d\d", cells[1]):
            cat, seg = CATEGORIES.get(cells[2]), SEGMENTS.get(cells[3])
            if cat and seg:
                t = datetime.strptime(cells[1], "%H:%M:%S")
                local = day.replace(hour=t.hour, minute=t.minute, second=t.second)
                sched[(cat, seg)] = ((local - offset).replace(tzinfo=timezone.utc), local)
    return sched or None


# ---------------------------------------------------------------- M4
def m4_day(day):
    cid, code, name = M4_CHANNEL
    return http(M4_URL, {"ChannelIds": cid + ",", "ShortCodes": code + ",", "Names": name + ",",
                         "Date": day.isoformat(), "Type": 0, "buttonType": "text_type",
                         "videoPageUrl": "https://m4sport.hu/videok", "newDesign": 1,
                         "TracksEnabledChannelIds": "", "debug": 0})


def text(s):
    s = re.sub(r"<span class=\"hms-sr-only.*?</span>", "", s, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def m4_airings(page):
    """A műkorcsolya adások egy napról: [{start, end, title, sub, link}]."""
    out = []
    for li in re.split(r'(?=<li class="program_body)', page)[1:]:
        li = li.split("</li>")[0]
        title = re.search(r"<h1[^>]*>(.*?)</h1>", li, re.S)
        sub = re.search(r'<p id="[^"]*p"[^>]*>(.*?)</p>', li, re.S)
        if not title:
            continue
        title = text(title.group(1))
        if "műkorcsolya" not in title.lower() and "jégtánc" not in title.lower():
            continue
        fr = re.search(r'data-from="([^"]+)"', li).group(1)
        till = re.search(r'data-till="([^"]+)"', li).group(1)
        video = re.search(r'data-videolink="([^"]*)"', li).group(1).strip()
        show = re.search(r"mediaklikk\.hu/musor/[a-z0-9-]+", li)
        out.append({
            "start": datetime.strptime(fr, "%Y-%m-%d %H:%M:%S%z"),
            "end": datetime.strptime(till, "%Y-%m-%d %H:%M:%S%z"),
            "title": title, "sub": text(sub.group(1)) if sub else "",
            "video": video, "show": "https://" + show.group(0) if show else SHOW_URL,
        })
    return out


def key_of(sub):
    """M4 alcím -> (kategória, szegmens), pl. 'Férfi rövidprogram - ...' -> ('M', 'SP')."""
    head = sub.split(" - ")[0].lower()
    cat = ("D" if "jégtánc" in head else "M" if "férfi" in head else
           "W" if "női" in head else "P" if "páros" in head else None)
    seg = ("RD" if "ritmus" in head else "SP" if "rövid" in head else
           "FS" if "szabad" in head else None)
    return (cat, seg) if cat and seg else None


# ---------------------------------------------------------------- összevetés
def assign(airings, events):
    """Minden adást egy ISU eseményhez (és ha lehet, programhoz) rendel."""
    for a in airings:
        a["event"], a["isu_start"] = None, None
        key = key_of(a["sub"])
        best = None
        for e in events:
            s, local = (e["schedule"] or {}).get(key, (None, None)) if key else (None, None)
            if s is None:
                continue
            delta = a["start"] - s
            if -LIVE_WINDOW <= delta <= timedelta(days=DAYS_AFTER) and (best is None or delta < best[0]):
                best = (delta, e, s, local)
        if best:
            a["event"], a["isu_start"], a["isu_local"] = best[1], best[2], best[3]
            continue
        # nincs időbeosztás: az esemény időablaka alapján
        near = [e for e in events if e["schedule"] is None
                and e["start"] - timedelta(days=DAYS_BEFORE) <= a["start"] <= e["end"] + timedelta(days=DAYS_AFTER)]
        if near:
            a["event"] = max(near, key=lambda e: e["start"])
    return [a for a in airings if a["event"]]


def classify(airings):
    groups = {}
    for a in airings:
        g = (a["event"]["event_id"], key_of(a["sub"]) if a["isu_start"] else a["sub"])
        groups.setdefault(g, []).append(a)
    for items in groups.values():
        items.sort(key=lambda a: a["start"])
        live = next((a for a in items if a["isu_start"]
                     and abs(a["start"] - a["isu_start"]) <= LIVE_WINDOW), None)
        for n, a in enumerate(items):
            if a["isu_start"] is None:
                a["kind"] = "unknown" if n == 0 else "repeat"
            elif a is live:
                a["kind"] = "live"
            elif n == 0 and live is None:
                a["kind"] = "delayed"
            else:
                a["kind"] = "repeat"


# ---------------------------------------------------------------- ICS
def esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    out, b = [], line.encode()
    while len(b) > 74:
        cut = 74
        while (b[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(b[:cut].decode())
        b = b" " + b[cut:]
    out.append(b.decode())
    return "\r\n".join(out)


def ics_time(dt):
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def vevent(a, now):
    e = a["event"]
    kind = KIND[a["kind"]]
    summary = f"{kind}: {a['title']} – {a['sub']}" if a["sub"] else f"{kind}: {a['title']}"
    link = a["video"] or (LIVE_URL if a["kind"] == "live" else a["show"])
    desc = [f"Adás: {kind} (M4 Sport)",
            f"ISU esemény: {e['name']} ({e['city']}, {e['country_name']})"]
    if a["isu_start"]:
        desc.append(f"Program kezdése a helyszínen: {a['isu_local']:%Y.%m.%d. %H:%M}")
    desc.append(f"Mediaklikk: {link}")
    uid = hashlib.md5(f"{a['start'].isoformat()}{a['title']}{a['sub']}".encode()).hexdigest() + "@isu-m4"
    return ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{now}",
            f"DTSTART:{ics_time(a['start'])}", f"DTEND:{ics_time(a['end'])}",
            f"SUMMARY:{esc(summary)}", f"DESCRIPTION:{esc(chr(10).join(desc))}",
            f"URL:{link}", "END:VEVENT"]


def main():
    today = datetime.now(timezone.utc).date()
    lo, hi = today - timedelta(days=M4_PAST), today + timedelta(days=M4_FUTURE)
    events = [e for e in isu_events()
              if e["end"].date() + timedelta(days=DAYS_AFTER) >= lo
              and e["start"].date() - timedelta(days=DAYS_BEFORE) <= hi]
    days = set()
    for e in events:
        e["schedule"] = isu_schedule(e)
        d = e["start"].date() - timedelta(days=DAYS_BEFORE)
        while d <= e["end"].date() + timedelta(days=DAYS_AFTER):
            if lo <= d <= hi:
                days.add(d)
            d += timedelta(days=1)
    airings = []
    for d in sorted(days):
        airings += m4_airings(m4_day(d))
    airings = assign(airings, events)
    classify(airings)

    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//isu-m4-kozvetitesek//HU",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:ISU műkorcsolya – M4 Sport"]
    for a in sorted(airings, key=lambda a: a["start"]):
        lines += vevent(a, now)
    lines.append("END:VCALENDAR")
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(fold(l) for l in lines) + "\r\n")
    print(f"{len(airings)} adás -> {OUT} ({len(events)} ISU esemény, {len(days)} napi műsor)")
    for a in sorted(airings, key=lambda a: a["start"]):
        print(f"  {a['start']:%m.%d %H:%M} {KIND[a['kind']]:<12} {a['sub']}")


if __name__ == "__main__":
    main()
