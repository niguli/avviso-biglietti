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
import time
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


def send_push(title: str, message: str, click_url: str) -> None:
    """Notifica istantanea sul telefono tramite l'app gratuita ntfy (ntfy.sh)."""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return
    r = requests.post("https://ntfy.sh/", timeout=10, json={
        "topic": topic, "title": title, "message": message,
        "priority": 5, "tags": ["tickets"], "click": click_url,
    })
    r.raise_for_status()


def notify(title: str, message: str, click_url: str) -> None:
    """Prima la push (immediata), poi l'email. Un errore in una non blocca l'altra."""
    for name, fn in (("push", lambda: send_push(title, message, click_url)),
                     ("email", lambda: send_mail(title, message))):
        try:
            fn()
        except Exception as e:
            print(f"[ERRORE invio {name}] {e}", file=sys.stderr)


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
        notify(f"🎟️ Biglietti disponibili ({len(new)}) – Sampdoria", body, page)
        print(f"[NUOVI BIGLIETTI – avviso inviato] {event_id}: {len(new)}")
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

    if os.environ.get("TEST_EMAIL") == "true":
        notify("✅ Prova avviso biglietti",
               "Se leggi questo messaggio, gli avvisi funzionano.",
               f"{BASE_URL}/Partita/{ids[0]}")
        print("[avviso di prova inviato]")

    # Resta attivo per LOOP_MINUTES minuti, controllando ogni INTERVAL_SECONDS secondi.
    loop_s = float(os.environ.get("LOOP_MINUTES", "0")) * 60
    interval = float(os.environ.get("INTERVAL_SECONDS", "30"))
    end = time.monotonic() + loop_s
    errors = 0
    while True:
        print(time.strftime("%H:%M:%S"), end=" ")
        for event_id in ids:
            try:
                check(event_id)
            except Exception as e:
                errors += 1
                print(f"[ERRORE] {event_id}: {e}", file=sys.stderr)
        if time.monotonic() + interval > end:
            break
        time.sleep(interval)
    return 0 if loop_s or not errors else 1


if __name__ == "__main__":
    sys.exit(main())
