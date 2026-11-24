# Defend a Web Research Agent Against Web Attacks

A marketing team uses an SEO agent to research competitors' landing and pricing pages on the web. Anyone outside your team can write a web page, so the agent must treat what it reads as data to analyze, never as instructions to follow.

For this exercise, we built seven fictional competitor pages, in [`web_fixtures/`](web_fixtures/). Each one hides an attack of one of two kinds:

- **Prompt injection:** text aimed at the model, not at people, that tries to change what the agent says or does.
  - Hidden: an invisible keyword block, a fake price in an HTML comment or a script, a hidden link. See [`acme-pricing.html`](web_fixtures/acme-pricing.html).
  - In plain sight: a "note to analysts" telling the agent how to rank the competitor. See [`fenwick-pricing.html`](web_fixtures/fenwick-pricing.html).
- **Server-side request forgery (SSRF):** getting the agent's fetch tool to request an address inside your own network, like an internal admin service.
  - A page can ask the agent to fetch one. See [`glenhaven-pricing.html`](web_fixtures/glenhaven-pricing.html).
  - A URL that looks public can redirect to one.

[`fixtures.json`](web_fixtures/fixtures.json) lists each page's attack, and the SSRF probe URLs. Your job is to defend the agent against both kinds, in its web server and its prompt, then prove each defense works.

## Exercise structure

- [`web_server.py`](web_server.py): the MCP server, with `search`, `naive_fetch` and the `fetch` tool you harden.
- [`.opencode/agents/seo-agent.md`](.opencode/agents/seo-agent.md): the hardened agent, which uses `fetch`.
- [`.opencode/agents/naive-seo-agent.md`](.opencode/agents/naive-seo-agent.md): the same agent with `naive_fetch`, for comparison.
- [`opencode.jsonc`](opencode.jsonc): the agent configuration. It registers `web_server.py` as the `web` MCP server.
- [`fixture_server.py`](fixture_server.py): a local stand-in for the web. It serves the competitor pages, a search over them, an open redirect, and an internal admin service that should never be reachable.
- [`web_fixtures/`](web_fixtures/): the seven competitor pages, and [`fixtures.json`](web_fixtures/fixtures.json), which lists the attacks and the SSRF probe URLs.
- [`run_defenses.py`](run_defenses.py): sends every SSRF probe to both fetch tools, then runs each page's question with both agents and reports which attacks were followed.
- [`shared/agent_runs.py`](../../shared/agent_runs.py): the functions that run an agent.

## Tasks

1. **Understand the attacks.** For each page in [`web_fixtures/`](web_fixtures/), read its entry in [`fixtures.json`](web_fixtures/fixtures.json) and find the planted attack. Decide which defense should stop it: removing what people can't see, marking the page as untrusted, or checking the URLs the agent fetches.
2. **Sanitize pages.** Make `fetch` in [`web_server.py`](web_server.py) return only the text a person would see. Remove scripts, styles, HTML comments, and elements hidden with the `hidden` attribute, `aria-hidden="true"` or a hiding style. Implement `is_hidden` and the two `VisibleText` methods.
3. **Mark pages as untrusted.** Make `wrap_untrusted` wrap the page text in `<untrusted_content>` tags that name the source URL. A page must not be able to close the block early with its own closing tag.
4. **Tell the agent what the tags mean.** Complete [`seo-agent.md`](.opencode/agents/seo-agent.md) so the agent:
   - treats everything between the tags as data, not instructions;
   - tells the user when a page tries to instruct it.
5. **Block internal addresses.** Make `check_url` refuse a URL when any address its hostname resolves to, from `resolve`, isn't public: private, loopback, link-local, unspecified, reserved or multicast. Raise a `ValueError` that says why. Python's [ipaddress module](https://docs.python.org/3/library/ipaddress.html) can classify an address.
6. **Check every redirect.** A URL that passes `check_url` can redirect to an internal address. Make `get_checked` follow redirects itself, and run `check_url` before every request.
7. **Prove the defenses.** Run [`run_defenses.py`](run_defenses.py). For each attack:
   - open both agents' traces in Langfuse, and compare what the model received from `naive_fetch` and from `fetch`;
   - name the layer that stopped it: sanitizing, the untrusted tags with the prompt, or the URL check.

8. **Attack your own defenses.** Write a new competitor page with an attack you think gets past the hardened agent. Add it to [`fixtures.json`](web_fixtures/fixtures.json), with the same fields as the other entries, and run it. Did it get through? Which layer would stop it?

> **Important:** don't change [`naive-seo-agent.md`](.opencode/agents/naive-seo-agent.md). It's the baseline your defenses are measured against.

## Set up and run

1. Set your keys for the model and for your Langfuse project.

   ```bash
   export OPENAI_API_KEY=<your key>
   export OPENAI_BASE_URL=<your base URL>
   export LANGFUSE_PUBLIC_KEY=<your project's public key>
   export LANGFUSE_SECRET_KEY=<your project's secret key>
   export LANGFUSE_BASE_URL=<your Langfuse address>
   ```

2. Run the probes and the pages' questions with both agents. The script starts the fixture server itself.

   ```bash
   python3 run_defenses.py
   ```

## Deliverables

- A completed [`web_server.py`](web_server.py), whose `fetch` sanitizes pages, marks them as untrusted and refuses internal addresses.
- A completed [`seo-agent.md`](.opencode/agents/seo-agent.md).
- The report from `run_defenses.py`: `fetch` blocks every SSRF probe, including the one that goes through the open redirect, and the hardened agent follows none of the seven planted attacks.
