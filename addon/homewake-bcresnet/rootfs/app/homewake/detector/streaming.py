"""Detector-local streaming state and counters for BC-ResNet runtime behavior."""

from __future__ import annotations

from dataclasses import dataclass, field

from homewake.detector.base import DetectorRuntimeState

DEFAULT_CONSECUTIVE_HITS = 3


@dataclass(frozen=True, slots=True)
class DetectorLoopCounters:
    """Structured detector-local counters for runtime reliability behavior."""

    detections: int = 0
    cooldown_suppressions: int = 0
    refractory_suppressions: int = 0
    duplicate_suppressions: int = 0
    invalid_frames: int = 0
    model_load_failures: int = 0
    runtime_failures: int = 0


@dataclass(slots=True)
class StreamingDetectionStateMachine:
    """Applies threshold gating, cooldown, refractory, and duplicate suppression."""

    cooldown_seconds: float
    refractory_hold_seconds: float
    reset_threshold: float
    required_consecutive_hits: int = DEFAULT_CONSECUTIVE_HITS
    _clock_seconds: float = field(default=0.0, init=False)
    _cooldown_until_seconds: float = field(default=0.0, init=False)
    _refractory_until_seconds: float = field(default=0.0, init=False)
    _consecutive_hits: int = field(default=0, init=False)
    _detections: int = field(default=0, init=False)
    _cooldown_suppressions: int = field(default=0, init=False)
    _refractory_suppressions: int = field(default=0, init=False)
    _duplicate_suppressions: int = field(default=0, init=False)
    _invalid_frames: int = field(default=0, init=False)
    _model_load_failures: int = field(default=0, init=False)
    _runtime_failures: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._clock_seconds = 0.0
        self._cooldown_until_seconds = 0.0
        self._refractory_until_seconds = 0.0
        self._consecutive_hits = 0
        self._detections = 0
        self._cooldown_suppressions = 0
        self._refractory_suppressions = 0
        self._duplicate_suppressions = 0
        self._invalid_frames = 0
        self._model_load_failures = 0
        self._runtime_failures = 0

    @property
    def counters(self) -> DetectorLoopCounters:
        return DetectorLoopCounters(
            detections=self._detections,
            cooldown_suppressions=self._cooldown_suppressions,
            refractory_suppressions=self._refractory_suppressions,
            duplicate_suppressions=self._duplicate_suppressions,
            invalid_frames=self._invalid_frames,
            model_load_failures=self._model_load_failures,
            runtime_failures=self._runtime_failures,
        )

    def record_invalid_frame(self) -> None:
        self._invalid_frames += 1

    def record_model_load_failure(self) -> None:
        self._model_load_failures += 1

    def record_runtime_failure(self) -> None:
        self._runtime_failures += 1

    def _update_refractory(self, *, now_seconds: float, score: float) -> None:
        if self._refractory_until_seconds <= 0.0:
            return
        if score > self.reset_threshold:
            self._refractory_until_seconds = max(
                self._refractory_until_seconds,
                now_seconds + self.refractory_hold_seconds,
            )
        elif now_seconds >= self._refractory_until_seconds:
            self._refractory_until_seconds = 0.0

    def evaluate(self, *, score: float, threshold: float, frame_duration_seconds: float) -> tuple[bool, DetectorRuntimeState]:
        self._clock_seconds += frame_duration_seconds
        now_seconds = self._clock_seconds
        self._update_refractory(now_seconds=now_seconds, score=score)

        if score >= threshold:
            self._consecutive_hits += 1
        else:
            self._consecutive_hits = 0

        cooldown_remaining = max(0.0, self._cooldown_until_seconds - now_seconds)
        refractory_remaining = max(0.0, self._refractory_until_seconds - now_seconds)
        cooldown_active = cooldown_remaining > 0.0
        refractory_active = refractory_remaining > 0.0

        if score >= threshold and (cooldown_active or refractory_active):
            self._duplicate_suppressions += 1
            if cooldown_active:
                self._cooldown_suppressions += 1
            else:
                self._refractory_suppressions += 1

        detected = self._consecutive_hits >= self.required_consecutive_hits and not cooldown_active and not refractory_active
        if detected:
            self._detections += 1
            self._consecutive_hits = 0
            self._cooldown_until_seconds = now_seconds + self.cooldown_seconds
            self._refractory_until_seconds = now_seconds + self.refractory_hold_seconds
            cooldown_remaining = max(0.0, self._cooldown_until_seconds - now_seconds)
            refractory_remaining = max(0.0, self._refractory_until_seconds - now_seconds)

        return detected, DetectorRuntimeState(
            cooldown_remaining_seconds=round(cooldown_remaining, 6),
            refractory_remaining_seconds=round(refractory_remaining, 6),
            armed=cooldown_remaining <= 0.0 and refractory_remaining <= 0.0,
        )
