"""Vision tests use generated images and in-memory HTTP transports only."""

import json

import httpx
from openai import OpenAI
from PIL import Image
import pytest

from geophotoloc.config import VisionConfig
from geophotoloc.vision import VisionAnalyzer


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "photo.jpg"
    Image.new("RGB", (120, 80), "blue").save(path)
    return path


@pytest.fixture
def extraction():
    def landmark(identifier, name, x, y):
        return dict(
            id=identifier, name=name, name_candidates=[], x=x, y=y,
            bbox=dict(x_min=x - 0.1, y_min=y - 0.1, x_max=x + 0.1, y_max=y + 0.1),
            visual_evidence=["Clearly visible outline"], confidence=None,
            identity_uncertain=True, coordinates_reliable=True,
        )
    return dict(
        landmarks=[landmark("lm_1", "Tower", 0.2, 0.3), landmark("lm_2", "Bridge", 0.8, 0.7)],
        scene_features=["river", "urban buildings"], warnings=[],
    )


@pytest.fixture
def mock_api():
    clients = []

    def make(payload=None, *, handler=None, max_retries=0):
        requests = []

        def respond(request):
            requests.append(request)
            if handler:
                return handler(request)
            return httpx.Response(200, json={
                "id": "mock_completion", "object": "chat.completion", "created": 0,
                "model": "qwen3.8-flash", "choices": [{
                    "index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(payload)},
                }],
            })

        config = VisionConfig(api_key="test-dummy-key", timeout=0.1, max_retries=max_retries)
        client = OpenAI(
            api_key=config.api_key.get_secret_value(), base_url=config.base_url,
            timeout=config.timeout, max_retries=config.max_retries,
            http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        )
        clients.append(client)
        return VisionAnalyzer(config, client), requests

    yield make
    for client in clients:
        client.close()
