# Enable Chrome AI ✨

Researched and scripted by [lcandy2](https://twitter.com/vanillaCitron).

[![Twitter](https://img.shields.io/twitter/follow/vanillaCitron)](https://twitter.com/vanillaCitron)


English | [中文](README.zh.md)

Attempt to enable Chrome AI features through local configuration changes, without clearing data or reinstalling. Availability still depends on the Chrome build, account, region, rollout and administrator policies.

<img width="512" alt="Google Chrome Gemini in Chrome" src="https://github.com/user-attachments/assets/a88c56a7-f20b-432a-926c-0184194225b4" />

Python helper for local country settings and Gemini eligibility caches, with a persistent country override, read-only diagnostics, backups and an optional launch switch. A successful local patch does not grant server-side access.

## ✅ Requirements
- Python `3.13+` (see `.python-version` / `pyproject.toml`)
- Google Chrome installed (Stable/Canary/Dev/Beta)

## ⚡️ Quick Start (uv)
1. Install uv (once):
   - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
   - macOS & Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - See [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/) for more options.
2. Install deps (creates venv automatically): `uv sync`.
3. Run the script: `uv run main.py`.
4. Save your browser work first. The script closes Chrome for the current OS user, waits for exit, patches and verifies the file, then restarts with the original arguments. It exits without an Enter prompt. On Windows automatic closing terminates processes; use `--no-close` after exiting Chrome manually if you prefer a normal shutdown.

## ⚡️ Quick Start (pip)
1. Create and activate a venv.
2. Install deps: `python -m pip install psutil`.
3. Run: `python main.py`.

## 🔧 What Happens
- Discovers Stable/Canary/Dev/Beta data directories on Windows, macOS and Linux. Windows honors `%LOCALAPPDATA%`; custom directories are supported.
- Sets or adds the boolean `is_glic_eligible: true` in each existing `profile.info_cache` entry.
- Sets `variations_country` to `"us"`.
- Sets or repairs `variations_permanent_overridden_country: "us"`, Chromium's persistent country override, which takes precedence over the version-bound cache.
- Creates or repairs `variations_permanent_consistency_country` as `["<Last Version>", "us"]`. Version whitespace is stripped. A missing/invalid version skips only this field.
- Backs up the exact original bytes to `Local State.backup-<UTC timestamp>`, atomically replaces the file and reads it back to verify. An already-patched file is not rewritten or backed up again.
- Preserves all other settings, including language, flags, account/encryption data, policies, consent and `variations_safe_seed_*` historical experiment snapshots.

## 🧪 Preview and Diagnostics

Preview without closing Chrome or writing files:

```shell
uv run main.py --dry-run
```

Read-only local check, including after restarting Chrome:

```shell
uv run main.py --check
```

Exit code `0` means the checked local fields match the patch; `1` means pending changes or an error. This does **not** test actual Gemini availability.

Select a Windows data directory in PowerShell:

```powershell
uv run main.py --user-data-dir "$env:LOCALAPPDATA\Google\Chrome\User Data"
```

For a custom installation, use the parent of the profile path shown in `chrome://version`: pass `User Data`, not `User Data\Default`.

After manually exiting all Chrome windows and background processes:

```shell
uv run main.py --no-close
```

Use `--no-restart` to leave Chrome closed. Automatic closing affects all recognized Chrome processes owned by the current OS user, even when a single data directory is selected. It excludes other OS users.

## 🔍 Chrome 154 and Changes After Restart

Verified against Chromium `154.0.8037.98` source:

- `is_glic_eligible` is a computed cache. Chrome recalculates it when account/eligibility state changes; setting it to `true` does not replace the eligibility checks.
- Permanent country and session country are separate inputs. Network updates can change `variations_country`, and newer seed storage may supply country data independently of the old local cache.
- To diagnose session-country issues, restart an already-running Chrome with the country override switch:

```shell
uv run main.py --restart-country
```

This adds or replaces `--variations-override-country=us` in the original command line for **this launch only**. It does not modify shortcuts. Chrome should be running before this command; otherwise the script asks you to launch manually with that switch. Future launches from an ordinary shortcut do not retain it. Check the command line in `chrome://version`.

The persistent preference overrides permanent country; the launch switch overrides both permanent and session country. These affect Chrome's regional experiments beyond AI. They do not change server-visible network location, account permissions or administrator policies.

If Gemini is still unavailable, inspect `chrome://policy`, sign-in state and Google's availability requirements. Work/school accounts may require administrator enablement. Chinese is supported; the script does not switch the UI to English. Gemini, AI history and DevTools AI also have different eligibility requirements.

Sources:

- [Chrome 154 eligibility and cache updates](https://chromium.googlesource.com/chromium/src/+/154.0.8037.98/chrome/browser/glic/public/glic_enabling.cc)
- [Chrome 154 country override precedence](https://chromium.googlesource.com/chromium/src/+/154.0.8037.98/components/variations/service/variations_field_trial_creator.cc)
- [Gemini in Chrome availability](https://support.google.com/chrome/answer/17140089)

## 🛟 Backups and Limitations

- Launch Chrome once to create `Local State`. Missing files, invalid JSON and permission errors are reported; one failed channel does not prevent processing the others.
- To restore, completely exit Chrome and copy the desired `Local State.backup-<UTC timestamp>` over `Local State`. A full restore also restores other local settings from that time.
- Run as the OS user who owns the profile. Process detection uses Chrome names; exit renamed/wrapped builds manually. Process checks and content comparisons reduce write races but cannot lock out a newly launched browser. Do not launch Chrome while patching.
- Restart preserves the browser process command line and working directory, not necessarily every window, unsaved form or tab state.
- Automated tests use temporary configurations and mocked processes; real Windows Chrome functionality still needs verification.
- Not affiliated with Google. Share only relevant diagnostic fields: full `Local State` files and backups contain account identifiers and encrypted data.

Run tests: `uv run python -m unittest discover -s tests -v`.

## 📜 License
Please credit this project when reposting or creating derivative works.

## 🙏 Acknowledgments
- [show-copilot](https://github.com/hzkaai/show-copilot)
