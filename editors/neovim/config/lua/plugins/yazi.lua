---@type LazySpec
return {
  "mikavilpas/yazi.nvim",
  version = "*",
  event = "VeryLazy",
  dependencies = {
    { "nvim-lua/plenary.nvim", lazy = true },
  },
  keys = {
    {
      "<leader>y",
      mode = { "n", "v" },
      "<cmd>Yazi<cr>",
      desc = "Open yazi at the current file",
    },
    {
      "<leader>Y",
      "<cmd>Yazi cwd<cr>",
      desc = "Open yazi in Neovim's working directory",
    },
  },
  ---@type YaziConfig | {}
  opts = {
    open_for_directories = false,
    change_neovim_cwd_on_close = false,
    floating_window_scaling_factor = 0.9,
    yazi_floating_window_border = "rounded",
    keymaps = {
      show_help = "<f1>",
    },
    integrations = {
      grep_in_directory = "telescope",
    },
    log_level = vim.log.levels.OFF,
  },
  init = function()
    vim.g.loaded_netrwPlugin = 1
  end,
}
