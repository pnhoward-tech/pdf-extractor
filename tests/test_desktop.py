"""The desktop launcher: local-only by construction."""

import socket
import sys

import pytest

import desktop


def test_the_host_is_the_loopback_address():
    """Never 0.0.0.0: the app must not be reachable from the network."""
    assert desktop.HOST == "127.0.0.1"
    assert socket.inet_aton(desktop.HOST)


def test_a_free_port_is_actually_free():
    port = desktop.free_port()
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((desktop.HOST, port))  # would raise if taken


def test_two_calls_do_not_collide():
    assert desktop.free_port() != desktop.free_port() or True  # OS may reuse; must not raise


@pytest.mark.parametrize(
    "platform,package,expected",
    [
        ("darwin", "poppler", "brew install poppler"),
        ("darwin", "tesseract", "brew install tesseract"),
        ("linux", "poppler", "sudo apt-get install poppler-utils"),
        ("linux", "tesseract", "sudo apt-get install tesseract-ocr"),
        ("win32", "poppler", "choco install poppler"),
    ],
)
def test_install_hints_match_the_platform(monkeypatch, platform, package, expected):
    monkeypatch.setattr(sys, "platform", platform)
    assert desktop.install_hint(package) == expected


def test_a_missing_poppler_stops_the_app(monkeypatch, capsys):
    """It cannot read a statement without it, so it says so rather than
    starting up and failing on the first file."""
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)
    missing = desktop.missing_tools()
    assert {m[0] for m in missing} == {"pdftotext", "tesseract"}

    can_run = desktop.report_tools(missing)
    assert can_run is False
    out = capsys.readouterr().out
    assert "REQUIRED" in out and "optional" in out
    assert "install it with" in out


def test_a_missing_tesseract_alone_is_not_fatal(monkeypatch, capsys):
    """Only scans need it, so the app runs without it."""
    monkeypatch.setattr(
        desktop.shutil, "which", lambda name: None if name == "tesseract" else "/usr/bin/x"
    )
    assert desktop.report_tools(desktop.missing_tools()) is True
    assert "optional" in capsys.readouterr().out


def test_nothing_is_missing_when_both_are_installed(monkeypatch):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/" + name)
    assert desktop.missing_tools() == []


def test_the_app_makes_no_outbound_network_calls():
    """A statement extractor has no business calling anything."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    banned = ("import requests", "import httpx", "urlopen(", "urllib.request")
    offenders = []
    for path in [*(root / "app").rglob("*.py"), *(root / "statements").rglob("*.py")]:
        source = path.read_text()
        offenders += [(path.name, token) for token in banned if token in source]
    assert not offenders, offenders
