# TaskUp · Kuskon AI

TaskUp is a hackathon MVP for AI Sana: a platform where a business turns a raw need into a structured task card, improves its readiness score, publishes it to an open catalogue, receives student-team proposals, and manually chooses one, several, or no teams.

## Core flow

1. Business enters a raw description.
2. The system detects missing information and asks 3–5 clarifying questions.
3. A task card is built and remains editable.
4. The business confirms the fields.
5. A transparent readiness score from 0 to 100 is calculated.
6. The task is published to the shared catalogue.
7. A student team independently submits an idea, plan, timeline, and prototype/repository link.
8. The business manually selects or rejects proposals.
9. A selected team may submit one result milestone; the business can confirm it and award demo progress points.

The AI never assigns a team automatically.

## Readiness score

The MVP uses the hackathon rubric:

- Context and need — 20
- Data and materials — 20
- Expected outcome — 15
- Success criteria — 15
- Constraints — 10
- Users — 10
- Business communication — 10

Total: **100**

Readiness levels:

- 0–39 — Draft
- 40–69 — Working
- 70–89 — Ready
- 90–100 — Priority

A low score does not hide a published task and does not block proposals.

## Languages

The UI supports:

- Қазақша
- English
- Русский

The user chooses a language on the landing screen and may switch it later from the sidebar. New AI/fallback clarification questions follow the selected interface language.

## Roles

The first screen requires a demo role choice:

- **Business representative** — create/edit tasks, review proposals, manually select/reject teams.
- **Student / team** — browse the open catalogue, submit proposals, and submit a milestone after selection.

A **Change role** button always returns to the role-selection screen.

This is a hackathon demo identity switch, not production authentication.

## Stack

- Python
- Streamlit
- SQLite
- Optional OpenAI Responses API
- python-dotenv

## Run locally

Create a virtual environment:

```powershell
python -m venv .venv
```

Install dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

If your environment is named differently, replace `.venv` with that folder name.

## OpenAI API key

The application works without an external API by using a clearly labelled local fallback.

To enable real AI:

1. Copy:

```text
.streamlit/secrets.toml.example
```

to:

```text
.streamlit/secrets.toml
```

2. Put your real key only in the local `secrets.toml`:

```toml
OPENAI_API_KEY = "YOUR_REAL_KEY"
OPENAI_MODEL = "gpt-4.1-mini"
```

3. Restart Streamlit.

The real `.streamlit/secrets.toml` is ignored by Git and must never be committed.

The app can also read `OPENAI_API_KEY` / `OPENAI_MODEL` from a local `.env` file or environment variables.

## AI safety / grounding rule

The AI is instructed to extract only information that already exists in the user's original description. Unknown fields remain empty. The returned structured card is validated before use, and the user must review and confirm the card before publication.

If the API fails, times out, returns malformed JSON, or violates the extraction constraints, TaskUp keeps the original text and falls back to the local clarification flow.

## Data

SQLite persists task cards, versions, scores, proposals, decisions, and result milestones.

On first run the app seeds synthetic hackathon data:

- at least 5 draft examples
- at least 5 published task cards
- 5 team profiles
- 5 proposals

The database files under `data/` are excluded from Git.

## Repository structure

```text
app.py                 Streamlit UI and navigation
ai_service.py          AI interview, schema validation, fallback
database.py            SQLite persistence and state transitions
scoring.py             Deterministic 0–100 readiness score
seed_data.py           Synthetic demo data
i18n.py                RU / KZ / EN interface text
tests/                  Core logic tests
.streamlit/config.toml  Streamlit theme
```

## 5-minute demo script

1. Choose **Business representative**.
2. Create a weak task description.
3. Run AI analysis and show at least 3 clarifying questions.
4. Fill missing fields and confirm the card.
5. Show the score increasing and the score breakdown.
6. Publish the task.
7. Change role to **Student / team**.
8. Find the task in the catalogue and submit a proposal.
9. Change role back to **Business representative**.
10. Open the proposal and manually select or reject the team.

This demonstrates the full hackathon scenario inside the MVP rather than on slides.
