# TeleClaude: Your Distributed Agent Platform

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-GPL--3.0-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-852%20passed-brightgreen.svg)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-85%25-brightgreen.svg)](coverage/html/index.html)
[![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Type Checking](https://img.shields.io/badge/type%20checking-mypy-blue.svg)](http://mypy-lang.org/)

TeleClaude is a sophisticated agent platform designed for seamless remote terminal control, powerful automation, and advanced AI-to-AI collaboration across multiple computers and communication channels. Manage your infrastructure, orchestrate complex tasks, and integrate with essential services like Discord and WhatsApp, all from a unified interface.

## Key Features

TeleClaude has evolved into a full-featured agent platform, offering:

- **Multi-Platform Integrations:**
  - **Telegram:** Robust control and real-time output streaming.
  - **Discord:** Seamless integration for bot commands and notifications.
  - **WhatsApp:** Upcoming support for business-critical communications and automation.
- **Remote Terminal Control:**
  - Manage multiple persistent terminal sessions across diverse machines.
  - Real-time output streaming and command execution from anywhere.
  - Intelligent session management and recovery.
- **Advanced Agent Platform:**
  - **Automated Jobs:** Schedule and manage recurring tasks, data synchronization, and maintenance routines.
  - **Multi-User Configurations:** Support for diverse user roles and access controls.
  - **Subscription Management:** Easily configure and manage subscriptions to various services and data feeds.
  - **AI-to-AI Collaboration (MCP):** Facilitate direct communication and task delegation between AI agents across different computers.
  - **Extensible Event Handling:** Integrate external event triggers and custom workflows for dynamic automation. (Note: The specific functionality of the 'hook service' is being refined but enables robust event-driven automation.)
- **Developer-Focused:**
  - Powerful CLI tools for managing agents, configurations, and deployments.
  - Adherence to rigorous code quality, testing, and security standards.

## Architecture Overview

TeleClaude employs a distributed, adapter-based architecture. It uses a core daemon to manage sessions, orchestrate agents, and communicate via the Model Context Protocol (MCP) for inter-agent collaboration. Adapters translate platform-specific inputs and outputs (TUI, Web, Telegram, Discord, upcoming WhatsApp) into a unified format, ensuring consistent control and visibility across all connected systems. The platform supports automated job execution and provides a flexible foundation for building complex, automated workflows.

## Getting Started

### Prerequisites

- Python 3.11 or higher
- tmux 3.0 or higher
- `uv` (Python package manager; must be on `PATH`)
- Telegram, Discord, and WhatsApp accounts (for respective integrations)
- Relevant API tokens/credentials for configured services.

### Installation

```bash
# Clone the repository
git clone https://github.com/morriz/teleclaude.git
cd teleclaude

# Install dependencies
make install

# Run installation wizard (interactive)
make init

# Or run in unattended mode
# (CI: env vars already set; Locally: source .env first if needed)
make init ARGS=-y
```

The installation wizard guides you through setting up your environment, configuring services (including Telegram bot, Discord bot credentials, and WhatsApp Business API access), and establishing connections.

### Configuration

Post-installation, configure TeleClaude by editing `.env` and `config.yml` to define your bot tokens, user IDs, API keys, and integration settings. Refer to `config.sample.yml` for detailed options.

## Key Capabilities

### Multi-Platform Communication

TeleClaude unifies your interactions through:

- **Telegram:** Your primary console for session control and real-time output.
- **Discord:** Integrate TeleClaude bots into your Discord servers for notifications and command execution.
- **WhatsApp:** Leverage the WhatsApp Business API for automated messaging, alerts, and customer interactions.

### Robust Job Management

The built-in job runner allows you to schedule, monitor, and automate recurring tasks. Define jobs for system maintenance, data synchronization, AI analysis, and more, with flexible scheduling and robust error handling.

### Advanced AI Collaboration (MCP)

Enable your AI agents to work together seamlessly. TeleClaude's Model Context Protocol (MCP) allows agents on different machines to communicate, delegate tasks, and share information, forming powerful collaborative systems.

### Extensible Event Handling

Leverage TeleClaude's event processing capabilities to build reactive systems. Integrate external services and data sources to trigger automated workflows based on real-time events.

## Development

```bash
make format       # Format code
make lint         # Run linting checks
make test         # Run all tests (unit + integration)
make dev          # Run daemon in foreground
```

See developer documentation for workflow, coding rules, and testing guidelines.

## Contributing

Contributions are welcome! Please follow our contribution guidelines and code style.

## Support

- **Issues:** [GitHub Issues](https://github.com/morriz/teleclaude/issues)
- **Discussions:** [GitHub Discussions](https://github.com/morriz/teleclaude/discussions)
- **Email:** maurice@instrukt.ai

## License

GPL-3.0-only

---

**Note:** This README is a draft based on current understanding. Specific details on the 'hook service' functionality will be refined as more context becomes available.
