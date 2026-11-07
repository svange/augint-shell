"""Terminal QR rendering shared by the pairing/tunnel integrations.

Both the T3 pairing URL and the Expo tunnel URL have to be scannable from a
phone before the terminal is handed over to an agent, so the code is drawn
with half-block characters (two matrix rows per text row) — the same way t3's
own CLI draws its codes, so the two outputs look identical in a terminal.
"""

from __future__ import annotations


def render_qr(data: str, border: int = 2) -> str | None:
    """Render *data* as a half-block QR code, or None if segno is missing."""
    try:
        import segno
    except ImportError:  # pragma: no cover - segno is a declared dependency
        return None

    matrix = [bytearray(row) for row in segno.make(data, error="m").matrix]
    size = len(matrix)

    def dark(x: int, y: int) -> bool:
        return 0 <= x < size and 0 <= y < size and bool(matrix[y][x])

    rows: list[str] = []
    for y in range(-border, size + border, 2):
        row = ""
        for x in range(-border, size + border):
            top, bottom = dark(x, y), dark(x, y + 1)
            row += "█" if top and bottom else "▀" if top else "▄" if bottom else " "
        rows.append(row)
    return "\n".join(rows)
