"""Metadata-only tool tracing. Never persist prompts, arguments or credentials."""
import collections
import contextvars
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import time
import uuid
from datetime import datetime, timezone

TRACE = contextvars.ContextVar("qoder_trace", default=None)
LOGGER = None


def label(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:/ -]{1,100}", value):
        return value
    return "nonstandard:" + hashlib.sha256(str(value).encode()).hexdigest()[:12]


def emit(stage, **fields):
    global LOGGER
    try:
        trace = TRACE.get()
        if trace is None:
            return
        if LOGGER is None:
            directory = Path.home() / ".qoder" / "diagnostics"
            directory.mkdir(mode=0o700, exist_ok=True)
            path = directory / "tool-trace.jsonl"
            fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            os.close(fd)
            os.chmod(path, 0o600)
            logger = logging.getLogger("qoder.tool_trace")
            logger.setLevel(logging.INFO)
            logger.propagate = False
            handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3)
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
            LOGGER = logger
        LOGGER.info(json.dumps({"time_utc": datetime.now(timezone.utc).isoformat(), "trace_id": trace, "stage": stage, **fields}, ensure_ascii=False))
    except Exception:
        pass


def tool_metadata(tools):
    result = []
    for tool in tools if isinstance(tools, list) else []:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "namespace":
            for entry in tool_metadata(tool.get("tools")):
                result.append({**entry, "namespace": label(tool.get("name"))})
            continue
        function = tool.get("function") or {}
        if not isinstance(function, dict):
            function = {}
        schema = function.get("parameters") or tool.get("parameters") or {}
        props = schema.get("properties") or {} if isinstance(schema, dict) else {}
        result.append({"type": label(tool.get("type")), "name": label(function.get("name") or tool.get("name")), "schema_type": label(schema.get("type")) if isinstance(schema, dict) else None, "argument_keys": [label(k) for k in props] if isinstance(props, dict) else [], "format_type": label((tool.get("format") or {}).get("type")) if isinstance(tool.get("format"), dict) else None})
    return result


def request_metadata(payload):
    messages = payload.get("messages") or []
    history = []
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        calls = message.get("tool_calls") or []
        history.append({"role": label(message.get("role")), "content_chars": len(str(message.get("content") or "")), "reasoning_present": bool(message.get("reasoning_content")), "tool_names": [label((c.get("function") or {}).get("name") or c.get("name")) for c in calls if isinstance(c, dict)], "tool_result_id_present": bool(message.get("tool_call_id"))})
    options = payload.get("stream_options") or {}
    choice = payload.get("tool_choice")
    if "input" in payload:
        incoming = payload.get("input")
        declarations = [{"input_index": index, "type": label(item.get("type")), "tools": tool_metadata(item.get("tools"))} for index, item in enumerate(incoming) if isinstance(item, dict) and item.get("type") in ("additional_tools", "tool_search_output")] if isinstance(incoming, list) else []
        agents = []
        for index, item in enumerate(incoming if isinstance(incoming, list) else []):
            if not isinstance(item, dict) or item.get("type") != "agent_message":
                continue
            content = item.get("content")
            parts = [part for part in content if isinstance(part, dict)] if isinstance(content, list) else []
            agents.append({"input_index": index, "author": label(item.get("author")), "recipient": label(item.get("recipient")), "content_types": [label(part.get("type")) for part in parts] if isinstance(content, list) else ["text"] if isinstance(content, str) else [], "content_chars": len(content) if isinstance(content, str) else sum(len(part["text"]) for part in parts if isinstance(part.get("text"), str))})
        return {"model": label(payload.get("model")), "stream": bool(payload.get("stream")), "reasoning_effort": label((payload.get("reasoning") or {}).get("effort")), "tools": tool_metadata(payload.get("tools")), "input_tool_declarations": declarations, "input_agent_messages": agents, "input_types": [label(item.get("type", "message")) for item in incoming if isinstance(item, dict)] if isinstance(incoming, list) else ["text"], "store": payload.get("store"), "tool_choice": label(choice) if not isinstance(choice, dict) else label(choice.get("type"))}
    return {"model": label(payload.get("model")), "stream": bool(payload.get("stream")), "reasoning_effort": label(payload.get("reasoning_effort")), "effort_field_present": "reasoning_effort" in payload, "tool_choice": label(choice) if not isinstance(choice, dict) else {"type": label(choice.get("type")), "name": label((choice.get("function") or {}).get("name") or choice.get("name"))}, "parallel_tool_calls": payload.get("parallel_tool_calls") if isinstance(payload.get("parallel_tool_calls"), bool) else None, "include_usage": bool(options.get("include_usage")) if isinstance(options, dict) else False, "tools": tool_metadata(payload.get("tools")), "messages": history}


