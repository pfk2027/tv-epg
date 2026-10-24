"""Build a trimmed XMLTV guide (epg.xml.gz) from the full source guide."""
import gzip
import io
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

SOURCE = "https://iptvx.one/epg/epg_lite.xml.gz"
HERE = Path(__file__).resolve().parent
CHANNELS_FILE = HERE / "channels.txt"
OUT_FILE = HERE / "epg.xml.gz"
PAST = timedelta(hours=3)
FUTURE = timedelta(hours=72)
MIN_CHANNELS = 50
MIN_PROGRAMMES = 1000


def download():
    last = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(SOURCE, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"download attempt {attempt} failed: {e}", file=sys.stderr)
            time.sleep(5 * attempt)
    raise SystemExit(f"download failed: {last}")


def parse_time(s):
    s = s.strip()
    return datetime.strptime(s, "%Y%m%d%H%M%S %z") if " " in s else \
        datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def main():
    wanted = {l.strip() for l in CHANNELS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()}
    raw = download()
    now = datetime.now(timezone.utc)
    lo, hi = now - PAST, now + FUTURE

    root = ET.Element("tv", {"generator-info-name": "tv-epg"})
    n_ch = n_pr = 0
    channels, programmes = [], []
    stream = gzip.GzipFile(fileobj=io.BytesIO(raw))
    for _, el in ET.iterparse(stream, events=("end",)):
        if el.tag == "channel":
            if el.get("id") in wanted:
                ch = ET.Element("channel", {"id": el.get("id")})
                for dn in el.findall("display-name"):
                    ch.append(ET.fromstring(ET.tostring(dn)))
                ic = el.find("icon")
                if ic is not None:
                    ch.append(ET.Element("icon", {"src": ic.get("src", "")}))
                channels.append(ch)
            el.clear()
        elif el.tag == "programme":
            if el.get("channel") in wanted:
                try:
                    start, stop = parse_time(el.get("start")), parse_time(el.get("stop"))
                except (ValueError, TypeError):
                    start = stop = None
                if start and stop and stop >= lo and start <= hi:
                    p = ET.Element("programme", {
                        "start": el.get("start"), "stop": el.get("stop"),
                        "channel": el.get("channel")})
                    for tag in ("title", "category"):
                        src = el.find(tag)
                        if src is not None:
                            c = ET.SubElement(p, tag, {k: v for k, v in src.attrib.items()})
                            c.text = src.text
                    programmes.append(p)
            el.clear()
    n_ch, n_pr = len(channels), len(programmes)
    root.extend(channels)
    root.extend(programmes)

    buf = io.BytesIO()
    ET.ElementTree(root).write(buf, encoding="utf-8", xml_declaration=True)
    tmp = OUT_FILE.with_suffix(".gz.tmp")
    with open(tmp, "wb") as f:
        with gzip.GzipFile(fileobj=f, mode="wb", compresslevel=9, mtime=0) as gz:
            gz.write(buf.getvalue())
    size = tmp.stat().st_size
    print(f"channels kept: {n_ch}/{len(wanted)}, programmes kept: {n_pr}, output: {size} bytes")
    if n_ch < MIN_CHANNELS or n_pr < MIN_PROGRAMMES:
        tmp.unlink()
        print("too little data, keeping previous epg.xml.gz", file=sys.stderr)
        sys.exit(1)
    tmp.replace(OUT_FILE)


if __name__ == "__main__":
    main()
