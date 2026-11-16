#!/usr/bin/env python3
"""
Monitora una o più pagine web e invia un'email quando il TESTO VISIBILE cambia.

Configurazione:
  - urls.txt   : una pagina per riga, opzionalmente con un selettore CSS
                 separato da " | " per controllare solo una parte della pagina.
                 Es:  https://example.com/news | div.article-list
  - Variabili d'ambiente per l'email:
        SMTP_HOST (default smtp.gmail.com)
        SMTP_PORT (default 465)
        SMTP_USER  (es. tuoindirizzo@gmail.com)
        SMTP_PASS  (per Gmail: una "password per le app", non la password normale)
        MAIL_TO    (destinatario; default = SMTP_USER)

Lo stato (ultimo testo visto per ogni pagina) è salvato nella cartella state/.
"""

import difflib
import hashlib
import os
import re
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).parent
STATE_DIR = BASE / "state"
URLS_FILE = BASE / "urls.txt"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; web-monitor/1.0)"}


def visible_text(html: str, selector: str | None) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template", "svg", "head"]):
        tag.decompose()
    root = soup.select_one(selector) if selector else soup.body or soup
    if root is None:
        raise ValueError(f"Selettore '{selector}' non trovato nella pagina")
    lines = (re.sub(r"\s+", " ", l).strip() for l in root.get_text("\n").splitlines())
    return "\n".join(l for l in lines if l)


def state_path(url: str, selector: str | None) -> Path:
    key = hashlib.sha1(f"{url}|{selector or ''}".encode()).hexdigest()[:16]
    return STATE_DIR / f"{key}.txt"


def send_mail(subject: str, body: str) -> None:
    user = os.environ["SMTP_USER"]
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = os.environ.get("MAIL_TO", user)
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port) as s:
        s.login(user, os.environ["SMTP_PASS"])
        s.send_message(msg)


def check(url: str, selector: str | None) -> None:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    new = visible_text(r.text, selector)
    path = state_path(url, selector)

    if not path.exists():
        path.write_text(new, encoding="utf-8")
        print(f"[prima lettura] {url}")
        return

    old = path.read_text(encoding="utf-8")
    if old == new:
        print(f"[invariata] {url}")
        return

    diff = "\n".join(difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile="prima", tofile="adesso", lineterm="", n=2))
    if len(diff) > 20000:
        diff = diff[:20000] + "\n… (diff troncato)"
    send_mail(f"Pagina cambiata: {url}",
              f"La pagina {url} è cambiata.\n\nRighe tolte (-) e aggiunte (+):\n\n{diff}\n")
    path.write_text(new, encoding="utf-8")
    print(f"[CAMBIATA – email inviata] {url}")


def main() -> int:
    STATE_DIR.mkdir(exist_ok=True)
    errors = 0
    for raw in URLS_FILE.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        url, _, sel = (p.strip() for p in raw.partition("|"))
        try:
            check(url, sel or None)
        except Exception as e:  # una pagina in errore non blocca le altre
            errors += 1
            print(f"[ERRORE] {url}: {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
