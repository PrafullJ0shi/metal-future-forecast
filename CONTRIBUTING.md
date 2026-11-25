# Contributing

Issues and small patches are welcome. A change should earn its place the way the existing readings did: a stated method, public data, tests, and limits written down.

## Before you start

- Read [DESIGN.md](DESIGN.md). The fun lives in the chrome (goo, blobs, mascots); charts and numbers stay flat, crisp and readable. Two fonts only (Luckiest Guy, Nunito). No emoji, no stock icons.
- The planned work is in [docs/ROADMAP.md](docs/ROADMAP.md).
- Run the tests (no network):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
```

## Pull requests

- Keep changes focused. A new reading needs tests and a README note.
- Formulas on GitHub use `$...$` and `$$`. In prose write "USD 1,000" so a dollar sign does not open math mode.
- Workflow changes go in [docs/github-workflow-sweep.yml](docs/github-workflow-sweep.yml) first; the maintainer copies them into `.github/workflows/`.
- No `Co-authored-by` trailers.
- Do not invent placeholder numbers. An empty state is a sentence, not a fake reading.
- Copy can be cheeky (it is a trading toy), but no slurs, nothing aimed at groups of people, and nothing you would not show a recruiter.

MIT licensed. No CLA.
