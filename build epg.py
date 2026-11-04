#!/usr/bin/env python3
"""
XuperTV - generador de guia (EPG) compacta para Roku.

Descarga varias guias XMLTV (.xml o .xml.gz), las une y escribe epg.json:
solo las horas cercanas, solo titulos reales de la fuente. No inventa nada.

Uso:
  python3 build_epg.py                     # fuentes por defecto
  python3 build_epg.py -s URL1 -s URL2     # fuentes propias
  python3 build_epg.py -o epg.json --back 3 --ahead 36

Sube epg.json a cualquier hosting estatico (GitHub Pages, tu servidor) y
pon esa URL en Ajustes > Guia de programacion. Ejecutalo cada 6-12 horas (cron).
"""
import argparse, gzip, io, json, re, sys, time, unicodedata, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

DEFAULT_SOURCES = [
    "https://epgshare01.online/epgshare01/epg_ripper_MX1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_US_SPORTS1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_US2.xml.gz",
]

NOISE = re.compile(r"\b(hd|sd|fhd|uhd|4k|tv|canal|channel)\b")


def norm(name):
    """Misma normalizacion que usa la app Roku (EpgKey)."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"\.(mx|us|ca|uk|es|ar|co|cl|pe|br)$", "", s)
    s = NOISE.sub(" ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def parse_time(t):
    # 20261103193700 +0000
    t = (t or "").strip()
    m = re.match(r"(\d{14})\s*([+-]\d{4})?", t)
    if not m:
        return None
    dt = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    off = m.group(2) or "+0000"
    sign = 1 if off[0] == "+" else -1
    delta = timedelta(hours=int(off[1:3]), minutes=int(off[3:5])) * sign
    return int((dt - delta).replace(tzinfo=timezone.utc).timestamp())


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "XuperTV-EPG/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if url.endswith(".gz") or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return io.BytesIO(data)


def read_source(fp, lo, hi):
    names, progs = {}, {}
    for _, el in ET.iterparse(fp, events=("end",)):
        if el.tag == "channel":
            cid = el.get("id")
            names[cid] = [d.text.strip() for d in el.findall("display-name") if d.text]
            el.clear()
        elif el.tag == "programme":
            a, b = parse_time(el.get("start")), parse_time(el.get("stop"))
            if a and b and b > lo and a < hi:
                title = el.findtext("title") or ""
                if title.strip():
                    progs.setdefault(el.get("channel"), []).append([a, b, title.strip()])
            el.clear()
    return names, progs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-s", "--source", action="append")
    ap.add_argument("-o", "--out", default="epg.json")
    ap.add_argument("--back", type=int, default=3, help="horas hacia atras")
    ap.add_argument("--ahead", type=int, default=36, help="horas hacia adelante")
    a = ap.parse_args()

    now = int(time.time())
    lo, hi = now - a.back * 3600, now + a.ahead * 3600
    merged = {}  # clave normalizada -> {names, programs}
    for url in (a.source or DEFAULT_SOURCES):
        try:
            names, progs = read_source(fetch(url), lo, hi)
        except Exception as e:  # una fuente caida no debe tumbar el resto
            print("AVISO: fallo %s -> %s" % (url, e), file=sys.stderr)
            continue
        added = 0
        for cid, plist in progs.items():
            cand = names.get(cid, []) + [cid]
            keys = {norm(n) for n in cand if norm(n)}
            if not keys:
                continue
            hit = next((merged[k] for k in keys if k in merged), None)
            if hit is None:  # la primera fuente que trae el canal gana
                hit = {"names": cand[:3], "programs": sorted(plist)}
                added += 1
            for k in keys:
                merged.setdefault(k, hit)
        print("%s: %d canales con programas" % (url.split("/")[-1], added))

    seen, channels = set(), []
    for v in merged.values():
        if id(v) not in seen:
            seen.add(id(v))
            channels.append(v)
    out = {"generated": now, "channels": {}}
    for k, v in merged.items():
        out["channels"][k] = v["programs"]
    out["names"] = {k: v["names"][0] for k, v in merged.items()}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("Escrito %s: %d canales, %d claves" % (a.out, len(channels), len(merged)))


if __name__ == "__main__":
    main()
