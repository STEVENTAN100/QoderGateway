"""Offline regression tests; no upstream credentials or account database."""
import asyncio
import json
from pathlib import Path
import sys
import unittest

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qoder2api import responses_api as api


RAW_INPUT = 'text(await tools.exec_command({cmd: "echo hello"}));\n// 中文'
USAGE = {
    "prompt_tokens": 10,
    "completion_tokens": 12,
    "total_tokens": 22,
    "prompt_tokens_details": {"cached_tokens": 3},
    "completion_tokens_details": {"reasoning_tokens": 8},
}
TOOLS = [{
    "type": "namespace", "name": "functions", "description": "Workspace tools",
    "tools": [
        {"type": "custom", "name": "exec", "description": "Run JavaScript",
         "format": {"type": "grammar", "syntax": "lark", "definition": "start: /[\\s\\S]+/"}},
        {"type": "function", "name": "wait", "parameters": {
            "type": "object", "properties": {"cell_id": {"type": "string"}}, "required": ["cell_id"]}},
    ],
}]


def request():
    return {"model": "gfmodel", "store": False, "reasoning": {"effort": "max"}, "tools": [],
            "input": [{"type": "additional_tools", "role": "developer", "tools": TOOLS},
                      {"role": "user", "content": [{"type": "input_text", "text": "Run the tool"}]}]}


def completion():
    return {"choices": [{"message": {"role": "assistant", "content": None, "reasoning_content": "thinking",
             "tool_calls": [{"id": "call_exact", "type": "function", "function": {
                 "name": "functions__exec", "arguments": json.dumps({"input": RAW_INPUT}, ensure_ascii=False)}}]},
             "finish_reason": "tool_calls"}], "usage": USAGE}


def stream_chunk(delta=None, finish=None, usage=None):
    value = {"choices": [{"delta": delta or {}, "finish_reason": finish}]}
    if usage is not None:
        value = {"choices": [], "usage": usage}
    return "data: " + json.dumps(value, ensure_ascii=False) + "\n\n"


async def collect(payload, chunks):
    async def source():
        for chunk in chunks:
            yield chunk
    _, tools = api.to_chat(payload)
    return [json.loads(event.split("data: ", 1)[1])
            async for event in api.stream_responses(payload, StreamingResponse(source()), tools)]


