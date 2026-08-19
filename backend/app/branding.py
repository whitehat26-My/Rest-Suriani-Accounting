"""The restaurant's visual identity, sampled from the logo artwork.

Print and screen share these values so a payslip handed to a member of staff and
the dashboard it came from look like the same business.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
# The wordmark with its background removed, so it can be placed on the maroon
# band with no seam. The source JPEG's background carried compression noise at
# the edges, which showed as a visible box wherever it was drawn.
LOGO_MARK_PATH = ASSETS_DIR / "logo-mark.png"
LOGO_PATH = ASSETS_DIR / "logo.png"

# Sampled directly from the logo file rather than guessed, so the letterhead
# band and the artwork sitting on it are the same maroon to the pixel.
MAROON = HexColor("#431215")
GOLD = HexColor("#E0BB48")
CREAM = HexColor("#F4D18D")

INK = HexColor("#1A1A1A")
INK_SOFT = HexColor("#5A5A5A")
INK_FAINT = HexColor("#8C8C8C")
RULE = HexColor("#D8D3CA")
BAND = HexColor("#F6F3EC")
WHITE = HexColor("#FFFFFF")

# Status tints, kept muted so they survive a black-and-white printer.
POSITIVE = HexColor("#0B6B2E")
NEGATIVE = HexColor("#9A2A1E")

# The trimmed mark is 911 x 264; anything drawn from it keeps this ratio.
LOGO_ASPECT = 911 / 264
