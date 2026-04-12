from __future__ import annotations

from pathlib import Path
import math

from homewakeword.audio import AudioChunk, floats_to_pcm16le, iter_wave_chunks
from homewakeword.config import AudioInputConfig, DetectorConfig
from homewakeword.detector.bcresnet import BCResNetStreamingFrontend


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / 'fixtures' / 'stream'


def _tone_chunk(amplitude: float, config: AudioInputConfig) -> AudioChunk:
    pcm = floats_to_pcm16le([amplitude] * config.frame_samples)
    return AudioChunk(
        pcm=pcm,
        sample_rate_hz=config.sample_rate_hz,
        sample_width_bytes=config.sample_width_bytes,
        channels=config.channels,
    )


def test_streaming_frontend_left_pads_until_one_second_context() -> None:
    audio_config = AudioInputConfig()
    frontend = BCResNetStreamingFrontend(audio_config=audio_config, detector_config=DetectorConfig())

    first = frontend.process_chunk(_tone_chunk(0.25, audio_config))
    second = frontend.process_chunk(_tone_chunk(0.25, audio_config))

    assert first.padded_left_samples == audio_config.window_samples - audio_config.frame_samples
    assert second.padded_left_samples == audio_config.window_samples - (audio_config.frame_samples * 2)
    assert first.frame_count == second.frame_count
    assert first.mel_bin_count == second.mel_bin_count == 40


def test_streaming_frontend_stops_padding_after_full_window() -> None:
    audio_config = AudioInputConfig()
    frontend = BCResNetStreamingFrontend(audio_config=audio_config, detector_config=DetectorConfig())

    final = None
    for _ in range(math.ceil(audio_config.window_samples / audio_config.frame_samples)):
        final = frontend.process_chunk(_tone_chunk(0.1, audio_config))

    assert final is not None
    assert final.padded_left_samples == 0


def test_replay_fixture_produces_deterministic_hash_sequence() -> None:
    audio_config = AudioInputConfig()
    detector_config = DetectorConfig()
    chunks = iter_wave_chunks(FIXTURE_ROOT / 'no_wake_negative.wav', audio_config)

    first_frontend = BCResNetStreamingFrontend(audio_config=audio_config, detector_config=detector_config)
    second_frontend = BCResNetStreamingFrontend(audio_config=audio_config, detector_config=detector_config)

    first_hashes = [first_frontend.process_chunk(chunk).feature_hash for chunk in chunks]
    second_hashes = [second_frontend.process_chunk(chunk).feature_hash for chunk in chunks]

    assert first_hashes == second_hashes
    assert len(first_hashes) > 0
