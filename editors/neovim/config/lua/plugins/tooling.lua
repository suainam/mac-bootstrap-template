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
}
