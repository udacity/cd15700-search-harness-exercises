// OpenCode sends the first model request without waiting for MCP servers to connect,
// so a one-shot `opencode run` never gets their tools. This holds the question until
// the tools are ready. https://github.com/anomalyco/opencode/issues/51812
const TOOL_PREFIX = "symbols_"
const TIMEOUT_MS = 30_000

export default {
  id: "wait-for-mcp",
  async setup(ctx: any) {
    await ctx.session.hook("prompt", async () => {
      const deadline = Date.now() + TIMEOUT_MS
      while (Date.now() < deadline) {
        const tools = await ctx.tool.list()
        if (tools.some((tool: any) => tool.id?.startsWith(TOOL_PREFIX))) return
        await new Promise((resolve) => setTimeout(resolve, 100))
      }
    })
  },
}
