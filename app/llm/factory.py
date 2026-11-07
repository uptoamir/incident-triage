"""Builds the LLM client from settings. Missing config never stops the app from starting."""

from app.config import Settings
from app.llm.base import LLMClient, LLMNotConfigured
from app.llm.openai_client import OpenAIChatClient


class UnconfiguredLLMClient:
    """Stands in when LLM settings are missing, so the app still starts and /search keeps working."""

    def __init__(self, settings: Settings, missing: list[str]):
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self.missing = missing

    def describe(self) -> dict:
        return {"provider": self.provider, "model": self.model, "configured": False, "missing": self.missing}

    def complete_json(self, *args, **kwargs):
        raise LLMNotConfigured(
            f"/assist needs an LLM, but it isn't configured: missing {', '.join(self.missing)}.",
            how_to_fix=[
                "set LLM_PROVIDER=openai, LLM_API_KEY=<your key>, LLM_MODEL=<model> in .env "
                "(see .env.example)",
                "for Azure: LLM_PROVIDER=azure-openai, LLM_MODEL=<deployment name>, "
                "AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_VERSION",
                "then restart: make run",
                "/search and /incidents work without it",
            ],
            details={"missing": self.missing},
        )


def build_llm_client(settings: Settings) -> LLMClient:
    missing = settings.llm_missing_vars()
    if missing:
        return UnconfiguredLLMClient(settings, missing)
    return OpenAIChatClient(settings)
