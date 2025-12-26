"""
Grok Validator PoC Backend
==========================
Multi-agent video generation preprocessing pipeline:
  Agent 1 (Image Analyzer) → Routing → Agent 2 (Neutral) or Agent 3 (Adult) → [Fragment 2 if 10s]

Supports:
  - 5-second videos: Single fragment generation
  - 10-second videos: Two fragments with continuation prompts
"""

import os
import json
import base64
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv

# Import all configuration from config.py
import config

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app)

# Project root directory
PROJECT_ROOT = Path(__file__).parent

# =============================================================================
# PROMPT LOADING (Fresh from files on each request)
# =============================================================================

def load_prompt(filepath: str) -> str:
    """Load a system prompt from file (fresh read, no caching)."""
    prompt_path = PROJECT_ROOT / filepath
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def get_agent1_prompt() -> str:
    """Load Agent 1 (Image Analyzer) system prompt."""
    return load_prompt(config.AGENT1_PROMPT_FILE)


def get_agent2_prompt() -> str:
    """Load Agent 2 (Neutral Enhancer) system prompt."""
    return load_prompt(config.AGENT2_PROMPT_FILE)


def get_agent3_prompt() -> str:
    """Load Agent 3 (Adult Enhancer) system prompt."""
    return load_prompt(config.AGENT3_PROMPT_FILE)


# Store latest result in memory (no database)
latest_result = None


# =============================================================================
# API CLIENT & COST CALCULATION
# =============================================================================

def get_client() -> OpenAI:
    """Get OpenAI client configured for xAI Grok API."""
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        raise ValueError("XAI_API_KEY environment variable is not set")
    return OpenAI(base_url=config.GROK_BASE_URL, api_key=api_key)


def get_model_pricing(model: str) -> dict:
    """Get pricing for a model from config, with fallback to default."""
    return config.MODEL_PRICING.get(model, config.MODEL_PRICING.get("_default", {
        "input_per_million": 0.20,
        "output_per_million": 0.50,
    }))


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> dict:
    """Calculate cost for an API call based on token usage."""
    pricing = get_model_pricing(model)
    
    input_cost = (input_tokens / 1_000_000) * pricing["input_per_million"]
    output_cost = (output_tokens / 1_000_000) * pricing["output_per_million"]
    total_cost = input_cost + output_cost
    
    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "input_cost_usd": round(input_cost, 6),
        "output_cost_usd": round(output_cost, 6),
        "total_cost_usd": round(total_cost, 6),
        "pricing": {
            "input_per_million": pricing["input_per_million"],
            "output_per_million": pricing["output_per_million"],
        }
    }


# =============================================================================
# AGENT 1: IMAGE ANALYZER
# =============================================================================

def run_agent1(client: OpenAI, image_base64: str, image_type: str) -> tuple[dict, dict, dict]:
    """
    Agent 1: Image Analyzer
    Analyzes the uploaded image to extract: people_count, minor_under_16, nsfw, description.
    Uses vision model (grok-2-vision-1212).
    
    Returns: (parsed_result, cost_info, request_details)
    """
    data_url = f"data:{image_type};base64,{image_base64}"
    
    user_content = [
        {
            "type": "image_url",
            "image_url": {
                "url": data_url,
                "detail": config.IMAGE_DETAIL
            }
        },
        {
            "type": "text",
            "text": "Analyze this image and provide the JSON output as specified."
        }
    ]
    
    messages = [
        {"role": "system", "content": get_agent1_prompt()},
        {"role": "user", "content": user_content}
    ]
    
    request_params = {
        "model": config.AGENT1_MODEL,
        "response_format": {"type": config.AGENT1_RESPONSE_FORMAT},
        "stream": config.STREAM_RESPONSES
    }
    
    if config.LOG_API_CALLS:
        print(f"[Agent 1] Calling {config.AGENT1_MODEL} with image ({image_type}, detail={config.IMAGE_DETAIL})")
    
    response = client.chat.completions.create(
        model=config.AGENT1_MODEL,
        messages=messages,
        response_format={"type": config.AGENT1_RESPONSE_FORMAT},
        stream=config.STREAM_RESPONSES
    )
    
    raw_content = response.choices[0].message.content
    
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0
    
    cost_info = calculate_cost(config.AGENT1_MODEL, input_tokens, output_tokens)
    
    if config.LOG_API_CALLS:
        print(f"[Agent 1] Response: {raw_content}")
        print(f"[Agent 1] Tokens: {input_tokens} in, {output_tokens} out | Cost: ${cost_info['total_cost_usd']:.6f}")
    
    # Parse JSON - handle potential markdown code blocks
    json_str = raw_content.strip()
    if json_str.startswith("```"):
        lines = json_str.split("\n")
        json_str = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    
    parsed_result = json.loads(json_str)
    
    # Build request details (truncate base64 for readability)
    truncated_image = f"{image_base64[:50]}...({len(image_base64)} chars total)"
    request_details = {
        "request": {
            "endpoint": f"{config.GROK_BASE_URL}/chat/completions",
            "parameters": request_params,
            "messages": [
                {"role": "system", "content": get_agent1_prompt()},
                {
                    "role": "user", 
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image_type};base64,{truncated_image}",
                                "detail": config.IMAGE_DETAIL
                            }
                        },
                        {"type": "text", "text": "Analyze this image and provide the JSON output as specified."}
                    ]
                }
            ]
        },
        "response": {
            "raw_content": raw_content,
            "parsed": parsed_result,
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens
            }
        }
    }
    
    return parsed_result, cost_info, request_details


