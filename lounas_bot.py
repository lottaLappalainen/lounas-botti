"""Scrapes lunch menus and posts them to a Teams channel."""

from __future__ import annotations

import datetime
import json
import os

import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

HELSINKI_TZ = ZoneInfo("Europe/Helsinki")

FINNISH_WEEKDAYS = {
    0: "Maanantai",
    1: "Tiistai",
    2: "Keskiviikko",
    3: "Torstai",
    4: "Perjantai",
    5: "Lauantai",
    6: "Sunnuntai",
}

# Essive case ("on Wednesday" = "keskiviikkona"), used in the message intro.
FINNISH_WEEKDAYS_ESSIVE = {
    0: "maanantaina",
    1: "tiistaina",
    2: "keskiviikkona",
    3: "torstaina",
    4: "perjantaina",
    5: "lauantaina",
    6: "sunnuntaina",
}

FINNISH_WEEKDAYS_UPPER = {name.upper(): name for name in FINNISH_WEEKDAYS.values()}

JUUSTOPORTTI_URL = "https://www.juustoportti.fi/liikenneasema/juustoportti-ylojarvi/"
AITOLEIPA_URL = "https://aitoleipa.fi/toimipiste/ylojarvi/"
PIRJONPAKARI_URL = "https://pirjonpakari.fi/leipomomyymalat-kahvilat/ylojarvi/"
LEMPI_URL = "https://www.xn--yljrvenlempi-icb4w.fi/"

REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (lounas-botti)"}


def _today_weekday_name(today: datetime.date | None = None) -> str:
    today = today or datetime.datetime.now(HELSINKI_TZ).date()
    return FINNISH_WEEKDAYS[today.weekday()]


