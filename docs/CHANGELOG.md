# Changelog
## 0.4.0
- Humanized console output with `Info:`, `Note:`, `Warning:`, and `Error:` prefixes; GitHub-link environment diagnostics are now INFO and no longer change a successful exit code.
- Dry-run reports the public destination from the site checkout's `hugo.toml`, with a site-relative fallback.
- Plain unchanged publishes now flush pending site commits created by earlier `--no-push` runs; batch and dry-run modes report pending debt without pushing.