class ResponsesTests(unittest.TestCase):
    def test_agent_messages_preserve_context_and_tool_history(self):
        payload = request()
        text = 'Message Type: FINAL_ANSWER\nPayload:\n已完成校验。\n  Indentation "quoted" \\ path'
        agent = {"type": "agent_message", "id": "amsg_history", "author": "/root/reviewer", "recipient": "/root",
                 "content": [{"type": "input_text", "text": text}, {"type": "input_text", "text": "Next step"}],
                 "role": "developer", "internal_chat_message_metadata_passthrough": {"turn_id": "turn_history"}}
        payload["input"] += [
            {"type": "custom_tool_call", "call_id": "call_history", "name": "exec", "namespace": "functions", "input": RAW_INPUT},
            {"type": "custom_tool_call_output", "call_id": "call_history", "output": "done"},
            agent,
            {"type": "agent_message", "author": "/root", "recipient": "/root/reviewer", "content": "Thanks"},
            {"role": "user", "content": "Continue"},
        ]
        before = json.dumps(payload, ensure_ascii=False)
        chat, _ = api.to_chat(payload)
        self.assertEqual(json.dumps(payload, ensure_ascii=False), before)
        self.assertEqual([item["role"] for item in chat["messages"]], ["user", "assistant", "tool", "user", "user", "user"])
        self.assertEqual(chat["messages"][2]["tool_call_id"], "call_history")
        converted = chat["messages"][3]["content"]
        header, body = converted.split("\n", 1)
        self.assertEqual(json.loads(header.removeprefix("Agent message ")), {"author": "/root/reviewer", "recipient": "/root"})
        self.assertEqual(body, text + "\nNext step")
        self.assertTrue(chat["messages"][4]["content"].endswith("\nThanks"))
        self.assertEqual(chat["messages"][-1]["content"], "Continue")
        self.assertEqual(chat["reasoning_effort"], "max")
        self.assertEqual([t["function"]["name"] for t in chat["tools"]], ["functions__exec", "functions__wait"])

    def test_invalid_and_encrypted_agent_messages_are_explicitly_rejected(self):
        base = {"type": "agent_message", "author": "/root/worker", "recipient": "/root",
                "content": [{"type": "input_text", "text": "Done"}]}
        for fields in ({"author": None}, {"author": " "}, {"recipient": 1}, {"recipient": ""},
                       {"content": None}, {"content": {}},
                       {"content": [{"type": "input_text", "text": 3}]},
                       {"content": [{"type": "input_image", "image_url": "x"}]},
                       {"content": [{"type": "encrypted_content", "encrypted_content": "secret"}]},
                       {"content": [*base["content"], {"type": "encrypted_content", "encrypted_content": "secret"}]}):
            with self.subTest(fields=fields), self.assertRaises(HTTPException) as caught:
                api.to_chat({**request(), "input": [{**base, **fields}]})
            self.assertEqual(caught.exception.status_code, 400)

    def test_agent_message_route_with_streaming_and_nonstreaming_tool_calls(self):
        app = FastAPI()
        observed = []
        async def handler(payload, authorization):
            observed.append(payload)
            if payload.get("stream"):
                async def source():
                    yield stream_chunk({"tool_calls": [{"index": 0, **completion()["choices"][0]["message"]["tool_calls"][0]}]})
                    yield stream_chunk(finish="tool_calls")
                    yield stream_chunk(usage=USAGE)
                    yield "data: [DONE]\n\n"
                return StreamingResponse(source())
            return completion()
        api.register_responses(app, handler)
        payload = request()
        payload["input"].insert(1, {"type": "agent_message", "author": "/root/reviewer", "recipient": "/root",
                                    "content": [{"type": "input_text", "text": "Please continue"}]})
        with TestClient(app) as client:
            for stream in (False, True):
                with self.subTest(stream=stream):
                    response = client.post("/v1/responses", json={**payload, "stream": stream})
                    self.assertEqual(response.status_code, 200)
                    result = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")][-1]["response"] if stream else response.json()
                    self.assertEqual(result["status"], "completed")
                    self.assertEqual(result["output"][-1]["input"], RAW_INPUT)
                    self.assertEqual(result["output"][-1]["call_id"], "call_exact")
                    self.assertEqual(result["usage"]["output_tokens_details"]["reasoning_tokens"], 8)
                    self.assertTrue(observed[-1]["messages"][0]["content"].endswith("\nPlease continue"))

    def test_additional_tools_and_custom_result_roundtrip(self):
        payload = request()
        chat, tools = api.to_chat(payload)
        self.assertEqual([t["function"]["name"] for t in chat["tools"]], ["functions__exec", "functions__wait"])
        self.assertIn("lark", chat["tools"][0]["function"]["description"])
        self.assertEqual(len(chat["messages"]), 1)
        result = api.from_completion(payload, completion(), tools)
        call = result["output"][-1]
        self.assertEqual((call["type"], call["name"], call["namespace"], call["call_id"]),
                         ("custom_tool_call", "exec", "functions", "call_exact"))
        self.assertEqual(call["input"], RAW_INPUT)
        self.assertEqual(result["usage"]["output_tokens_details"]["reasoning_tokens"], 8)
        payload["input"] += result["output"] + [{"type": "custom_tool_call_output", "call_id": "call_exact",
                                                  "output": [{"type": "input_text", "text": "done"}]}]
        chat, _ = api.to_chat(payload)
        self.assertEqual(json.loads(chat["messages"][-2]["tool_calls"][0]["function"]["arguments"])["input"], RAW_INPUT)
        self.assertEqual(chat["messages"][-1], {"role": "tool", "tool_call_id": "call_exact", "content": "done"})

    def test_repeated_declarations_configuration_and_choice(self):
        payload = request()
        payload["input"].insert(1, {"type": "additional_tools", "role": "developer", "tools": [{
            "type": "namespace", "name": "functions", "tools": [{"type": "custom", "name": "exec", "description": "Latest"}]}]})
        payload["input"].insert(2, {"type": "configuration_update", "reasoning": {"effort": "low"}})
        payload["tool_choice"] = {"type": "custom", "namespace": "functions", "name": "exec"}
        payload["max_output_tokens"] = 64
        chat, _ = api.to_chat(payload)
        self.assertEqual(len(chat["tools"]), 2)
        self.assertTrue(chat["tools"][0]["function"]["description"].startswith("Latest"))
        self.assertEqual(chat["reasoning_effort"], "max")
        self.assertEqual(chat["max_tokens"], 64)
        self.assertEqual(chat["tool_choice"], {"type": "function", "function": {"name": "functions__exec"}})
        payload.pop("reasoning")
        self.assertEqual(api.to_chat(payload)[0]["reasoning_effort"], "low")
        payload = request()
        payload["input"][0]["type"] = "tool_search_output"
        self.assertEqual(len(api.to_chat(payload)[0]["tools"]), 2)

    def test_six_efforts_preserved(self):
        for model in ("gfmodel", "gmodel"):
            for effort in ("none", "low", "medium", "high", "xhigh", "max"):
                payload = {**request(), "model": model, "reasoning": {"effort": effort}}
                self.assertEqual(api.to_chat(payload)[0]["reasoning_effort"], effort)

    def test_namespaces_do_not_collide(self):
        definitions = [{"type": "namespace", "name": ns, "tools": [
            {"type": "function", "name": "run", "parameters": {"type": "object"}}]} for ns in ("a", "b")]
        tools = api.Tools(definitions)
        self.assertNotEqual(tools.resolve("run", "a").alias, tools.resolve("run", "b").alias)
        with self.assertRaises(HTTPException):
            tools.resolve("run")

    def test_streaming_custom_raw_input_event_sequence(self):
        args = json.dumps({"input": RAW_INPUT}, ensure_ascii=False)
        chunks = [stream_chunk({"reasoning_content": "thinking"})]
        for n, part in enumerate((args[:6], args[6:22], args[22:])):
            call = {"index": 0, "function": {"arguments": part}}
            if n == 0:
                call["id"] = "call_exact"
                call["function"]["name"] = "functions__exec"
            chunks.append(stream_chunk({"tool_calls": [call]}))
        chunks += [stream_chunk(finish="tool_calls"), stream_chunk(usage=USAGE), "data: [DONE]\n\n"]
        events = asyncio.run(collect(request(), chunks))
        self.assertEqual([e["sequence_number"] for e in events], list(range(len(events))))
        self.assertEqual(events[-1]["type"], "response.completed")
        deltas = [e["delta"] for e in events if e["type"] == "response.custom_tool_call_input.delta"]
        self.assertEqual("".join(deltas), RAW_INPUT)
        final = events[-1]["response"]
        self.assertEqual(final["output"][-1]["call_id"], "call_exact")
        self.assertEqual(final["output"][-1]["namespace"], "functions")
        self.assertEqual(final["usage"]["output_tokens_details"]["reasoning_tokens"], 8)
        self.assertEqual(final["output"][0]["summary"][0]["text"], "thinking")

    def test_streaming_function_and_length(self):
        chunks = [stream_chunk({"content": "partial"}), stream_chunk({"tool_calls": [{
            "index": 0, "id": "call_wait", "function": {"name": "functions__wait", "arguments": '{"cell_id":"job"}'}}]}),
            stream_chunk(finish="length"), stream_chunk(usage=USAGE)]
        events = asyncio.run(collect(request(), chunks))
        self.assertEqual(events[-1]["type"], "response.incomplete")
        self.assertEqual(events[-1]["response"]["incomplete_details"], {"reason": "max_output_tokens"})
        call = events[-1]["response"]["output"][-1]
        self.assertEqual((call["type"], call["name"], call["namespace"]), ("function_call", "wait", "functions"))
        self.assertEqual(call["arguments"], '{"cell_id":"job"}')

    def test_invalid_custom_input_fails_stream(self):
        events = asyncio.run(collect(request(), [stream_chunk({"tool_calls": [{"index": 0, "id": "bad",
            "function": {"name": "functions__exec", "arguments": '{"input":'}}]})]))
        self.assertEqual(events[-1]["type"], "response.failed")
        self.assertTrue(events[-1]["response"]["error"])

    def test_route_auth_and_unsupported_items(self):
        app = FastAPI()
        async def handler(payload, authorization):
            if authorization != "Bearer test":
                raise HTTPException(401)
            return completion()
        api.register_responses(app, handler)
        with TestClient(app) as client:
            self.assertEqual(client.post("/v1/responses", json=request()).status_code, 401)
            result = client.post("/v1/responses", json=request(), headers={"Authorization": "Bearer test"})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["output"][-1]["input"], RAW_INPUT)
            bad = [
                {"previous_response_id": "resp_missing"}, {"store": True},
                {"tools": [{"type": "web_search"}]},
                {"input": [{"type": "additional_tools", "role": "user", "tools": TOOLS}]},
                {"input": [{"type": "additional_tools", "role": "developer", "tools": {}}]},
                {"input": [{"type": "configuration_update", "reasoning": "invalid"}]},
                {"input": [{"role": "user", "content": [{"type": "input_image", "image_url": "x"}]}]},
            ]
            for fields in bad:
                with self.subTest(fields=fields):
                    response = client.post("/v1/responses", json={**request(), **fields}, headers={"Authorization": "Bearer test"})
                    self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
