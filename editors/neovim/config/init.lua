vim.g.python3_host_prog = vim.fn.expand("~/.local/share/neovim-python/bin/python")
vim.g.loaded_perl_provider = 0
vim.g.loaded_ruby_provider = 0
vim.g.loaded_node_provider = 0

require("config.lazy")