# =============================================================================
# ROUTING LOGIC
# =============================================================================

def determine_route(agent1_result: dict) -> dict:
    """
    Determine which agent to use and whether safety gate applies.
    
    Routing logic:
    - If nsfw=True AND ROUTE_TO_ADULT_WHEN_NSFW: Route to Agent 3 (adult)
    - Otherwise: Route to Agent 2 (neutral)
    
    Safety gate (only for Agent 3):
    - If minor_under_16 != "no": Block processing
    
    Returns: {
        "agent": "agent2" | "agent3" | "blocked",
        "gate_applied": bool,
        "gate_passed": bool | None,
        "reason": str
    }
    """
    nsfw = agent1_result.get("nsfw", False)
    minor_status = agent1_result.get("minor_under_16", "unclear")
    
    if nsfw and config.ROUTE_TO_ADULT_WHEN_NSFW:
        # Adult content requested - safety gate applies
        if minor_status not in config.GATE_ALLOWED_VALUES:
            return {
                "agent": "blocked",
                "gate_applied": True,
                "gate_passed": False,
                "reason": f"Adult content blocked: minor_under_16='{minor_status}' (requires: {config.GATE_ALLOWED_VALUES})"
            }
        return {
            "agent": "agent3",
            "gate_applied": True,
            "gate_passed": True,
            "reason": "Adult content allowed: no minors detected"
        }
    else:
        # Neutral content - no safety gate needed
        return {
            "agent": "agent2",
            "gate_applied": False,
            "gate_passed": None,
            "reason": "Neutral content: routed to safe enhancer"
        }


# =============================================================================
# USER MESSAGE BUILDER (Handles continuation for Fragment 2+)
# =============================================================================

def build_user_message(
    user_prompt: str,
    image_description: str,
    people_count: int,
    previous_fragment: dict = None
) -> str:
    """
    Build the user message for Agent 2 or Agent 3.
    Includes continuation context if this is Fragment 2+.
    
    Args:
        user_prompt: Original user prompt
        image_description: Description from Agent 1
        people_count: Number of people from Agent 1
        previous_fragment: If provided, includes continuation context
                          {"prompt": "...", "time_range": "0-5 sec"}
    
    Returns: Formatted user message string
    """
    message = f"""Image analysis:
- People count: {people_count}
- Description: {image_description}

User's original prompt:
{user_prompt}"""

    if previous_fragment:
        message += f"""

--- Previous Fragment ({previous_fragment['time_range']}) ---
Enhanced prompt used: "{previous_fragment['prompt']}"

Generate the continuation for the next 5-second fragment. Advance the action naturally from where the previous fragment ended."""

    return message


# =============================================================================
# AGENT 2 & 3: PROMPT ENHANCERS
# =============================================================================

