"""Silero-style VAD backend modeled after openWakeWord behavior."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np

if TYPE_CHECKING:
    import onnxruntime as ort

from homewakeword.config import VADConfig

DEFAULT_VAD_MODEL = (
    Path(__file__).resolve().parent / "resources" / "models" / "silero_vad.onnx"
)


class VADRuntimeError(RuntimeError):
    """Raised when the VAD backend cannot be initialized or used."""


@dataclass(slots=True)
class SileroVAD:
    """Silero VAD backend closely matching openWakeWord's usage pattern."""

    config: VADConfig
    prediction_buffer: deque[float] = field(default_factory=lambda: deque(maxlen=125))
    _session: "ort.InferenceSession | None" = field(default=None, init=False)
    _h: np.ndarray = field(init=False)
    _c: np.ndarray = field(init=False)
    _sample_rate: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self._sample_rate = np.array(16000).astype(np.int64)
        self.reset_states()

    @property
    def model_path(self) -> Path:
        return (self.config.model_path or DEFAULT_VAD_MODEL).resolve()

    def open(self) -> None:
        if self._session is not None:
            return
        if not self.model_path.exists():
            raise VADRuntimeError(f"VAD model does not exist: {self.model_path}")
        try:
            import onnxruntime as ort  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise VADRuntimeError("VAD requires onnxruntime to be installed") from exc
        options = ort.SessionOptions()
        options.inter_op_num_threads = self.config.n_threads
        options.intra_op_num_threads = self.config.n_threads
        self._session = ort.InferenceSession(
            str(self.model_path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.reset_states()

    def close(self) -> None:
        self._session = None
        self.reset_states()
        self.prediction_buffer.clear()

    def reset_states(self, batch_size: int = 1) -> None:
        self._h = np.zeros((2, batch_size, 64), dtype=np.float32)
        self._c = np.zeros((2, batch_size, 64), dtype=np.float32)

    def predict(self, samples: np.ndarray, frame_size: int = 480) -> float:
        if self._session is None:
            raise VADRuntimeError("VAD runtime is not open")
        if samples.ndim != 1:
            raise VADRuntimeError("VAD expects a one-dimensional int16 PCM array")
        if samples.dtype != np.int16:
            samples = samples.astype(np.int16)

        chunks = [
            (samples[i : i + frame_size] / 32767.0).astype(np.float32)
            for i in range(0, samples.shape[0], frame_size)
        ]
        frame_predictions: list[float] = []
        for chunk in chunks:
            ort_inputs = {
                "input": chunk[None, :],
                "h": self._h,
                "c": self._c,
                "sr": self._sample_rate,
            }
            outputs = self._session.run(None, ort_inputs)
            score, self._h, self._c = cast(
                tuple[np.ndarray, np.ndarray, np.ndarray], tuple(outputs)
            )
            frame_predictions.append(float(score[0][0]))
        if not frame_predictions:
            return 0.0
        return float(np.mean(frame_predictions))

    def __call__(self, samples: np.ndarray, frame_size: int = 160 * 4) -> float:
        score = self.predict(samples, frame_size)
        self.prediction_buffer.append(score)
        return score

    def recent_max_score(self) -> float:
        vad_frames = list(self.prediction_buffer)[-7:-4]
        if not vad_frames:
            return 0.0
        return float(max(vad_frames))
