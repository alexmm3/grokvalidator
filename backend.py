"""
Grok Validator PoC Backend
Two-step flow: Agent 1 (Image Extractor) -> Gate -> Agent 2 (Wan 2.2 Prompt Enhancer)
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


def load_prompt(filepath: str) -> str:
    """Load a system prompt from file (fresh read, no caching)."""
    prompt_path = PROJECT_ROOT / filepath
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def get_agent1_prompt() -> str:
    """Load Agent 1 system prompt fresh from file each time."""
    return load_prompt(config.AGENT1_PROMPT_FILE)


def get_agent2_prompt() -> str:
    """Load Agent 2 system prompt fresh from file each time."""
    return load_prompt(config.AGENT2_PROMPT_FILE)


# Store latest result in memory (no database)
latest_result = None


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
    """
    Calculate cost for an API call based on token usage.
    Returns detailed cost breakdown.
    """
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


def run_agent1(client: OpenAI, image_base64: str, image_type: str) -> tuple[dict, dict, dict]:
    """
    Agent 1: Image Extractor
    Uses grok-2-vision-1212 (preferred vision model) to analyze image.
    Returns JSON with people_count, minor_under_16, nsfw, description.
    Returns: (parsed_result, cost_info, request_details)
    """
    # Build data URL for the image (truncated for logging)
    data_url = f"data:{image_type};base64,{image_base64}"
    
    # Build user message content
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
    
    # Request parameters
    request_params = {
        "model": config.AGENT1_MODEL,
        "response_format": {"type": config.AGENT1_RESPONSE_FORMAT},
        "stream": config.STREAM_RESPONSES
    }
    
    if config.LOG_API_CALLS:
        print(f"[Agent 1] Calling {config.AGENT1_MODEL} with image ({image_type}, detail={config.IMAGE_DETAIL})")
    
    # Vision models (grok-2-vision-1212 and later) support response_format for structured JSON output
    response = client.chat.completions.create(
        model=config.AGENT1_MODEL,
        messages=messages,
        response_format={"type": config.AGENT1_RESPONSE_FORMAT},
        stream=config.STREAM_RESPONSES
    )
    
    raw_content = response.choices[0].message.content
    
    # Extract token usage
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0
    
    # Calculate cost
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
    
    # Build request details for debugging (truncate base64 for readability)
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


def check_gate(agent1_result: dict) -> dict:
    """
    Non-LLM gate: Check minor_under_16 field.
    Returns gate decision based on GATE_ALLOWED_VALUES in config.
    """
    minor_status = agent1_result.get("minor_under_16", "unclear")
    
    if minor_status in config.GATE_ALLOWED_VALUES:
        return {
            "passed": True,
            "reason": "No minors detected in image",
            "minor_under_16": minor_status
        }
    elif minor_status == "yes":
        return {
            "passed": False,
            "reason": "Minor under 16 detected in image - processing blocked",
            "minor_under_16": minor_status
        }
    else:  # "unclear" or any other value not in allowed list
        return {
            "passed": False,
            "reason": "Unable to confirm absence of minors - processing blocked for safety",
            "minor_under_16": minor_status
        }


def run_agent2(client: OpenAI, user_prompt: str, image_description: str, people_count: int) -> tuple[dict, dict, dict]:
    """
    Agent 2: Wan 2.2 Prompt Enhancer
    Uses grok-4-1-fast-non-reasoning (preferred text model) to rewrite user prompt.
    Returns JSON with {prompt, nsfw} for optimized Wan 2.2 image-to-video generation.
    Returns: (parsed_result with {prompt, nsfw}, cost_info, request_details)
    """
    # Provide context from Agent 1 to Agent 2
    user_content = f"""Image analysis results:
- People count: {people_count}
- Description: {image_description}

