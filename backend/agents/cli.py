"""Terminal REPL to talk to the NutriMind agent (no Telegram needed).

Usage:
    uv run python -m agents.cli
    uv run python -m agents.cli --image plate.jpg "is this a good lunch?"

Requires ANTHROPIC_API_KEY and CRONOMETER_* in the repo-root .env, and the
Cronometer MCP server reachable (or run it via stdio — see notes). Google Health
is optional; the agent skips it if unavailable.
"""

import argparse
import asyncio
import mimetypes
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from agents.nutrition_agent import ImageInput, run_turn


async def _one_shot(text: str, image_path: str | None) -> None:
    image = None
    if image_path:
        data = Path(image_path).read_bytes()
        media_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        image = ImageInput(data=data, media_type=media_type)
    reply = await run_turn(text, image=image)
    print(f"\nNutriMind: {reply}\n")


async def _repl() -> None:
    history: list[dict] = []
    print("NutriMind REPL — type a message (Ctrl-C to quit).")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        history.append({"role": "user", "content": text})
        reply = await run_turn(text, history=history[:-1])
        history.append({"role": "assistant", "content": reply})
        print(f"NutriMind> {reply}\n")


def main() -> None:
    load_dotenv(find_dotenv(usecwd=True), override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="*", help="message (omit for interactive REPL)")
    parser.add_argument("--image", help="path to a food photo to include")
    args = parser.parse_args()

    if args.text or args.image:
        asyncio.run(_one_shot(" ".join(args.text), args.image))
    else:
        asyncio.run(_repl())


if __name__ == "__main__":
    main()
