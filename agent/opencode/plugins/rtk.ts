import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { Plugin } from "@opencode/plugin"

const execFileAsync = promisify(execFile)

export default Plugin.define({
  id: "rtk",
  async setup(ctx) {
    await ctx.tool.hook("execute.before", async (event) => {
      if (event.tool !== "bash" && event.tool !== "shell") return
      const input = event.input as { command?: unknown }
      if (typeof input?.command !== "string" || !input.command) return

      try {
        const { stdout } = await execFileAsync("rtk", ["rewrite", input.command])
        const rewritten = stdout.trim()
        if (rewritten && rewritten !== input.command) input.command = rewritten
      } catch {
        // Exit 1 means RTK has no rewrite for this command.
      }
    })
  },
})
