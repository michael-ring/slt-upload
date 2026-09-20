# AGENTS.md

## Project overview

This repository contains `sltupload`, a FastAPI service for members of the SLT Observatory to upload finished image edits to a configured filesystem path. The app authenticates with Discord OAuth, restricts access to specific allowed guilds, caches a project catalog from a source S3 bucket, and stores approved images using a member-specific path.

## Instructions

- Keep comments under three lines.
- Comment only what the code cannot say itself.
- Use a timeout for test suite commands and run focused tests for changed code.
- Use named parameters for all calls where supported.
- Use `uv` to manage virtual environments and dependencies.
- Call Python tools through `uv`. Ex: `uv run ruff check`.
- Use `ruff` and `ty` to format, lint, and check the code for errors.