User's original prompt:
{user_prompt}"""
    
    messages = [
        {"role": "system", "content": get_agent2_prompt()},
        {"role": "user", "content": user_content}
    ]
    
    # Request parameters
    request_params = {
        "model": config.AGENT2_MODEL,
        "response_format": {"type": "json_object"},
        "stream": config.STREAM_RESPONSES
    }
    
    if config.LOG_API_CALLS:
        print(f"[Agent 2] Calling {config.AGENT2_MODEL}")
    
    response = client.chat.completions.create(
        model=config.AGENT2_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        stream=config.STREAM_RESPONSES
    )
    
    raw_content = response.choices[0].message.content
    
    # Extract token usage
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0
    
    # Calculate cost
    cost_info = calculate_cost(config.AGENT2_MODEL, input_tokens, output_tokens)
    
    if config.LOG_API_CALLS:
        print(f"[Agent 2] Response: {raw_content}")
        print(f"[Agent 2] Tokens: {input_tokens} in, {output_tokens} out | Cost: ${cost_info['total_cost_usd']:.6f}")
    
    # Parse JSON response (contains: prompt, nsfw)
    parsed_result = json.loads(raw_content)
    
    # Build request details for debugging
    request_details = {
        "request": {
            "endpoint": f"{config.GROK_BASE_URL}/chat/completions",
            "parameters": request_params,
            "messages": [
                {"role": "system", "content": get_agent2_prompt()},
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


@app.route("/")
def serve_index():
    """Serve the frontend HTML."""
    return send_from_directory(".", "index.html")


@app.route("/run", methods=["POST"])
def run_pipeline():
    """
    Main endpoint: Run the two-step flow.
    Accepts multipart form with 'image' file and 'prompt' text.
    Returns JSON with agent1_result, gate_decision, agent2_result (if gate passed), and costs.
    """
    global latest_result
    
    try:
        # Validate inputs
        if "image" not in request.files:
            return jsonify({"error": "No image file provided"}), 400
        
        image_file = request.files["image"]
        user_prompt = request.form.get("prompt", "").strip()
        
        if not user_prompt:
            return jsonify({"error": "No prompt provided"}), 400
        
        # Validate image type (from config)
        content_type = image_file.content_type
        if content_type not in config.ALLOWED_IMAGE_TYPES:
            return jsonify({
                "error": f"Unsupported image type: {content_type}. Allowed: {config.ALLOWED_IMAGE_TYPES}"
            }), 400
        
        # Read and encode image
        image_data = image_file.read()
        
        # Check size (from config)
        if len(image_data) > config.MAX_IMAGE_SIZE_BYTES:
            max_mb = config.MAX_IMAGE_SIZE_BYTES / (1024 * 1024)
            return jsonify({"error": f"Image too large. Maximum size is {max_mb:.0f} MiB."}), 400
        
        image_base64 = base64.b64encode(image_data).decode("utf-8")
        
        # Get API client
        client = get_client()
        
        # Initialize cost tracking
        costs = {
            "agent1": None,
            "agent2": None,
            "total": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0
            }
        }
        
        # Step 1: Run Agent 1 (Image Extractor)
        agent1_result, agent1_cost, agent1_details = run_agent1(client, image_base64, content_type)
        costs["agent1"] = agent1_cost
        costs["total"]["input_tokens"] += agent1_cost["input_tokens"]
        costs["total"]["output_tokens"] += agent1_cost["output_tokens"]
        costs["total"]["total_tokens"] += agent1_cost["total_tokens"]
        costs["total"]["total_cost_usd"] += agent1_cost["total_cost_usd"]
        
        # Step 2: Check gate
        gate_decision = check_gate(agent1_result)
        
        # Add gate details for debugging
        gate_details = {
            "rule": f"minor_under_16 must be in {config.GATE_ALLOWED_VALUES}",
            "input_value": agent1_result.get("minor_under_16", "unclear"),
            "decision": gate_decision
        }
        
        # Build result
        result = {
            "agent1_result": agent1_result,
            "agent1_details": agent1_details,
            "gate_decision": gate_decision,
            "gate_details": gate_details,
            "agent2_result": None,
            "agent2_details": None,
            "costs": costs if config.TRACK_COSTS else None
        }
        
        # Step 3: Run Agent 2 if gate passed
        if gate_decision["passed"]:
            agent2_result, agent2_cost, agent2_details = run_agent2(
                client,
                user_prompt,
                agent1_result.get("description", ""),
                agent1_result.get("people_count", 0)
            )
            result["agent2_result"] = agent2_result
            result["agent2_details"] = agent2_details
            costs["agent2"] = agent2_cost
            costs["total"]["input_tokens"] += agent2_cost["input_tokens"]
            costs["total"]["output_tokens"] += agent2_cost["output_tokens"]
            costs["total"]["total_tokens"] += agent2_cost["total_tokens"]
            costs["total"]["total_cost_usd"] += agent2_cost["total_cost_usd"]
        
        # Round total cost
        costs["total"]["total_cost_usd"] = round(costs["total"]["total_cost_usd"], 6)
        
        if config.LOG_API_CALLS:
            print(f"[Pipeline] Total cost: ${costs['total']['total_cost_usd']:.6f} ({costs['total']['total_tokens']} tokens)")
        
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
        # Log full exception for debugging
        import traceback
        print(f"[Pipeline Error] {type(e).__name__}: {e}")
        traceback.print_exc()
        return jsonify({"error": f"Pipeline failed: {type(e).__name__}: {str(e)}"}), 500


@app.route("/result", methods=["GET"])
def get_result():
    """
    Lightweight endpoint to fetch the latest run result.
    """
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
        "image_detail": config.IMAGE_DETAIL,
        "agent1_response_format": config.AGENT1_RESPONSE_FORMAT,
        "stream_responses": config.STREAM_RESPONSES,
        "gate_allowed_values": config.GATE_ALLOWED_VALUES,
        "max_image_size_bytes": config.MAX_IMAGE_SIZE_BYTES,
        "allowed_image_types": config.ALLOWED_IMAGE_TYPES,
        "log_api_calls": config.LOG_API_CALLS,
        "track_costs": config.TRACK_COSTS,
        "pricing": config.MODEL_PRICING
    })


if __name__ == "__main__":
    # Check for API key at startup
    if not os.environ.get("XAI_API_KEY"):
        print("WARNING: XAI_API_KEY environment variable is not set!")
        print("Set it in .env file or export XAI_API_KEY='your-api-key-here'")
    
    print("=" * 60)
    print("Grok Validator PoC Backend")
    print("=" * 60)
    print(f"Base URL:      {config.GROK_BASE_URL}")
    print(f"Agent 1 Model: {config.AGENT1_MODEL}")
    print(f"Agent 2 Model: {config.AGENT2_MODEL}")
    print(f"Image Detail:  {config.IMAGE_DETAIL}")
    print(f"Gate Allows:   {config.GATE_ALLOWED_VALUES}")
    print(f"Log API Calls: {config.LOG_API_CALLS}")
    print(f"Track Costs:   {config.TRACK_COSTS}")
    print("-" * 60)
    print("Prompts:       Loaded fresh from files on each request")
    print(f"  Agent 1:     {config.AGENT1_PROMPT_FILE}")
    print(f"  Agent 2:     {config.AGENT2_PROMPT_FILE}")
    print("-" * 60)
    print("Pricing (per million tokens):")
    for model, pricing in config.MODEL_PRICING.items():
        if model != "_default":
            print(f"  {model}: ${pricing['input_per_million']:.2f} in / ${pricing['output_per_million']:.2f} out")
    print("=" * 60)
    
    app.run(
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        debug=config.DEBUG_MODE
    )