def run_prompt_enhancer(
    client: OpenAI,
    agent_name: str,
    user_prompt: str,
    image_description: str,
    people_count: int,
    previous_fragment: dict = None
) -> tuple[dict, dict, dict]:
    """
    Run prompt enhancement (Agent 2 or Agent 3).
    
    Args:
        client: OpenAI client
        agent_name: "agent2" (neutral) or "agent3" (adult)
        user_prompt: Original user prompt
        image_description: From Agent 1
        people_count: From Agent 1
        previous_fragment: For Fragment 2+, contains previous prompt
    
    Returns: (parsed_result, cost_info, request_details)
    """
    # Select appropriate prompt and model
    if agent_name == "agent3":
        system_prompt = get_agent3_prompt()
        model = config.AGENT3_MODEL
        agent_label = "Agent 3 (Adult)"
    else:
        system_prompt = get_agent2_prompt()
        model = config.AGENT2_MODEL
        agent_label = "Agent 2 (Neutral)"
    
    # Build user message (with continuation context if Fragment 2+)
    user_content = build_user_message(
        user_prompt, 
        image_description, 
        people_count, 
        previous_fragment
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]
    
    request_params = {
        "model": model,
        "response_format": {"type": "json_object"},
        "stream": config.STREAM_RESPONSES
    }
    
    fragment_info = ""
    if previous_fragment:
        fragment_info = " (Fragment 2 - continuation)"
    
    if config.LOG_API_CALLS:
        print(f"[{agent_label}] Calling {model}{fragment_info}")
    
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        stream=config.STREAM_RESPONSES
    )
    
    raw_content = response.choices[0].message.content
    
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0
    
    cost_info = calculate_cost(model, input_tokens, output_tokens)
    
    if config.LOG_API_CALLS:
        print(f"[{agent_label}] Response: {raw_content}")
        print(f"[{agent_label}] Tokens: {input_tokens} in, {output_tokens} out | Cost: ${cost_info['total_cost_usd']:.6f}")
    
    parsed_result = json.loads(raw_content)
    
    request_details = {
        "request": {
            "endpoint": f"{config.GROK_BASE_URL}/chat/completions",
            "parameters": request_params,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]
        },
        "response": {
            "raw_content": raw_content,
            "parsed": parsed_result,
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens
            }
        }
    }
    
    return parsed_result, cost_info, request_details


# =============================================================================
# ROUTES
# =============================================================================

@app.route("/")
def serve_index():
    """Serve the frontend HTML."""
    return send_from_directory(".", "index.html")


