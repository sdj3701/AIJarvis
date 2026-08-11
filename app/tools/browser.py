"""Safe browser URL opening without shell injection."""

from __future__ import annotations

import os
import sys
import webbrowser


def open_url_with_browser(url: str) -> None:
    if sys.platform == "win32":
        os.startfile(url)
    else:
        webbrowser.open(url, new=2, autoraise=True)