class ResponseSummary:
    def __init__(self):
        self.events = 0
        self.tool_events = 0
        self.names = set()
        self.argument_chars = 0
        self.reasoning_chars = 0
        self.content_chars = 0
        self.finish = set()
        self.usage_events = 0
        self.errors = 0
        self.done = False
        self.text_tool_prefix = False

    def observe(self, obj):
        if not isinstance(obj, dict):
            return
        if isinstance(obj.get("body"), str):
            try:
                obj = json.loads(obj["body"])
            except ValueError:
                return
        if not isinstance(obj, dict):
            return
        self.events += 1
        if obj.get("object") == "response":
            self.observe_responses(obj)
            return
        kind = obj.get("type", "")
        if kind.startswith("response."):
            if kind == "response.output_item.done":
                self.observe_responses({"output": [obj.get("item") or {}]})
            elif kind in ("response.completed", "response.incomplete", "response.failed"):
                final = obj.get("response") or {}
                self.done = True
                self.usage_events += isinstance(final.get("usage"), dict)
                self.errors += kind == "response.failed"
                self.finish.add(final.get("status", "unknown"))
            return
        if obj.get("error") or obj.get("code") == "provider_error":
            self.errors += 1
        if isinstance(obj.get("usage"), dict):
            self.usage_events += 1
        for choice in obj.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            if choice.get("finish_reason"):
                self.finish.add(label(choice["finish_reason"]))
            delta = choice.get("delta") or choice.get("message") or {}
            if not isinstance(delta, dict):
                continue
            content = delta.get("content") or ""
            self.content_chars += len(content) if isinstance(content, str) else 0
            self.text_tool_prefix |= isinstance(content, str) and content.lstrip().startswith("Tool calls:")
            self.reasoning_chars += len(delta.get("reasoning_content") or "")
            for call in delta.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                self.tool_events += 1
                function = call.get("function") or {}
                if function.get("name"):
                    self.names.add(label(function["name"]))
                self.argument_chars += len(function.get("arguments") or "")

    def observe_responses(self, obj):
        if isinstance(obj.get("usage"), dict):
            self.usage_events += 1
        for item in obj.get("output") or []:
            kind = item.get("type")
            if kind in ("function_call", "custom_tool_call"):
                self.tool_events += 1
                self.names.add(label((item.get("namespace") + "." if item.get("namespace") else "") + item.get("name", "")))
                self.argument_chars += len(item.get("input") or item.get("arguments") or "")
            elif kind == "message":
                self.content_chars += sum(len(part.get("text") or "") for part in item.get("content") or [])
            elif kind == "reasoning":
                self.reasoning_chars += sum(len(part.get("text") or "") for part in item.get("summary") or [])

    def fields(self):
        return {"events": self.events, "tool_call_events": self.tool_events, "tool_names": sorted(self.names), "tool_argument_chars": self.argument_chars, "reasoning_chars": self.reasoning_chars, "content_chars": self.content_chars, "finish_reasons": sorted(self.finish), "usage_events": self.usage_events, "error_events": self.errors, "done": self.done, "textual_tool_call_prefix_seen": self.text_tool_prefix}


class ToolTraceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") not in ("/v1/chat/completions", "/v1/responses"):
            return await self.app(scope, receive, send)
        token = TRACE.set(uuid.uuid4().hex)
        start = time.monotonic()
        request = bytearray()
        response = bytearray()
        summary = ResponseSummary()
        request_logged = False
        status = None
        streaming = False

        async def traced_receive():
            nonlocal request_logged
            message = await receive()
            if message["type"] == "http.request" and not request_logged:
                if len(request) <= 16 * 1024 * 1024:
                    request.extend(message.get("body", b""))
                if not message.get("more_body"):
                    request_logged = True
                    try:
                        payload = json.loads(request)
                        emit("client_request", endpoint=scope.get("path"), **request_metadata(payload))
                    except Exception:
                        emit("client_request", metadata_unavailable=True, request_bytes=len(request))
                    request.clear()
            return message

        async def traced_send(message):
            nonlocal status, streaming
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = dict(message.get("headers") or [])
                streaming = b"text/event-stream" in headers.get(b"content-type", b"")
                message = {**message, "headers": list(message.get("headers") or []) + [(b"x-qoder-trace-id", TRACE.get().encode())]}
            elif message["type"] == "http.response.body":
                response.extend(message.get("body", b""))
                if streaming:
                    while b"\n" in response:
                        line, _, tail = response.partition(b"\n")
                        response[:] = tail
                        if line.startswith(b"data:"):
                            value = line[5:].strip()
                            if value == b"[DONE]":
                                summary.done = True
                            else:
                                try:
                                    summary.observe(json.loads(value))
                                except Exception:
                                    pass
                elif not message.get("more_body"):
                    try:
                        summary.observe(json.loads(response))
                    except Exception:
                        pass
                    response.clear()
                if len(response) > 16 * 1024 * 1024:
                    response.clear()
            await send(message)

        try:
            await self.app(scope, traced_receive, traced_send)
        finally:
            emit("client_response", http_status=status, streaming=streaming, elapsed_s=round(time.monotonic() - start, 3), **summary.fields())
            TRACE.reset(token)
