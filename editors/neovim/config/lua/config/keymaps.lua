local map = vim.keymap.set

map("n", "<M-h>", "<cmd><C-U>TmuxNavigateLeft<CR>", { silent = true })
map("n", "<M-j>", "<cmd><C-U>TmuxNavigateDown<CR>", { silent = true })
map("n", "<M-k>", "<cmd><C-U>TmuxNavigateUp<CR>", { silent = true })
map("n", "<M-l>", "<cmd><C-U>TmuxNavigateRight<CR>", { silent = true })
