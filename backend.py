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

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app)

# Grok API configuration (per grok_api_readme.txt)
BASE_URL = "https://api.x.ai/v1"
VISION_MODEL = "grok-2-vision-latest"
TEXT_MODEL = "grok-4"

# Load prompts from files
PROMPTS_DIR = Path(__file__).parent / "prompts"

def load_prompt(filename: str) -> str:
    """Load a system prompt from the prompts/ folder."""
    prompt_path = PROMPTS_DIR / filename
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().strip()

# Load system prompts at startup
AGENT1_SYSTEM_PROMPT = load_prompt("agent1_image_extractor.txt")
AGENT2_SYSTEM_PROMPT = load_prompt("agent2_wan_enhancer.txt")

# Store latest result in memory (no database)
latest_result = None


def get_client() -> OpenAI:
    """Get OpenAI client configured for xAI Grok API."""
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        raise ValueError("XAI_API_KEY environment variable is not set")
    return OpenAI(base_url=BASE_URL, api_key=api_key)


def run_agent1(client: OpenAI, image_base64: str, image_type: str) -> dict:
    """
    Agent 1: Image Extractor
    Analyzes image and returns JSON with people_count, minor_under_16, description.
    """
    # Build data URL for the image
    data_url = f"data:{image_type};base64,{image_base64}"
    
    messages = [
        {"role": "system", "content": AGENT1_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": data_url, "detail": "high"}
                },
                {
                    "type": "text",
                    "text": "Analyze this image and provide the JSON output as specified."
                }
            ]
        }
    ]
    
    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=messages,
        response_format={"type": "json_object"}
    )
    
    raw_content = response.choices[0].message.content
    return json.loads(raw_content)


def check_gate(agent1_result: dict) -> dict:
    """
    Non-LLM gate: Check minor_under_16 field.
    Returns gate decision with passed=True only if minor_under_16 is "no".
    """
    minor_status = agent1_result.get("minor_under_16", "unclear")
    
    if minor_status == "no":
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
    else:  # "unclear" or any other value
        return {
            "passed": False,
            "reason": "Unable to confirm absence of minors - processing blocked for safety",
            "minor_under_16": minor_status
        }


def run_agent2(client: OpenAI, user_prompt: str, image_description: str, people_count: int) -> str:
    """
    Agent 2: Wan 2.2 Prompt Enhancer
    Rewrites user prompt into optimized format for Wan 2.2 image-to-video.
    """
    # Provide context from Agent 1 to Agent 2
    context = f"""Image analysis results:
- People count: {people_count}
- Description: {image_description}

User's original prompt:
{user_prompt}"""
    
    messages = [
        {"role": "system", "content": AGENT2_SYSTEM_PROMPT},
        {"role": "user", "content": context}
    ]
    
    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=messages
    )
    
    return response.choices[0].message.content.strip()


@app.route("/")
def serve_index():
    """Serve the frontend HTML."""
    return send_from_directory(".", "index.html")


@app.route("/run", methods=["POST"])
def run_pipeline():
    """
    Main endpoint: Run the two-step flow.
    Accepts multipart form with 'image' file and 'prompt' text.
    Returns JSON with agent1_result, gate_decision, and agent2_result (if gate passed).
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
        
        # Validate image type
        content_type = image_file.content_type
        if content_type not in ["image/jpeg", "image/jpg", "image/png"]:
            return jsonify({"error": f"Unsupported image type: {content_type}. Use JPEG or PNG."}), 400
        
        # Read and encode image
        image_data = image_file.read()
        
        # Check size (max 20 MiB per grok_api_readme.txt)
        if len(image_data) > 20 * 1024 * 1024:
            return jsonify({"error": "Image too large. Maximum size is 20 MiB."}), 400
        
        image_base64 = base64.b64encode(image_data).decode("utf-8")
        
        # Get API client
        client = get_client()
        
        # Step 1: Run Agent 1 (Image Extractor)
        agent1_result = run_agent1(client, image_base64, content_type)
        
        # Step 2: Check gate
        gate_decision = check_gate(agent1_result)
        
        # Build result
        result = {
            "agent1_result": agent1_result,
            "gate_decision": gate_decision,
            "agent2_result": None
        }
        
        # Step 3: Run Agent 2 if gate passed
        if gate_decision["passed"]:
            agent2_result = run_agent2(
                client,
                user_prompt,
                agent1_result.get("description", ""),
                agent1_result.get("people_count", 0)
            )
            result["agent2_result"] = agent2_result
        
        # Store for /result endpoint
        latest_result = result
        
        return jsonify(result)
    
    except ValueError as e:
        return jsonify({"error": str(e)}), 500
    except json.JSONDecodeError as e:
        return jsonify({"error": f"Failed to parse Agent 1 JSON response: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Pipeline failed: {str(e)}"}), 500


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


if __name__ == "__main__":
    # Check for API key at startup
    if not os.environ.get("XAI_API_KEY"):
        print("WARNING: XAI_API_KEY environment variable is not set!")
        print("Set it with: export XAI_API_KEY='your-api-key-here'")
    
    print("Starting Grok Validator PoC Backend...")
    print(f"Agent 1 Model: {VISION_MODEL}")
    print(f"Agent 2 Model: {TEXT_MODEL}")
    app.run(host="0.0.0.0", port=5050, debug=True)

