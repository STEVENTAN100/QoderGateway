"""Stateless Responses adapter for Qoder, including function/custom namespaces."""
import copy
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse


def new_id(prefix):
    return prefix + uuid.uuid4().hex[:24]


@dataclass
class Tool:
    name: str
    namespace: str | None
    kind: str
    alias: str


class Tools:
    def __init__(self, definitions):
        self.by_alias = {}
        self.by_name = {}
        self.definitions = []
        self.positions = {}
        self.original = copy.deepcopy(definitions or [])
        if not isinstance(self.original, list):
            raise HTTPException(400, detail="Tool definitions must be an array")
        for definition in self.original:
            if not isinstance(definition, dict):
                raise HTTPException(400, detail="Tool definitions must be objects")
            if definition.get("type") == "namespace":
                children = definition.get("tools") or []
                if not isinstance(children, list):
                    raise HTTPException(400, detail="Namespace tools must be an array")
                for child in children:
                    self.add(child, definition.get("name"), definition.get("description", ""))
            else:
                self.add(definition, definition.get("namespace"))

    def add(self, definition, namespace=None, namespace_description=""):
        if not isinstance(definition, dict):
            raise HTTPException(400, detail="Tool definitions must be objects")
        kind = definition.get("type")
        if kind not in ("function", "custom"):
            raise HTTPException(400, detail=f"Unsupported Responses tool type: {kind}. This endpoint supports function, custom and namespace tools.")
        name = definition.get("name")
        if not isinstance(name, str) or not name:
            raise HTTPException(400, detail="Tool name is required")
        if namespace is not None and (not isinstance(namespace, str) or not namespace):
            raise HTTPException(400, detail="Tool namespace must be a nonempty string")
        key = (namespace, name)
        existing = self.by_name.get(key)
        alias = existing.alias if existing else (namespace + "__" if namespace else "") + name
        if not existing and (not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", alias) or alias in self.by_alias):
            alias = "tool_" + hashlib.sha256(json.dumps(key).encode()).hexdigest()[:32]
        tool = Tool(name, namespace, kind, alias)
        self.by_alias[alias] = tool
        self.by_name[key] = tool
        description = "\n".join(p for p in (namespace_description, definition.get("description", "")) if p)
        if kind == "custom":
            description += "\nThis is a free-form tool. Put the exact raw tool input in the JSON string field input, without adding Markdown code fences."
            fmt = definition.get("format") or {}
            if fmt.get("type") == "grammar":
                grammar = fmt.get("grammar") or fmt
                description += "\nThe raw input must obey this " + str(grammar.get("syntax", "")) + " grammar:\n" + str(grammar.get("definition", ""))
            parameters = {"type": "object", "properties": {"input": {"type": "string", "description": "Exact raw text to send to the custom tool"}}, "required": ["input"], "additionalProperties": False}
        else:
            parameters = copy.deepcopy(definition.get("parameters") or {"type": "object", "properties": {}})
        converted = {"type": "function", "function": {"name": alias, "description": description, "parameters": parameters}}
        if existing:
            # Repeated additional_tools items occur when Codex resends history.
            # The latest declaration updates this tool without creating duplicates.
            self.definitions[self.positions[key]] = converted
        else:
            self.positions[key] = len(self.definitions)
            self.definitions.append(converted)

    def resolve(self, name, namespace=None):
        if (namespace, name) in self.by_name:
            return self.by_name[namespace, name]
        if name in self.by_alias:
            return self.by_alias[name]
        matches = [t for t in self.by_alias.values() if t.name == name]
        if namespace is None and len(matches) == 1:
            return matches[0]
        raise HTTPException(400, detail=f"Tool is not defined or ambiguous: {name}")


def text_content(content):
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if not isinstance(content, list):
        raise HTTPException(400, detail="Message content must be text or a content array")
    parts = []
    for part in content:
        if not isinstance(part, dict) or part.get("type") not in ("input_text", "output_text", "text"):
            raise HTTPException(400, detail="This Responses endpoint currently supports text content; image/file content is not implemented")
        parts.append(part.get("text") or "")
    return "\n".join(parts)


def to_chat(payload):
    if payload.get("previous_response_id"):
        raise HTTPException(400, detail="This endpoint is stateless. Send the complete input history and store=false instead of previous_response_id")
    if payload.get("background"):
        raise HTTPException(400, detail="Background Responses are not implemented")
    if payload.get("store") is True:
        raise HTTPException(400, detail="Server-side response storage is not implemented; use store=false")
    fmt = (payload.get("text") or {}).get("format") or {}
    if fmt.get("type", "text") != "text":
        raise HTTPException(400, detail="Structured response formats are not implemented")
    messages = []
    if payload.get("instructions"):
        messages.append({"role": "system", "content": payload["instructions"]})
    incoming = payload.get("input", [])
    if isinstance(incoming, str):
        incoming = [{"role": "user", "content": incoming}]
    if not isinstance(incoming, list):
        raise HTTPException(400, detail="input must be a string or array")
    definitions = copy.deepcopy(payload.get("tools") or [])
    if not isinstance(definitions, list):
        raise HTTPException(400, detail="tools must be an array")
    history_reasoning = {}
    for item in incoming:
        if not isinstance(item, dict):
            raise HTTPException(400, detail="Response input items must be objects")
        if item.get("type") == "additional_tools":
            if item.get("role", "developer") != "developer":
                raise HTTPException(400, detail="additional_tools role must be developer")
            additional = item.get("tools")
            if not isinstance(additional, list):
                raise HTTPException(400, detail="additional_tools.tools must be an array")
            definitions.extend(copy.deepcopy(additional))
        elif item.get("type") == "tool_search_output":
            # The search may have been executed by the client. Make its loaded
            # tools available without exposing this control item as user text.
            loaded = item.get("tools")
            if not isinstance(loaded, list):
                raise HTTPException(400, detail="tool_search_output.tools must be an array")
            definitions.extend(copy.deepcopy(loaded))
        elif item.get("type") == "configuration_update":
            update = item.get("reasoning") or {}
            if not isinstance(update, dict):
                raise HTTPException(400, detail="configuration_update.reasoning must be an object")
            if "effort" in update:
                history_reasoning["effort"] = update["effort"]
    tools = Tools(definitions)
    for item in incoming:
        if not isinstance(item, dict):
            raise HTTPException(400, detail="Response input items must be objects")
        kind = item.get("type", "message")
        if kind in ("additional_tools", "configuration_update", "tool_search_output"):
            # These are declarations/configuration, not conversational messages.
            continue
        elif kind == "message":
            role = item.get("role", "user")
            role = "system" if role == "developer" else role
            if role not in ("system", "user", "assistant"):
                raise HTTPException(400, detail=f"Unsupported message role: {role}")
            messages.append({"role": role, "content": text_content(item.get("content"))})
        elif kind in ("function_call", "custom_tool_call"):
            tool = tools.resolve(item.get("name"), item.get("namespace"))
            if tool.kind != ("custom" if kind == "custom_tool_call" else "function"):
                raise HTTPException(400, detail="Tool call type does not match its definition")
            call_id = item.get("call_id")
            if not call_id:
                raise HTTPException(400, detail="Tool call requires call_id")
            arguments = json.dumps({"input": item.get("input", "")}, ensure_ascii=False) if tool.kind == "custom" else item.get("arguments", "{}")
            call = {"id": call_id, "type": "function", "function": {"name": tool.alias, "arguments": arguments}}
            if messages and messages[-1]["role"] == "assistant" and messages[-1].get("tool_calls"):
                messages[-1]["tool_calls"].append(call)
            else:
                messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
        elif kind in ("function_call_output", "custom_tool_call_output"):
            if not item.get("call_id"):
                raise HTTPException(400, detail="Tool output requires call_id")
            messages.append({"role": "tool", "tool_call_id": item["call_id"], "content": text_content(item.get("output"))})
        elif kind == "reasoning":
            # Qoder has no OpenAI encrypted reasoning state. The full text/tool
            # history still travels with each stateless request.
            continue
        else:
            raise HTTPException(400, detail=f"Unsupported Responses input item type: {kind}")
    if not messages:
        raise HTTPException(400, detail="At least one input message or tool output is required")
    chat = {"model": payload.get("model", "gfmodel"), "messages": messages, "tools": tools.definitions, "stream": bool(payload.get("stream"))}
    reasoning = {**history_reasoning, **(payload.get("reasoning") or {})}
    if "effort" in reasoning:
        chat["reasoning_effort"] = reasoning["effort"]
    if "max_output_tokens" in payload and payload["max_output_tokens"] is not None:
        value = payload["max_output_tokens"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 16:
            raise HTTPException(400, detail="max_output_tokens must be an integer >=16")
        chat["max_tokens"] = value
    if "parallel_tool_calls" in payload:
        chat["parallel_tool_calls"] = payload["parallel_tool_calls"]
    choice = payload.get("tool_choice", "auto")
    if isinstance(choice, dict):
        if choice.get("type") not in ("function", "custom"):
            raise HTTPException(400, detail="Unsupported tool_choice type")
        tool = tools.resolve(choice.get("name"), choice.get("namespace"))
        choice = {"type": "function", "function": {"name": tool.alias}}
    elif choice not in ("auto", "none", "required"):
        raise HTTPException(400, detail="Unsupported tool_choice")
    chat["tool_choice"] = choice
    if chat["stream"]:
        chat["stream_options"] = {"include_usage": True}
    return chat, tools


def responses_usage(usage):
    if not isinstance(usage, dict):
        return None
    mapping = {"prompt_tokens": "input_tokens", "completion_tokens": "output_tokens", "total_tokens": "total_tokens"}
    out = {target: usage[source] for source, target in mapping.items() if source in usage}
    if "prompt_tokens_details" in usage:
        out["input_tokens_details"] = copy.deepcopy(usage["prompt_tokens_details"])
    if "completion_tokens_details" in usage:
        out["output_tokens_details"] = copy.deepcopy(usage["completion_tokens_details"])
    return out


def custom_input(arguments):
    try:
        obj = json.loads(arguments)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Upstream custom tool arguments are not valid JSON") from exc
    if not isinstance(obj, dict) or not isinstance(obj.get("input"), str):
        raise RuntimeError("Upstream custom tool arguments require a string input")
    return obj["input"]


def tool_item(call, tools, status="completed", item_id=None):
    function = call.get("function") or {}
    tool = tools.by_alias.get(function.get("name"))
    if tool is None:
        raise RuntimeError("Upstream invoked a tool not present in the request")
    item = {"id": item_id or new_id("ctc_" if tool.kind == "custom" else "fc_"), "type": "custom_tool_call" if tool.kind == "custom" else "function_call", "call_id": call.get("id") or new_id("call_"), "name": tool.name, "status": status}
    if tool.namespace:
        item["namespace"] = tool.namespace
    arguments = function.get("arguments", "")
    if tool.kind == "custom":
        item["input"] = custom_input(arguments) if status != "in_progress" else ""
    else:
        item["arguments"] = arguments
    return item


def response_object(payload, output, usage=None, status="completed", response_id=None, created=None):
    return {"id": response_id or new_id("resp_"), "object": "response", "created_at": created or int(time.time()), "status": status, "error": None, "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None, "instructions": payload.get("instructions"), "model": payload.get("model", "gfmodel"), "output": output, "parallel_tool_calls": payload.get("parallel_tool_calls", False), "previous_response_id": None, "reasoning": payload.get("reasoning"), "store": False, "tools": payload.get("tools", []), "tool_choice": payload.get("tool_choice", "auto"), "text": payload.get("text", {"format": {"type": "text"}}), "max_output_tokens": payload.get("max_output_tokens"), "metadata": payload.get("metadata") or {}, "usage": responses_usage(usage)}


def from_completion(payload, completion, tools):
    choice = completion["choices"][0]
    message = choice["message"]
    output = []
    if message.get("reasoning_content"):
        output.append({"id": new_id("rs_"), "type": "reasoning", "summary": [{"type": "summary_text", "text": message["reasoning_content"]}]})
    if message.get("content"):
        output.append({"id": new_id("msg_"), "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": message["content"], "annotations": []}]})
    for call in message.get("tool_calls") or []:
        output.append(tool_item(call, tools))
    return response_object(payload, output, completion.get("usage"), "incomplete" if choice.get("finish_reason") == "length" else "completed")


async def stream_responses(payload, chat_response, tools):
    response_id, created = new_id("resp_"), int(time.time())
    output, calls = [], {}
    message_index = reasoning_index = None
    usage = None
    finish = None
    sequence = 0

    def event(kind, **fields):
        nonlocal sequence
        data = {"type": kind, "sequence_number": sequence, **fields}
        sequence += 1
        return "event: " + kind + "\ndata: " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n\n"

    def snapshot(status):
        return response_object(payload, copy.deepcopy(output), usage, status, response_id, created)

    yield event("response.created", response=snapshot("in_progress"))
    yield event("response.in_progress", response=snapshot("in_progress"))
    pending = ""
    try:
        async for part in chat_response.body_iterator:
            pending += part.decode() if isinstance(part, bytes) else part
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                    continue
                chunk = json.loads(line[5:].strip())
                if isinstance(chunk.get("usage"), dict):
                    usage = chunk["usage"]
                for choice in chunk.get("choices") or []:
                    finish = choice.get("finish_reason") or finish
                    delta = choice.get("delta") or {}
                    if delta.get("reasoning_content"):
                        if reasoning_index is None:
                            reasoning_index = len(output)
                            output.append({"id": new_id("rs_"), "type": "reasoning", "summary": []})
                            yield event("response.output_item.added", output_index=reasoning_index, item=copy.deepcopy(output[-1]))
                            output[-1]["summary"].append({"type": "summary_text", "text": ""})
                            yield event("response.reasoning_summary_part.added", item_id=output[-1]["id"], output_index=reasoning_index, summary_index=0, part={"type": "summary_text", "text": ""})
                        item = output[reasoning_index]
                        item["summary"][0]["text"] += delta["reasoning_content"]
                        yield event("response.reasoning_summary_text.delta", item_id=item["id"], output_index=reasoning_index, summary_index=0, delta=delta["reasoning_content"])
                    if delta.get("content"):
                        if message_index is None:
                            message_index = len(output)
                            output.append({"id": new_id("msg_"), "type": "message", "role": "assistant", "status": "in_progress", "content": []})
                            yield event("response.output_item.added", output_index=message_index, item=copy.deepcopy(output[-1]))
                            output[-1]["content"].append({"type": "output_text", "text": "", "annotations": []})
                            yield event("response.content_part.added", item_id=output[-1]["id"], output_index=message_index, content_index=0, part=copy.deepcopy(output[-1]["content"][0]))
                        item = output[message_index]
                        item["content"][0]["text"] += delta["content"]
                        yield event("response.output_text.delta", item_id=item["id"], output_index=message_index, content_index=0, delta=delta["content"], logprobs=[])
                    for update in delta.get("tool_calls") or []:
                        index = update.get("index", 0)
                        call = calls.setdefault(index, {"id": "", "function": {"name": "", "arguments": ""}, "output_index": None})
                        if update.get("id"):
                            call["id"] = update["id"]
                        function = update.get("function") or {}
                        if function.get("name"):
                            call["function"]["name"] = function["name"]
                        if call["output_index"] is None and call["function"]["name"]:
                            call["output_index"] = len(output)
                            output.append(tool_item(call, tools, "in_progress"))
                            yield event("response.output_item.added", output_index=call["output_index"], item=copy.deepcopy(output[-1]))
                        arguments = function.get("arguments") or ""
                        call["function"]["arguments"] += arguments
                        if call["output_index"] is not None and arguments:
                            item = output[call["output_index"]]
                            if item["type"] == "function_call":
                                item["arguments"] = call["function"]["arguments"]
                                yield event("response.function_call_arguments.delta", item_id=item["id"], output_index=call["output_index"], delta=arguments)
        for call in calls.values():
            if call["output_index"] is None:
                raise RuntimeError("Upstream tool call has no tool name")
            index = call["output_index"]
            item = tool_item(call, tools, item_id=output[index]["id"])
            output[index] = item
            if item["type"] == "custom_tool_call":
                # Decode the JSON string only after complete arguments arrive;
                # never stream JSON escape fragments as free-form tool input.
                yield event("response.custom_tool_call_input.delta", item_id=item["id"], output_index=index, delta=item["input"])
                yield event("response.custom_tool_call_input.done", item_id=item["id"], output_index=index, input=item["input"])
            else:
                yield event("response.function_call_arguments.done", item_id=item["id"], output_index=index, arguments=item["arguments"])
        for index, item in enumerate(output):
            if item["type"] == "reasoning":
                part = item["summary"][0]
                yield event("response.reasoning_summary_text.done", item_id=item["id"], output_index=index, summary_index=0, text=part["text"])
                yield event("response.reasoning_summary_part.done", item_id=item["id"], output_index=index, summary_index=0, part=copy.deepcopy(part))
            elif item["type"] == "message":
                item["status"] = "incomplete" if finish == "length" else "completed"
                part = item["content"][0]
                yield event("response.output_text.done", item_id=item["id"], output_index=index, content_index=0, text=part["text"], logprobs=[])
                yield event("response.content_part.done", item_id=item["id"], output_index=index, content_index=0, part=copy.deepcopy(part))
            yield event("response.output_item.done", output_index=index, item=copy.deepcopy(item))
        status = "incomplete" if finish == "length" else "completed"
        yield event("response." + status, response=snapshot(status))
    except Exception as exc:
        failed = snapshot("failed")
        failed["error"] = {"code": "upstream_error", "message": str(exc)}
        yield event("response.failed", response=failed)
    finally:
        if hasattr(chat_response.body_iterator, "aclose"):
            await chat_response.body_iterator.aclose()


def register_responses(app, chat_handler):
    @app.post("/v1/responses")
    async def create_response(payload: dict[str, Any], authorization: str | None = Header(default=None)):
        chat, tools = to_chat(payload)
        # Reuse existing API authentication, account routing and upstream errors.
        result = await chat_handler(chat, authorization)
        if chat["stream"]:
            return StreamingResponse(stream_responses(payload, result, tools), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
        return JSONResponse(from_completion(payload, result, tools))
