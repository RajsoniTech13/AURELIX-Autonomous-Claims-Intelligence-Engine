import os
import json
import re
from typing import Type, TypeVar, Dict, Any, List
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from backend.app.config import settings

T = TypeVar("T", bound=BaseModel)

def clean_json_string(s: str) -> str:
    # Helper to strip markdown formatting around JSON
    s = s.strip()
    if s.startswith("```json"):
        s = s[7:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()

def get_llm():
    if settings.OPENAI_API_KEY:
        return ChatOpenAI(model="gpt-4o-mini", temperature=0.1, openai_api_key=settings.OPENAI_API_KEY)
    return None

def call_structured_llm(
    prompt_template: str,
    variables: Dict[str, Any],
    response_model: Type[T],
    fallback_parser_func
) -> T:
    llm = get_llm()
    if llm:
        try:
            # Build prompt
            prompt = ChatPromptTemplate.from_template(prompt_template)
            chain = prompt | llm.with_structured_output(response_model)
            result = chain.invoke(variables)
            return result
        except Exception as e:
            print(f"Error calling live LLM, falling back to simulated parser: {e}")
            # Fall back to simulated parser on failure
    
    # Fallback to local parsing logic (Mock Mode)
    return fallback_parser_func(variables, response_model)
