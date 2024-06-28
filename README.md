# Demospace AI Voice Agent

This project is the implementation for Demospace's AI agent, which interacts with a user via voice and sends visual assets in real time. It uses LiveKit for real-time streaming over WebRTC and links multiple ML models (Deepgram, Claude/OpenAI, Eleven Labs) to power the voice-to-voice workflow.

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

### Contributing

Contributions are welcome! Please open an issue or submit a pull request for any changes.

### Acknowledgements

- [LiveKit](https://livekit.io/) for providing the real-time streaming infrastructure.
- All contributors and maintainers of the project.
