-- luvus.lua: Neovim integration for Luvus 3-pane IDE.
-- Source from init.lua with:  dofile(vim.fn.expand("~/.omp/agent/managed-skills/luvus-nvim-qa-workspace/scripts/luvus.lua"))
--
-- Provides:
--   <leader>aa  (visual mode) - Dispatch selection to agent pane (luvus agent send)
--   :LuvusQA                - Run Playwriter ARIA verification on current project

local M = {}

local SKILL_DIR = vim.fn.expand("~/.omp/agent/managed-skills/luvus-nvim-qa-workspace")
local QA_SCRIPT = SKILL_DIR .. "/scripts/verify-ui.py"

-- <leader>aa: dispatch visual selection to agent
vim.keymap.set("v", "<leader>aa", function()
	local s_start = vim.fn.getpos("'<")[2]
	local s_end = vim.fn.getpos("'>")[2]
	local file = vim.fn.expand("%:p")

	vim.ui.input({ prompt = "Delegate to Agent: " }, function(task)
		if not task or task == "" then return end
		local prompt = string.format(
			"Target: %s (lines %d-%d)\nInstruction: %s",
			file, s_start, s_end, task
		)
		vim.fn.system(string.format("luvus agent send agent %q", prompt))
		vim.notify("[luvus] dispatched to agent", vim.log.levels.INFO)
	end)
end, { desc = "Dispatch Selection to Luvus Agent" })

-- :LuvusQA - run verify-ui.py and show result in a floating notification
vim.api.nvim_create_user_command("LuvusQA", function(opts)
	local url = opts.args ~= "" and opts.args or "http://localhost:5173"
	vim.notify("[luvus] running Playwriter verification on " .. url, vim.log.levels.INFO)

	vim.fn.jobstart({ "python3", QA_SCRIPT, url }, {
		on_exit = function(_, exit_code)
			if exit_code == 0 then
				vim.notify("[luvus] QA verification passed", vim.log.levels.INFO)
			else
				vim.notify("[luvus] QA verification FAILED (exit " .. exit_code .. ")", vim.log.levels.ERROR)
			end
		end,
		on_stdout = function(_, data)
			if data and #data > 0 then
				local payload = table.concat(data, "\n")
				if #payload > 0 and payload:len() < 2000 then
					print(payload)
				end
			end
		end,
	})
end, { nargs = "?", desc = "Run Luvus Playwriter QA verification" })

-- Back-compat alias
vim.api.nvim_create_user_command("HerdrQA", function(opts)
	vim.cmd("LuvusQA " .. (opts.args or ""))
end, { nargs = "?", desc = "Alias for LuvusQA" })

return M
