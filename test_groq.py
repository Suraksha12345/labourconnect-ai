import os
from dotenv import load_dotenv
from groq import Groq

# Load the API key from .env file
load_dotenv()

# Create a client to talk to Groq
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Send a test message to LLaMA 3
response = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[
        {
            "role": "user",
            "content": "Is 350 rupees per day a fair wage for a mason in rural Karnataka? Answer in 2 sentences."
        }
    ]
)

# Print the AI's answer
print(response.choices[0].message.content)