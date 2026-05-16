# dashboard-cal

A Skylight-style wall dashboard built in Python for a Surface Pro 3 running Windows.

Features:

- **Google Calendar** — month or week grid with a circle on today, dots on days with events, tap a day to see details
- **Weather** — configurable 1–7 day forecast strip at the bottom (Open-Meteo, no API key)
- **Todos** — local list, persisted in SQLite
- **Grocery list** — synced with Google Tasks (a configurable task list)
- **Photo background** — slideshow from a local folder you control
- **Material Design 3** theme — built on Flet (Flutter)
- **Kiosk mode** — fullscreen, sleep suppressed, cursor hidden when idle

## Why these choices

- **Google Keep has no public API.** This app uses **Google Tasks** instead — the closest official equivalent. One synced task list named in `config.yaml` (default: `Grocery`).
- **Google Photos API was restricted in March 2025** (third-party apps can only see media they upload). This app uses a **local folder** instead. Sync your photos to that folder however you like (Google Drive desktop, Photos download, OneDrive).

## Requirements

- Windows 10 / 11 (designed for Surface Pro 3, works anywhere)
- Python 3.11 or newer
- A Google account (for Calendar + Tasks)
- A folder of background photos

## Setup

### 1. Install

```powershell
cd $HOME\git\dashboard-cal
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

### 2. Create a Google OAuth client (one-time, ~10 minutes)

1. Go to <https://console.cloud.google.com/>
2. Create a new project (or pick one).
3. **APIs & Services → Library** → enable both:
   - **Google Calendar API**
   - **Google Tasks API**
4. **APIs & Services → OAuth consent screen**
   - User type: **External** (or Internal if you're on a Workspace account)
   - Add yourself as a Test user (no need to verify the app — it's just for you)
   - Scopes: you can leave blank; the app requests them at runtime
5. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
   - Application type: **Desktop app**
   - Download the JSON, save it as `credentials.json` in the project root (next to `pyproject.toml`).

`credentials.json` is in `.gitignore` and never leaves your machine.

### 3. Configure

Copy and edit:

```powershell
copy config.example.yaml config.yaml
notepad config.yaml
```

Key fields:

- `weather.zip_code` — e.g. `"98101"`
- `weather.country` — ISO country (e.g. `"US"`)
- `weather.forecast_days` — 1 to 7
- `tasks.list_name` — name of the Google Tasks list to use for groceries (created on first launch if it doesn't exist)
- `photos.folder` — local folder of background photos (`~` is expanded)
- `ui.fullscreen` — `true` for kiosk, `false` for windowed
- `calendar.default_view` — `month` or `week`

### 4. First launch

```powershell
dashboard-cal
```

A browser window opens for Google sign-in. Grant access to Calendar (read-only) and Tasks. The refresh token is then stored in **Windows Credential Manager** — no plaintext tokens on disk.

### 5. Autostart on boot (optional, for true kiosk)

```powershell
.\scripts\install-startup-shortcut.ps1
```

This puts a shortcut in your Windows Startup folder. Sign out and back in (or reboot) and the dashboard launches automatically.

To remove: delete `dashboard-cal.lnk` from `shell:startup`.

## Configuration reference

See `config.example.yaml` — every field is documented inline.

## Project layout

```
src/dashboard_cal/
  app.py                  Flet shell + refresh loop
  config.py               pydantic settings + zip -> lat/lon geocoding
  theme.py                Material 3 color tokens
  auth/                   OAuth + keyring token storage
  services/               calendar, tasks, todos, weather, photos
  ui/                     calendar_view, event_sheet, side_panel, weather_strip, background
```

## Privacy & security

- OAuth refresh tokens are stored in the OS keyring (Windows Credential Manager).
- `config.yaml`, `credentials.json`, and the SQLite database (`*.db`) are all gitignored.
- No event details, contact info, or token contents are written to logs — only operation outcomes and counts.
- Network access is restricted to a small allowlist of hostnames (`oauth2.googleapis.com`, `www.googleapis.com`, `api.open-meteo.com`, `geocoding-api.open-meteo.com`).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Browser doesn't open on first run | Run `dashboard-cal` from a regular user session (not SYSTEM); make sure a default browser is set |
| "Token has been expired or revoked" | Run `dashboard-cal --reauth` to redo the OAuth flow |
| Weather strip empty | Bad zip code or no internet — check `config.yaml` and `dashboard-cal.log` |
| Photo background black | Folder empty, path wrong, or no supported image extension (jpg/png/webp/heic/jpeg) |
| Tasks list not found | App auto-creates the list named in `config.yaml` on first sync; check the Tasks app in Gmail/Calendar |

## Development

```powershell
pip install -e ".[dev]"
pytest
ruff check .
```

## License

MIT
