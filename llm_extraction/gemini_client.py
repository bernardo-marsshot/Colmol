# llm_extraction/gemini_client.py
import os
import json
from google import genai
from google.genai import types

def call_gemini(system_prompt: str, user_prompt: str, model: str = "gemini-2.5-flash"):
    """
    Chama Google Gemini API com JSON estruturado.
    Usa modelo Flash (gratuito até 15 req/min, 1500 req/dia).
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não está definida (configura nas Secrets do Replit)")
    
    client = genai.Client(api_key=api_key)
    
    try:
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Content(role="user", parts=[types.Part(text=user_prompt)])
            ],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )
        
        raw_json = response.text
        if not raw_json:
            raise ValueError("Resposta vazia do Gemini")
        
        return json.loads(raw_json)
    
    except Exception as e:
        raise RuntimeError(f"Erro ao chamar Gemini API: {e}")
