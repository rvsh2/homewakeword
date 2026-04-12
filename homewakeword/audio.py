"""Audio streaming helpers and deterministic frontend utilities."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import struct
from typing import Iterable, Protocol, cast
import wave

from homewakeword.config import AudioInputConfig, LogMelFrontendConfig


class AudioFormatError(ValueError):
    """Raised when audio does not satisfy the frozen runtime contract."""


class NoiseSuppressionRuntimeError(RuntimeError):
    """Raised when Speex noise suppression cannot be initialized or used."""


class _NoiseSuppressorProtocol(Protocol):
    def process(self, pcm: bytes) -> bytes: ...


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


@dataclass(frozen=True, slots=True)
class WindowedSamples:
    """One deterministic rolling-window snapshot."""

    samples: tuple[float, ...]
    chunk_index: int
    padded_left_samples: int
    chunk_rms: float
    chunk_peak_abs: float


@dataclass(frozen=True, slots=True)
class FrontendFeatures:
    """Deterministic frontend output for one streaming step."""

    frames: tuple[tuple[float, ...], ...]
    feature_hash: str
    chunk_index: int
    padded_left_samples: int
    chunk_rms: float
    chunk_peak_abs: float

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def mel_bin_count(self) -> int:
        return len(self.frames[0]) if self.frames else 0


def validate_audio_chunk(chunk: AudioChunk, config: AudioInputConfig) -> None:
    """Validates one runtime chunk against the frozen PCM contract."""

    if chunk.sample_rate_hz != config.sample_rate_hz:
        raise AudioFormatError(
            f"unsupported sample rate: expected {config.sample_rate_hz} Hz, got {chunk.sample_rate_hz} Hz"
        )
    if chunk.sample_width_bytes != config.sample_width_bytes:
        raise AudioFormatError(
            f"unsupported sample width: expected {config.sample_width_bytes} bytes, got {chunk.sample_width_bytes} bytes"
        )
    if chunk.channels != config.channels:
        raise AudioFormatError(
            f"unsupported channel count: expected {config.channels}, got {chunk.channels}"
        )
    if chunk.frame_count != config.frame_samples:
        raise AudioFormatError(
            f"unsupported chunk alignment: expected {config.frame_samples} samples, got {chunk.frame_count}"
        )


def pcm16le_to_floats(pcm: bytes) -> tuple[float, ...]:
    """Converts mono PCM16 little-endian bytes into normalized floats."""

    if len(pcm) % 2 != 0:
        raise AudioFormatError("PCM16 payload must contain an even number of bytes")
    frame_count = len(pcm) // 2
    if frame_count == 0:
        return ()
    samples = struct.unpack("<" + "h" * frame_count, pcm)
    return tuple(sample / 32768.0 for sample in samples)


def floats_to_pcm16le(samples: Iterable[float]) -> bytes:
    """Encodes normalized floats into PCM16 little-endian bytes."""

    encoded: list[int] = []
    for sample in samples:
        clipped = max(-1.0, min(1.0, sample))
        if clipped >= 1.0:
            value = 32767
        else:
            value = int(round(clipped * 32768.0))
            value = max(-32768, min(32767, value))
        encoded.append(value)
    return struct.pack("<" + "h" * len(encoded), *encoded) if encoded else b""


def _rms(samples: tuple[float, ...]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def _peak_abs(samples: tuple[float, ...]) -> float:
    if not samples:
        return 0.0
    return max(abs(sample) for sample in samples)


def _hash_frames(frames: tuple[tuple[float, ...], ...]) -> str:
    normalized = [[round(value, 6) for value in frame] for frame in frames]
    payload = json.dumps(normalized, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class RollingAudioWindow:
    """Maintains a left-padded rolling one-second audio context."""

    def __init__(self, config: AudioInputConfig) -> None:
        self._config = config
        self._samples: list[float] = []
        self._chunk_index = 0

    def reset(self) -> None:
        self._samples.clear()
        self._chunk_index = 0

    def append(self, chunk: AudioChunk) -> WindowedSamples:
        validate_audio_chunk(chunk, self._config)
        chunk_samples = pcm16le_to_floats(chunk.pcm)
        self._chunk_index += 1
        self._samples.extend(chunk_samples)
        if len(self._samples) > self._config.window_samples:
            overflow = len(self._samples) - self._config.window_samples
            del self._samples[:overflow]
        padded_left_samples = max(0, self._config.window_samples - len(self._samples))
        window = [0.0] * padded_left_samples + self._samples
        return WindowedSamples(
            samples=tuple(window),
            chunk_index=self._chunk_index,
            padded_left_samples=padded_left_samples,
            chunk_rms=_rms(chunk_samples),
            chunk_peak_abs=_peak_abs(chunk_samples),
        )


@dataclass(slots=True)
class SpeexNoiseSuppressor:
    """Stateful SpeexDSP noise suppression matching openWakeWord usage."""

    frame_size: int = 160
    sample_rate_hz: int = 16_000
    _noise_suppressor: _NoiseSuppressorProtocol | None = None

    def open(self) -> None:
        if self._noise_suppressor is not None:
            return
        try:
            from speexdsp_ns import NoiseSuppression  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise NoiseSuppressionRuntimeError(
                "Speex noise suppression requires the 'speexdsp-ns' package"
            ) from exc
        self._noise_suppressor = NoiseSuppression.create(
            self.frame_size, self.sample_rate_hz
        )

    def close(self) -> None:
        self._noise_suppressor = None

    def process_chunk(self, chunk: AudioChunk) -> AudioChunk:
        if self._noise_suppressor is None:
            raise NoiseSuppressionRuntimeError(
                "Speex noise suppression is not initialized"
            )
        validate_audio_chunk(
            chunk,
            AudioInputConfig(
                sample_rate_hz=self.sample_rate_hz,
                sample_width_bytes=chunk.sample_width_bytes,
                channels=chunk.channels,
                frame_samples=chunk.frame_count,
                window_seconds=chunk.frame_count / self.sample_rate_hz,
            ),
        )
        samples = struct.unpack("<" + "h" * chunk.frame_count, chunk.pcm)
        processed_frames: list[bytes] = []
        noise_suppressor = cast(_NoiseSuppressorProtocol, self._noise_suppressor)
        for start in range(0, len(samples), self.frame_size):
            frame = samples[start : start + self.frame_size]
            processed_frames.append(
                noise_suppressor.process(struct.pack("<" + "h" * len(frame), *frame))
            )
        return AudioChunk(
            pcm=b"".join(processed_frames),
            sample_rate_hz=chunk.sample_rate_hz,
            sample_width_bytes=chunk.sample_width_bytes,
            channels=chunk.channels,
        )


def iter_wave_chunks(path: Path, config: AudioInputConfig) -> list[AudioChunk]:
    """Loads a WAV file and returns padded 80 ms chunks."""

    with wave.open(str(path), "rb") as wav_file:
        sample_rate_hz = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width_bytes = wav_file.getsampwidth()
        if sample_rate_hz != config.sample_rate_hz:
            raise AudioFormatError(
                f"unsupported sample rate: expected {config.sample_rate_hz} Hz, got {sample_rate_hz} Hz"
            )
        if channels != config.channels:
            raise AudioFormatError(
                f"unsupported channel count: expected {config.channels}, got {channels}"
            )
        if sample_width_bytes != config.sample_width_bytes:
            raise AudioFormatError(
                f"unsupported sample width: expected {config.sample_width_bytes} bytes, got {sample_width_bytes} bytes"
            )
        pcm = wav_file.readframes(wav_file.getnframes())

    bytes_per_frame = config.sample_width_bytes * config.channels
    bytes_per_chunk = config.frame_samples * bytes_per_frame
    chunks: list[AudioChunk] = []
    for start in range(0, len(pcm), bytes_per_chunk):
        chunk_pcm = pcm[start : start + bytes_per_chunk]
        if len(chunk_pcm) < bytes_per_chunk:
            chunk_pcm = chunk_pcm + (b"\x00" * (bytes_per_chunk - len(chunk_pcm)))
        chunks.append(
            AudioChunk(
                pcm=chunk_pcm,
                sample_rate_hz=config.sample_rate_hz,
                sample_width_bytes=config.sample_width_bytes,
                channels=config.channels,
            )
        )
    if not chunks:
        chunks.append(
            AudioChunk(
                pcm=b"\x00" * bytes_per_chunk,
                sample_rate_hz=config.sample_rate_hz,
                sample_width_bytes=config.sample_width_bytes,
                channels=config.channels,
            )
        )
    return chunks


def _hz_to_mel(hz: float) -> float:
    return 2595.0 * math.log10(1.0 + hz / 700.0)


def _mel_to_hz(mel: float) -> float:
    return 700.0 * (10 ** (mel / 2595.0) - 1.0)


@lru_cache(maxsize=32)
def _mel_center_frequencies(
    sample_rate_hz: int, n_mels: int, f_min_hz: float, f_max_hz: float
) -> tuple[float, ...]:
    mel_min = _hz_to_mel(f_min_hz)
    mel_max = _hz_to_mel(f_max_hz)
    if n_mels <= 1:
        return (_mel_to_hz((mel_min + mel_max) / 2.0),)
    step = (mel_max - mel_min) / (n_mels - 1)
    return tuple(_mel_to_hz(mel_min + index * step) for index in range(n_mels))


@lru_cache(maxsize=32)
def _hamming_window(win_length: int) -> tuple[float, ...]:
    if win_length <= 1:
        return (1.0,) * max(1, win_length)
    return tuple(
        0.54 - 0.46 * math.cos((2.0 * math.pi * index) / (win_length - 1))
        for index in range(win_length)
    )


def _goertzel_power(
    frame: tuple[float, ...], sample_rate_hz: int, target_frequency_hz: float
) -> float:
    if not frame:
        return 0.0
    omega = (2.0 * math.pi * target_frequency_hz) / sample_rate_hz
    coeff = 2.0 * math.cos(omega)
    s_prev = 0.0
    s_prev2 = 0.0
    for sample in frame:
        value = sample + coeff * s_prev - s_prev2
        s_prev2 = s_prev
        s_prev = value
    power = s_prev2 * s_prev2 + s_prev * s_prev - coeff * s_prev * s_prev2
    return max(power, 0.0)


def compute_log_mel_features(
    samples: tuple[float, ...],
    sample_rate_hz: int,
    frontend_config: LogMelFrontendConfig,
) -> FrontendFeatures:
    """Computes deterministic log-mel-style frames for task-3 diagnostics.

    This is intentionally a frontend/replay-oriented implementation. It does not
    claim numerical parity with any external training or inference pipeline.
    """

    expected_window_samples = frontend_config.window_samples(sample_rate_hz)
    if len(samples) != expected_window_samples:
        raise AudioFormatError(
            f"expected {expected_window_samples} window samples, got {len(samples)}"
        )

    window = _hamming_window(frontend_config.win_length)
    centers = _mel_center_frequencies(
        sample_rate_hz,
        frontend_config.n_mels,
        frontend_config.f_min_hz,
        frontend_config.f_max_hz,
    )
    frame_total = 1 + (
        (len(samples) - frontend_config.win_length) // frontend_config.hop_length
    )
    frames: list[tuple[float, ...]] = []
    for frame_index in range(frame_total):
        start = frame_index * frontend_config.hop_length
        raw_frame = samples[start : start + frontend_config.win_length]
        weighted_frame = tuple(
            value * weight for value, weight in zip(raw_frame, window, strict=True)
        )
        mel_bins = []
        for frequency in centers:
            power = _goertzel_power(weighted_frame, sample_rate_hz, frequency)
            mel_bins.append(math.log(max(power, frontend_config.log_floor)))
        frames.append(tuple(mel_bins))
    frozen_frames = tuple(frames)
    return FrontendFeatures(
        frames=frozen_frames,
        feature_hash=_hash_frames(frozen_frames),
        chunk_index=0,
        padded_left_samples=0,
        chunk_rms=0.0,
        chunk_peak_abs=0.0,
    )


def frontend_features_from_window(
    window: WindowedSamples,
    sample_rate_hz: int,
    frontend_config: LogMelFrontendConfig,
) -> FrontendFeatures:
    """Binds rolling-window metadata to deterministic frontend features."""

    base = compute_log_mel_features(window.samples, sample_rate_hz, frontend_config)
    return FrontendFeatures(
        frames=base.frames,
        feature_hash=base.feature_hash,
        chunk_index=window.chunk_index,
        padded_left_samples=window.padded_left_samples,
        chunk_rms=window.chunk_rms,
        chunk_peak_abs=window.chunk_peak_abs,
    )
