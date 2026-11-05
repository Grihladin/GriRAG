<img src="docs/images/icon.svg" width="64" height="64" alt="">

# GriRAG

Ask questions about your PDFs, Word files and web pages. GriRAG reads every page as an image, so tables,
charts and layout survive, and answers with citations to the exact pages it used. Ask a quick question, or use
Research mode to have a conversation with a deep agent that searches and reads your documents in several steps.
It runs on your computer, for one user.

**[Read the documentation →](https://gri-rag.mintlify.site)**

<img src="docs/images/screenshot-home.png" alt="The GriRAG home page: an Ask box with Ask and Research modes, and the first page of each document in the library.">

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/pipeline-dark.png">
  <img src="docs/images/pipeline.png" alt="Add a document: PDF, DOCX or link, then PDF or screenshot (Gotenberg), page images (PyMuPDF), page vectors (Voyage via OpenRouter), Qdrant. Ask a question: question, query vector, 8 best pages from Qdrant, vision model, answer with page citations.">
</picture>

Every document becomes page images, and each page is embedded with a multimodal model and stored in Qdrant.
A question is embedded the same way, and the 8 closest pages go to a vision model, which answers only from them
and cites each page it used ([S1], [S2], …). More in the
[architecture docs](https://gri-rag.mintlify.site/architecture).

The approach follows [PixelRAG](https://github.com/StarTrail-org/PixelRAG) (Apache-2.0). No PixelRAG code is
used; the answer prompt is adapted from its `SYSTEM_PROMPT_EVIDENCE_QA`.

## Quick start

Runs on macOS and Linux. Needs Docker ([Docker Desktop](https://www.docker.com/products/docker-desktop/), or on
Linux Docker Engine with the Compose plugin), `make` (macOS: `xcode-select --install`; Debian/Ubuntu:
`sudo apt install make`) and an OpenRouter account with a few dollars of credit. Adding pages costs about $1 per
1,000, a question under $0.001.

1. Clone and create the settings file:
   ```bash
   git clone https://github.com/Grihladin/GriRAG.git && cd GriRAG
   cp .env.example .env
   ```
2. Create a key at https://openrouter.ai/settings/keys and put it into `.env` as `OPENROUTER_API_KEY`.
3. Start it (the first build takes a few minutes; on macOS it opens Docker Desktop if needed):
   ```bash
   make up
   ```
4. Open http://127.0.0.1:8000, click **Add**, drop in a PDF or paste a link, and ask a question once its status
   is ready.

Your library lives in `data/`. `make down` stops everything; after a `git pull`, run `make up` again.

## Limitations

- No OCR or keyword search. Follow-up questions are in Research mode, which costs several model calls a
  question.
- Answers read the 8 best pages (`ANSWER_PAGES`), so facts spread over more pages can be missed.
- Web pages keep their first 50 pages; logged-in and paywalled sites index the login page.
- A web page is captured once, when added: later changes to the site don't reach the library. Delete it and add
  the link again to update it.
- Web capture only scrolls the main page, so a saved page can miss content inside scrolling panels, behind clicks or
  tabs, and rows that long lists drop once they scroll away. On a very slow load a chart can stay blank.
- Files can only be PDF or Word (`.docx`), since almost anything can be converted to one of them.
- No authentication: keep it on 127.0.0.1.

## How safe is Gotenberg?

Every link you add opens in a real browser and its scripts run there, and Word files go through LibreOffice, both
inside the Gotenberg container. That makes it the riskiest part of GriRAG, so it is boxed in:

- It cannot see `data/` or your OpenRouter key: nothing is mounted into it and the key reaches only the app.
- It runs as a non-root user with `no-new-privileges` and a 2 GB memory limit, and its port listens on 127.0.0.1 only.
- The browser refuses private addresses, so a page cannot load your network, your computer, Qdrant or the app.

It is not a full sandbox. Chromium runs with `--no-sandbox`, so the container is the only wall, and the address rule
binds the browser, not the container. A site that exploits a browser bug would get a shell there with internet
access, and could reach Qdrant and the app directly. Neither has a login, so it could read or delete your library.
Add links you trust, and keep Gotenberg up to date.

## License

[MIT](LICENSE)
