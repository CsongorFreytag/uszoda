#!/usr/bin/env python3
"""FLOW Yoga Debrecen órarend -> flowyoga.ics (Google Naptárhoz).

Az oldal (flowyoga.hu/debreceni-yoga-studio) órarendje egy Motibro widget,
ezt olvassuk be közvetlenül. Esemény címe: Foglalkozás - Oktató; leírás: Intenzitás, Terem.
Csak a Python standard könyvtárát használja.

Használat:  python flowyoga_ics.py [kimeneti.ics]
"""
import re
import sys
import html
import hashlib
import urllib.request
from datetime import datetime, timezone

URL = "https://www.motibro.com/visitors/reservation_widget?operator=flow-yoga-debrecen"
PAGE = "https://flowyoga.hu/debreceni-yoga-studio/"
OUT = sys.argv[1] if len(sys.argv) > 1 else "flowyoga.ics"
TZ = "Europe/Budapest"
EARLIEST = "12:00"  # ennél korábban kezdődő órák kimaradnak
MONTHS = {m: i for i, m in enumerate(
    ["január", "február", "március", "április", "május", "június", "július",
     "augusztus", "szeptember", "október", "november", "december"], 1)}


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def text(cell):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<!--.*?-->|<[^>]+>", " ", cell, flags=re.S))).strip()


def parse(page):
    """-> [(YYYYMMDD, kezdés, vég, foglalkozás, oktató, terem, link)]"""
    out = []
    body = page.split("<tbody", 1)[-1].split("</tbody>", 1)[0]
    for row in re.split(r"<tr[^>]*>", body)[1:]:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 6:
            continue
        d = re.search(r"(\d{4})\. (\w+) (\d+)\.", text(cells[0]))
        t = re.search(r"(\d\d:\d\d) - (\d\d:\d\d)", text(cells[3]))
        if not d or not t or d.group(2) not in MONTHS:
            continue
        day = f"{d.group(1)}{MONTHS[d.group(2)]:02d}{int(d.group(3)):02d}"
        link = re.search(r'href="([^"]+)"', row)
        out.append((day, t.group(1), t.group(2), text(cells[4]), text(cells[2]),
                    text(cells[5]), link.group(1) if link else PAGE))
    return out


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


def main():
    events = [e for e in parse(fetch()) if e[1] >= EARLIEST]
    if not events:
        sys.exit("Nem található óra, a kimenet nem íródott felül.")
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//flowyoga-orarend//HU",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:FLOW Yoga Debrecen", f"X-WR-TIMEZONE:{TZ}"]
    for day, a, b, name, trainer, room, link in events:
        base, _, intensity = name.partition(" - ")
        desc = ([f"Intenzitás: {intensity}"] if intensity else []) + [f"Terem: {room}"]
        uid = hashlib.md5(f"{day}{a}{b}{name}{trainer}{room}".encode()).hexdigest() + "@flowyoga"
        lines += [
            "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{now}",
            f"DTSTART;TZID={TZ}:{day}T{a.replace(':', '')}00",
            f"DTEND;TZID={TZ}:{day}T{b.replace(':', '')}00",
            f"SUMMARY:{esc(f'{base} - {trainer}')}",
            f"DESCRIPTION:{esc(chr(10).join(desc))}",
            f"LOCATION:{esc('FLOW Yoga Debrecen')}",
            f"URL:{link}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(fold(l) for l in lines) + "\r\n")
    print(f"{len(events)} esemény -> {OUT}")


if __name__ == "__main__":
    main()
