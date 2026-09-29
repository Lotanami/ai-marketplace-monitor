![AI Marketplace Monitor](docs/AIMM_neutral.png)

<div align="center">

[![PyPI - Version](https://img.shields.io/pypi/v/ai-marketplace-monitor.svg)](https://pypi.python.org/pypi/ai-marketplace-monitor)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/ai-marketplace-monitor.svg)](https://pypi.python.org/pypi/ai-marketplace-monitor)
[![Tests](https://github.com/BoPeng/ai-marketplace-monitor/workflows/tests/badge.svg)](https://github.com/BoPeng/ai-marketplace-monitor/actions?workflow=tests)
[![Codecov](https://codecov.io/gh/BoPeng/ai-marketplace-monitor/branch/main/graph/badge.svg)](https://codecov.io/gh/BoPeng/ai-marketplace-monitor)
[![Read the Docs](https://readthedocs.org/projects/ai-marketplace-monitor/badge/)](https://ai-marketplace-monitor.readthedocs.io/)
[![PyPI - License](https://img.shields.io/pypi/l/ai-marketplace-monitor.svg)](https://pypi.python.org/pypi/ai-marketplace-monitor)

[![Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](https://www.contributor-covenant.org/version/2/1/code_of_conduct/)

</div>

An intelligent tool that monitors Facebook Marketplace listings using AI to help you find the best deals. Get instant notifications when items matching your criteria are posted, with AI-powered analysis of each listing.

**📚 [Read the Full Documentation](https://ai-marketplace-monitor.readthedocs.io/)**

![Search In Action](docs/search_in_action.png)

Example notification from PushBullet:

```
Found 1 new gopro from facebook
[Great deal (5)] Go Pro hero 12
$180, Houston, TX
https://facebook.com/marketplace/item/1234567890
AI: Great deal; A well-priced, well-maintained camera meets all search criteria, with extra battery and charger.
```

## What's New

- **Built-in Web UI**: Edit config, add AI backends, and monitor live logs from your browser — starts automatically with the monitor. See [Web UI documentation](docs/webui.md).
- **Anthropic/Claude AI Backend**: Use Claude models (e.g. `claude-sonnet-4-20250514`) to evaluate listings alongside OpenAI, DeepSeek, Gemini, and Ollama. See [AI Services](docs/README.md#ai-services) for configuration.
- **Configurable Rate Limiting**: Rate limiting framework for all notification types with per-instance and global limits. Telegram notifications use optimized defaults automatically.

**Table of Contents:**

- [What's New](#whats-new)
- [✨ Key Features](#-key-features)
- [🚀 Quick Start](#-quick-start)
- [💡 Example Usage](#-example-usage)
- [📚 Documentation](#-documentation)
- [🤝 Contributing](#-contributing)
- [📜 License](#-license)
- [💬 Support](#-support)
- [🙏 Credits](#-credits)

## ✨ Key Features

🔍 **Smart Search**

- Search multiple products using keywords
- Filter by price and location
- Exclude irrelevant results and spammers
- Support for different Facebook Marketplace layouts

🤖 **AI-Powered**

- Intelligent listing evaluation
- Smart recommendations
- Multiple AI service providers supported
- Self-hosted model option (Ollama)

📱 **Notifications**

- PushBullet, PushOver, Telegram, or Ntfy notifications
- HTML email notifications with images
- Customizable notification levels
- Repeated notification options

🖥️ **Web UI**

- Built-in config editor with TOML syntax highlighting
- Live log streaming and filtering
- Add, edit, and delete config sections from your browser
- No password required on localhost

![Web UI](docs/webui_screenshot.png)

🌎 **Location Support**

- Multi-city search
- Pre-defined regions (USA, Canada, etc.)
- Customizable search radius
- Flexible seller location filtering

## 🚀 Quick Start

> **⚠️ Legal Notice**: Facebook's EULA prohibits automated data collection without authorization. This tool was developed for personal, hobbyist use only. You are solely responsible for ensuring compliance with platform terms and applicable laws.

### Installation

> **Requires Python 3.10 or higher.** Check your version with `python --version`. If your system default is older, use `pip3.10` (or `pip3.11`, `pip3.12`, etc.) instead of `pip`, or create a virtual environment with the correct version.

```bash
pip install ai-marketplace-monitor
playwright install
```

### Basic Configuration

Create `~/.ai-marketplace-monitor/config.toml`:

```toml
[marketplace.facebook]
search_city = 'houston'  # Replace with your city

[item.gopro]
search_phrases = 'Go Pro Hero 11'
min_price = 100
max_price = 300

[user.me]
pushbullet_token = 'your_token_here'  # Get from pushbullet.com
```

### Optional Marketplace home feed

To also discover personalized “For You” items, add these settings to your existing
sections (keep your search phrases unchanged):

```toml
[monitor]
persistent_chrome = true

[marketplace.facebook]
scan_for_you = true
for_you_max_listings = 25
for_you_scrolls = 2
```

Sign in to Facebook in the monitor's dedicated persistent Chrome profile first.
Home-feed discovery runs after keyword searches for each configured item and reuses
its filters, AI prompts, rating threshold, and notifications. It defaults to off.
The limit counts unique listing IDs, including known cards (1–100); scrolls are
bounded (0–20). Feed failures do not prevent keyword searches.

IDs already encountered in that search or present in the listing-details cache
are skipped before detail retrieval and AI evaluation, including previously
rejected listings. This also skips cached items whose price may have changed;
keyword searches retain their existing change detection. Clearing the listing
cache makes those IDs eligible again. Logs report found, known, and new counts.

### Optional HardwareSwapUK source

Add a separate item to read the newest 100 public r/HardwareSwapUK posts per scan:

```toml
[marketplace.hardwareswapuk]
enabled = true

[item.reddit_pc]
marketplace = "hardwareswapuk"
search_phrases = "gaming pc"
ai = ["nvidia"] # Use an AI backend already configured in your setup.
rating = 4
```

Copy your desired prompt/rating settings into this item. Facebook items and searches
stay separate. The source only accepts `[SG]` posts, excludes `[BG]`/`[SP]`, and
prioritizes complete-PC/system titles while retaining newest-first order within
each group. Search phrases describe your criteria to AI; they are not a Reddit
search query. Post bodies preserve the advertised specs; missing price/location
are marked “Not stated”. Existing AI evaluation, rating filtering and notification
backends handle the normalized listings.

Public JSON requests use a 30-second timeout and no login or API keys. Public
access is not guaranteed: blocked/rate-limited/unparseable responses are logged
and skipped until the next scheduled scan. Cached Reddit post IDs are skipped
before AI, including rejected listings; edited prices/bodies are not re-evaluated
until the listing cache is cleared. Timing separates feed retrieval from each
listing's processing (including AI). No browser is used by this source, though
the existing monitor startup still launches its configured browser.

A credential-free standalone NVIDIA GPU setup is available in
[`gpu-hunter.example.toml`](gpu-hunter.example.toml), including NVIDIA NIM,
Discord, Facebook keyword searches and HardwareSwapUK. Customize the example
city and provide the two environment variables before use.

### Run the Monitor

```bash
ai-marketplace-monitor
```

The program will open a browser, search Facebook Marketplace, and notify you of matching items. A web UI also starts automatically at [http://127.0.0.1:8467](http://127.0.0.1:8467) for editing config and monitoring logs — see [Web UI Guide](docs/webui.md).

### Run with Docker

A prebuilt Linux image is published to GitHub Container Registry. It bundles Python, Playwright Chromium, a virtual display (Xvfb), and an embedded noVNC client so you can solve Facebook CAPTCHAs / interactive logins from the web UI — useful on macOS, headless servers, or NAS boxes.

```bash
docker run -d --name aimm \
  -p 8467:8467 \
  -v "$HOME/.ai-marketplace-monitor:/root/.ai-marketplace-monitor" \
  -e FACEBOOK_USERNAME -e FACEBOOK_PASSWORD \
  -e ANTHROPIC_API_KEY \
  --restart unless-stopped \
  ghcr.io/bopeng/ai-marketplace-monitor:latest
```

Then open [http://localhost:8467](http://localhost:8467). When Facebook needs an interactive login or CAPTCHA, click the **Browser** button in the header to view and control the in-container Chromium.

Mounting `~/.ai-marketplace-monitor` shares your existing config, cache, and logs between the host install and the container — so you can switch back and forth freely. Update with `docker pull ghcr.io/bopeng/ai-marketplace-monitor:latest && docker restart aimm`.

To build the image yourself instead of pulling: `docker build -t aimm .` from a checkout of this repo.

## 💡 Example Usage

**Find GoPro cameras under $300:**

```toml
[item.gopro]
search_phrases = 'Go Pro Hero'
keywords = "('Go Pro' OR gopro) AND (11 OR 12 OR 13)"
min_price = 100
max_price = 300
```

**Search nationwide with shipping:**

```toml
[item.rare_item]
search_phrases = 'vintage collectible'
search_region = 'usa'
delivery_method = 'shipping'
seller_locations = []
```

**AI-powered filtering:**

```toml
[ai.openai]
api_key = 'your_openai_key'

[item.camera]
description = '''High-quality DSLR camera in good condition.
Exclude listings with water damage or missing parts.'''
rating = 4  # Only notify for 4+ star AI ratings
```

## 📚 Documentation

For detailed information on setup and advanced features, see the comprehensive documentation:

- **[📖 Full Documentation](https://ai-marketplace-monitor.readthedocs.io/)** - Complete guide and reference
- **[🚀 Quick Start Guide](https://ai-marketplace-monitor.readthedocs.io/en/latest/quickstart.html)** - Get up and running in 10 minutes
- **[🔍 Features Overview](https://ai-marketplace-monitor.readthedocs.io/en/latest/features.html)** - Complete feature list
- **[📱 Usage Guide](https://ai-marketplace-monitor.readthedocs.io/en/latest/usage.html)** - Command-line options and tips
- **[🔧 Configuration Guide](https://ai-marketplace-monitor.readthedocs.io/en/latest/configuration-guide.html)** - Notifications, AI prompts, multi-location search
- **[⚙️ Configuration Reference](https://ai-marketplace-monitor.readthedocs.io/en/latest/configuration.html)** - Complete configuration reference
- **[🖥️ Web UI Guide](docs/webui.md)** - Built-in web interface for config editing and monitoring

### Key Topics Covered in Documentation

**Notification Setup:**

- Email (SMTP), PushBullet, PushOver, Telegram, Ntfy
- Multi-user configurations
- HTML email templates

**AI Integration:**

- OpenAI, DeepSeek, Gemini, Anthropic, Ollama setup
- Custom prompt configuration
- Rating thresholds and filtering

**Advanced Search:**

- Multi-city and region search
- Currency conversion
- Keyword filtering with Boolean logic
- Proxy/anonymous searching

**Configuration:**

- TOML file structure
- Environment variables
- Multiple marketplace support
- Language/translation support

## 🤝 Contributing

Contributions are welcome! Here are some ways you can contribute:

- 🐛 Report bugs and issues
- 💡 Suggest new features
- 🔧 Submit pull requests
- 📚 Improve documentation
- 🏪 Add support for new marketplaces
- 🌍 Add support for new regions and languages
- 🤖 Add support for new AI providers
- 📱 Add new notification methods

Please read our [Contributing Guidelines](https://ai-marketplace-monitor.readthedocs.io/en/latest/contributing.html) before submitting a Pull Request.

## 📜 License

This project is licensed under the **Affero General Public License (AGPL)**. For the full terms and conditions, please refer to the official [GNU AGPL v3](https://www.gnu.org/licenses/agpl-3.0.en.html).

## 💬 Support

We provide multiple ways to access support and contribute to AI Marketplace Monitor:

- 📖 [Documentation](https://ai-marketplace-monitor.readthedocs.io/) - Comprehensive guides and instructions
- 🤝 [Discussions](https://github.com/BoPeng/ai-marketplace-monitor/discussions) - Community support and ideas
- 🐛 [Issues](https://github.com/BoPeng/ai-marketplace-monitor/issues) - Bug reports and feature requests
- 💖 [Become a sponsor](https://github.com/sponsors/BoPeng) - Support development
- 💰 [Donate via PayPal](https://www.paypal.com/donate/?hosted_button_id=3WT5JPQ2793BN) - Alternative donation method

**Important Note:** Due to time constraints, priority support is provided to sponsors and donors. For general questions, please use the GitHub Discussions or Issues.

## 🙏 Credits

- Some of the code was copied from [facebook-marketplace-scraper](https://github.com/passivebot/facebook-marketplace-scraper).
- Region definitions were copied from [facebook-marketplace-nationwide](https://github.com/gmoz22/facebook-marketplace-nationwide/), which is released under an MIT license as of Jan 2025.
- This package was created with [Cookiecutter](https://github.com/cookiecutter/cookiecutter) and the [cookiecutter-modern-pypackage](https://github.com/fedejaure/cookiecutter-modern-pypackage) project template.
