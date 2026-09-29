from unittest.mock import Mock

import pytest

from ai_marketplace_monitor import ai
from ai_marketplace_monitor.ai import (
    AIResponse,
    DeepSeekBackend,
    GeminiBackend,
    OllamaBackend,
    OllamaConfig,
    OpenAIBackend,
)
from ai_marketplace_monitor.facebook import FacebookItemConfig, FacebookMarketplaceConfig
from ai_marketplace_monitor.listing import Listing


@pytest.mark.skipif(True, reason="Condition met, skipping this test")
def test_ai(
    ollama_config: OllamaConfig,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    listing: Listing,
) -> None:
    ai = OllamaBackend(ollama_config)
    # ai.config = ollama_config
    res = ai.evaluate(listing, item_config, marketplace_config)
    assert res.score >= 1 and res.score <= 5


def test_prompt(
    ollama: OllamaBackend,
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
) -> None:
    prompt = ollama.get_prompt(listing, item_config, marketplace_config)
    assert item_config.name in prompt
    assert (item_config.description or "something weird") in prompt
    assert str(item_config.min_price) in prompt
    assert str(item_config.max_price) in prompt

    assert listing.title in prompt
    assert listing.condition in prompt
    assert listing.price in prompt
    assert listing.post_url in prompt


def test_extra_prompt(
    ollama: OllamaBackend,
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
) -> None:
    marketplace_config.extra_prompt = "This is an extra prompt"
    prompt = ollama.get_prompt(listing, item_config, marketplace_config)
    assert "extra prompt" in prompt
    #
    item_config.extra_prompt = "This overrides marketplace prompt"
    prompt = ollama.get_prompt(listing, item_config, marketplace_config)
    assert "extra prompt" not in prompt
    assert "overrides marketplace prompt" in prompt
    #
    assert "Great deal: Fully matches" in prompt
    item_config.rating_prompt = "something else"
    prompt = ollama.get_prompt(listing, item_config, marketplace_config)
    assert "Great deal: Fully matches" not in prompt
    assert "something else" in prompt
    #
    assert "Evaluate how well this listing" in prompt
    marketplace_config.prompt = "myprompt"
    prompt = ollama.get_prompt(listing, item_config, marketplace_config)
    assert "Evaluate how well this listing" not in prompt
    assert "myprompt" in prompt


@pytest.mark.parametrize(
    ("backend_class", "model"),
    [
        (OpenAIBackend, "nvidia/nemotron-3.5-lightning-30b-a3b"),
        (OpenAIBackend, "mistralai/mistral-nemotron"),
        (OpenAIBackend, None),
        (DeepSeekBackend, None),
        (GeminiBackend, None),
        (OllamaBackend, "llama3.1:8b"),
    ],
)
@pytest.mark.parametrize("retry", [False, True])
def test_model_generation_parameters(
    backend_class: type[OpenAIBackend],
    model: str | None,
    retry: bool,
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = backend_class(
        backend_class.get_config(
            name="test",
            api_key="test-key",
            model=model,
            base_url="https://example.com/v1",
            max_retries=2,
        )
    )
    client = Mock()
    response = Mock()
    response.choices = [Mock(message=Mock(content="Rating 4: Good value for the price"))]
    client.chat.completions.create.side_effect = (
        [RuntimeError("temporary failure"), response] if retry else [response]
    )
    monkeypatch.setattr(backend, "connect", lambda: setattr(backend, "client", client))
    monkeypatch.setattr(AIResponse, "from_cache", Mock(return_value=None))
    save = Mock()
    monkeypatch.setattr(AIResponse, "to_cache", save)
    sleep = Mock()
    monkeypatch.setattr(ai.time, "sleep", sleep)
    prompt = backend.get_prompt(listing, item_config, marketplace_config)

    result = backend.evaluate(listing, item_config, marketplace_config)

    expected = {
        "model": model or backend.default_model,
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful assistant that can confirm if a user's search criteria matches the item he is interested in.",
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }
    if model == "nvidia/nemotron-3.5-lightning-30b-a3b":
        expected.update(
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            max_tokens=1024,
        )
    assert client.chat.completions.create.call_count == (2 if retry else 1)
    for call in client.chat.completions.create.call_args_list:
        assert call.args == ()
        assert call.kwargs == expected
    assert result.score == 4
    assert result.comment == "Good value for the price"
    save.assert_called_once_with(listing, item_config, marketplace_config)
    if retry:
        sleep.assert_called_once_with(5)
    else:
        sleep.assert_not_called()


def test_nemotron_cached_rating_skips_request(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = OpenAIBackend(
        OpenAIBackend.get_config(
            name="nvidia",
            api_key="test-key",
            model="nvidia/nemotron-3.5-lightning-30b-a3b",
        )
    )
    cached = AIResponse(4, "Previously evaluated")
    monkeypatch.setattr(AIResponse, "from_cache", Mock(return_value=cached))
    connect = Mock()
    monkeypatch.setattr(backend, "connect", connect)
    assert backend.evaluate(listing, item_config, marketplace_config) is cached
    connect.assert_not_called()
