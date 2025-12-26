# Grok Validator PoC

A proof-of-concept module for video generation preprocessing using the xAI Grok API. Analyzes images, routes content, and generates optimized prompts for Wan 2.2 image-to-video generation.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           INPUT                                         │
│   Image (JPEG/PNG) + User Prompt + Duration (5s or 10s)                │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  AGENT 1: Image Analyzer (grok-2-vision-1212)                           │
│  → Extracts: people_count, minor_under_16, nsfw, description            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  CONTENT ROUTING                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ IF nsfw=true AND minor_under_16="no" → Agent 3 (Adult)          │   │
│  │ IF nsfw=true AND minor_under_16≠"no" → BLOCKED (safety gate)    │   │
│  │ ELSE → Agent 2 (Neutral)                                         │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌───────────────────────────┐       ┌───────────────────────────┐
│  AGENT 2 (Neutral)        │       │  AGENT 3 (Adult)          │
│  Safe content enhancer    │       │  Adult content enhancer   │
│  grok-4-1-fast-non-reason │       │  grok-4-1-fast-non-reason │
└───────────────────────────┘       └───────────────────────────┘
                    │                               │
                    └───────────────┬───────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  FRAGMENT GENERATION                                                    │
│  5s video  → 1 fragment                                                 │
│  10s video → 2 fragments (Fragment 2 includes continuation context)     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                              OUTPUT JSON
```

## Agents

| Agent | Model | Purpose |
|-------|-------|---------|
| **Agent 1** | `grok-2-vision-1212` | Image analysis: extracts people count, minor detection, NSFW flag, description |
| **Agent 2** | `grok-4-1-fast-non-reasoning` | Neutral/safe prompt enhancement for regular video content |
| **Agent 3** | `grok-4-1-fast-non-reasoning` | Adult content prompt enhancement (only when nsfw=true and no minors) |

## Safety Gate

The safety gate **only applies to adult content** (Agent 3):
- If `nsfw=true` AND `minor_under_16` is NOT `"no"` → **BLOCKED**
- Neutral content (Agent 2) bypasses the safety gate entirely

This means a child in an image can still be processed for safe content (e.g., birthday party video), but any adult/NSFW content with potential minors is blocked.

## Setup

### 1. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Set your xAI API key

Create a `.env` file in the project root:

```bash
XAI_API_KEY=your-api-key-here
```

### 3. Run the server

```bash
python backend.py
```

The server starts at `http://localhost:5050`

## Usage

1. Open `http://localhost:5050` in your browser
2. Upload a JPEG or PNG image (max 20 MiB)
3. Enter a prompt describing the desired video
4. Select duration: **5 sec** (1 fragment) or **10 sec** (2 fragments)
5. Click "Run Pipeline"
6. View results:
   - **Agent 1**: Image analysis with NSFW/minor flags
   - **Routing**: Which agent was selected and why
   - **Fragments**: Enhanced prompts for each video segment

## ⚠️ IMPORTANT: Demo Mode vs Production

### Fragment 2 Image Source

**DEMO MODE (current implementation):**
- Fragment 2 uses the **same uploaded image** as Fragment 1
- This is for demonstration purposes only

**PRODUCTION IMPLEMENTATION REQUIRED:**
- Fragment 2 should use the **last frame of the previously generated video**
- This ensures visual continuity between video segments
- Implementation requires integration with your video generation pipeline

```python
# PRODUCTION: Replace this
fragment_2_image = original_uploaded_image  # ❌ Demo mode

# WITH this
fragment_2_image = extract_last_frame(generated_video_fragment_1)  # ✅ Production
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve the frontend HTML |
| `/run` | POST | Run the full pipeline (multipart form: `image`, `prompt`, `duration`) |
| `/result` | GET | Fetch the latest run result |
| `/health` | GET | Health check |
| `/config` | GET | View current configuration |

### Request: POST /run

```bash
curl -X POST http://localhost:5050/run \
  -F "image=@photo.jpg" \
  -F "prompt=The person walks toward the camera" \
  -F "duration=10"
