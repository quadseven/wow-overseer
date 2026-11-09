# Live proof probes

Many tickets end in a "Live:" box that a read-only SELECT can settle. A probe is that SELECT, kept in `liveproof/probes/<repo>/<ticket>.sql`, so a schedule can evaluate it instead of a person. Ticket: wow-overseer#2125.

## Add a probe

1. Create `liveproof/probes/wow-overseer/<ticket>.sql` (or `mod-overseer/`).
2. Start with the header, then a comment saying what proves and what disproves:

   ```sql
   -- ticket: 1234
   -- repo: quadseven/wow-overseer
   -- What the Live box asks; proven when ...; disproven when ...
   SELECT '1234' AS ticket, CASE ... END AS verdict, CONCAT(...) AS evidence;
   ```

3. The statement returns exactly one row with three columns: `ticket` (the same number as the file name), `verdict` (`proven`, `disproven` or `no_evidence`) and `evidence` (counts and ids that let a reader check the verdict).
4. Say `proven` only when the query alone settles the Live box. If the proof also needs a log line, leave the ticket manual.
5. Run `python3 -m unittest tests.test_liveproof`. It parses every probe and checks the header.

Remove a probe when its ticket closes.

## The read-only rule

`liveproof/run.py` parses each file with sqlglot and refuses anything that is not exactly one plain SELECT: writes, a second statement, `SELECT ... INTO`, locking reads, a UNION, and functions such as `SLEEP` or `LOAD_FILE`. A refused or failing probe is recorded as an `error` verdict and never reaches the database. Use a database account with SELECT only; the connection also sets `SESSION TRANSACTION READ ONLY`.

## Run

```
LIVEPROOF_DB_HOST=... LIVEPROOF_DB_USER=... LIVEPROOF_DB_PASSWORD=... python3 liveproof/run.py
```

This needs PyMySQL and sqlglot (`tests/requirements.txt`). It writes `liveproof/verdicts/verdicts-<UTC time>.json` (or `--out DIR`, `LIVEPROOF_OUT`) and exits 0. The directory is git-ignored.

## The two-run rule

One run can be a batch artifact. `liveproof/report.py` reads the two newest verdict files and lists the tickets that are `proven` in both. Only those qualify to close.

```
python3 liveproof/report.py            # dry run: prints the gh commands
python3 liveproof/report.py --apply    # comments the evidence, then closes
```

Without `--apply` nothing is commented or closed. With it, an issue that is already closed is skipped, and a failed comment stops the close.

The CronJob that runs the probes on a schedule is a follow-up.
