from unittest.mock import Mock, patch

from app.gigachat_client import get_access_token, request_completion


@patch("app.gigachat_client.httpx.post")
def test_get_access_token_uses_basic_authorization_and_personal_scope(post):
    response = Mock()
    response.json.return_value = {"access_token": "short-lived-token"}
    post.return_value = response

    token = get_access_token("saved-key", scope="GIGACHAT_API_PERS")

    assert token == "short-lived-token"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Basic saved-key"
    assert post.call_args.kwargs["data"] == {"scope": "GIGACHAT_API_PERS"}
    assert post.call_args.kwargs["headers"]["RqUID"]


@patch("app.gigachat_client.httpx.post")
def test_request_completion_exchanges_token_then_uses_bearer_token(post):
    oauth_response = Mock()
    oauth_response.json.return_value = {"access_token": "short-lived-token"}
    completion_response = Mock()
    completion_response.json.return_value = {
        "choices": [{"message": {"content": "{}"}}],
        "model": "GigaChat",
    }
    post.side_effect = [oauth_response, completion_response]

    result = request_completion(
        {"model": "GigaChat", "messages": []},
        credentials="Basic already-prefixed",
    )

    assert result["model"] == "GigaChat"
    assert post.call_count == 2
    assert post.call_args_list[0].kwargs["headers"]["Authorization"] == "Basic already-prefixed"
    assert post.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer short-lived-token"
