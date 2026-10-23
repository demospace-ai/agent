# Demospace AI Voice Agent

This project is the implementation for Demospace's AI agent, which interacts with a user via voice and sends visual asset URLs in real time. The active worker uses LiveKit for real-time streaming over WebRTC and links Deepgram, Claude, Eleven Labs, and Silero to power the voice-to-voice workflow.

Note that to use this agent, you'll need to have the Demospace frontend application running as well, connected to your LiveKit server.

## Features

- Real-time voice interaction with AI agent
- Integration with LiveKit for WebRTC streaming
- Utilizes multiple machine learning models for voice processing

## Getting Started

### Prerequisites

- Python 3.11 or higher
- Poetry 1.2 or higher
- LiveKit server setup
- API keys for Deepgram, Anthropic, and Eleven Labs

### Installation

1. Clone the repository:

   ```sh
   git clone https://github.com/yourusername/your-repo-name.git
   cd your-repo-name
   ```

2. Install the required Python packages:
   ```sh
   poetry install
   ```

### Usage

1. Start the LiveKit server and obtain the necessary credentials.
2. Run the main script:
   ```sh
   poetry run python main.py start
   ```

### Project Structure

- `main.py`: Entry point of the application.
- `livekit/`: Contains modules related to LiveKit integration.
- `agents/`: Contains AI agent-related modules and functions.
- `models/`: Contains machine learning models used for voice processing.

## Dependency maintenance and offline checks

The active `main.py` worker does not use the OpenAI LiveKit plugin or Pillow image
processing. The unused `livekit-plugins-openai` dependency was removed because its
image extra pins an affected Pillow release. The existing OpenAI SDK is retained
for the legacy adapter source; that adapter is not part of the active worker or
the supported voice-flow checks. Reintroducing image support requires compatible,
patched dependencies, not the old plugin constraint.

Explicit minimum versions protect the transitive aiohttp, PyJWT, and fsspec
dependencies. Use Poetry 1.8.2 for lockfile updates, preserving unrelated package
versions where possible. After installing the lockfile, run:

```sh
poetry install --no-root --sync
poetry run python -m pip check
ENVIRONMENT=production poetry run python -W error::ResourceWarning -m unittest discover -s tests -v
ENVIRONMENT=production poetry run python main.py --help
```

These checks use dummy credentials, local memory, or loopback HTTP/WebSocket
servers. They do not start a voice session, download a model, or contact live
providers. `ENVIRONMENT=production` prevents the current environment helper from
loading `.env.local`. The Docker image remains Python 3.11.8 with Poetry 1.4.2;
offline checks on another Python version do not replace production-image or
live-provider verification.

### Contributing

Contributions are welcome! Please open an issue or submit a pull request for any changes.

### Acknowledgements

- [LiveKit](https://livekit.io/) for providing the real-time streaming infrastructure.
- All contributors and maintainers of the project.
