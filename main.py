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


def _get_available_actions(current_head: Head) -> str:
    if current_head == Head.option:
        return [
            "add an image",
            "add a text",
            "end the option",
        ]
    if current_head == Head.quiz:
        return ["add a text", "add an image", "begin an Options", "end the quiz"]
    if current_head == Head.options:
        return ["end the Options", "add more Option"]
    if current_head == Head.root:
        return ["save the all quiz(zes) into an archive file", "begin another quiz"]


@mcp.tool()
def begin_quiz(ctx: ContextType, name: str | None) -> str:
    """Ask the builder to begin a quiz. Name it with context. Use this tool ONLY IF either: 1. the last quiz has been ended; 2. it's the first time use."""
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
    return f"Quiz ended. {_format_available_actions(_get_available_actions(context.state.head))}"


@mcp.tool()
def add_text(ctx: ContextType, content: str) -> str:
    """Ask the builder to add a piece of text to the ongoing quiz. Use only if there's currently an onging quiz."""
    context = ctx.request_context.lifespan_context
    _assert_valid(context.state.head in [Head.quiz, Head.option])
    context.quiz_builder.add_text(content)
    return f"Text added. {_format_available_actions(_get_available_actions(context.state.head))}"


@mcp.tool()
def add_image(ctx: ContextType, file_path: str, caption: str | None = None) -> str:
    """Ask the builder to add an image to the ongoing quiz."""
    context = ctx.request_context.lifespan_context
    _file_path = Path(file_path)
    if not _file_path.is_file():
        raise ValueError("file doesn't exist")
    context.quiz_builder.begin_image(alt_text=caption).attach_image_file(
        file_path
    ).end_image()
    return f"Image added. {_format_available_actions(_get_available_actions(context.state.head))}"


@mcp.tool()
def begin_options(ctx: ContextType, name: str | None = None) -> str:
    """Ask the builder to begin an Options, which is the container of multiple Option, serving as choices. The user can interact with them by choosing one or several of the assumed answers. You don't have to but can give the Options a descriptive name."""
    context = ctx.request_context.lifespan_context
    context.quiz_builder.begin_options(name)
    context.state.increase_level()
    return f"Options begun. {_format_available_actions(_get_available_actions(context.state.head))}"


@mcp.tool()
def begin_option(ctx: ContextType, is_answer_key: bool, priority: int = 0) -> str:
    """Ask the builder to begin an Option, which is the container of ONE text or image item. The user can do either: 1. single choice if only one of the Option in the current Options container is marked as the answer key, or 2. multiple choice if more than one is marked as answer key. Reorder the Option when necessary using the `priority` parameter, higher the value the prior. Same priority means random order when presented to the user. Adding more text or image items will OVERWRITE the previous one. Use this tool only if there's an Options container currently onging."""
    context = ctx.request_context.lifespan_context
    context.quiz_builder.begin_option(is_key=is_answer_key, priority=priority)
    context.state.increase_level()
    return f"Option begun. {_format_available_actions(_get_available_actions(context.state.head))}"


@mcp.tool()
def end_option(ctx: ContextType) -> str:
    """Ask the builder to end the Option. This will bring back the last onging Options. Only use after you have begun an Option and added content to it."""
    context = ctx.request_context.lifespan_context
    context.quiz_builder.end_option()
    context.state.decrease_level()
    return f"Option ended. {_format_available_actions(_get_available_actions(context.state.head))}"


@mcp.tool()
def end_options(ctx: ContextType) -> str:
    """Ask the builder to end the Options. Use only after you have begun an Options and added content to it."""
    context = ctx.request_context.lifespan_context
    context.quiz_builder.end_options()
    context.state.decrease_level()
    return f"Options ended. {_format_available_actions(_get_available_actions(context.state.head))}"


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
