# ========== Tap ==========
tap "rtk-ai/tap"
tap "anomalyco/tap"
tap "wangnov/tap"
tap "can1357/tap"

# ========== CLI 核心 ==========
brew "git"
brew "curl"
brew "jq"
brew "tree"
brew "ripgrep"
brew "fd"
brew "ast-grep"
brew "neovim"
brew "tree-sitter-cli"
# ========== Shell 增强 ==========
brew "fzf"
brew "pngpaste"
brew "lua"
brew "direnv"
brew "zoxide"
brew "eza"
brew "bat"
brew "yazi"
# ========== 语言 & 运行时 ==========
brew "node"
brew "bun"
brew "uv"
# ========== Agent 工具链 & 多路复用 ==========
brew "herdr"
brew "anomalyco/tap/opencode-v2"
brew "omp"
brew "rtk"
brew "codex-threadripper"
cask "codex"
brew "gh"
brew "lazygit"

# ========== 容器 ==========
brew "docker"
brew "docker-buildx"
brew "docker-compose"
brew "colima"

# ========== 浏览器 ==========
cask "google-chrome"
# Optional fallback editor; no longer installed by default.
# cask "visual-studio-code"
# cask "zed"

# ========== 终端 & 系统增强 ==========
cask "ghostty"
cask "hammerspoon"
cask "shottr"
cask "maccy"
# ========== 网络 & 安全 ==========
brew "cloudflared"
cask "zerotier-one"
cask "clash-verge-rev"
cask "bitwarden"
cask "uuremote"
cask "hyperconnect"
brew "bitwarden-cli"
brew "age"
brew "sops"
brew "gitleaks"
# ========== 办公 & 系统字体 ==========
cask "wpsoffice-cn"
cask "chatgpt"
cask "font-sf-mono-nerd-font-ligaturized"
# ========== npm CLI ==========
# LazyCodex is intentionally not global-installed; its official installer writes
# the current Codex plugin/cache state: npx lazycodex-ai@latest install --no-tui --no-codex-autonomous
npm "reasonix"
npm "context-mode"
npm "codebase-memory-mcp"
npm "@waishnav/devspace"
npm "playwriter"
npm "pnpm"
npm "@monid-ai/cli"
npm "@moonrepo/cli"
npm "@upstash/context7-mcp"
npm "js-yaml"
# 见 python/requirements-common.txt

# ========== 动态加载环境与体验层 (Native Inclusion) ==========
private_dir = ENV["MAC_BOOTSTRAP_PRIVATE_DIR"] || File.expand_path("../../private", __FILE__)
profile = ENV["MAC_BOOTSTRAP_PROFILE"]
if profile.nil? || profile.empty?
  profile_script = File.expand_path("scripts/resolve-profile.sh", __dir__)
  if File.executable?(profile_script)
    profile = `#{profile_script}`.strip
  else
    profile = "work"
  end
end

[
  File.join(private_dir, "profiles", profile, "Brewfile"),
  File.join(private_dir, "profiles", profile, "Brewfile.experimental")
].each do |extra_file|
  instance_eval(File.read(extra_file)) if File.exist?(extra_file)
end
