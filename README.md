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
   - **Agent 1 JSON**: Raw extraction result with `people_count`, `minor_under_16`, `description`
   - **Gate Decision**: PASSED or BLOCKED based on minor detection
   - **Agent 2 Output**: Enhanced prompt for Wan 2.2 (only if gate passed)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve the frontend HTML |
| `/run` | POST | Run the full pipeline (multipart form: `image` + `prompt`) |
| `/result` | GET | Fetch the latest run result |
| `/health` | GET | Health check |

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
    "description": "A woman with long brown hair..."
  },
  "gate_decision": {
    "passed": true,
    "reason": "No minors detected in image",
    "minor_under_16": "no"
  },
  "agent2_result": "One woman with long brown hair walks slowly toward the camera..."
}
```

## Project Structure

```
GrokValidator/
├── backend.py              # Flask backend with Grok API integration
├── index.html              # Single-page frontend
├── requirements.txt        # Python dependencies
├── grok_api_readme.txt     # Grok API reference
├── prompts/
│   ├── agent1_image_extractor.txt   # Agent 1 system prompt
│   └── agent2_wan_enhancer.txt      # Agent 2 system prompt
└── README.md
```

## Models Used

- **Agent 1**: `grok-2-vision-latest` (vision model for image analysis)
- **Agent 2**: `grok-4` (text model for prompt enhancement)

## Notes

- The gate is conservative: any `minor_under_16` value other than `"no"` blocks processing
- System prompts are loaded from `prompts/` folder at runtime for easy editing
- No database or authentication; latest result stored in memory only

