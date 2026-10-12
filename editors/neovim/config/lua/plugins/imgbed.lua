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

  -- 去除 JSONC 可能包含的单行注释（只去除独立行注释，避免误伤 https://）
  content = content:gsub("\n%s*//[^\r\n]*", "\n"):gsub("^%s*//[^\r\n]*", "")

  local ok, parsed = pcall(vim.json.decode, content)
  if not ok or type(parsed) ~= "table" then
    return nil, "解析 private/imgbed/config.jsonc 失败"
  end

  return parsed, nil
end
local is_uploading = false

local function get_cache_file()
  return vim.fn.stdpath("cache") .. "/imgbed_hashes.json"
end

local function load_hash_cache()
  local f = io.open(get_cache_file(), "r")
  if not f then
    return {}
  end
  local content = f:read("*a")
  f:close()
  local ok, data = pcall(vim.json.decode, content)
  return (ok and type(data) == "table") and data or {}
end

local function save_hash_cache(cache)
  local f = io.open(get_cache_file(), "w")
  if f then
    f:write(vim.json.encode(cache))
    f:close()
  end
end

local function upload_clipboard_image()
  local notif_opts = { id = "imgbed_upload", title = "ImgBed", icon = "󰸭" }

  if is_uploading then
    vim.notify("已有图片正在上传中，请稍候...", vim.log.levels.WARN, notif_opts)
    return
  end

  if vim.fn.executable("pngpaste") == 0 then
    vim.notify("未检测到 pngpaste，请先安装: brew install pngpaste", vim.log.levels.ERROR, notif_opts)
    return
  end

  local tmp_file = vim.fn.tempname() .. ".png"
  local paste_res = vim.system({ "pngpaste", tmp_file }):wait()
  if paste_res.code ~= 0 then
    vim.notify("剪切板中没有图片数据", vim.log.levels.WARN, notif_opts)
    return
  end

  -- 计算图片文件的 SHA-256 哈希值
  local img_f = io.open(tmp_file, "rb")
  local img_bytes = img_f and img_f:read("*a") or ""
  if img_f then
    img_f:close()
  end
  local img_hash = vim.fn.sha256(img_bytes)

  -- 本地去重缓存检查（秒传）
  local cache = load_hash_cache()
  local cached_url = cache[img_hash]
  if cached_url and cached_url ~= "" then
    vim.uv.fs_unlink(tmp_file)
    local md = string.format("![](%s)", cached_url)
    vim.api.nvim_put({ md }, "c", true, true)
    vim.notify(
      string.format("⚡ 命中本地去重缓存 (秒传 0.0s): %s", cached_url),
      vim.log.levels.INFO,
      notif_opts
    )
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

  local spinner_frames = { "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏" }
  local frame_idx = 1
  local start_time = vim.uv.now()
  local timer = vim.uv.new_timer()


  local function update_notify()
    local elapsed = (vim.uv.now() - start_time) / 1000
    local frame = spinner_frames[frame_idx]
    frame_idx = (frame_idx % #spinner_frames) + 1
    vim.notify(
      string.format("%s 正在上传到图床... (%.1fs)", frame, elapsed),
      vim.log.levels.INFO,
      notif_opts
    )
  end

  update_notify()
  if timer then
    timer:start(150, 150, vim.schedule_wrap(update_notify))
  end
  is_uploading = true
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
      is_uploading = false

      if timer and timer:is_active() then
        timer:stop()
        timer:close()
      end

      local total_time = (vim.uv.now() - start_time) / 1000

      if out.code ~= 0 then
        vim.notify(
          string.format("❌ 图床上传失败: curl 退出码 %d (%.1fs)", out.code, total_time),
          vim.log.levels.ERROR,
          notif_opts
        )
        return
      end

      local ok, res = pcall(vim.json.decode, out.stdout or "")
      if ok and type(res) == "table" and res[1] and res[1].src then
        local img_url = res[1].src

        -- 写入本地去重缓存
        cache[img_hash] = img_url
        save_hash_cache(cache)

        local md = string.format("![](%s)", img_url)
        vim.api.nvim_put({ md }, "c", true, true)
        vim.notify(
          string.format("✅ 图片上传成功并已插入 (%.1fs)", total_time),
          vim.log.levels.INFO,
          notif_opts
        )
      else
        vim.notify(
          string.format("❌ 图床响应解析失败: %s (%.1fs)", out.stdout or "", total_time),
          vim.log.levels.ERROR,
          notif_opts
        )
      end
    end)
  end)
end

vim.api.nvim_create_user_command("ImgBedPaste", upload_clipboard_image, {
  desc = "Upload clipboard image to ImgBed and insert Markdown",
})

vim.keymap.set({ "n", "v" }, "<leader>ip", upload_clipboard_image, {
  desc = "Paste clipboard image to ImgBed",
})
return {
  {
    "LazyVim/LazyVim",
    keys = {
      {
        "<leader>ip",
        upload_clipboard_image,
        desc = "Paste clipboard image to ImgBed",
        mode = { "n", "v" },
      },
    },
  },
}
