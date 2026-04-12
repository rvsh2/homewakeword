"""Typed audio payloads shared between protocol and detector layers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """A block of mono PCM audio ready for detector consumption."""

    pcm: bytes
    sample_rate_hz: int
    sample_width_bytes: int
    channels: int = 1

    @property
    def frame_count(self) -> int:
        """Returns the number of PCM frames represented by this chunk."""

        bytes_per_frame = self.sample_width_bytes * self.channels
        if bytes_per_frame == 0:
            return 0
        return len(self.pcm) // bytes_per_frame
