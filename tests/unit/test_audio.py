from __future__ import annotations

import math
from pathlib import Path
import wave

import pytest

from homewakeword.audio import (
    AudioChunk,
    AudioFormatError,
    RollingAudioWindow,
    compute_log_mel_features,
    floats_to_pcm16le,
    iter_wave_chunks,
    pcm16le_to_floats,
    validate_audio_chunk,
)
from homewakeword.config import AudioInputConfig, LogMelFrontendConfig


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "stream"


def _write_wav(path: Path, sample_rate_hz: int, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate_hz)
        wav_file.writeframes(floats_to_pcm16le(samples))


def test_validate_audio_chunk_rejects_unsupported_sample_rate() -> None:
    config = AudioInputConfig()
    chunk = AudioChunk(
        pcm=b"\x00\x00" * config.frame_samples,
        sample_rate_hz=44_100,
        sample_width_bytes=2,
    )

    with pytest.raises(AudioFormatError, match="unsupported sample rate"):
        validate_audio_chunk(chunk, config)


def test_iter_wave_chunks_pads_final_chunk_to_alignment(tmp_path: Path) -> None:
    config = AudioInputConfig()
    sample_count = config.frame_samples + 320
    path = tmp_path / "partial.wav"
    _write_wav(path, config.sample_rate_hz, [0.1] * sample_count)

    chunks = iter_wave_chunks(path, config)

    assert len(chunks) == 2
    assert all(chunk.frame_count == config.frame_samples for chunk in chunks)
    tail_samples = pcm16le_to_floats(chunks[-1].pcm)
    assert tail_samples[-1] == 0.0


def test_silence_features_are_finite_and_stable() -> None:
    config = AudioInputConfig()
    frontend = LogMelFrontendConfig()
    silence = tuple(0.0 for _ in range(config.window_samples))

    features = compute_log_mel_features(silence, config.sample_rate_hz, frontend)

    assert features.frame_count > 0
    assert features.mel_bin_count == frontend.n_mels
    assert all(math.isfinite(value) for frame in features.frames for value in frame)
    first_value = features.frames[0][0]
    assert all(value == first_value for frame in features.frames for value in frame)


def test_feature_generation_is_deterministic_for_fixture() -> None:
    config = AudioInputConfig()
    frontend = LogMelFrontendConfig()
    chunks = iter_wave_chunks(FIXTURE_ROOT / "no_wake_negative.wav", config)
    window = RollingAudioWindow(config)
    final_window = None
    for chunk in chunks:
        final_window = window.append(chunk)
    assert final_window is not None

    first = compute_log_mel_features(final_window.samples, config.sample_rate_hz, frontend)
    second = compute_log_mel_features(final_window.samples, config.sample_rate_hz, frontend)

    assert first.feature_hash == second.feature_hash
    assert first.frames == second.frames
