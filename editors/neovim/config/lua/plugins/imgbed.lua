local function get_config()
  local config_root = vim.uv.fs_realpath(vim.fn.stdpath("config")) or vim.fn.stdpath("config")
  local repo_path = vim.fn.fnamemodify(config_root, ":h:h:h:h") .. "/private/imgbed/config.jsonc"

  local cfg_file = nil
  if vim.fn.filereadable(repo_path) == 1 then
    cfg_file = repo_path
  else
    local fallback = vim.fn.expand("~/work/config/mac-bootstrap/private/imgbed/config.jsonc")
    if vim.fn.filereadable(fallback) == 1 then
      cfg_file = fallback
    end
  end

  if not cfg_file then
    return nil, "未找到 private/imgbed/config.jsonc 配置文件"
  end

  local f = io.open(cfg_file, "r")
  if not f then
    return nil, "无法读取配置文件: " .. cfg_file
  end

  local content = f:read("*a")
  f:close()

  -- 去除 JSONC 可能包含的单行注释
  content = content:gsub("//[^\r\n]*", "")

  local ok, parsed = pcall(vim.json.decode, content)
  if not ok or type(parsed) ~= "table" then
    return nil, "解析 private/imgbed/config.jsonc 失败"
  end

  return parsed, nil
end

local function upload_clipboard_image()
  if vim.fn.executable("pngpaste") == 0 then
    vim.notify("未检测到 pngpaste，请先安装: brew install pngpaste", vim.log.levels.ERROR)
    return
  end

  local tmp_file = vim.fn.tempname() .. ".png"
  local paste_res = vim.system({ "pngpaste", tmp_file }):wait()
  if paste_res.code ~= 0 then
    vim.notify("剪切板中没有图片数据", vim.log.levels.WARN)
    return
  end

  local cfg, err = get_config()
  if not cfg then
    vim.uv.fs_unlink(tmp_file)
    vim.notify(err, vim.log.levels.ERROR)
    return
  end

  local upload_key = cfg.upload_api_key
  if not upload_key or upload_key == "" then
    vim.uv.fs_unlink(tmp_file)
    vim.notify("配置中缺少 upload_api_key", vim.log.levels.ERROR)
    return
  end

  local host = cfg.url and cfg.url:gsub("/+$", "") or ""
  if host == "" then
    vim.uv.fs_unlink(tmp_file)
    vim.notify("配置中缺少 url", vim.log.levels.ERROR)
    return
  end
  local api_url = host .. "/upload?returnFormat=full"

  vim.notify("正在上传剪切板图片到图床...", vim.log.levels.INFO)

  vim.system({
    "curl",
    "-s",
    "-X",
    "POST",
    api_url,
    "-H",
    "Authorization: Bearer " .. upload_key,
    "-F",
    "file=@" .. tmp_file .. ";type=image/png",
  }, { text = true }, function(out)
    vim.uv.fs_unlink(tmp_file)

    vim.schedule(function()
      if out.code ~= 0 then
        vim.notify("图床上传失败: curl 退出码 " .. out.code, vim.log.levels.ERROR)
        return
      end

      local ok, res = pcall(vim.json.decode, out.stdout or "")
      if ok and type(res) == "table" and res[1] and res[1].src then
        local img_url = res[1].src
        local md = string.format("![](%s)", img_url)
        vim.api.nvim_put({ md }, "c", true, true)
        vim.notify("图片上传成功并已插入: " .. img_url, vim.log.levels.INFO)
      else
        vim.notify("图床响应解析失败: " .. (out.stdout or ""), vim.log.levels.ERROR)
      end
    end)
  end)
end

vim.api.nvim_create_user_command("ImgBedPaste", upload_clipboard_image, {
  desc = "Upload clipboard image to ImgBed and insert Markdown",
})

return {
  {
    "LazyVim/LazyVim",
    keys = {
      {
        "<leader>ip",
        upload_clipboard_image,
        desc = "Paste clipboard image to ImgBed",
        mode = "n",
      },
    },
  },
}
