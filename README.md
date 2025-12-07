# Practiso MCP

Set of tools to utilize LLMs as Practiso archive generators.

## Get started

Dozens of MCP clients are available. They are probably the same.

Here is an OpenCode configuration example:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "practiso-mcp": {
      "type": "local",
      "command": ["uvx", "practiso-mcp"]
    }
  },
}
```
