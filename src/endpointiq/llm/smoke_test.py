"""Smoke test / helper for Groq via LangChain."""

import os

from pydantic import BaseModel, Field


class SimpleAnalysisOutput(BaseModel):
    """Structured test output model."""

    status: str = Field(description="Status of the check (e.g. PASS, WARN, FAIL)")
    summary: str = Field(description="Short summary of the response")
    key_points: list[str] = Field(description="Key analysis points")


def run_groq_smoke_test(api_key: str | None = None) -> SimpleAnalysisOutput | None:
    """Runs a quick smoke test against Groq using LangChain ChatGroq.

    Returns parsed Pydantic output if successful.
    """
    key = api_key or os.environ.get("GROQ_API_KEY")
    if not key or key == "gsk_your_key_here":
        raise ValueError("GROQ_API_KEY is not set or is using placeholder value.")

    from langchain_core.prompts import ChatPromptTemplate
    from langchain_groq import ChatGroq
    from pydantic import SecretStr

    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0.0,
        api_key=SecretStr(key),
    )

    structured_llm = llm.with_structured_output(SimpleAnalysisOutput)

    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert API security analyst. Output structured data as requested."),
        ("human", "Perform a 1-sentence sanity check on endpoint: {endpoint_name}"),
    ])

    chain = prompt | structured_llm
    res = chain.invoke({"endpoint_name": "POST /api/v1/auth/login"})
    if isinstance(res, SimpleAnalysisOutput):
        return res
    return None
