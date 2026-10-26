"""Contrôles statiques : pas de réseau, pas de périmètre exclu, schéma non exposé."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Exception produit : sync Google Calendar (serveur → Google uniquement, CSP form-action 'self').
_GOOGLE_HTTPS_ALLOW = (
    "https://accounts.google.com/o/oauth2/v2/auth",
    "https://oauth2.googleapis.com/token",
    "https://oauth2.googleapis.com/revoke",
    "https://openidconnect.googleapis.com/v1/userinfo",
    "https://www.googleapis.com/calendar/v3",
    "https://www.googleapis.com/auth/calendar",
)


def test_pas_de_reseau_externe_ni_d_exposition():
    texts = []
    for path in (ROOT / "app").rglob("*"):
        if path.suffix in {".py", ".html", ".css"}:
            texts.append(path.read_text(encoding="utf-8"))
    texts.append((ROOT / "launcher.py").read_text(encoding="utf-8"))
    blob = "\n".join(texts)
    assert "0.0.0.0" not in blob
    scrubbed = blob
    for url in _GOOGLE_HTTPS_ALLOW:
        scrubbed = scrubbed.replace(url, "")
    assert "https://" not in scrubbed
    assert "http://" not in scrubbed.replace("http://127.0.0.1", "")
    assert "index_projection" not in blob
    assert "SELECT *" not in blob and "SELECT f.*" not in blob


def test_perimetre_exclu_absent_du_code():
    blob = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "app").rglob("*.py"))
    for word in ("stripe", "smtp", "paypal", "telegram", "habitude", "coach"):
        assert word not in blob.lower()
