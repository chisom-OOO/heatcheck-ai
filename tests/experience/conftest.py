"""Shared helpers for the E-001 tests."""

from __future__ import annotations

import importlib.util
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "tests" / "fixtures" / "quotes" / "e001"


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "make_e001_bundle", Path(__file__).with_name("make_e001_bundle.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def builder():
    return load_builder()


@pytest.fixture
def no_network(monkeypatch):
    """Any socket use fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, refuse)