```

### Response Format

```json
{
  "duration": 10,
  "num_fragments": 2,
  "agent1_result": {
    "people_count": 1,
    "minor_under_16": "no",
    "nsfw": false,
    "description": "A woman with long brown hair..."
  },
  "agent1_details": { "request": {...}, "response": {...} },
  "routing": {
    "agent": "agent2",
    "gate_applied": false,
    "gate_passed": null,
    "reason": "Neutral content: routed to safe enhancer"
  },
  "fragments": [
    {
      "fragment_number": 1,
      "time_range": "0-5 sec",
      "agent_used": "agent2",
      "result": { "prompt": "...", "nsfw": false },
      "details": { "request": {...}, "response": {...} },
      "cost": {...}
    },
    {
      "fragment_number": 2,
      "time_range": "5-10 sec",
      "agent_used": "agent2",
      "result": { "prompt": "...", "nsfw": false },
      "details": {...},
      "cost": {...},
      "_demo_note": "DEMO MODE: Using same uploaded image. PRODUCTION: Use last frame of previous video fragment as first frame."
    }
  ],
  "costs": {
    "agent1": {...},
    "fragments": [...],
    "total": { "input_tokens": 2000, "output_tokens": 300, "total_cost_usd": 0.00055 }
  }
}
```

## Project Structure

```
GrokValidator/
├── backend.py                        # Flask backend with full pipeline
├── config.py                         # All configuration (models, routing, etc.)
├── index.html                        # Single-page frontend
├── requirements.txt                  # Python dependencies
├── .env                              # API key (not in git)
├── .gitignore
├── grok_api_readme.txt               # Grok API reference
├── prompts/
│   ├── agent1_image_extractor.txt    # Agent 1 system prompt
│   ├── agent2_neutral_enhancer.txt   # Agent 2 system prompt (safe content)
│   └── agent3_adult_enhancer.txt     # Agent 3 system prompt (adult content)
└── README.md
```

## Configuration

All settings are in `config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `AGENT1_MODEL` | `grok-2-vision-1212` | Vision model for image analysis |
| `AGENT2_MODEL` | `grok-4-1-fast-non-reasoning` | Text model for neutral enhancement |
| `AGENT3_MODEL` | `grok-4-1-fast-non-reasoning` | Text model for adult enhancement |
| `ROUTE_TO_ADULT_WHEN_NSFW` | `True` | Route NSFW content to Agent 3 |
| `GATE_ALLOWED_VALUES` | `["no"]` | Minor status values that pass safety gate |
| `VIDEO_DURATIONS` | `[5, 10]` | Supported video lengths (seconds) |
| `FRAGMENT_LENGTH` | `5` | Length of each fragment (seconds) |
| `IMAGE_DETAIL` | `low` | Vision API detail level |
| `SERVER_PORT` | `5050` | Server port |
| `TRACK_COSTS` | `True` | Include cost info in responses |

## Pricing

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|-------|----------------------|------------------------|
| `grok-2-vision-1212` | $0.20 | $0.50 |
| `grok-4-1-fast-non-reasoning` | $0.20 | $0.50 |

## Integration Guide

This module is designed to be integrated into your video generation backend:

```python
from grok_validator import GrokValidator

class VideoGenerator:
    def __init__(self):
        self.validator = GrokValidator(api_key="your-key")
    
    def generate_video(self, image, prompt, duration=5):
        # Step 1: Run validation pipeline
        result = self.validator.process(image, prompt, duration)
        
        if result.get("blocked"):
            raise ValueError(result["routing"]["reason"])
        
        # Step 2: Generate video fragments
        generated_videos = []
        for i, fragment in enumerate(result["fragments"]):
            # Use appropriate image for each fragment
            if i == 0:
                frame_image = image
            else:
                # PRODUCTION: Use last frame of previous video
                frame_image = extract_last_frame(generated_videos[-1])
            
            video = self.wan22_generate(
                first_frame=frame_image,
                prompt=fragment["result"]["prompt"]
            )
            generated_videos.append(video)
        
        # Step 3: Concatenate fragments
        if len(generated_videos) > 1:
            return concatenate_videos(generated_videos)
        return generated_videos[0]
```

## Notes

- System prompts are loaded fresh from files on each request (no restart needed to update)
- The `_demo_note` field in Fragment 2+ responses reminds developers about production requirements
- View Raw buttons in the UI show full request/response details for debugging
- All agents output structured JSON with `response_format: json_object`
