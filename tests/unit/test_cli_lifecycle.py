from __future__ import annotations

import threading

from homewake.cli import _serve_forever


def test_serve_forever_returns_when_stop_event_is_set() -> None:
    stop_event = threading.Event()
    stop_event.set()

    _serve_forever(stop_event)
