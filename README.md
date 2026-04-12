# HomeWakeWord

HomeWakeWord is a **wake word detection** engine for **Home Assistant**, packaged as a **Home Assistant add-on** and exposed through **Wyoming**.

The project is built on top of ideas and patterns from:

- [BC-ResNet](https://github.com/rolyantrauts/bcresnet)
- [openWakeWord](https://github.com/dscripka/openWakeWord)
- Home Assistant integration experience around `ha-openwakeword-installer`

## What it provides

- local wake word detection
- Home Assistant integration through Wyoming
- support for built-in wake words
- import of custom models

## Supported wake words

Currently available:

- `okay_nabu`
- `hey_jarvis`
- `alexa`
- `hey_mycroft`
- `hey_rhasspy`

## Installation

### Home Assistant add-on

1. Add this repository as a custom add-on repository in Home Assistant.
2. Install the **HomeWakeWord** add-on.
3. Start the add-on.
4. In Home Assistant, add the Wyoming integration and point it to the HomeWakeWord host and port.
5. Select the wake word you want to use in your Assist voice pipeline.

Default Wyoming endpoint:

- host: the machine running the add-on
- port: `10700`

### Custom models

To use custom wake words, place validated model bundles in:

- `/share/homewakeword/models`

Optional compatibility scanning can also use:

- `/share/openwakeword`

The add-on will only load models that include a valid manifest and validation metadata.

## How to use it with Home Assistant

1. Build or install the `homewakeword` add-on.
2. Start the add-on.
3. In Home Assistant, add the Wyoming service that points to HomeWakeWord.
4. Select the wake word in your voice pipeline.

Default add-on configuration:

- host: `0.0.0.0`
- port: `10700`
- model manifest: `/app/models/manifest.yaml`
- custom model directory: `/share/homewakeword/models`

After startup, the add-on exposes a Wyoming service that Home Assistant can use for wake word detection.

## How to run it

### Run in Home Assistant

1. Add this repository as a custom add-on repository in Home Assistant.
2. Install the `homewakeword` add-on.
3. Start the add-on.
4. Add the **Wyoming** integration in Home Assistant.
5. Point Wyoming to the HomeWakeWord host and port `10700`.
6. Select one of the available wake words in your Assist pipeline.

### Run locally

Install the package:

```bash
python -m pip install -e .
```

Start the runtime:

```bash
python -m homewakeword.cli serve
```

Run a self-test instead:

```bash
python -m homewakeword.cli serve --self-test --report /tmp/self-test.json
```

### Run the add-on image locally

```bash
docker build -f addon/homewakeword-bcresnet/Dockerfile -t local/homewakeword .
docker run --rm local/homewakeword --self-test --report /tmp/self-test.json
```

### Run with Docker Compose

Example `docker-compose.yml`:

```yaml
services:
  homewakeword:
    image: local/homewakeword
    container_name: homewakeword
    ports:
      - "10700:10700"
    volumes:
      - ./data:/data
      - ./share:/share
    command: ["serve"]
```

Start it with:

```bash
docker compose up -d
```

Then connect Home Assistant Wyoming to:

- host: the machine running Docker
- port: `10700`

## Custom wake words

HomeWakeWord supports custom model import.

Primary import path:

- `/share/homewakeword/models`

Optional compatibility path:

- `/share/openwakeword`

Important: importing a model requires a **full bundle**, not just a model file. A standalone `.tflite` file is not enough. The runtime expects the model, manifest, and validation metadata.

## Technology

- audio frontend: 16 kHz, mono, PCM16
- detection model: **BC-ResNet**
- integration layer: **Wyoming**
- packaging: **Home Assistant add-on**

## Limitations

- this is not a binary drop-in replacement for openWakeWord
- only properly validated models are advertised by the runtime
- some behavior depends on the local Docker / Home Assistant Supervisor environment

## Additional documentation

- developer setup: [docs/development.md](docs/development.md)
- release workflow: [docs/release.md](docs/release.md)

For maintainers, the repository also includes the scripted review workflow based on:

- `python -m scripts.generate_review`
- `python -m scripts.commit_with_review`

## License

This project is released under the **MIT** license.

See [LICENSE](LICENSE).
