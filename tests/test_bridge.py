"""Exercise wire conversion with isolated dependencies and no database."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest

SRC = Path(__file__).resolve().parents[1] / "src" / "qoder2api"
PACKAGE = "_gateway_test_runtime"
package = ModuleType(PACKAGE)
package.__path__ = [str(SRC)]
sys.modules[PACKAGE] = package
auth = ModuleType(PACKAGE + ".auth")
auth.SessionContext = object
auth.bearer_headers = lambda *args: {}
env = ModuleType(PACKAGE + ".env")
env.httpx_client_kwargs = lambda: {}
sys.modules[auth.__name__] = auth
sys.modules[env.__name__] = env
spec = importlib.util.spec_from_file_location(PACKAGE + ".bridge", SRC / "bridge.py")
bridge = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bridge
spec.loader.exec_module(bridge)

USAGE = {"prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16,
         "completion_tokens_details": {"reasoning_tokens": 5}, "prompt_tokens_details": {"cached_tokens": 3}}
SESSION = SimpleNamespace(identity=SimpleNamespace(user_type="personal_standard"))


def wire(obj):
    return "data: " + json.dumps({"body": json.dumps(obj, ensure_ascii=False)}, ensure_ascii=False)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.original = bridge.qoder_stream_lines

    def tearDown(self):
        bridge.qoder_stream_lines = self.original

    def replay(self, events):
        async def upstream(session, body, model):
            for line in events:
                yield line
        bridge.qoder_stream_lines = upstream

    def test_actual_usage_reasoning_finish_and_stream_options(self):
        self.replay([
            wire({"choices": [{"delta": {"role": "assistant", "reasoning_content": "think", "content": "A"}}]}),
            wire({"choices": [{"delta": {}, "finish_reason": "length"}], "usage": {**USAGE, "credits": 9}}),
            wire({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16}}),
            "data: [DONE]",
        ])
        req = {"model": "gfmodel", "reasoning_effort": "max", "messages": [{"role": "user", "content": "test"}]}
        result = asyncio.run(bridge.complete_openai_response(req, SESSION))
        self.assertEqual(result["usage"], USAGE)
        self.assertEqual(result["choices"][0]["message"]["reasoning_content"], "think")
        self.assertEqual(result["choices"][0]["message"]["content"], "A")
        self.assertEqual(result["choices"][0]["finish_reason"], "length")
        async def collect(payload):
            return [line async for line in bridge.stream_openai_response(payload, SESSION)]
        for include in (False, True):
            lines = asyncio.run(collect({**req, "stream_options": {"include_usage": include}}))
            self.assertEqual(lines[-1], "data: [DONE]\n\n")
            chunks = [json.loads(line[5:]) for line in lines[:-1]]
            self.assertEqual("".join(c["delta"].get("reasoning_content", "") for x in chunks for c in x["choices"]), "think")
            self.assertEqual("".join(c["delta"].get("content", "") for x in chunks for c in x["choices"]), "A")
            usage_chunks = [x for x in chunks if not x["choices"]]
            self.assertEqual(len(usage_chunks), int(include))
            if include:
                self.assertEqual(chunks[-1]["usage"], USAGE)
            for chunk in chunks:
                if chunk["choices"]:
                    self.assertEqual("usage" in chunk, include)
                    self.assertIsNone(chunk.get("usage"))

    def test_missing_usage_not_fabricated(self):
        self.replay([wire({"choices": [{"delta": {"content": "A"}, "finish_reason": "stop"}]})])
        result = asyncio.run(bridge.complete_openai_response({"model": "gfmodel"}, SESSION))
        self.assertNotIn("usage", result)

    def test_reasoning_and_fragmented_tool_arguments(self):
        self.replay([
            wire({"choices": [{"delta": {"reasoning_content": "think", "tool_calls": [{"index": 0, "id": "c1",
                "type": "function", "function": {"name": "run", "arguments": '{"x":'}}]}}]}),
            wire({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]}, "finish_reason": "tool_calls"}]}),
        ])
        req = {"model": "gfmodel", "tools": [{"type": "function", "function": {"name": "run"}}]}
        result = asyncio.run(bridge.complete_openai_response(req, SESSION))
        message = result["choices"][0]["message"]
        self.assertIsNone(message["content"])
        self.assertEqual(message["reasoning_content"], "think")
        self.assertEqual(message["tool_calls"][0]["function"]["arguments"], '{"x":1}')
        self.assertEqual(result["choices"][0]["finish_reason"], "tool_calls")

    def test_effort_and_tool_options_not_rewritten(self):
        for model in ("gfmodel", "gmodel"):
            for effort in ("none", "low", "medium", "high", "xhigh", "max", " Max ", "", None):
                body, _, _ = bridge.build_qoder_body({"model": model, "reasoning_effort": effort,
                    "max_tokens": 64, "tool_choice": "required", "parallel_tool_calls": False}, SESSION)
                self.assertEqual(body["parameters"], {"max_tokens": 64, "reasoning_effort": effort})
                self.assertEqual(body["tool_choice"], "required")
                self.assertFalse(body["parallel_tool_calls"])
        self.assertEqual(bridge.build_qoder_body({}, SESSION)[0]["parameters"]["reasoning_effort"], "none")

    def test_provider_error_is_not_empty_success(self):
        for obj in ({"error": {"code": "1210", "message": "unsupported"}},
                    {"code": "provider_error", "details": "unsupported effort"}):
            self.replay([wire(obj)])
            with self.assertRaises(RuntimeError):
                asyncio.run(bridge.complete_openai_response({"model": "gfmodel"}, SESSION))
        self.assertTrue(bridge.extract_delta("null").is_empty)
        self.assertTrue(bridge.extract_delta('{"body":"null"}').is_empty)


if __name__ == "__main__":
    unittest.main()
