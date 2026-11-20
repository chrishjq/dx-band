# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import dataclass

import sounddevice as sd


@dataclass(frozen=True, slots=True)
class AudioOutputDevice:
    index: int
    name: str
    channels: int
    default_sample_rate_hz: int


def list_output_devices() -> tuple[AudioOutputDevice, ...]:
    devices: list[AudioOutputDevice] = []
    for index, raw in enumerate(sd.query_devices()):
        channels = int(raw["max_output_channels"])
        if channels <= 0:
            continue
        devices.append(
            AudioOutputDevice(
                index=index,
                name=str(raw["name"]),
                channels=channels,
                default_sample_rate_hz=round(float(raw["default_samplerate"])),
            )
        )
    return tuple(devices)
