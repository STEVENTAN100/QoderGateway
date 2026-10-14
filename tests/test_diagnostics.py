"""Check trace metadata without recording credentials or tool contents."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qoder2api import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_responses_trace_preserves_output_and_excludes_sensitive_text(self):
        private = "PRIVATE_VALUE_SENTINEL"
        input_text = "text('" + private + "');"
        call = {"id": "ctc_test", "type": "custom_tool_call", "call_id": "call_test",
                "name": "exec", "namespace": "functions", "status": "completed", "input": input_text}
        final = {"object": "response", "status": "completed", "output": [call],
                 "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}}
        payload = {"model": "gfmodel", "stream": True, "reasoning": {"effort": "max"}, "tools": [],
                   "input": [{"type": "additional_tools", "role": "developer", "tools": [{
                       "type": "namespace", "name": "functions", "description": private, "tools": [{
                           "type": "custom", "name": "exec", "description": private, "format": {"type": "text"}}]}]},
                       {"role": "user", "content": private}]}
        events = [{"type": "response.output_item.done", "item": call},
                  {"type": "response.completed", "response": final}]
        encoded = ["event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n" for event in events]
        app = FastAPI()
        app.add_middleware(diagnostics.ToolTraceMiddleware)
        @app.post("/v1/responses")
        async def body_handler(payload: dict):
            async def stream():
                for piece in encoded:
                    yield piece
            return StreamingResponse(stream(), media_type="text/event-stream")
        previous_logger = diagnostics.LOGGER
        diagnostics.LOGGER = None
        try:
            with tempfile.TemporaryDirectory() as directory, patch.object(Path, "home", return_value=Path(directory)):
                # The application creates .qoder when its database initializes;
                # this isolated test deliberately does not import that module.
                (Path(directory) / ".qoder").mkdir()
                with TestClient(app) as client:
                    response = client.post("/v1/responses", json=payload, headers={"Authorization": "Bearer " + private})
                self.assertEqual(response.text, "".join(encoded))
                trace = response.headers["x-qoder-trace-id"]
                log = (Path(directory) / ".qoder/diagnostics/tool-trace.jsonl").read_text()
                self.assertNotIn(private, log)
                records = [json.loads(line) for line in log.splitlines()]
                self.assertEqual({record["trace_id"] for record in records}, {trace})
                self.assertEqual({record["stage"] for record in records}, {"client_request", "client_response"})
                inbound = next(record for record in records if record["stage"] == "client_request")
                self.assertEqual(inbound["input_tool_declarations"][0]["tools"][0]["name"], "exec")
                self.assertEqual(inbound["input_tool_declarations"][0]["tools"][0]["namespace"], "functions")
                outbound = next(record for record in records if record["stage"] == "client_response")
                self.assertEqual(outbound["tool_names"], ["functions.exec"])
                self.assertEqual(outbound["tool_argument_chars"], len(input_text))
                self.assertTrue(outbound["done"])
                self.assertIsNone(diagnostics.TRACE.get())
                for handler in diagnostics.LOGGER.handlers[:]:
                    handler.close()
                    diagnostics.LOGGER.removeHandler(handler)
        finally:
            diagnostics.LOGGER = previous_logger


if __name__ == "__main__":
    unittest.main()
