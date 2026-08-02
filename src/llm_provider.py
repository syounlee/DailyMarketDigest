import os

# For Ollama, different roles can use different local models (e.g. a Korean-
# specialized model for translation, a stronger English model for the final
# write-up). Hosted providers (Claude/Gemini) ignore role - one strong model
# already handles both languages well, so splitting adds no value there.
_OLLAMA_ROLE_DEFAULTS = {
    "kr": ("OLLAMA_MODEL_KR", "exaone3.5:7.8b"),
    "en": ("OLLAMA_MODEL_EN", "llama3.1:8b"),
    "default": ("OLLAMA_MODEL", "llama3"),
}


def get_chat_model(role: str = "default"):
    """Return a LangChain chat model instance selected by the LLM_PROVIDER env var.

    `role` only affects local Ollama model selection ("kr", "en", or "default"),
    letting a pipeline use two different local models in sequence.
    """
    provider = os.environ.get("LLM_PROVIDER", "claude").lower()

    if provider == "claude":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model="claude-sonnet-5")

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model="gemini-2.5-flash")

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        env_var, default_model = _OLLAMA_ROLE_DEFAULTS.get(role, _OLLAMA_ROLE_DEFAULTS["default"])
        return ChatOllama(
            model=os.environ.get(env_var, default_model),
            base_url=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        )

    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r} (expected claude, gemini, or ollama)")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    for role in ("kr", "en"):
        model = get_chat_model(role)
        print(f"[{role}] {model.invoke('Say hello in one short sentence.').content}")
