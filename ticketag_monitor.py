#!/usr/bin/env python3
"""
Avvisa via email quando compaiono biglietti in rivendita su Ticketag (Sampdoria).

Legge direttamente i dati che usa la pagina:
  https://sampdoria-ticketag.ticketone.it/api/events/<ID>/tickets
e manda un'email solo per i biglietti NUOVI (non ripete l'avviso per quelli già segnalati).

Variabili d'ambiente: SMTP_USER, SMTP_PASS, MAIL_TO (facoltativo), EVENT_IDS
(uno o più ID partita separati da virgola; l'ID è l'ultima parte dell'indirizzo della pagina).
"""

import json
import os
import sys
from pathlib import Path

import requests

from monitor import send_mail  # riusa l'invio email dell'altro script

BASE_URL = "https://sampdoria-ticketag.ticketone.it"
STATE_DIR = Path(__file__).parent / "state"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; web-monitor/1.0)",
           "Accept": "application/json"}


def describe(t: dict) -> str:
    sect = " ".join(str(t[k]) for k in ("section", "subSection") if t.get(k))
    where = f"Fila {t.get('row', '?')}, Posto {t.get('seat', '?')}"
    price = t.get("price")
    price = f"{price / 100:.2f} €" if isinstance(price, (int, float)) else "prezzo n.d."
    return f"- {sect or 'Settore n.d.'} – {where} – {price}"


def key(t: dict) -> str:
    return str(t.get("id") or json.dumps(t, sort_keys=True))


def check(event_id: str) -> None:
    r = requests.get(f"{BASE_URL}/api/events/{event_id}/tickets", headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    offers = (data.get("tickets") or []) + (data.get("bundles") or [])

    state_file = STATE_DIR / f"ticketag_{event_id}.json"
    seen = set(json.loads(state_file.read_text())) if state_file.exists() else set()
    current = {key(t): t for t in offers}
    new = [t for k, t in current.items() if k not in seen]

    if new:
        page = f"{BASE_URL}/Partita/{event_id}"
        body = (f"Ci sono {len(new)} nuovi posti in rivendita:\n\n"
                + "\n".join(describe(t) for t in new)
                + f"\n\nCorri a prenderli: {page}\n")
        send_mail(f"🎟️ Biglietti disponibili ({len(new)}) – Sampdoria", body)
        print(f"[NUOVI BIGLIETTI – email inviata] {event_id}: {len(new)}")
    else:
        print(f"[nessun nuovo biglietto] {event_id} (in vendita ora: {len(offers)})")

    # Ricorda solo quelli ancora in vendita: se uno sparisce e ricompare, avvisa di nuovo.
    state_file.write_text(json.dumps(sorted(current)))


def main() -> int:
    STATE_DIR.mkdir(exist_ok=True)
    ids = [i.strip() for i in os.environ.get("EVENT_IDS", "").split(",") if i.strip()]
    if not ids:
        print("Imposta EVENT_IDS", file=sys.stderr)
        return 1
    errors = 0
    for event_id in ids:
        try:
            check(event_id)
        except Exception as e:
            errors += 1
            print(f"[ERRORE] {event_id}: {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
