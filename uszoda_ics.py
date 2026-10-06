#!/usr/bin/env python3
"""Debreceni Sportuszoda pályabeosztás -> uszoda.ics (Google Naptárhoz).

Az oldal egyszerre egy napot mutat (a napválasztó a k9 POST-paraméter), 7 napra előre.
Minden medencére (50m, 25m, Tanmedence) a SZABAD (lakossági) sávidőkből naptáresemény lesz.
Csak a Python standard könyvtárát használja.

Használat:  python uszoda_ics.py [kimeneti.ics]
"""
import re
import sys
import hashlib
import urllib.parse
import urllib.request
from datetime import datetime, timezone

URL = "https://www.debrecenisportuszoda.hu/palyabeosztas"
OUT = sys.argv[1] if len(sys.argv) > 1 else "uszoda.ics"
POOLS = {"50m-es medence"}  # csak ez; None = mind
MIN_LANES = 1  # ennél kevesebb szabad sávú idősáv nem kerül be
TZ = "Europe/Budapest"


def fetch(data=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(URL, data=body, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_day(html):
    """-> {medence: {sáv: [(kezdés, vég), ...]}} a szabad időkre."""
    result = {}
    sections = html.split('fc-left"')[1:]
    for sec in sections:
        pool = re.search(r"</b>\s*\|\s*([^<]+)<", sec)
        if not pool:
            continue
        pool = pool.group(1).strip()
        body = sec.split("<tbody>", 1)[-1].split("</tbody>", 1)[0]
        lanes = [re.sub(r"\s+", " ", l).strip()
                 for l in re.findall(r"<th class='fc-day-header[^>]*>([^<]+)</th>", sec)]
        cols = re.split(r"<td class='fc-event-container", body)[1:]
        lane_map = {}
        for name, col in zip(lanes, cols):
            slots = re.findall(r"(\d\d:\d\d) - (\d\d:\d\d) SZABAD", col)
            lane_map[name] = slots
        result[pool] = lane_map
    return result


def segments(lane_map):
    """Sávhalmaz szerinti idősávok: [(kezdés, vég, [sávok])] összevonva."""
    points = sorted({t for s in lane_map.values() for a, b in s for t in (a, b)})
    segs = []
    for a, b in zip(points, points[1:]):
        free = [n for n, s in lane_map.items() if any(x <= a and b <= y for x, y in s)]
        if len(free) < MIN_LANES:
            continue
        if segs and segs[-1][1] == a and segs[-1][2] == free:
            segs[-1] = (segs[-1][0], b, free)
        else:
            segs.append((a, b, free))
    return segs


def esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    out, b = [], line.encode()
    while len(b) > 74:
        cut = 74
        while (b[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(b[:cut].decode())
        b = b[cut:]
        b = b" " + b
    out.append(b.decode())
    return "\r\n".join(out)


def main():
    first = fetch()
    dates = re.findall(r"<option value='(\d{4}-\d\d-\d\d)'", first)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//uszoda-palyabeosztas//HU",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:Debreceni Sportuszoda - szabad sávok", f"X-WR-TIMEZONE:{TZ}"]
    count = 0
    for d in dates:
        html = first if d == dates[0] else fetch({"keres": "igen", "k9": d})
        for pool, lane_map in parse_day(html).items():
            if POOLS and pool not in POOLS:
                continue
            for a, b, free in segments(lane_map):
                day = d.replace("-", "")
                uid = hashlib.md5(f"{d}{pool}{a}{b}{free}".encode()).hexdigest() + "@uszoda"
                n = f"{len(free)}/{len(lane_map)}"
                lines += [
                    "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{now}",
                    f"DTSTART;TZID={TZ}:{day}T{a.replace(':', '')}00",
                    f"DTEND;TZID={TZ}:{day}T{b.replace(':', '')}00",
                    f"SUMMARY:{esc(f'Szabad sávok ({n}) – {pool}')}",
                    f"DESCRIPTION:{esc('Szabad sávok: ' + ', '.join(free))}",
                    f"LOCATION:{esc('Debreceni Sportuszoda')}",
                    f"URL:{URL}", "TRANSP:TRANSPARENT", "END:VEVENT"]
                count += 1
    lines.append("END:VCALENDAR")
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(fold(l) for l in lines) + "\r\n")
    print(f"{count} esemény -> {OUT} ({dates[0]} … {dates[-1]})")


if __name__ == "__main__":
    main()
