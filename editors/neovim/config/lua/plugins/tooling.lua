return {
  {
    "folke/lazy.nvim",
    opts = {
      rocks = {
        enabled = false,
        hererocks = false,
      },
    },
  },
  {
    "stevearc/conform.nvim",
    opts = function(_, opts)
      opts.formatters_by_ft = opts.formatters_by_ft or {}
      opts.formatters_by_ft.fish = nil
    end,
  },
  {
    "ChmaraX/herdr-nvim",
    opts = {
      prefix = "<leader>h", -- 使用 <leader>h 避免与 LazyVim 原生 <leader>a 快捷键冲突
      clear_after_send = true,
    },
  },
}