def scrape_juustoportti(today: datetime.date | None = None) -> list[str]:
    """Return today's Juustoportti Ylöjärvi lunch items as a list of strings."""
    weekday_name = _today_weekday_name(today)

    response = requests.get(JUUSTOPORTTI_URL, headers=REQUEST_HEADERS, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    container = soup.select_one("#lounaslista div.lunch-list")
    if container is None:
        return []

    items: list[str] = []
    current_day = None
    for el in container.find_all(["h4", "p", "div"], recursive=False):
        if el.name == "div" and "more-days" in (el.get("class") or []):
            # Second week is hidden behind a "show more" button — the current
            # week's Mon-Fri is always in the visible part above this point.
            break
        if el.name == "h4":
            current_day = el.get_text(strip=True).split(" ")[0]
            continue
        if el.name != "p" or current_day != weekday_name:
            continue
        classes = el.get("class") or []
        if "option-name" in classes:
            items.append(el.get_text(strip=True))
        elif "option-description" in classes and items:
            items[-1] = f"{items[-1]} – {el.get_text(strip=True)}"

    return items


def scrape_aitoleipa(today: datetime.date | None = None) -> list[str]:
    """Return today's Aitoleipä Ylöjärvi lunch items as a list of strings."""
    weekday_name = _today_weekday_name(today)

    response = requests.get(AITOLEIPA_URL, headers=REQUEST_HEADERS, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    for day_el in soup.select("div.lounas-item"):
        title_el = day_el.select_one(".lounas-day-title")
        if title_el is None or title_el.get_text(strip=True) != weekday_name:
            continue

        content = day_el.select_one(".lounas-content-inner")
        if content is None:
            return []

        items: list[str] = []
        for p in content.find_all("p", recursive=False):
            strong = p.find("strong")
            em = p.find("em")
            if strong is not None:
                items.append(strong.get_text(strip=True))
            elif em is not None and items:
                items[-1] = f"{items[-1]} – {em.get_text(strip=True)}"
        return items

    return []


def scrape_pirjonpakari(today: datetime.date | None = None) -> list[str]:
    """Return today's Pirjon Pakari Ylöjärvi lunch items as a list of strings.

    The list is "valid until further notice" (one soup per weekday, no dates),
    so it's the same every week rather than scoped to a specific date.
    """
    weekday_name = _today_weekday_name(today)
    weekday_values = set(FINNISH_WEEKDAYS.values())

    response = requests.get(PIRJONPAKARI_URL, headers=REQUEST_HEADERS, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    container = soup.select_one("div.lunchlist")
    if container is None:
        return []

    current_day = None
    for p in container.select("p.wp-block-paragraph"):
        text = p.get_text(strip=True)
        if p.find("strong") is not None and text in weekday_values:
            current_day = text
            continue
        if current_day == weekday_name:
            return [text]
        current_day = None

    return []


def scrape_lempi(today: datetime.date | None = None) -> list[str]:
    """Return today's Lempi (lounasbuffet) items as a list of strings.

    Lempi's page is a hand-formatted, multi-vendor layout with no clean
    section boundaries, so this walks <strong> tags after the "LOUNAS
    BUFFET" heading and stops at the first all-caps entry that isn't a
    weekday name — that marks the end of the buffet listing and the start
    of unrelated price-list/promo text.
    """
    weekday_name = _today_weekday_name(today)

    response = requests.get(LEMPI_URL, headers=REQUEST_HEADERS, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    start = None
    for p in soup.select("p.vendor-name"):
        if "LOUNAS BUFFET" in p.get_text():
            start = p
            break
    if start is None:
        return []

    items_by_day: dict[str, list[str]] = {}
    current_day = None
    for strong in start.find_all_next("strong"):
        text = strong.get_text(strip=True)
        if not text:
            continue
        key = text.rstrip(":").upper()
        if key in FINNISH_WEEKDAYS_UPPER:
            current_day = FINNISH_WEEKDAYS_UPPER[key]
            items_by_day.setdefault(current_day, [])
            continue
        if text.isupper():
            break
        if current_day:
            items_by_day[current_day].append(text)

    return items_by_day.get(weekday_name, [])


def format_teams_message(
    sections: list[tuple[str, list[str]]],
    today: datetime.date | None = None,
) -> dict:
    """Combine one or more (restaurant name, items) sections into a Teams payload.

    The payload has a single "text" field with Markdown content, matching the
    default "Post to a channel when a webhook request is received" Workflows
    template, so no extra Adaptive Card authoring is needed on the Teams side.
    """
    today = today or datetime.datetime.now(HELSINKI_TZ).date()
    weekday_essive = FINNISH_WEEKDAYS_ESSIVE[today.weekday()]
    date_str = f"{today.day}.{today.month}"

    lines = [f"Tänään {date_str} {weekday_essive} meillä on ylöjärvellä tarjolla lounaaksi:"]
    for name, items in sections:
        lines.append("")
        lines.append(f"**{name}**")
        if items:
            lines.extend(f"- {item}" for item in items)
        else:
            lines.append("_Ei löytynyt lounaslistaa tänään – tarkista sivu manuaalisesti._")

    return {"text": "\n".join(lines)}


def send_to_teams(payload: dict, webhook_url: str) -> None:
    """POST a formatted payload to a Teams Workflows webhook URL."""
    response = requests.post(webhook_url, json=payload, timeout=15)
    response.raise_for_status()


def _should_send_now(now: datetime.datetime) -> bool:
    """Guard against the GitHub Actions cron double-fire around DST changes.

    The workflow schedules two cron triggers (one per Finnish UTC offset) so
    that 10:30 local time is always covered. Only one of them actually lands
    near 10:30 on a given day — this filters out the other one. It only
    applies to the real GitHub Actions "schedule" trigger; manual runs
    (workflow_dispatch) and local runs always send, so testing isn't tied to
    the clock.
    """
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        return True
    if now.weekday() > 4:
        return False
    target = now.replace(hour=10, minute=30, second=0, microsecond=0)
    return abs((now - target).total_seconds()) <= 10 * 60


def main(now: datetime.datetime | None = None) -> None:
    now = now or datetime.datetime.now(HELSINKI_TZ)

    if not _should_send_now(now):
        print(f"Skipping run — {now.isoformat()} is outside the weekday/10:30 send window.")
        return

    today = now.date()
    sections = [
        ("Juustoportti", scrape_juustoportti(today)),
        ("Aitoleipä", scrape_aitoleipa(today)),
        ("Pirjon Pakari", scrape_pirjonpakari(today)),
        ("Lempi", scrape_lempi(today)),
    ]
    payload = format_teams_message(sections, today)

    webhook_url = os.environ.get("TEAMS_WEBHOOK_URL")
    if webhook_url:
        send_to_teams(payload, webhook_url)
        print("Sent to Teams.")
    else:
        print("TEAMS_WEBHOOK_URL not set — printing payload instead of sending:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
