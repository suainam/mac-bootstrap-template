-- Autocmds are automatically loaded on the VeryLazy event (or immediately if arguments passed)
-- Disable LazyVim's wrap_spell group which forces spell = true on markdown/text
vim.api.nvim_create_autocmd("FileType", {
  pattern = { "text", "plaintex", "typst", "gitcommit", "markdown" },
  callback = function()
    vim.opt_local.spell = false
  end,
})