@app.route("/run", methods=["POST"])
def run_pipeline():
    """
    Main pipeline endpoint.
    
    Accepts multipart form with:
      - 'image': Image file (JPEG/PNG)
      - 'prompt': User prompt text
      - 'duration': Video duration in seconds (5 or 10, default: 5)
    
    Returns JSON with:
      - agent1_result: Image analysis
      - routing: Which agent was selected and why
      - fragments: Array of enhanced prompts (1 for 5s, 2 for 10s)
      - costs: Token usage and cost breakdown
    """
    global latest_result
    
    try:
        # Validate inputs
        if "image" not in request.files:
            return jsonify({"error": "No image file provided"}), 400
        
        image_file = request.files["image"]
        user_prompt = request.form.get("prompt", "").strip()
        duration = int(request.form.get("duration", config.DEFAULT_DURATION))
        
        if not user_prompt:
            return jsonify({"error": "No prompt provided"}), 400
        
        if duration not in config.VIDEO_DURATIONS:
            return jsonify({"error": f"Invalid duration. Allowed: {config.VIDEO_DURATIONS}"}), 400
        
        # Validate image type
        content_type = image_file.content_type
        if content_type not in config.ALLOWED_IMAGE_TYPES:
            return jsonify({
                "error": f"Unsupported image type: {content_type}. Allowed: {config.ALLOWED_IMAGE_TYPES}"
            }), 400
        
        # Read and encode image
        image_data = image_file.read()
        
        if len(image_data) > config.MAX_IMAGE_SIZE_BYTES:
            max_mb = config.MAX_IMAGE_SIZE_BYTES / (1024 * 1024)
            return jsonify({"error": f"Image too large. Maximum size is {max_mb:.0f} MiB."}), 400
        
        image_base64 = base64.b64encode(image_data).decode("utf-8")
        
        # Get API client
        client = get_client()
        
        # Initialize cost tracking
        costs = {
            "agent1": None,
            "fragments": [],
            "total": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0
            }
        }
        
        # Calculate number of fragments
        num_fragments = duration // config.FRAGMENT_LENGTH
        
        if config.LOG_API_CALLS:
            print(f"\n{'='*60}")
            print(f"[Pipeline] Starting: {duration}s video ({num_fragments} fragment(s))")
            print(f"{'='*60}")
        
        # =================================================================
        # STEP 1: Agent 1 - Image Analysis
        # =================================================================
        agent1_result, agent1_cost, agent1_details = run_agent1(client, image_base64, content_type)
        costs["agent1"] = agent1_cost
        costs["total"]["input_tokens"] += agent1_cost["input_tokens"]
        costs["total"]["output_tokens"] += agent1_cost["output_tokens"]
        costs["total"]["total_tokens"] += agent1_cost["total_tokens"]
        costs["total"]["total_cost_usd"] += agent1_cost["total_cost_usd"]
        
        # =================================================================
        # STEP 2: Routing Decision
        # =================================================================
        routing = determine_route(agent1_result)
        
        if config.LOG_API_CALLS:
            print(f"[Routing] → {routing['agent'].upper()} ({routing['reason']})")
        
        # Build result structure
        result = {
            "duration": duration,
            "num_fragments": num_fragments,
            "agent1_result": agent1_result,
            "agent1_details": agent1_details,
            "routing": routing,
            "fragments": [],
            "costs": costs if config.TRACK_COSTS else None
        }
        
        # Check if blocked
        if routing["agent"] == "blocked":
            result["blocked"] = True
            result["blocked_reason"] = routing["reason"]
            costs["total"]["total_cost_usd"] = round(costs["total"]["total_cost_usd"], 6)
            latest_result = result
            return jsonify(result)
        
        # =================================================================
        # STEP 3: Generate Fragment(s)
        # =================================================================
        agent_name = routing["agent"]
        image_description = agent1_result.get("description", "")
        people_count = agent1_result.get("people_count", 0)
        
        for fragment_num in range(1, num_fragments + 1):
            time_start = (fragment_num - 1) * config.FRAGMENT_LENGTH
            time_end = fragment_num * config.FRAGMENT_LENGTH
            time_range = f"{time_start}-{time_end} sec"
            
            # For Fragment 2+, include previous fragment's prompt
            previous_fragment = None
            if fragment_num > 1 and len(result["fragments"]) > 0:
                prev = result["fragments"][-1]
                previous_fragment = {
                    "prompt": prev["result"]["prompt"],
                    "time_range": prev["time_range"]
                }
            
            if config.LOG_API_CALLS:
                print(f"\n[Fragment {fragment_num}] Generating prompt for {time_range}...")
            
            # Run prompt enhancer
            frag_result, frag_cost, frag_details = run_prompt_enhancer(
                client,
                agent_name,
                user_prompt,
                image_description,
                people_count,
                previous_fragment
            )
            
            # Build fragment info
            fragment_info = {
                "fragment_number": fragment_num,
                "time_range": time_range,
                "agent_used": agent_name,
                "result": frag_result,
                "details": frag_details,
                "cost": frag_cost
            }
            
            # =========================================================
            # DEMO MODE NOTE: For Fragment 2+, we're using the SAME
            # uploaded image. In PRODUCTION, you should use the LAST
            # FRAME of the previously generated video as the first
            # frame for this fragment.
            # =========================================================
            if fragment_num > 1:
                fragment_info["_demo_note"] = (
                    "DEMO MODE: Using same uploaded image. "
                    "PRODUCTION: Use last frame of previous video fragment as first frame."
                )
                if config.LOG_API_CALLS:
                    print(f"[Fragment {fragment_num}] ⚠️  DEMO: Using same image (production: use last frame of previous video)")
            
            result["fragments"].append(fragment_info)
            
            # Update costs
            costs["fragments"].append(frag_cost)
            costs["total"]["input_tokens"] += frag_cost["input_tokens"]
            costs["total"]["output_tokens"] += frag_cost["output_tokens"]
            costs["total"]["total_tokens"] += frag_cost["total_tokens"]
            costs["total"]["total_cost_usd"] += frag_cost["total_cost_usd"]
        
        # Round total cost
        costs["total"]["total_cost_usd"] = round(costs["total"]["total_cost_usd"], 6)
        
        if config.LOG_API_CALLS:
            print(f"\n{'='*60}")
            print(f"[Pipeline] Complete: ${costs['total']['total_cost_usd']:.6f} ({costs['total']['total_tokens']} tokens)")
            print(f"{'='*60}\n")
        
        # Store for /result endpoint
        latest_result = result
        
        return jsonify(result)
    
    except ValueError as e:
        print(f"[Pipeline Error] ValueError: {e}")
        return jsonify({"error": str(e)}), 500
    except json.JSONDecodeError as e:
        print(f"[Pipeline Error] JSON decode failed: {e}")
        return jsonify({"error": f"Failed to parse JSON response: {str(e)}"}), 500
    except Exception as e:
        import traceback
        print(f"[Pipeline Error] {type(e).__name__}: {e}")
        traceback.print_exc()
        return jsonify({"error": f"Pipeline failed: {type(e).__name__}: {str(e)}"}), 500


