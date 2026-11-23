# SPDX-License-Identifier: GPL-3.0-or-later
"""Terreno reads files and tiles it did not write: KML/KMZ from a phone or a
colleague, tiles from a server the user picked. Neither may exhaust memory
because a header says so, and a damaged KMZ is reported, not raised."""
from __future__ import annotations

import io
import zipfile

import pytest

from plugins.terreno import kml, tiles

KML = ("<kml xmlns='http://www.opengis.net/kml/2.2'><Document><Placemark><name>A</name>"
       "<Point><coordinates>-71.5,-16.4,0</coordinates></Point></Placemark></Document></kml>")


def _kmz(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


# -- KML / KMZ ---------------------------------------------------------------------------

def test_a_normal_kmz_still_reads(tmp_path):
    features = kml.parse_file(_kmz(tmp_path / "ok.kmz", {"doc.kml": KML}))
    assert [f.name for f in features] == ["A"]


def test_a_kmz_member_that_inflates_past_the_limit_is_refused_before_reading(
        tmp_path, monkeypatch):
    monkeypatch.setattr(kml, "MAX_KML_BYTES", 1000)
    padded = KML.replace("<name>A</name>", "<name>A</name><!--" + "x" * 5000 + "-->")
    path = _kmz(tmp_path / "big.kmz", {"doc.kml": padded})
    assert path.stat().st_size < 1000            # small on disk, large inflated
    read = []
    monkeypatch.setattr(zipfile.ZipFile, "read",
                        lambda self, name, pwd=None: read.append(name) or b"")
    with pytest.raises(ValueError, match="inflates"):
        kml.parse_file(path)
    assert read == []                            # refused before inflating


def test_a_plain_kml_past_the_limit_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(kml, "MAX_KML_BYTES", 1000)
    path = tmp_path / "big.kml"
    path.write_text(KML + " " * 2000, encoding="utf-8")
    with pytest.raises(ValueError):
        kml.parse_file(path)


def test_a_damaged_kmz_is_a_value_error_that_kmlin_reports(tmp_path):
    path = _kmz(tmp_path / "doc.kmz", {"doc.kml": KML})
    data = bytearray(path.read_bytes())
    start = data.find(b"PK\x03\x04") + 30 + len(b"doc.kml")
    data[start:start + 8] = b"\xff" * 8          # corrupt the deflated stream
    path.write_bytes(bytes(data))
    with pytest.raises(ValueError, match="damaged KMZ"):
        kml.parse_file(path)


def test_an_overlay_image_past_the_limit_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(kml, "MAX_KML_BYTES", 1000)
    path = _kmz(tmp_path / "ov.kmz", {"doc.kml": KML, "files/o.png": b"\0" * 5000})
    with pytest.raises(ValueError):
        kml.overlay_image(path)


# Guards, not fixes: the XML parser already refuses these. If a future
# Python or expat changes its defaults, these tests say so before a user does.

def test_guard_an_external_entity_is_not_resolved():
    hostile = ("<?xml version='1.0'?><!DOCTYPE kml [<!ENTITY x SYSTEM 'file:///etc/passwd'>]>"
               "<kml><Document><Placemark><name>&x;</name><Point>"
               "<coordinates>0,0,0</coordinates></Point></Placemark></Document></kml>")
    assert kml.parse(hostile) == []


def test_guard_an_entity_bomb_is_not_expanded():
    levels = "".join(f"<!ENTITY e{i} '{f'&e{i - 1};' * 10}'>" for i in range(1, 10))
    bomb = (f"<?xml version='1.0'?><!DOCTYPE kml [<!ENTITY e0 'xxxxxxxxxx'>{levels}]>"
            "<kml><Document><Placemark><name>&e9;</name></Placemark></Document></kml>")
    assert kml.parse(bomb) == []


# -- tiles -----------------------------------------------------------------------------------

class _Response:
    def __init__(self, body, length=None, chunk=None):
        self._body = io.BytesIO(body)
        self.headers = {} if length is None else {"Content-Length": str(length)}
        self._chunk = chunk
        self.reads = 0

    def read(self, n=-1):
        self.reads += 1
        return self._body.read(self._chunk if self._chunk else n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(monkeypatch, response):
    opened = []

    def urlopen(request, timeout=None):
        opened.append(request.full_url)
        return response
    monkeypatch.setattr(tiles.urllib.request, "urlopen", urlopen)
    return opened


def test_a_normal_tile_is_returned(monkeypatch):
    _serve(monkeypatch, _Response(b"PNG" * 10, length=30))
    assert tiles.fetch_url("https://tiles.test/1/2/3.png") == b"PNG" * 10


def test_plain_http_is_still_fetched_for_local_servers(monkeypatch):
    opened = _serve(monkeypatch, _Response(b"ok"))
    assert tiles.fetch_url("http://192.168.1.20/tiles/1/2/3.png") == b"ok"
    assert opened


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/1/2/3.png", "1/2/3.png"])
def test_other_schemes_are_refused_without_opening(monkeypatch, url):
    opened = _serve(monkeypatch, _Response(b"secret"))
    with pytest.raises(tiles.TileError, match="only http and https"):
        tiles.fetch_url(url)
    assert opened == []


def test_a_declared_length_past_the_limit_is_not_read(monkeypatch):
    response = _Response(b"x" * 100, length=100)
    _serve(monkeypatch, response)
    with pytest.raises(tiles.TileError):
        tiles.fetch_url("https://tiles.test/a.png", max_bytes=50)
    assert response.reads == 0


def test_a_body_past_the_limit_is_cut_whatever_the_header_says(monkeypatch):
    response = _Response(b"x" * 400, length=None, chunk=80)
    _serve(monkeypatch, response)
    with pytest.raises(tiles.TileError):
        tiles.fetch_url("https://tiles.test/a.png", max_bytes=100)
    assert response.reads <= 3                   # stopped once past 100 bytes
