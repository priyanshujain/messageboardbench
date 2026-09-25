"""Confirm the model slug, the key, and tool support. Costs about a cent.

basic_agent loops uselessly against a model that cannot call a tool, so the second check
matters as much as the first: a model that answers "hi" but ignores tools would burn the
whole message limit on every sample and score zero for a reason that looks like honesty.
"""

import asyncio
import os

from dotenv import load_dotenv
from inspect_ai.model import ChatMessageUser, GenerateConfig, get_model
from inspect_ai.tool import ToolInfo, ToolParams
from inspect_ai.util import JSONSchema

async def main() -> None:
    load_dotenv()
    model_name = os.environ.get("MBB_MODEL", "openrouter/z-ai/glm-5.3-flash")
    model_args = {}
    if model_name.startswith("openai-api/cline/cline-pass/"):
        model_args = {
            "base_url": "https://api.cline.bot/api/v1",
            "responses_api": False,
            "stream": True,
            "strict_tools": False,
        }
    model = get_model(model_name, **model_args)

    out = await model.generate("hi")
    print(f"[1/2] generate: {out.completion.strip()[:120]!r}")
    print(f"      tokens: in={out.usage.input_tokens} out={out.usage.output_tokens}")

    add = ToolInfo(
        name="add",
        description="Add two integers.",
        parameters=ToolParams(
            properties={
                "a": JSONSchema(type="integer", description="first addend"),
                "b": JSONSchema(type="integer", description="second addend"),
            },
            required=["a", "b"],
        ),
    )
    out = await model.generate(
        [ChatMessageUser(content="Use the add tool to add 17 and 25. Do not answer directly.")],
        tools=[add],
        config=GenerateConfig(max_tokens=200),
    )
    calls = out.message.tool_calls or []
    print(f"[2/2] tool calls: {[(c.function, c.arguments) for c in calls]}")
    print("      TOOL SUPPORT OK" if calls else "      NO TOOL CALL: basic_agent will not work")


if __name__ == "__main__":
    asyncio.run(main())
