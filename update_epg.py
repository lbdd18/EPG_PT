#!/usr/bin/env python3
"""Regenera guide.xml (XMLTV) a partir do guia publico (modo "convidado",
sem login) da NOS TV, para todos os canais.

Uso:
    python3 update_epg.py

Pensado para correr diariamente via GitHub Actions (ver
.github/workflows/update-epg.yml), mas tambem podes correr localmente.
"""

import concurrent.futures
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
LOGOS_DIR = BASE_DIR / "Logos"
XMLTV_PATH = BASE_DIR / "guide.xml"

API_BASE = "https://api.clg.nos.pt/nostv/ott"
MAGE_BASE = "https://mage2.stream.nos.pt/mage/v1/Images"
# Client id publico usado pelo site nostv.pt em modo "convidado" (sem login).
CLIENT_ID = "xe1dgrShwdR1DVOKGmsj8Ut4QLlGyOFI"
# Onde os logos ficam publicamente acessiveis depois do push (raw.githubusercontent.com).
LOGOS_BASE_URL = "https://raw.githubusercontent.com/lbdd18/EPG_PT/main/Logos"

LISBON = ZoneInfo("Europe/Lisbon")
UTC = ZoneInfo("UTC")
DAYS_AHEAD = 2            # hoje + amanha
CHANNEL_BATCH_SIZE = 40   # canais por pedido de grelha, para nao sobrecarregar a API

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "X-Apikey": CLIENT_ID,
    "X-Core-DeviceType": "web",
    "X-Core-AppVersion": "2.20.2.2",
    "X-Core-ContentRatingLimit": "0",
    "X-Core-TimeZoneOffset": "0",
}


def api_get(path, params):
    url = f"{API_BASE}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_channels():
    return api_get("/channels/guest", {"client_id": CLIENT_ID})


def fetch_schedule(channel_ids, min_date, max_date):
    items = []
    for i in range(0, len(channel_ids), CHANNEL_BATCH_SIZE):
        batch = channel_ids[i : i + CHANNEL_BATCH_SIZE]
        items.extend(
            api_get(
                "/schedule/range/contents/guest",
                {
                    "channels": ",".join(batch),
                    "minDate": min_date,
                    "maxDate": max_date,
                    "isDateInclusive": "true",
                    "client_id": CLIENT_ID,
                },
            )
        )
    return items


def magify(source_uri):
    """Constroi o URL publico de imagem (proxy mage2.stream.nos.pt) a partir
    do URL interno devolvido pela API."""
    params = {"sourceUri": source_uri, "client_id": CLIENT_ID}
    ext = source_uri.rsplit(".", 1)[-1].lower()
    if ext == "png":
        params["format"] = "image/png"
    elif ext in ("jpg", "jpeg"):
        params["format"] = "image/jpeg"
    return f"{MAGE_BASE}?{urllib.parse.urlencode(params)}"


def safe_filename(name):
    unaccented = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", unaccented).strip("_")
    return cleaned or "canal"


def channel_logo_source(channel):
    for img in channel.get("Images", []):
        if img.get("Type") == 16:  # icone do canal
            return img["Url"]
    images = channel.get("Images") or []
    return images[0]["Url"] if images else None


def download_logo(channel):
    service_id = channel["ServiceId"]
    src = channel_logo_source(channel)
    if not src:
        return service_id, None

    ext = src.rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg"):
        ext = "png"
    filename = f"{service_id}-{safe_filename(channel['Name'])}.{ext}"
    dest = LOGOS_DIR / filename

    req = urllib.request.Request(magify(src), headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            dest.write_bytes(resp.read())
    except urllib.error.URLError as exc:
        print(f"  ! falhou logo de {channel['Name']}: {exc}", file=sys.stderr)
        return service_id, None
    return service_id, filename


def to_xmltv_time(iso_utc):
    dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return dt.astimezone(LISBON).strftime("%Y%m%d%H%M%S %z")


def build_xmltv(channels, schedule_items, logo_files):
    cache_bust = datetime.now(LISBON).strftime("%Y%m%d")
    tv = ET.Element(
        "tv",
        {
            "generator-info-name": "nos-tv-epg",
            "source-info-name": "NOS TV (guia publico / modo convidado)",
        },
    )
    for ch in sorted(channels, key=lambda c: int(c.get("Position") or 9999)):
        sid = ch["ServiceId"]
        chan_el = ET.SubElement(tv, "channel", {"id": sid})
        ET.SubElement(chan_el, "display-name").text = ch["Name"]
        logo_file = logo_files.get(sid)
        if logo_file:
            # O parametro de versao muda a cada execucao para forcar clientes
            # (Jellyfin, etc.) a re-descarregar o logo em vez de servirem uma
            # copia antiga em cache do mesmo URL indefinidamente.
            ET.SubElement(
                chan_el, "icon", {"src": f"{LOGOS_BASE_URL}/{logo_file}?v={cache_bust}"}
            )

    for item in schedule_items:
        sid = item.get("AiringChannel", {}).get("ServiceId")
        meta = item.get("Metadata", {})
        prog = ET.SubElement(
            tv,
            "programme",
            {
                "start": to_xmltv_time(item["UtcDateTimeStart"]),
                "stop": to_xmltv_time(item["UtcDateTimeEnd"]),
                "channel": sid,
            },
        )
        ET.SubElement(prog, "title", {"lang": "pt"}).text = meta.get("Title") or "Sem informacao"
        if meta.get("SubTitle"):
            ET.SubElement(prog, "sub-title", {"lang": "pt"}).text = meta["SubTitle"]
        if meta.get("Description"):
            ET.SubElement(prog, "desc", {"lang": "pt"}).text = meta["Description"]
        if meta.get("GenreDisplay"):
            ET.SubElement(prog, "category", {"lang": "pt"}).text = meta["GenreDisplay"]

    ET.indent(tv, space="  ")
    ET.ElementTree(tv).write(XMLTV_PATH, encoding="UTF-8", xml_declaration=True)


def main():
    print("A obter lista de canais...")
    channels = fetch_channels()
    print(f"  {len(channels)} canais")

    if LOGOS_DIR.exists():
        for old_file in LOGOS_DIR.iterdir():
            old_file.unlink()
    else:
        LOGOS_DIR.mkdir()

    print("A descarregar logos...")
    logo_files = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        for sid, filename in pool.map(download_logo, channels):
            if filename:
                logo_files[sid] = filename
    print(f"  {len(logo_files)}/{len(channels)} logos guardados em {LOGOS_DIR}")

    today_local = datetime.now(LISBON).replace(hour=0, minute=0, second=0, microsecond=0)
    range_end_local = today_local + timedelta(days=DAYS_AHEAD)
    min_date = today_local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    max_date = range_end_local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(
        f"A obter grelha de programacao ({DAYS_AHEAD} dias, "
        f"{today_local.date()} a {range_end_local.date()})..."
    )
    schedule_items = fetch_schedule(
        [c["ServiceId"] for c in channels], min_date, max_date
    )
    print(f"  {len(schedule_items)} emissoes")

    build_xmltv(channels, schedule_items, logo_files)
    print(f"Escrito {XMLTV_PATH}")


if __name__ == "__main__":
    main()
