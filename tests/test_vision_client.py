import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from geophotoloc.config import VisionConfig
from geophotoloc.models import VisionExtractionResult
from geophotoloc.vision import VisionAnalyzer, VisionAPIError, VisionResponseError


def test_request_and_structured_result(mock_api, extraction, photo):
    analyzer, requests = mock_api(extraction)
    result = analyzer.analyze(photo)
    assert isinstance(result, VisionExtractionResult)
    assert len(result.landmarks) == 2
    assert len(result.relations) == 4
    assert result.image.processed_size.width == 120
    assert any("uncalibrated" in warning for warning in result.warnings)
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    data = json.loads(request.content)
    assert data["model"] == "qwen3.8-flash"
    assert data["response_format"] == {"type": "json_object"}
    assert data["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert request.extensions["timeout"]["read"] == 0.1


@pytest.mark.parametrize("status,message", [
    (401, "authentication"), (429, "rate limit"), (400, "HTTP 400"), (500, "HTTP 500"),
])
def test_api_errors_sanitized(mock_api, photo, status, message):
    analyzer, requests = mock_api(handler=lambda request: httpx.Response(
        status, json={"error": {"message": "sensitive-test-key response-body", "type": "test"}},
    ))
    with pytest.raises(VisionAPIError, match=message) as caught:
        analyzer.analyze(photo)
    assert "sensitive-test-key" not in str(caught.value)
    assert len(requests) == 1


@pytest.mark.parametrize("error,message", [
    (httpx.ReadTimeout, "timed out"), (httpx.ConnectError, "Cannot connect"),
])
def test_network_errors(mock_api, photo, error, message):
    def handler(request):
        raise error("secret-test-key", request=request)
    analyzer, requests = mock_api(handler=handler)
    with pytest.raises(VisionAPIError, match=message) as caught:
        analyzer.analyze(photo)
    assert len(requests) == 1
    assert "secret-test-key" not in str(caught.value)


def test_bounded_retry_on_rate_limit(mock_api, photo):
    analyzer, requests = mock_api(
        handler=lambda request: httpx.Response(
            429, headers={"retry-after-ms": "1"}, json={"error": {"message": "rate limit"}},
        ), max_retries=1,
    )
    with pytest.raises(VisionAPIError, match="rate limit"):
        analyzer.analyze(photo)
    assert len(requests) == 2


def test_empty_recognition_is_valid(mock_api, photo):
    analyzer, _ = mock_api(dict(landmarks=[], scene_features=["sky"], warnings=[]))
    result = analyzer.analyze(photo)
    assert result.landmarks == []
    assert result.relations == []
    assert result.scene_features == ["sky"]
    assert any("No recognizable" in warning for warning in result.warnings)


def test_bad_response_not_retried(mock_api, photo):
    analyzer, requests = mock_api(dict(landmarks=[{"id": "invalid"}], scene_features=[], warnings=[]))
    with pytest.raises(VisionResponseError):
        analyzer.analyze(photo)
    assert len(requests) == 1


@pytest.mark.parametrize("body", [{}, {"choices": [{}]}, {"choices": [{"finish_reason": "stop"}]}])
def test_malformed_api_envelope(mock_api, photo, body):
    analyzer, requests = mock_api(handler=lambda request: httpx.Response(200, json=body))
    with pytest.raises(VisionResponseError):
        analyzer.analyze(photo)
    assert len(requests) == 1


@pytest.mark.parametrize("choices", [
    [],
    [SimpleNamespace(finish_reason="length", message=SimpleNamespace(refusal=None, content="{}"))],
    [SimpleNamespace(finish_reason="stop", message=SimpleNamespace(refusal="refused", content=None))],
    [SimpleNamespace(finish_reason="stop", message=SimpleNamespace(refusal=None, content=None))],
])
def test_incomplete_or_empty_response(photo, choices):
    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(choices=choices)
    with pytest.raises(VisionResponseError):
        VisionAnalyzer(VisionConfig(api_key="dummy"), client).analyze(photo)


def test_sdk_receives_config(monkeypatch, photo, extraction):
    from geophotoloc.vision import client as module
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
        finish_reason="stop", message=SimpleNamespace(refusal=None, content=json.dumps(extraction)),
    )])
    factory = Mock(return_value=client)
    monkeypatch.setattr(module, "OpenAI", factory)
    config = VisionConfig(api_key="test-only", timeout=15, max_retries=1)
    assert len(VisionAnalyzer(config).analyze(photo).landmarks) == 2
    factory.assert_called_once_with(
        api_key="test-only", base_url=config.base_url, timeout=15, max_retries=1,
    )
    client.__exit__.assert_called_once()
