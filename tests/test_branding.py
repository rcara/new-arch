"""Refonte visuelle New Arch — logo, thème clair par défaut, assets brand."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import create_app
from app.clock import FrozenClock
from app.http import resolve_theme
from tests.test_flows import Web

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "app" / "static" / "brand"
FONTS = ROOT / "app" / "static" / "fonts" / "brand"


@pytest.fixture
def clock():
    return FrozenClock(datetime(2027, 2, 20, 8, 0, tzinfo=timezone.utc))


@pytest.fixture
def world(tmp_path, clock):
    home = tmp_path / "inst"
    app = create_app(home=home, clock=clock, testing=True)
    web = Web(app)
    web.bootstrap()
    return web, app, home, clock


def test_brand_assets_present():
    for name in ("logo-full.png", "logo-mark.png", "logo-header.png", "favicon-32.png", "app-icon-192.png"):
        path = BRAND / name
        assert path.is_file(), name
        assert path.stat().st_size > 500
    assert (FONTS / "manrope-latin-600.woff2").is_file()
    assert (FONTS / "inter-latin-400.woff2").is_file()


def test_default_theme_is_light():
    assert resolve_theme(None) == "light"
    assert resolve_theme("") == "light"
    assert resolve_theme("dark") == "dark"


def test_shell_shows_official_logo_and_tagline(world):
    web, _app, _home, _clock = world
    home = web.get("/")
    assert home.status_code == 200
    assert b'data-theme="light"' in home.data
    assert b"brand/logo-mark.png" in home.data
    assert b"New Arch" in home.data
    assert b"Tableau de bord" in home.data or b"Bonjour" in home.data

    # Guest / login surfaces brand mark + signature
    web.submit("/deconnexion", {})
    login = web.get("/connexion")
    assert login.status_code == 200
    assert b"brand/logo-mark.png" in login.data
    assert "Organiser le foyer".encode() in login.data or b"simplement" in login.data


def test_css_tokens_and_static_served(world):
    web, app, _home, _clock = world
    css = web.c.get("/static/app.css", headers={"Host": "127.0.0.1:8765"})
    assert css.status_code == 200
    body = css.data.decode("utf-8")
    assert "--brand-navy:#24364A" in body or "--brand-navy: #24364A" in body.replace(" ", "")
    assert "--brand-ivory:#F7F4EE" in body.replace(" ", "") or "#F7F4EE" in body
    assert "Manrope" in body and "Inter" in body
    mark = web.c.get("/static/brand/logo-mark.png", headers={"Host": "127.0.0.1:8765"})
    assert mark.status_code == 200
    assert mark.data[:8] == b"\x89PNG\r\n\x1a\n"


def _first_pixel_alpha(path):
    """Alpha du pixel (0, 0) d'un PNG RGBA 8 bits (ligne 0 : le premier pixel n'est jamais filtré)."""
    import struct
    import zlib

    data = path.read_bytes()
    pos, idat = 8, b""
    width = depth = color = None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, _height, depth, color = struct.unpack(">IIBB", chunk[:10])
        elif kind == b"IDAT":
            idat += chunk
        pos += 12 + length
    assert depth == 8 and color == 6, (path.name, depth, color)
    return zlib.decompress(idat)[1 + 3]


def test_logos_have_transparent_background():
    for name in ("logo-mark.png", "logo-full.png", "logo-lockup.png", "logo-header.png", "favicon-32.png"):
        assert _first_pixel_alpha(BRAND / name) == 0, name
