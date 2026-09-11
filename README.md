# rtu-calendar-sync

Generates an up-to-date `planning.ics` file from the RTU group timetable
(nodarbibas.rtu.lv), filtered down to the courses actually taken, and
republishes it automatically every day via GitHub Actions.

## Setup (one-time)

1. Create a **public** GitHub repo and push this folder to it:

   ```bash
   cd rtu-calendar-sync
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<your-user>/rtu-calendar-sync.git
   git push -u origin main
   ```

2. On GitHub: **Settings > Actions > General > Workflow permissions**,
   make sure "Read and write permissions" is checked (otherwise the job
   won't be able to commit/push the file).

3. Trigger the workflow once by hand: **Actions** tab >
   "Update RTU calendar" > **Run workflow**. Check the logs: the
   "Matières ignorées" section (the script's console output stays in
   French) lists everything that got excluded — make sure none of your
   real courses ended up in there (if so, adjust `MY_COURSES` in
   `sync_calendar.py`).

4. Once `planning.ics` exists in the repo, subscribe to this URL:

   ```
   https://raw.githubusercontent.com/<your-user>/rtu-calendar-sync/main/planning.ics
   ```

   - **Google Calendar** (web): `+` button next to "Other calendars" >
     "From URL" > paste the URL.
   - **iOS**: Settings > Calendar > Accounts > Add Account > Other >
     Add Subscribed Calendar > paste the URL.

   Both refresh automatically at regular intervals (usually every few
   hours, not in real time).

## Every new semester

Update these constants at the top of `sync_calendar.py`, commit, push:

- `SEMESTER_LABEL_CONTAINS` (e.g. `"26/27-SP"` for the spring semester)
- `MY_COURSES` if your subjects change

## How it works

`nodarbibas.rtu.lv` exposes a small internal JSON API (no session state to
maintain). The script:

1. resolves the `semesterId`, `programId`, `semesterProgramId` matching
   your program/group,
2. fetches every event for the **whole group** over the semester (the site
   has no per-student filtering, only per-group),
3. keeps only the events whose title matches an entry in `MY_COURSES`,
4. generates an `.ics` with a **stable** UID per event (a hash of the
   event's content, not a random UUID) — without that, every daily
   regeneration would create duplicates instead of updating existing
   events.