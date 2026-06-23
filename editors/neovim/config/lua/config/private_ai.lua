local M = {}

local function load_private_config()
  local config_root = vim.uv.fs_realpath(vim.fn.stdpath("config")) or vim.fn.stdpath("config")
  local private_path = vim.fn.fnamemodify(config_root, ":h:h:h:h")
    .. "/private/editors/neovim/ai.lua"

  if vim.fn.filereadable(private_path) == 0 then
    return {}
  end

  local ok, config = pcall(dofile, private_path)
  if not ok or type(config) ~= "table" then
    vim.notify("Failed to load private Neovim AI config", vim.log.levels.WARN)
    return {}
  end

  return config
end

M.values = load_private_config()

function M.get(key, fallback)
  local value = M.values[key]
  if value == nil or value == "" then
    return fallback
  end
  return value
end

return M
