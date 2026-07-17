# Privacy Notes

This tool is designed for local-first analysis of private chat exports.

Recommended rules:

- Do not commit raw chat exports.
- Do not commit generated `exports/` folders unless you have reviewed them.
- Do not commit `.env` files or Cloudflare tokens.
- Be careful with generated HTML and JSON: they can include speaker names,
  timestamps, and message snippets.
- If you publish the static site, assume every generated file under the output
  directory is public.

The repository includes only source code and a small fictional sample chat.
