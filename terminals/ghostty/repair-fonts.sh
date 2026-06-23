#!/usr/bin/env bash
set -euo pipefail

FONT_DIR="${HOME}/Library/Fonts"
REGISTRY="${HOME}/Library/Preferences/com.apple.FontRegistry.user.plist"

shopt -s nullglob
fonts=("${FONT_DIR}"/LigaSFMonoNerdFont-*.otf)
shopt -u nullglob

if [ "${#fonts[@]}" -eq 0 ]; then
  cat >&2 <<'EOF'
Liga SFMono Nerd Font files not found.
Install the managed Homebrew cask first:
  brew install --cask font-sf-mono-nerd-font-ligaturized
EOF
  exit 1
fi

if [ -f "$REGISTRY" ] && xattr -p com.apple.quarantine "$REGISTRY" >/dev/null 2>&1; then
  xattr -d com.apple.quarantine "$REGISTRY"
fi

for font in "${fonts[@]}"; do
  xattr -d com.apple.quarantine "$font" >/dev/null 2>&1 || true
done

swift_script="$(mktemp -t ghostty-liga-register.XXXXXX.swift)"
trap 'rm -f "$swift_script"' EXIT

cat >"$swift_script" <<'SWIFT'
import Foundation
import CoreText

let urls = CommandLine.arguments.dropFirst().map { URL(fileURLWithPath: $0) }
if urls.isEmpty {
    fputs("No font files passed\n", stderr)
    exit(1)
}

var failures = 0
for url in urls {
    var unregisterError: Unmanaged<CFError>?
    _ = CTFontManagerUnregisterFontsForURL(url as CFURL, .user, &unregisterError)

    var registerError: Unmanaged<CFError>?
    let ok = CTFontManagerRegisterFontsForURL(url as CFURL, .user, &registerError)
    if !ok {
        let text = registerError?.takeRetainedValue().localizedDescription ?? "unknown error"
        if !text.localizedCaseInsensitiveContains("already registered") {
            fputs("\(url.lastPathComponent): \(text)\n", stderr)
            failures += 1
        }
    }
}

let descriptor = CTFontDescriptorCreateWithNameAndSize("Liga SFMono Nerd Font" as CFString, 13.5)
let matches = (CTFontDescriptorCreateMatchingFontDescriptors(descriptor, nil) as? [CTFontDescriptor]) ?? []
print("liga-font-files \(urls.count)")
print("liga-match-count \(matches.count)")

if failures > 0 || matches.isEmpty {
    exit(1)
}
SWIFT

CLANG_MODULE_CACHE_PATH="${TMPDIR:-/tmp}/codex-swift-module-cache" swift "$swift_script" "${fonts[@]}"
