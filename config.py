"""
Grok Validator Configuration
============================
All API and application settings in one place.
Edit this file to customize behavior without touching the main application code.
"""

# =============================================================================
# GROK API CONFIGURATION
# =============================================================================

# Base URL for xAI Grok API (per grok_api_readme.txt)
GROK_BASE_URL = "https://api.x.ai/v1"

# -----------------------------------------------------------------------------
# MODEL SELECTION
# -----------------------------------------------------------------------------
# Agent 1: Image analysis model (must support vision/image input)
# Preferred: "grok-2-vision-1212" (recommended vision model for image understanding)
# Options: "grok-2-vision-latest" (alias), "grok-2-vision-1212"
AGENT1_MODEL = "grok-2-vision-1212"

# Agent 2: Text generation model (text-to-text)
# Preferred: "grok-4-1-fast-non-reasoning" (recommended for prompt enhancement tasks)
# Options: "grok-4" (latest), "grok-4-1-fast-non-reasoning", "grok-2"
AGENT2_MODEL = "grok-4-1-fast-non-reasoning"

# -----------------------------------------------------------------------------
# API REQUEST PARAMETERS
# -----------------------------------------------------------------------------

# Image detail level for vision requests
# Options: "high" (better accuracy), "low" (faster, less detail)
IMAGE_DETAIL = "low"

# Response format for Agent 1 (structured JSON output)
# Options: "json_object" (ensures valid JSON), "text" (free-form)
AGENT1_RESPONSE_FORMAT = "json_object"

# Whether to stream responses (False = wait for complete response)
STREAM_RESPONSES = False

# =============================================================================
# SAFETY GATE CONFIGURATION
# =============================================================================

# Values of minor_under_16 that will PASS the gate (allow Agent 2 to run)
# Conservative default: only "no" passes, "yes" and "unclear" both block
GATE_ALLOWED_VALUES = ["no"]

# =============================================================================
# APPLICATION SETTINGS
# =============================================================================

# Server host and port
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5050

# Flask debug mode (set to False in production)
DEBUG_MODE = True

# Maximum image size in bytes (20 MiB per Grok API docs)
MAX_IMAGE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MiB

# Allowed image MIME types (per grok_api_readme.txt)
ALLOWED_IMAGE_TYPES = [
    "image/jpeg",
    "image/jpg",
    "image/png"
]

# =============================================================================
# PROMPT FILE PATHS
# =============================================================================

# Relative paths from project root to system prompt files
AGENT1_PROMPT_FILE = "prompts/agent1_image_extractor.txt"
AGENT2_PROMPT_FILE = "prompts/agent2_wan_enhancer.txt"

# =============================================================================
# LOGGING / DEBUG
# =============================================================================

# Print API request/response info to console (useful for debugging)
LOG_API_CALLS = True

# =============================================================================
# PRICING (per million tokens, in USD)
# =============================================================================
# Source: xAI pricing as of Dec 2024
# Update these values if pricing changes

MODEL_PRICING = {
    # grok-2-vision-latest (alias) and grok-2-vision-1212
    # Vision model - used for Agent 1 image analysis
    "grok-2-vision-latest": {
        "input_per_million": 0.20,   # Text + Image input tokens
        "output_per_million": 0.50,
    },
    "grok-2-vision-1212": {
        "input_per_million": 0.20,
        "output_per_million": 0.50,
    },
    
    # grok-4-1-fast-non-reasoning
    # Fast text model without reasoning - used for Agent 2 prompt enhancement
    "grok-4-1-fast-non-reasoning": {
        "input_per_million": 0.20,
        "output_per_million": 0.50,
    },
    
    # Fallback for other models (grok-4, etc.)
    "grok-4": {
        "input_per_million": 2.00,   # Flagship pricing
        "output_per_million": 10.00,
    },
    
    # Default fallback if model not found
    "_default": {
        "input_per_million": 0.20,
        "output_per_million": 0.50,
    },
}

# Enable cost tracking in API responses
TRACK_COSTS = True
