import os
from openai import OpenAI
from deepeval.models.base_model import DeepEvalBaseLLM

class GroqJudge(DeepEvalBaseLLM):
    def __init__(self, model="openai/gpt-oss-120b"):
        self.model_name = model
        self.client = OpenAI(
            api_key=os.environ["GROQ_API_KEY"],
            base_url="https://api.groq.com/openai/v1"
        )

    def load_model(self):
        return self.client

    def generate(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    async def a_generate(self, prompt: str) -> str:
        return self.generate(prompt)

    def get_model_name(self):
        return self.model_name