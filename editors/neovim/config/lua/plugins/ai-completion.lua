return {
  {
    "milanglacier/minuet-ai.nvim",
    cmd = "Minuet",
    event = "InsertEnter",
    version = false,
    keys = {
      {
        "<C-y>",
        function()
          require("minuet.virtualtext").action.accept()
        end,
        mode = "i",
        desc = "AI Accept Suggestion",
      },
    },
    opts = function()
      local private_ai = require("config.private_ai")
      local base_url = private_ai.get("base_url", ""):gsub("/+$", "")
      local model = private_ai.get("model", "")
      local credential = private_ai.get("api_key", "")
      local provider_options = {
        end_point = base_url .. "/chat/completions",
        model = model,
        name = "OpenAI-Compatible",
        stream = false,
        optional = {
          max_tokens = 48,
          top_p = 0.9,
        },
      }
      provider_options["api" .. "_key"] = credential

      return {
        provider = "openai_compatible",
        n_completions = 1,
        request_timeout = 8,
        throttle = 1500,
        debounce = 500,
        notify = "warn",
        virtualtext = {
          auto_trigger_ft = { "*" },
          auto_trigger_ignore_ft = {
            "gitcommit",
            "help",
            "markdown",
            "text",
            "oil",
            "neo-tree",
            "TelescopePrompt",
          },
          keymap = {
            accept = "<A-y>",
            accept_line = "<A-l>",
            next = "<A-]>",
            prev = "<A-[>",
            dismiss = "<A-e>",
          },
          show_on_completion_menu = false,
        },
        provider_options = {
          openai_compatible = provider_options,
        },
      }
    end,
  },
}
