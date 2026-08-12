"""Scrapes lunch menus and posts them to a Teams channel."""

from __future__ import annotations

import datetime

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


if __name__ == "__main__":
    print("Juustoportti Ylöjärvi:")
    for item in scrape_juustoportti():
        print(f"- {item}")

    print("\nAitoleipä Ylöjärvi:")
    for item in scrape_aitoleipa():
        print(f"- {item}")
