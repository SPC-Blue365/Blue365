# CLAUDE.md

Guidance for AI assistants (and humans) working in this repository.

## What this is

A single-page **Streamlit chatbot template**. It renders a chat UI that streams
responses from OpenAI's `gpt-3.5-turbo` model. The user supplies their own
OpenAI API key at runtime through a password field in the UI — there is no
backend, database, or auth layer. This is a demo/template app derived from
Streamlit's ["Build conversational apps"](https://docs.streamlit.io/develop/tutorials/llms/build-conversational-apps)
tutorial.

## Layout

The entire codebase is small and flat:

| Path | Purpose |
| --- | --- |
| `streamlit_app.py` | The whole application — UI, session state, and OpenAI streaming call. |
| `requirements.txt` | Python dependencies (`streamlit`, `openai`). |
| `README.md` | User-facing run instructions. |
| `.devcontainer/devcontainer.json` | Codespaces/dev container config; installs deps and auto-runs the app on port 8501. |
| `.github/CODEOWNERS` | Ownership (`@streamlit/community-cloud`). |
| `LICENSE` | Apache 2.0. |

There are no subpackages, modules, or `src/` directory — new code generally
belongs in `streamlit_app.py` unless a feature clearly warrants its own module.

## How the app works

`streamlit_app.py` runs top-to-bottom on every interaction (Streamlit reruns the
whole script per event). Key points:

1. The OpenAI API key is read from a `st.text_input(type="password")`. Until a
   key is entered, the app shows an info banner and stops.
2. Chat history lives in `st.session_state.messages` (a list of
   `{"role", "content"}` dicts) so it survives Streamlit reruns.
3. On new input, the message is appended to session state, then the full history
   is sent to `client.chat.completions.create(..., stream=True)`.
4. The reply is streamed to the UI with `st.write_stream(...)` and appended back
   to session state.

## Development

### Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

The app serves on `http://localhost:8501`.

### Dev container / Codespaces

Opening in a dev container installs requirements and auto-starts the app
(`streamlit run streamlit_app.py`) on port 8501 — see
`.devcontainer/devcontainer.json`.

### Dependencies

Add runtime dependencies to `requirements.txt` (unpinned, matching the existing
style). There is no separate dev/test dependency file.

## Conventions

- **Python 3.11** is the target (per the dev container image).
- Keep the app runnable as a single script; prefer Streamlit-native widgets and
  `st.session_state` over external state.
- Match the existing style: 4-space indentation, plain `import`s at the top,
  explanatory comments before non-obvious blocks (as in the current file).
- **Never commit API keys or secrets.** Keys are entered at runtime by the user;
  if you need to store one for local dev, use `.streamlit/secrets.toml` and
  `st.secrets` (git-ignored) — do not hardcode.

## Tooling notes

- There is **no test suite, linter config, or CI workflow** in this repo. If you
  add tests or checks, wire them up rather than assuming they exist.
- After changing `streamlit_app.py`, verify the app still starts
  (`streamlit run streamlit_app.py`) — this is the primary smoke test.

## Git workflow

- The default branch is `main`.
- Do not push directly to `main`; work on a feature branch and open a PR.
- Do not commit secrets or the `.streamlit/secrets.toml` file.
