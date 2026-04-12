# HomeWakeWord

HomeWakeWord is a **wake word detection engine** for **Home Assistant**.
It runs as a **Home Assistant add-on** and exposes wake word detection through the **Wyoming protocol**.

It is built around:

- [BC-ResNet](https://github.com/rolyantrauts/bcresnet)
- [openWakeWord](https://github.com/dscripka/openWakeWord)
- Home Assistant voice / Wyoming integration patterns

## Features

- local wake word detection
- Wyoming integration for Home Assistant
- built-in wake words
- custom model import

## Supported wake words

- `okay_nabu`
- `hey_jarvis`
- `alexa`
- `hey_mycroft`
- `hey_rhasspy`

## Home Assistant installation

1. Add this repository as a custom add-on repository in Home Assistant.
2. Install the **HomeWakeWord** add-on.
3. Start the add-on.
4. Add the **Wyoming** integration in Home Assistant.
5. Use:
   - host: `homewakeword` if Home Assistant is on the same Docker network
   - port: `10700`
6. Select the wake word in your Assist configuration.

## Default add-on settings

- host: `0.0.0.0`
- port: `10700`
- model manifest: `/app/models/manifest.yaml`
- custom model directory: `/share/homewakeword/models`

## Custom wake words

Custom model bundles should be placed in:

- `/share/homewakeword/models`

Optional compatibility path:

- `/share/openwakeword`

Important:

- a standalone `.tflite` file is **not enough**
- the runtime expects a full bundle with model, manifest, and validation metadata

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

## Run locally with Docker

Build the image:

```bash
docker build -f addon/homewakeword/Dockerfile -t local/homewakeword .
```

Run it:

```bash
docker run --rm -p 10700:10700 local/homewakeword serve --host 0.0.0.0 --port 10700
```

## Run with Docker Compose

This repository includes a ready-to-use file:

- `docker-compose.yml`

Start it with:

```bash
docker compose up -d
```

## Technology

- audio frontend: 16 kHz, mono, PCM16
- detection model: **BC-ResNet**
- protocol layer: **Wyoming**
- packaging: **Home Assistant add-on**

## Limitations

- this is not a binary drop-in replacement for openWakeWord
- only validated models are advertised by the runtime
- some behavior depends on the local Docker / Home Assistant Supervisor environment

## License

This project is released under the **MIT** license.

See [LICENSE](LICENSE).
