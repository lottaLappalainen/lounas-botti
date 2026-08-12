"""Scrapes lunch menus and posts them to a Teams channel."""

from __future__ import annotations

import datetime
import json

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

JUUSTOPORTTI_URL = "https://www.juustoportti.fi/liikenneasema/juustoportti-ylojarvi/"
AITOLEIPA_URL = "https://aitoleipa.fi/toimipiste/ylojarvi/"

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


if __name__ == "__main__":
    sections = [
        ("Juustoportti", scrape_juustoportti()),
        ("Aitoleipä", scrape_aitoleipa()),
    ]
    payload = format_teams_message(sections)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
