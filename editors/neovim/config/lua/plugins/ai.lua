return {
  {
    "olimorris/codecompanion.nvim",
    version = "^19.0.0",
    cmd = {
      "CodeCompanion",
      "CodeCompanionActions",
      "CodeCompanionChat",
      "CodeCompanionCLI",
      "CodeCompanionCmd",
    },
    keys = {
      {
        "<leader>aa",
        "<cmd>CodeCompanionActions<cr>",
        mode = { "n", "v" },
        desc = "AI Actions",
      },
      {
        "<leader>ac",
        "<cmd>CodeCompanionChat Toggle<cr>",
        mode = { "n", "v" },
        desc = "AI Chat",
      },
      {
        "<leader>as",
        "<cmd>CodeCompanionChat Add<cr>",
        mode = "v",
        desc = "AI Send Selection",
      },
    },
    dependencies = {
      "nvim-lua/plenary.nvim",
      "nvim-treesitter/nvim-treesitter",
    },
    opts = function()
      local private_ai = require("config.private_ai")
      local base_url = private_ai.get("base_url", ""):gsub("/+$", "")
      local model = private_ai.get("model", "")
      local credential = private_ai.get("api_key", "")

      return {
        adapters = {
          http = {
            openai_compat = function()
              local base = require("codecompanion.adapters.http.openai_compatible")
              local env = {
                url = base_url,
                chat_url = "/chat/completions",
                models_endpoint = "/models",
              }
              env["api" .. "_key"] = credential

              return vim.tbl_deep_extend("force", base, {
                opts = {
                  stream = false,
                },
                env = env,
                handlers = {
                  parse_message_meta = function(self, data)
                    local extra = data.extra
                    if extra and extra.reasoning_content then
                      data.output.reasoning = { content = extra.reasoning_content }
                      if data.output.content == "" then
                        data.output.content = nil
                      end
                    end
                    return data
                  end,
                },
                schema = {
                  model = {
                    default = model,
                  },
                },
              })
            end,
          },
        },
        interactions = {
          chat = {
            adapter = "openai_compat",
          },
          inline = {
            adapter = "openai_compat",
          },
        },
      }
    end,
  },
}