@app.route("/result", methods=["GET"])
def get_result():
    """Fetch the latest run result."""
    if latest_result is None:
        return jsonify({"error": "No results available. Run the pipeline first."}), 404
    return jsonify(latest_result)


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


@app.route("/config", methods=["GET"])
def get_config():
    """Return current configuration (excluding sensitive data)."""
    return jsonify({
        "grok_base_url": config.GROK_BASE_URL,
        "agent1_model": config.AGENT1_MODEL,
        "agent2_model": config.AGENT2_MODEL,
        "agent3_model": config.AGENT3_MODEL,
        "image_detail": config.IMAGE_DETAIL,
        "video_durations": config.VIDEO_DURATIONS,
        "default_duration": config.DEFAULT_DURATION,
        "fragment_length": config.FRAGMENT_LENGTH,
        "route_to_adult_when_nsfw": config.ROUTE_TO_ADULT_WHEN_NSFW,
        "gate_allowed_values": config.GATE_ALLOWED_VALUES,
        "max_image_size_bytes": config.MAX_IMAGE_SIZE_BYTES,
        "allowed_image_types": config.ALLOWED_IMAGE_TYPES,
        "log_api_calls": config.LOG_API_CALLS,
        "track_costs": config.TRACK_COSTS,
        "pricing": config.MODEL_PRICING
    })


# =============================================================================
# STARTUP
# =============================================================================

if __name__ == "__main__":
    if not os.environ.get("XAI_API_KEY"):
        print("WARNING: XAI_API_KEY environment variable is not set!")
        print("Set it in .env file or export XAI_API_KEY='your-api-key-here'")
    
    print("=" * 60)
    print("Grok Validator PoC Backend")
    print("=" * 60)
    print(f"Base URL:      {config.GROK_BASE_URL}")
    print("-" * 60)
    print("Agents:")
    print(f"  Agent 1:     {config.AGENT1_MODEL} (Image Analyzer)")
    print(f"  Agent 2:     {config.AGENT2_MODEL} (Neutral Enhancer)")
    print(f"  Agent 3:     {config.AGENT3_MODEL} (Adult Enhancer)")
    print("-" * 60)
    print("Routing:")
    print(f"  NSFW → Adult: {config.ROUTE_TO_ADULT_WHEN_NSFW}")
    print(f"  Gate Allows:  {config.GATE_ALLOWED_VALUES}")
    print("-" * 60)
    print("Video:")
    print(f"  Durations:   {config.VIDEO_DURATIONS} seconds")
    print(f"  Fragment:    {config.FRAGMENT_LENGTH} seconds each")
    print("-" * 60)
    print("Prompts (loaded fresh on each request):")
    print(f"  Agent 1:     {config.AGENT1_PROMPT_FILE}")
    print(f"  Agent 2:     {config.AGENT2_PROMPT_FILE}")
    print(f"  Agent 3:     {config.AGENT3_PROMPT_FILE}")
    print("-" * 60)
    print("Pricing (per million tokens):")
    for model, pricing in config.MODEL_PRICING.items():
        if model != "_default":
            print(f"  {model}: ${pricing['input_per_million']:.2f} in / ${pricing['output_per_million']:.2f} out")
    print("=" * 60)
    print()
    print("⚠️  DEMO MODE: Fragment 2 uses same image as Fragment 1")
    print("   PRODUCTION: Should use last frame of generated video")
    print()
    print("=" * 60)
    
    app.run(
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        debug=config.DEBUG_MODE
    )
