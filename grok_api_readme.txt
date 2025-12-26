xAI Grok API integration notes (text and image analysis)

1) Base URL and auth
* Base URL: https://api.x.ai
* API version prefix: /v1
* Auth header:
  Authorization: Bearer <XAI_API_KEY>
* Content type:
  Content-Type: application/json

2) Which endpoint to use
A) Recommended (stateful): Responses API
* POST /v1/responses
  Stores responses for 30 days by default and returns a response id you can fetch later or continue from.
* GET /v1/responses/{response_id}
* DELETE /v1/responses/{response_id}

B) OpenAI compatible (stateless by default): Chat Completions API
* POST /v1/chat/completions
  Works for chat and image understanding models.

Tip: For vision requests, xAI recommends disabling server-side storing (store: false) to avoid failures.

3) Discover available models at runtime (do not hardcode long term)
* GET /v1/models
  Minimal list of model ids available to your key.
* GET /v1/language-models
  Full info, including input modalities (text, image), output modalities, and pricing fields.
* GET /v1/language-models/{model_id}
  Full info for one model.

Example (curl) to list models:
curl https://api.x.ai/v1/models \
  -H "Authorization: Bearer $XAI_API_KEY"

4) Text to text request examples

4.1) Responses API (curl)
curl https://api.x.ai/v1/responses \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-4",
    "input": [
      { "role": "system", "content": "You are a helpful assistant." },
      { "role": "user", "content": "Write a short summary of the benefits of caching in APIs." }
    ]
  }'

Continuing a conversation (Responses API) with previous_response_id:
curl https://api.x.ai/v1/responses \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-4",
    "previous_response_id": "<PAST_RESPONSE_ID>",
    "input": [
      { "role": "user", "content": "Now rewrite it as bullet points." }
    ]
  }'

Retrieve later:
curl https://api.x.ai/v1/responses/<RESPONSE_ID> \
  -H "Authorization: Bearer $XAI_API_KEY"

4.2) Chat Completions (curl)
curl https://api.x.ai/v1/chat/completions \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-4",
    "messages": [
      { "role": "system", "content": "You are a helpful assistant." },
      { "role": "user", "content": "Give me 3 startup name ideas for a photo organizer app." }
    ]
  }'

5) Image analysis (vision) request examples

5.1) Message format for images
For vision capable models, set the user message "content" to a list of parts:
* an image part with:
  { "type": "image_url", "image_url": { "url": "...", "detail": "high" } }
* and a text part with:
  { "type": "text", "text": "..." }

The image_url.url value can be either:
* a data URL: data:image/jpeg;base64,<base64_image_string>
* or a normal https URL to an image on the internet

Practical limits and formats (from xAI docs):
* Max image size: 20 MiB
* Supported types: jpg/jpeg, png
* Order is flexible: image and text parts can appear in any order

5.2) Chat Completions vision example (curl, base64 data URL)
curl https://api.x.ai/v1/chat/completions \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-2-vision-latest",
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "image_url",
            "image_url": {
              "url": "data:image/jpeg;base64,<BASE64_IMAGE_STRING>",
              "detail": "high"
            }
          },
          {
            "type": "text",
            "text": "Describe the image and list any visible objects."
          }
        ]
      }
    ],
    "stream": false
  }'

5.3) Chat Completions vision example (curl, hosted image URL)
curl https://api.x.ai/v1/chat/completions \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-2-vision-latest",
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "image_url",
            "image_url": {
              "url": "https://example.com/image.png",
              "detail": "high"
            }
          },
          {
            "type": "text",
            "text": "Extract the text you can read in the image."
          }
        ]
      }
    ]
  }'

5.4) Python example using the OpenAI SDK pointed at xAI (matches xAI cookbook)
BASE_URL = "https://api.x.ai/v1"

from openai import OpenAI
import base64

def base64_encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

client = OpenAI(base_url=BASE_URL, api_key=os.environ["XAI_API_KEY"])

messages = [{
  "role": "user",
  "content": [
    {
      "type": "image_url",
      "image_url": { "url": f"data:image/jpg;base64,{base64_encode_image('photo.jpg')}" }
    },
    { "type": "text", "text": "Describe what you see in this image." }
  ]
}]

resp = client.chat.completions.create(
  model="grok-2-vision-latest",
  messages=messages
)

print(resp.choices[0].message.content)

6) Response formatting (JSON outputs)
Both Chat Completions and Responses support response_format style controls in the request schema:
* "json_object" for valid JSON output (legacy style)
* "json_schema" with an explicit schema for structured outputs

Example (Chat Completions) requesting JSON:
{
  "model": "grok-4",
  "messages": [{ "role": "user", "content": "Return a JSON object with keys: title, tags" }],
  "response_format": { "type": "json_object" }
}

7) Streaming
Both APIs have a stream boolean in the schema. When enabled, the server returns SSE style deltas and terminates with:
data: [DONE]

8) Optional: deferred chat completions
Chat Completions schema supports "deferred": true which returns a request id.
Fetch the completed result later:
GET /v1/chat/deferred-completion/{request_id}

9) Key documentation and machine readable specs to hand to Cursor
* OpenAPI spec (authoritative schemas and endpoint list):
  https://api.x.ai/api-docs/openapi.json
* Chat and image understanding guide:
  https://docs.x.ai/docs/guides/chat
* Models and pricing plus image input constraints:
  https://docs.x.ai/docs/models
* Multimodal cookbook example (OpenAI SDK + base64 image data URL):
  https://docs.x.ai/cookbook/examples/multimodal/structured_data_extraction
  