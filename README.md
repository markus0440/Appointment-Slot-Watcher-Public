# Slot Monitoring Telegram Bot

> A bot that searches for appointment slots in specified cities, is controlled via Telegram, and uses a Chrome (Selenium) browser to work with the site.

## Quick Start (Docker Compose)

This project already includes a `docker-compose.yml`. You only need to prepare the environment and run it.
### 0) Telegram Bot setup
1. Create a bot via **@BotFather** and get the `API_TOKEN`.  
2. Fetch your `ADMIN_CHAT_ID` via **@userinfobot** or **@RawDataBot**.  
3. In Telegram, send `/start` to your bot — you’ll see the menu buttons. Click “Registration (Admin)” and enter the admin account login/password.  
   - After registering an account on the site, log out and log back in so the site asks for a phone number; then set the number.

### 1) Prepare the repository
- Place the project in a path without Cyrillic characters.
- Rename `.envexample` to `.env`.
- Put your user agreement text (or a link) into `agreements/pd_agreement.txt` (do not rename the file).

### 2) Configure `.env`
Open `.env` and fill in the variables:

```dotenv
# --- Telegram ---
API_TOKEN=                 # bot token from @BotFather
ADMIN_CHAT_ID=             # admin chat_id

# --- Scheduler ---
SCHED_INTERVAL_SEC=60      # auto-search interval in seconds
ALLOWED_CITIES=Ekaterinburg,Moscow,Vladivostok,Saint-Petersburg  # allowed cities (comma-separated, no spaces)

# --- Database ---
DB_USER=appuser
DB_PASSWORD=strong_password
DB_HOST=db
DB_PORT=5432
DB_NAME=appdb

# --- Selenium ---
WEBDRIVER_URL=http://selenium:4444

# --- VNC ---
SE_VNC_PASSWORD=pass       # password for Selenium's VNC page

# --- Agreement path ---
AGREEMENT_PATH=agreements/pd_agreement.txt
```
### 3) Launch the stack

```bash
docker compose up -d
```

Check:
- Open `http://localhost:7900/`, enter `SE_VNC_PASSWORD` — you should see the VNC screen.
- App logs: `docker compose logs -f app`

> Ports and service names come from your `docker-compose.yml`. If you changed them, adjust the URLs/commands accordingly.

---

## Admin control buttons

- `start_job` — start the web-bot (auto-search uses `SCHED_INTERVAL_SEC`).  
- `run_once` — perform a one-time search.  
- `stop_job` — stop the web-bot.  
- `continue` — continue after a captcha.

> When slots are found, registered users receive a notification like “Applications appeared” and the city name.

---

## Common operations

- **Open Selenium VNC:** `http://localhost:7900/` (password from `SE_VNC_PASSWORD`).  
- **App logs:** `docker compose logs -f app`  
- **Update images:** `docker compose pull && docker compose up -d`  
- **Stop:** `docker compose down` (DB data persists in the `db_data` volume if configured)

---

## Gotchas & tips

- You need to manually solve CAPTCHAs by going to `http://localhost:7900/`. The bot sends a notification to the administrator when a CAPTCHA occurs.
- If something goes wrong: wait for the error to show up, then press `stop_job`. In a worst case, restart Selenium and the app:
  ```bash
  docker compose restart selenium app
  ```
- Keeping project paths without Cyrillic helps avoid issues with tools and scripts.  
- If the button menu “disappears”, type `/start` to restore it.

---

## Local run (without Docker) — optional

You can run locally (Python 3.11 + venv), bring up Postgres manually, and use Docker only for Selenium. Follow your original instructions for Python setup, DB/user creation, and the Selenium container command.

---

## License & agreement

The user agreement text lives in `agreements/pd_agreement.txt`. If it’s too large, you can place a link inside that file.

---

## Technical summary

- **Services:** `db` (PostgreSQL), `selenium` (standalone-chrome, VNC), `app` (Python 3.11 + your code).  
- **Typical ports:** `4444` (Selenium Grid), `7900` (Selenium VNC), optionally `55432` (Postgres, host port mapped to container 5432).  
