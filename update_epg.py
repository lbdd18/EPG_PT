#!/usr/bin/env python3
"""Regenera guide.xml (XMLTV) a partir do guia publico (modo "convidado",
sem login) da NOS TV, para todos os canais.

Uso:
    python3 update_epg.py

Pensado para correr diariamente via GitHub Actions (ver
.github/workflows/update-epg.yml), mas tambem podes correr localmente.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
XMLTV_PATH = BASE_DIR / "guide.xml"

API_BASE = "https://api.clg.nos.pt/nostv/ott"
# Client id publico usado pelo site nostv.pt em modo "convidado" (sem login).
CLIENT_ID = "xe1dgrShwdR1DVOKGmsj8Ut4QLlGyOFI"

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


def to_xmltv_time(iso_utc):
    dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return dt.astimezone(LISBON).strftime("%Y%m%d%H%M%S %z")


def build_xmltv(channels, schedule_items):
    tv = ET.Element(
        "tv",
        {
            "generator-info-name": "nos-tv-epg",
            "source-info-name": "NOS TV (guia publico / modo convidado)",
        },
    )
    for ch in sorted(channels, key=lambda c: int(c.get("Position") or 9999)):
        chan_el = ET.SubElement(tv, "channel", {"id": ch["ServiceId"]})
        ET.SubElement(chan_el, "display-name").text = ch["Name"]

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

    build_xmltv(channels, schedule_items)
    print(f"Escrito {XMLTV_PATH}")


if __name__ == "__main__":
    main()
