# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

def format_time_ms(value_ms: int) -> str:
    value_ms = max(0, value_ms)
    minutes, remainder_ms = divmod(value_ms, 60_000)
    seconds, milliseconds = divmod(remainder_ms, 1000)
    return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def parse_time_ms(value: str) -> int:
    value = value.strip()
    try:
        minutes_text, rest = value.split(":", maxsplit=1)
        seconds_text, milliseconds_text = rest.split(".", maxsplit=1)
        minutes = int(minutes_text)
        seconds = int(seconds_text)
        milliseconds = int(milliseconds_text.ljust(3, "0")[:3])
    except (ValueError, TypeError) as exc:
        raise ValueError("时间格式应为 mm:ss.mmm") from exc
    if minutes < 0 or not 0 <= seconds < 60 or milliseconds < 0:
        raise ValueError("时间值无效")
    return minutes * 60_000 + seconds * 1000 + milliseconds
