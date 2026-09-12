#!/usr/bin/env python3
"""Interactive terminal client for testing a self-hosted MTG Azor deployment.

This is a reference/testing client, not a production one -- it exists so
someone who just ran ./setup.sh && ./run_bot.sh can try the API from a
terminal without writing any code of their own. Build your own client
(web, Discord, Telegram, whatever) against /chat and /chat/stream for real
end-user access; see docs/DESCRIPTION.md's API reference.

Usage:
    ./scripts/chat_cli.py
    ./scripts/chat_cli.py --url http://localhost:8000 --api-key mykey
    ./scripts/chat_cli.py --no-stream

Talks to /chat/stream (SSE) by default; --no-stream uses the plain /chat
endpoint instead. Only dependency is `requests`, already in
server/requirements.txt and installed into .venv by setup.sh.
"""

import argparse
import json
import os
import sys

import requests

DEFAULT_URL = "http://localhost:8000"


def iter_sse_events(response):
    """Parses a text/event-stream response into (event, data) pairs.

    Hand-rolled rather than pulling in an SSE client library: the format
    /chat/stream actually emits (event: <name>\\ndata: <json>\\n\\n, one
    event per block) is simple enough that a real dependency isn't worth
    it for a single-file reference script.
    """
    event = None
    data_lines = []
    for raw_line in response.iter_lines(decode_unicode=True):
        if raw_line == "":
            if event is not None:
                yield event, "\n".join(data_lines)
            event = None
            data_lines = []
            continue
        if raw_line is None:
            continue
        if raw_line.startswith("event:"):
            event = raw_line[len("event:"):].strip()
        elif raw_line.startswith("data:"):
            data_lines.append(raw_line[len("data:"):].strip())
    if event is not None and data_lines:
        yield event, "\n".join(data_lines)


def print_error_response(resp):
    try:
        detail = resp.json().get("detail", resp.text)
    except ValueError:
        detail = resp.text
    print(f"\n[HTTP {resp.status_code}] {detail}")


def print_citations(sources):
    if not sources:
        return
    labels = [
        ("rules", "Rules"),
        ("rulings", "Rulings"),
        ("web_links", "Web"),
        ("images", "Images"),
    ]
    lines = [
        f"  {label}: {', '.join(sources[key])}"
        for key, label in labels
        if sources.get(key)
    ]
    if lines:
        print("\n".join(lines))


def send_streaming(base_url, headers, query, conversation_id):
    payload = {"query": query}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    with requests.post(
        f"{base_url}/chat/stream",
        json=payload,
        headers=headers,
        stream=True,
        timeout=(10, 300),
    ) as resp:
        if resp.status_code != 200:
            print_error_response(resp)
            return conversation_id
        sources = None
        new_conversation_id = conversation_id
        for event, data in iter_sse_events(resp):
            if event == "token":
                print(json.loads(data)["text"], end="", flush=True)
            elif event == "sources":
                sources = json.loads(data)
            elif event == "error":
                print(f"\n[error] {json.loads(data)['message']}")
            elif event == "done":
                new_conversation_id = json.loads(data)["conversation_id"]
        print()
        print_citations(sources)
        return new_conversation_id


def send_once(base_url, headers, query, conversation_id):
    payload = {"query": query}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    resp = requests.post(f"{base_url}/chat", json=payload, headers=headers, timeout=300)
    if resp.status_code != 200:
        print_error_response(resp)
        return conversation_id
    data = resp.json()
    print(data["answer"])
    print_citations(data.get("sources"))
    return data["conversation_id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--url",
        default=os.environ.get("MTG_AZOR_URL", DEFAULT_URL),
        help=f"Base URL of the running mtg-judge API (default: {DEFAULT_URL}, or $MTG_AZOR_URL)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("MTG_AZOR_API_KEY"),
        help="X-API-Key to send, if the deployment requires one (default: $MTG_AZOR_API_KEY)",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Use POST /chat instead of streaming /chat/stream",
    )
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    headers = {"X-API-Key": args.api_key} if args.api_key else {}

    try:
        health = requests.get(f"{base_url}/health", headers=headers, timeout=5).json()
        print(f"Connected to {base_url} (provider={health.get('provider')}, ready={health.get('ready')})")
    except requests.exceptions.RequestException as exc:
        print(f"Could not reach {base_url}/health ({exc}).")
        print("Is the server running? See README.md's Quick Start, or ./run_bot.sh.")
        sys.exit(1)

    print("Type a Magic: The Gathering rules question, '/new' for a fresh conversation, or '/exit' to quit.\n")

    send = send_once if args.no_stream else send_streaming
    conversation_id = None
    while True:
        try:
            query = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            continue
        if query in ("/exit", "/quit"):
            break
        if query == "/new":
            conversation_id = None
            print("(started a new conversation)")
            continue
        print("azor> ", end="", flush=True)
        try:
            conversation_id = send(base_url, headers, query, conversation_id)
        except requests.exceptions.RequestException as exc:
            print(f"\n[connection error] {exc}")

    print("Bye.")


if __name__ == "__main__":
    main()
