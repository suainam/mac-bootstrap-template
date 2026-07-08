local clipboard = vim.env.SSH_CONNECTION and "" or "unnamedplus"

vim.opt.clipboard = clipboard

if clipboard ~= "" then
  local group = vim.api.nvim_create_augroup("LocalClipboardRestore", { clear = true })

  -- LazyVim defers clipboard setup, so restore our local preference after startup.
  vim.api.nvim_create_autocmd("User", {
    group = group,
    pattern = "VeryLazy",
    callback = function()
      vim.opt.clipboard = clipboard
      vim.api.nvim_clear_autocmds({ group = group })
    end,
  })

  vim.api.nvim_create_autocmd("VimEnter", {
    group = group,
    once = true,
    callback = function()
      if vim.o.clipboard == "" then
        vim.opt.clipboard = clipboard
      end
    end,
  })

  vim.api.nvim_create_autocmd("TextYankPost", {
    group = group,
    callback = function()
      local event = vim.v.event
      if event.operator ~= "y" then
        return
      end
      if event.regname == "+" or event.regname == "*" then
        return
      end

      -- Keep local yanks synced even when LazyVim defers clipboard restore.
      vim.fn.setreg("+", event.regcontents, event.regtype)
    end,
  })
end

vim.opt.relativenumber = true
vim.opt.wrap = false
vim.opt.scrolloff = 5
vim.opt.sidescrolloff = 15

-- LazyVim enables spell for markdown by default; turn it off so Chinese,
-- code identifiers and proper nouns are not flagged as misspellings.
vim.api.nvim_create_augroup("NoSpellForDocs", { clear = true })
vim.api.nvim_create_autocmd("FileType", {
  group = "NoSpellForDocs",
  pattern = { "markdown", "markdown.mdx", "text", "plaintex", "tex", "rst", "asciidoc" },
  callback = function()
    vim.opt_local.spell = false
  end,
})
