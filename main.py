import gzip
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context
from mcp.server.session import ServerSession
from practiso_sdk.build import Builder

from state_tracking import BuildingStateTracker, Head


@dataclass
class AppContext:
    quiz_builder: Builder
    state: BuildingStateTracker


@asynccontextmanager
async def app_lifespan(_: FastMCP) -> AsyncIterator[AppContext]:
    builder = Builder()
    state = BuildingStateTracker()
    try:
        yield AppContext(quiz_builder=builder, state=state)
    finally:
        if state.valid and not state.built:
            archive = await builder.build()
            save_name = f'unsaved_{datetime.now().strftime("%Y%m%d_%H%M%S")}.psarchive'
            with gzip.open(save_name, "wb") as fd:
                fd.write(archive.to_bytes())
        elif not state.valid and not state.empty:
            print(
                f"Warning: archive was left invalid at {state.head.name} and was UNSAVED",
                file=sys.stderr,
            )


mcp = FastMCP("Practiso Archive Tools", json_response=True, lifespan=app_lifespan)

ContextType = Context[ServerSession, AppContext]


def _format_available_actions(actions: list[str]) -> str:
    return (
        "Now you can "
        + ("either: " if len(actions) == 2 else "")
        + (
            actions[0]
            if len(actions) == 1
            else "; ".join(
                f"{index+1}. {option}" for (index, option) in enumerate(actions)
            )
        )
        + "."
    )


def _format_and_clause(items: list[str]) -> str:
    if len(items) == 0:
        raise ValueError("empty items")
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-2]) + ", " + _format_and_clause(items[-2:])


def _assert_valid(is_valid: bool, instructions: str | None = None):
    if not is_valid:
        raise RuntimeError(
            "you are in an illegal state" + f"; {instructions}" if instructions else ""
        )


@mcp.tool()
def begin_quiz(ctx: ContextType, name: str | None = None) -> str:
    """Ask the builder to begin a quiz. Use this tool ONLY IF either: 1. the last quiz has been ended; 2. it's the first time use."""
    context = ctx.request_context.lifespan_context
    _assert_valid(context.state.head == Head.root)
    context.quiz_builder.begin_quiz(name=name)
    context.state.increase_level()
    return "Quiz begun. Now you can add content to the quiz."


@mcp.tool()
def end_quiz(ctx: ContextType):
    """Ask the builder to end the current quiz, making the future incoming content in a separate one. Use only there's an ongoing quiz."""
    context = ctx.request_context.lifespan_context
    _assert_valid(context.state.head == Head.quiz)
    context.quiz_builder.end_quiz()
    context.state.decrease_level()
    return f"Quiz ended. {_format_available_actions(['save the all quiz(zes) into an archive file', 'begin another quiz'])}"


@mcp.tool()
def add_text(ctx: ContextType, content: str) -> str:
    """Ask the builder to add a piece of text in the ongoing quiz. Use only if there's currently an onging quiz."""
    context = ctx.request_context.lifespan_context
    _assert_valid(context.state.head in [Head.quiz, Head.option])
    context.quiz_builder.add_text(content)
    availble_actions = ["add more content"]
    if context.state.head == Head.quiz:
        availble_actions.append("end the quiz")
    return f"Text added. {_format_available_actions(availble_actions)}"


@mcp.tool()
async def save(ctx: ContextType, path: str) -> str:
    """Save the your edit into a file. Use only if the builder is NOT empty, AND the last quiz has been ended. `path` must be absolute, and the file extension must be `.psarchive`"""

    _path = Path(path)
    if not _path.is_absolute():
        raise ValueError("path is not absolute")
    if _path.is_dir():
        raise ValueError("path is an existing directory")
    if _path.suffix != ".psarchive":
        raise ValueError("path doesn't end with `.psarchive`")

    context = ctx.request_context.lifespan_context
    _assert_valid(not context.state.empty, instructions="begin a quiz first")
    _assert_valid(
        context.state.valid,
        instructions=f"end the {_format_and_clause(list(head for head in (Head(i).name for i in range(context.state.level, 0, -1))))}",
    )

    with gzip.open(_path, "wb") as fd:
        content = await context.quiz_builder.build()
        fd.write(content.to_bytes())
    return f"Your edit has been saved to `{_path}`"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
