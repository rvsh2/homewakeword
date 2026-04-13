# HomeWakeWord

HomeWakeWord is a **wake word detection engine** for **Home Assistant**.
It runs as a **Home Assistant add-on** and exposes wake word detection through the **Wyoming protocol**.

The project is built on top of:

- [BC-ResNet](https://github.com/rolyantrauts/bcresnet)
- [openWakeWord](https://github.com/dscripka/openWakeWord)
- Home Assistant voice / Wyoming integration patterns

## Features

- local wake word detection
- Wyoming integration for Home Assistant
- built-in wake words
- custom model import
- optional real openWakeWord-backed inference backend

## Supported wake words

- `okay_nabu`
- `hey_jarvis`
- `alexa`
- `hey_mycroft`
- `hey_rhasspy`

## Install in Home Assistant

### Add-on runtime

1. Add this repository as a custom add-on repository in Home Assistant.
2. Install the **HomeWakeWord** add-on.
3. Start the add-on.
4. Add the built-in **Wyoming** integration in Home Assistant.
5. Use:
   - host: `homewakeword`
   - port: `10700`
6. Select the wake word in your Assist configuration.

### Install via HACS

This repository is also HACS-installable as a custom **Integration**.

1. Open **HACS**.
2. Add this repository as a custom repository.
3. Select repository type **Integration**.
4. Install **HomeWakeWord**.
5. Restart Home Assistant.
6. Add the **HomeWakeWord** integration.

Important:

- HACS installs only the lightweight **HomeWakeWord** helper integration under `custom_components/`
- HACS does **not** install, start, or manage the HomeWakeWord add-on runtime
- the actual runtime still runs through the **HomeWakeWord add-on** and the built-in **Wyoming** integration
- use the built-in **Wyoming** integration with host `homewakeword` and port `10700`
- the built-in **Wyoming** integration should use host `homewakeword` and port `10700`

## Default add-on settings

- host: `0.0.0.0`
- port: `10700`
- model manifest: `/app/models/manifest.yaml`
- custom model directory: `/share/homewakeword/models`
- **VAD: enabled by default**
- **Speex noise suppression: enabled by default**

## Custom wake words

Primary model import path:

- `/share/homewakeword/models`

Optional compatibility path:

- `/share/openwakeword`

Supported import styles:

- full model bundle
- standalone `.tflite` file

If only a `.tflite` file is present, HomeWakeWord generates a sidecar manifest automatically.

## Run locally

Install:

```bash
python -m pip install -e .
```

Run the service:

```bash
python -m homewakeword.cli serve --host 0.0.0.0 --port 10700
```

Run a self-test:

```bash
python -m homewakeword.cli serve --self-test --report /tmp/self-test.json
```

## Run with Docker

Build the image:

```bash
docker build -f addon/homewakeword/Dockerfile -t local/homewakeword .
```

Run it:

```bash
docker run --rm -p 10700:10700 local/homewakeword serve --host 0.0.0.0 --port 10700
```

## Run with Docker Compose

This repository includes:

- `docker-compose.yml`

Start it with:

```bash
docker compose up -d
```

## Troubleshooting

### `Failed to connect` in Wyoming

Check that:

- the add-on is running
- Wyoming is listening on `0.0.0.0:10700`
- Home Assistant can resolve host `homewakeword`
- Home Assistant and HomeWakeWord are on the same Docker network if you use the container name as host

### HACS helper shows failed connectivity

Check that:

- the add-on is started
- host is `homewakeword`
- port is `10700`
- the Wyoming integration can reach the container from Home Assistant

### Custom model is not shown

Check that the model or bundle is placed in:

- `/share/homewakeword/models`

or optionally:

- `/share/openwakeword`

## Technology

- audio frontend: 16 kHz, mono, PCM16
- detection model: **BC-ResNet**
- optional real backend: **openWakeWord-based inference**
- VAD: **Silero VAD**
- noise suppression: **SpeexDSP**
- protocol layer: **Wyoming**
- packaging: **Home Assistant add-on**

## Additional documentation

- developer setup: [docs/development.md](docs/development.md)
- release workflow: [docs/release.md](docs/release.md)

Maintainer tooling includes:

- `python -m scripts.generate_review`
- `python -m scripts.commit_with_review`

## License

This project is released under the **MIT** license.

See [LICENSE](LICENSE).
