import os
from io import BytesIO
from google import genai
from google.genai.types import GenerateContentConfig, Modality
from PIL import Image

client = genai.Client(api_key= os.getenv("GEMINI_API_KEY"))

# 1. Generate the image
response = client.models.generate_content(
    model="gemini-2.5-flash-image",
    contents="A cinematic macro shot of a glowing mechanical fox mascot",
    config=GenerateContentConfig(
        response_modalities=[Modality.TEXT, Modality.IMAGE],
    ),
)

# 2. Extract and Save
for part in response.candidates[0].content.parts:
    if part.inline_data:
        img = Image.open(BytesIO(part.inline_data.data))
        img.save("generated_fox.png")
        
# 3. Post to your DB API
# (Example using requests to your own endpoint)
# requests.post("https://your-api.com/upload", files={'file': open('generated_fox.png', 'rb')})