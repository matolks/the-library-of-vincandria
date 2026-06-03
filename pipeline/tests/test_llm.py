from __future__ import annotations

from dataclasses import dataclass

from pipeline import llm


@dataclass
class _Usage:
    input_tokens: int = 10
    output_tokens: int = 20
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class _TextBlock:
    text: str
    type: str = "text"


@dataclass
class _ToolUseBlock:
    input: dict
    name: str = "emit_blocks"
    type: str = "tool_use"


@dataclass
class _Response:
    content: list[_TextBlock]
    usage: _Usage
    model: str = "claude-sonnet-4-6"


class _Messages:
    def __init__(self) -> None:
        self.last_request = None

    def create(self, **request):
        self.last_request = request
        if "tools" in request:
            return _Response(
                content=[_ToolUseBlock({"blocks": []})],
                usage=_Usage(),
            )
        return _Response(
            content=[_TextBlock('{"blocks": []}')],
            usage=_Usage(),
        )


class _Client:
    def __init__(self) -> None:
        self.messages = _Messages()


def test_call_llm_can_use_json_schema_output_config():
    client = _Client()

    result = llm.call_llm("system", "user", client=client, structured_json=True)

    assert result.blocks == []
    assert client.messages.last_request["tools"][0]["name"] == "emit_blocks"
    assert client.messages.last_request["tools"][0]["input_schema"] == (
        llm.BLOCKS_JSON_SCHEMA
    )
    assert client.messages.last_request["tool_choice"] == {
        "type": "tool",
        "name": "emit_blocks",
    }


def test_call_llm_omits_json_schema_output_config_by_default():
    client = _Client()

    llm.call_llm("system", "user", client=client)

    assert "tools" not in client.messages.last_request
    assert "tool_choice" not in client.messages.last_request
