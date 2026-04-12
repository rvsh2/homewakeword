# pyright: reportMissingImports=false
"""Wyoming protocol-facing runtime shell.

This module deliberately depends on detector interfaces rather than any concrete
BC-ResNet implementation details so protocol code stays swappable.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Self

from homewakeword.audio import AudioChunk
from homewakeword.config import HomeWakeWordConfig, WyomingServerConfig
from homewakeword.detector.base import WakeWordDetector
from homewakeword.events import DetectionEvent, DetectionEventType
from homewakeword.health import RuntimeHealth, build_runtime_health
from homewakeword.registry import ModelInventoryRecord
from wyoming.audio import AudioChunk as WyomingAudioChunk
from wyoming.audio import AudioChunkConverter, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Attribution, Describe, Info, WakeModel, WakeProgram
from wyoming.server import AsyncEventHandler, AsyncServer
from wyoming.wake import Detect, Detection, NotDetected


@dataclass(slots=True)
class WyomingRuntime:
    """Binds protocol configuration to a detector contract."""

    config: HomeWakeWordConfig
    detector: WakeWordDetector

    def handle_audio_chunk(self, chunk: AudioChunk) -> DetectionEvent:
        """Translate one detector decision into a structured runtime event."""

        decision = self.detector.process(chunk)
        if decision.detected:
            event_type = DetectionEventType.DETECTION
        elif decision.vad_suppressed:
            event_type = DetectionEventType.SUPPRESSED_VAD
        elif decision.state.cooldown_remaining_seconds > 0:
            event_type = DetectionEventType.SUPPRESSED_COOLDOWN
        elif decision.state.refractory_remaining_seconds > 0:
            event_type = DetectionEventType.SUPPRESSED_REFRACTORY
        else:
            event_type = DetectionEventType.SCORED

        return DetectionEvent(
            type=event_type,
            detector_backend=self.detector.backend_name,
            occurred_at=datetime.now(tz=timezone.utc),
            decision=decision,
        )


@dataclass(frozen=True, slots=True)
class WyomingWakeWord:
    """Protocol-facing wake word metadata reported by the service boundary."""

    name: str


@dataclass(frozen=True, slots=True)
class WyomingServiceDescription:
    """Static service metadata for Wyoming-style discovery/describe flows."""

    uri: str
    wake_words: tuple[WyomingWakeWord, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "uri": self.uri,
            "wake_words": [wake_word.name for wake_word in self.wake_words],
        }


@dataclass(frozen=True, slots=True)
class WyomingDetectionEvent:
    """Protocol-level wake detection payload emitted by the Wyoming layer."""

    type: str
    wake_word: str
    service_uri: str
    occurred_at: datetime

    def as_dict(self) -> dict[str, str]:
        return {
            "type": self.type,
            "wake_word": self.wake_word,
            "service_uri": self.service_uri,
            "occurred_at": self.occurred_at.isoformat(),
        }


@dataclass(slots=True)
class _WyomingDetectionSession:
    """Per-connection Wyoming wake-detection stream state."""

    requested_names: frozenset[str] | None = None
    audio_converter: AudioChunkConverter | None = None
    pending_audio: bytearray = field(default_factory=bytearray)
    next_timestamp_ms: int = 0
    emitted_detection: bool = False


class _HomeWakeWordEventHandler(AsyncEventHandler):
    """Official Wyoming async event handler bridged to the runtime shell."""

    def __init__(
        self,
        server: WyomingServer,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        super().__init__(reader, writer)
        self._server = server
        self._session = _WyomingDetectionSession()

    async def handle_event(self, event: Event) -> bool:
        event_type = event.type
        if Describe.is_type(event_type):
            await self.write_event(self._server.info().event())
            return True

        if Detect.is_type(event_type):
            detect = Detect.from_event(event)
            self._session.requested_names = (
                None if not detect.names else frozenset(detect.names)
            )
            return True

        if AudioStart.is_type(event_type):
            start = AudioStart.from_event(event)
            self._server.reset_detector()
            self._session.audio_converter = self._server.audio_chunk_converter()
            self._session.pending_audio.clear()
            self._session.next_timestamp_ms = (
                0 if start.timestamp is None else start.timestamp
            )
            self._session.emitted_detection = False
            return True

        if WyomingAudioChunk.is_type(event_type):
            chunk = WyomingAudioChunk.from_event(event)
            if self._session.audio_converter is None:
                self._session.audio_converter = self._server.audio_chunk_converter()
                if chunk.timestamp is not None:
                    self._session.next_timestamp_ms = chunk.timestamp
            converter = self._session.audio_converter
            assert converter is not None
            converted = converter.convert(chunk)
            await self._process_audio_bytes(converted.audio)
            return True

        if AudioStop.is_type(event_type):
            await self._flush_pending_audio()
            if not self._session.emitted_detection:
                await self.write_event(NotDetected().event())
            self._session.pending_audio.clear()
            return True

        return True

    async def _process_audio_bytes(self, audio_bytes: bytes) -> None:
        self._session.pending_audio.extend(audio_bytes)
        while len(self._session.pending_audio) >= self._server.bytes_per_chunk:
            chunk_pcm = bytes(
                self._session.pending_audio[: self._server.bytes_per_chunk]
            )
            del self._session.pending_audio[: self._server.bytes_per_chunk]
            detection = self._server.handle_audio_chunk(
                AudioChunk(
                    pcm=chunk_pcm,
                    sample_rate_hz=self._server.runtime.config.audio.sample_rate_hz,
                    sample_width_bytes=self._server.runtime.config.audio.sample_width_bytes,
                    channels=self._server.runtime.config.audio.channels,
                )
            )
            timestamp_ms = self._session.next_timestamp_ms
            self._session.next_timestamp_ms += self._server.chunk_duration_ms
            if detection is None:
                continue
            if (
                self._session.requested_names is not None
                and detection.wake_word not in self._session.requested_names
            ):
                continue
            self._session.emitted_detection = True
            await self.write_event(
                Detection(name=detection.wake_word, timestamp=timestamp_ms).event()
            )

    async def _flush_pending_audio(self) -> None:
        if not self._session.pending_audio:
            return
        missing_bytes = self._server.bytes_per_chunk - len(self._session.pending_audio)
        if missing_bytes > 0:
            self._session.pending_audio.extend(b"\x00" * missing_bytes)
        await self._process_audio_bytes(b"")


def _wake_phrase(name: str) -> str:
    return " ".join(part.capitalize() for part in name.replace("_", " ").split())


@dataclass(slots=True)
class WyomingServer:
    """Thin protocol-facing shell for Wyoming-style startup and event emission."""

    config: WyomingServerConfig
    runtime: WyomingRuntime
    loaded_wake_words: tuple[str, ...] = ()
    inventory: tuple[ModelInventoryRecord, ...] = ()
    config_echo: dict[str, object] = field(default_factory=dict)
    _running: bool = False
    _bound_port: int | None = None
    _async_server: AsyncServer | None = field(default=None, init=False, repr=False)
    _loop: asyncio.AbstractEventLoop | None = field(
        default=None, init=False, repr=False
    )
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _detector_lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    @classmethod
    def from_runtime(
        cls,
        runtime: WyomingRuntime,
        *,
        loaded_wake_words: tuple[str, ...] = (),
        inventory: tuple[ModelInventoryRecord, ...] = (),
        config_echo: dict[str, object] | None = None,
    ) -> Self:
        return cls(
            config=runtime.config.server,
            runtime=runtime,
            loaded_wake_words=loaded_wake_words,
            inventory=inventory,
            config_echo={} if config_echo is None else config_echo,
        )

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def uri(self) -> str:
        port = self.config.port if self._bound_port is None else self._bound_port
        return f"tcp://{self.config.host}:{port}"

    @property
    def bytes_per_chunk(self) -> int:
        audio_config = self.runtime.config.audio
        return (
            audio_config.frame_samples
            * audio_config.sample_width_bytes
            * audio_config.channels
        )

    @property
    def chunk_duration_ms(self) -> int:
        return int(round(self.runtime.config.audio.frame_duration_seconds * 1000.0))

    def audio_chunk_converter(self) -> AudioChunkConverter:
        audio_config = self.runtime.config.audio
        return AudioChunkConverter(
            rate=audio_config.sample_rate_hz,
            width=audio_config.sample_width_bytes,
            channels=audio_config.channels,
        )

    def start(self, *, bind_listener: bool = True) -> None:
        if self._running:
            return

        self.runtime.detector.open()
        if not bind_listener:
            self._running = True
            return

        started = threading.Event()
        startup_error: list[BaseException] = []

        def _run_server_loop() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)

            async def _start_async_server() -> None:
                try:
                    async_server = AsyncServer.from_uri(
                        f"tcp://{self.config.host}:{self.config.port}"
                    )
                    self._async_server = async_server
                    await async_server.start(self._create_handler)
                    self._bound_port = self._resolve_bound_port(async_server)
                except BaseException as exc:  # pragma: no cover - propagated to caller
                    startup_error.append(exc)
                    loop.call_soon(loop.stop)
                finally:
                    started.set()

            loop.create_task(_start_async_server())
            try:
                loop.run_forever()
            finally:
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    with suppress(Exception):
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                loop.close()

        self._thread = threading.Thread(
            target=_run_server_loop,
            name="homewakeword-wyoming-server",
            daemon=True,
        )
        self._thread.start()
        if not started.wait(timeout=5.0):
            try:
                self.runtime.detector.close()
            finally:
                self._running = False
                self._cleanup_server_state()
            raise RuntimeError("failed to start Wyoming TCP server before timeout")
        if startup_error:
            try:
                self.runtime.detector.close()
            finally:
                self._running = False
                self._cleanup_server_state()
            raise RuntimeError(
                f"failed to start Wyoming TCP server: {startup_error[0]}"
            ) from startup_error[0]

        self._running = True

    def stop(self) -> None:
        try:
            if self._loop is not None and self._async_server is not None:
                future = asyncio.run_coroutine_threadsafe(
                    self._shutdown_async_server(), self._loop
                )
                with suppress(FutureTimeoutError):
                    future.result(timeout=5.0)
                self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=5.0)
            self.runtime.detector.close()
        finally:
            self._running = False
            self._cleanup_server_state()

    def describe(self) -> WyomingServiceDescription:
        return WyomingServiceDescription(
            uri=self.uri,
            wake_words=tuple(
                WyomingWakeWord(name=wake_word) for wake_word in self.loaded_wake_words
            ),
        )

    def info(self) -> Info:
        return Info(
            wake=[
                WakeProgram(
                    name="homewakeword",
                    description="HomeWakeWord wake word detection service.",
                    attribution=Attribution(name="homewakeword", url=""),
                    installed=True,
                    version=None,
                    models=[
                        WakeModel(
                            name=wake_word,
                            description=_wake_phrase(wake_word),
                            phrase=_wake_phrase(wake_word),
                            attribution=Attribution(name="homewakeword", url=""),
                            installed=True,
                            languages=[],
                            version=None,
                        )
                        for wake_word in self.loaded_wake_words
                    ],
                )
            ]
        )

    def handle_audio_chunk(self, chunk: AudioChunk) -> WyomingDetectionEvent | None:
        with self._detector_lock:
            event = self.runtime.handle_audio_chunk(chunk)
        if event.type is not DetectionEventType.DETECTION:
            return None
        return WyomingDetectionEvent(
            type=event.type.value,
            wake_word=event.label,
            service_uri=self.uri,
            occurred_at=event.occurred_at,
        )

    def health(self) -> RuntimeHealth:
        return build_runtime_health(
            running=self._running,
            loaded_wake_words=self.loaded_wake_words,
            inventory=self.inventory,
            config=self.config_echo,
        )

    def reset_detector(self) -> None:
        with self._detector_lock:
            self.runtime.detector.reset()

    def _create_handler(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> _HomeWakeWordEventHandler:
        return _HomeWakeWordEventHandler(self, reader, writer)

    def _resolve_bound_port(self, async_server: AsyncServer) -> int | None:
        transport = getattr(async_server, "_server", None)
        sockets = None if transport is None else getattr(transport, "sockets", None)
        if not sockets:
            return None
        socket_name = sockets[0].getsockname()
        if isinstance(socket_name, tuple) and len(socket_name) >= 2:
            return int(socket_name[1])
        return None

    async def _shutdown_async_server(self) -> None:
        if self._async_server is None:
            return
        await self._async_server.stop()
        transport = getattr(self._async_server, "_server", None)
        if transport is not None:
            await transport.wait_closed()

    def _cleanup_server_state(self) -> None:
        self._async_server = None
        self._bound_port = None
        self._loop = None
        self._thread = None
