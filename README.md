# Grok Validator PoC

A proof-of-concept app demonstrating a two-step image validation and prompt enhancement flow using the xAI Grok API.

## Flow Overview

1. **Agent 1 (Image Extractor)**: Analyzes uploaded image, extracts people count, minor detection, and description
2. **Safety Gate**: Non-LLM check that blocks processing if minors might be present (`minor_under_16` != "no")
3. **Agent 2 (Wan 2.2 Prompt Enhancer)**: Rewrites user prompt for optimal Wan 2.2 image-to-video generation

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your xAI API key

Create a `.env` file in the project root:

```bash
XAI_API_KEY=your-api-key-here
```

Or export it directly:

```bash
export XAI_API_KEY='your-api-key-here'
```

### 3. Run the server

```bash
python backend.py
```

The server starts at `http://localhost:5050`

## Usage

1. Open `http://localhost:5050` in your browser
2. Upload a JPEG or PNG image (max 20 MiB)
3. Enter a prompt describing the video you want to generate
4. Click "Run Pipeline"
5. View results:
   - **Agent 1 JSON**: Raw extraction result with `people_count`, `minor_under_16`, `nsfw`, `description`
   - **Gate Decision**: PASSED or BLOCKED based on minor detection
   - **Agent 2 Output**: Enhanced prompt JSON with `prompt` and `nsfw` fields (only if gate passed)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve the frontend HTML |
| `/run` | POST | Run the full pipeline (multipart form: `image` + `prompt`) |
| `/result` | GET | Fetch the latest run result |
| `/health` | GET | Health check |
| `/config` | GET | View current configuration (non-sensitive) |

### Example: Run pipeline with curl

```bash
curl -X POST http://localhost:5050/run \
  -F "image=@photo.jpg" \
  -F "prompt=The person walks toward the camera"
```

### Response format

```json
{
  "agent1_result": {
    "people_count": 1,
    "minor_under_16": "no",
    "nsfw": false,
    "description": "A woman with long brown hair..."
  },
  "agent1_details": {
    "request": {
      "endpoint": "https://api.x.ai/v1/chat/completions",
      "parameters": {"model": "grok-2-vision-1212", "response_format": {"type": "json_object"}},
      "messages": [...]
    },
    "response": {
      "raw_content": "...",
      "parsed": {...},
      "usage": {"prompt_tokens": 1234, "completion_tokens": 56, "total_tokens": 1290}
    }
  },
  "gate_decision": {
    "passed": true,
    "reason": "No minors detected in image",
    "minor_under_16": "no"
  },
  "gate_details": {
    "rule": "minor_under_16 must be in ['no']",
    "input_value": "no",
    "decision": {...}
  },
  "agent2_result": {
    "prompt": "One woman with long brown hair walks slowly toward the camera...",
    "nsfw": false
  },
  "agent2_details": {
    "request": {...},
    "response": {...}
  },
  "costs": {
    "agent1": {"model": "grok-2-vision-1212", "input_tokens": 1234, "output_tokens": 56, "total_cost_usd": 0.000275},
    "agent2": {"model": "grok-4-1-fast-non-reasoning", ...},
    "total": {"input_tokens": 1500, "output_tokens": 120, "total_tokens": 1620, "total_cost_usd": 0.00036}
  }
}
```

The `*_details` fields contain the full request/response data for debugging and verification.

## Project Structure

```
GrokValidator/
├── backend.py              # Flask backend with Grok API integration
├── config.py               # All configuration settings (models, params, etc.)
├── index.html              # Single-page frontend
├── requirements.txt        # Python dependencies
├── .env                    # API key (not committed to git)
├── grok_api_readme.txt     # Grok API reference
├── prompts/
│   ├── agent1_image_extractor.txt   # Agent 1 system prompt
│   └── agent2_wan_enhancer.txt      # Agent 2 system prompt
└── README.md
```

## Configuration

All settings are centralized in `config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `GROK_BASE_URL` | `https://api.x.ai/v1` | Grok API base URL |
| `AGENT1_MODEL` | `grok-2-vision-1212` | **Preferred** vision model for image analysis |
| `AGENT2_MODEL` | `grok-4-1-fast-non-reasoning` | **Preferred** text model for prompt enhancement |
| `IMAGE_DETAIL` | `low` | Image detail level (`high` or `low`) |
| `AGENT1_RESPONSE_FORMAT` | `json_object` | Forces structured JSON output |
| `GATE_ALLOWED_VALUES` | `["no"]` | Values that pass the safety gate |
| `SERVER_PORT` | `5050` | Server port |
| `LOG_API_CALLS` | `True` | Log API requests to console |
| `TRACK_COSTS` | `True` | Track and report API call costs |
| `AGENT1_PROMPT_FILE` | `prompts/agent1_image_extractor.txt` | Agent 1 system prompt file |
| `AGENT2_PROMPT_FILE` | `prompts/agent2_wan_enhancer.txt` | Agent 2 system prompt file |

View current config at runtime: `GET /config`

## Models Used

- **Agent 1**: `grok-2-vision-1212` - **Preferred vision model** for image analysis
  - Supports structured JSON output via `response_format`
  - Optimized for image understanding tasks
  - Pricing: $0.20 per million input tokens, $0.50 per million output tokens

- **Agent 2**: `grok-4-1-fast-non-reasoning` - **Preferred text model** for prompt enhancement
  - Fast, non-reasoning model ideal for structured tasks
  - Supports JSON output for structured responses
  - Pricing: $0.20 per million input tokens, $0.50 per million output tokens

## Features

- **View Raw**: Click "View Raw" buttons in the UI to see full request/response details for each step
- **Live Prompt Editing**: System prompts are loaded fresh from `prompts/` on each request (no restart needed)
- **Cost Tracking**: Real-time cost calculation based on token usage and model pricing

## Notes

- The gate is conservative: any `minor_under_16` value other than `"no"` blocks processing
- System prompts are loaded fresh from `prompts/` folder on each API call for easy live editing
- No database or authentication; latest result stored in memory only
- Image base64 is truncated in `*_details` for readability (full image is sent to API)

