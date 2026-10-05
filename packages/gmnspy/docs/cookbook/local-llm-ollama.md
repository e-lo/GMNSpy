---
title: Run language models locally with Ollama
audience: users
kind: howto
summary: Install Ollama, pull a small Qwen model, and use it for natural-language selection in the Workbench and the CLI. Nothing leaves your machine and there is no API key.
---

# Run language models locally with Ollama

## When to use this

You want natural-language selection ("I-40 EB between South Miami Boulevard and Airport
Boulevard") without sending anything to a cloud provider and without an API key. Ollama runs
open models such as Qwen on your own computer, and gmnspy talks to it over
`http://localhost:11434`.

## Why local

- **Nothing leaves your machine.** Your utterances, street names and project notes go to a
  server on `localhost`, not to a vendor.
- **Better answers by default — in the Workbench.** Because nothing leaves the machine, the
  `"auto"` quality settings turn on for a local endpoint there: grounding (the network's street
  names and route numbers), project notes (`GMNSPY.md`) and the close-match retry. See
  [What is sent, and quality settings](workbench.md#what-is-sent-and-quality-settings). The CLI's
  `gmnspy select` sends only your utterance to the parser, with none of that extra context,
  whichever provider you choose.
- **No API key.** There is nothing to store or rotate.

The trade-off is that a small local model is slower than a hosted one on most laptops, and makes
more mistakes. See [Troubleshooting](#troubleshooting).

## Install Ollama

Use the installer for your system from [ollama.com/download](https://ollama.com/download). The
commands below come from Ollama's own download page and docs; if they have moved on, follow
ollama.com instead.

=== "macOS"

    Download the app from [ollama.com/download](https://ollama.com/download), open the `.dmg` and
    drag **Ollama** into **Applications**. Ollama's docs list macOS 14 Sonoma or newer. When the app
    first starts, it offers to put the `ollama` command on your `PATH`.

    Ollama's download page also offers the same install script as Linux. A Homebrew formula
    exists too, but it is community-maintained and isn't covered by Ollama's docs; the app is the
    supported route.

=== "Linux"

    Ollama's install script:

    ```bash
    curl -fsSL https://ollama.com/install.sh | sh
    ```

    Piping a script into `sh` runs it with your permissions. Download it and read it first if you
    prefer:

    ```bash
    curl -fsSL https://ollama.com/install.sh -o ollama-install.sh
    less ollama-install.sh
    sh ollama-install.sh
    ```

    Ollama's [Linux docs](https://docs.ollama.com/linux) also describe a manual install from a
    tarball.

=== "Windows"

    Download and run **OllamaSetup.exe** from [ollama.com/download](https://ollama.com/download).
    It installs for your account without administrator rights. Ollama's docs list Windows 10 22H2
    or newer. The download page also shows a PowerShell one-liner.

## Start it, then check it

- **macOS and Windows:** open the Ollama app. It runs the server in the background (on Windows,
  from the system tray).
- **Linux:** the install script normally sets Ollama up as a service. If it isn't running, start it
  with `sudo systemctl start ollama`, or run `ollama serve` in a terminal and leave it open.

By default the server listens on `127.0.0.1` port `11434`, which is also gmnspy's default
`llm.ollama.base_url`. Then check each layer:

```bash
ollama list                    # Ollama answers, and shows the models you have (none yet is fine)
uv run gmnspy llm status       # gmnspy can reach it; prints the next step if it can't
uv run gmnspy llm test ollama  # a token-free connection test
```

If Ollama is reachable but has no models, `gmnspy llm status` says
`next step: run: gmnspy llm pull qwen3:4b`.

## Get a model

The default is Qwen 3 4B (`qwen3:4b`). Any one of these does the same thing:

- In a terminal, with Ollama's own command:

    ```bash
    ollama pull qwen3:4b
    ```

- In a terminal, through gmnspy. It shows the size and asks before downloading (`--yes` skips
  the question), then shows a progress bar:

    ```bash
    uv run gmnspy llm pull qwen3:4b
    ```

- In the Workbench: open **Models…**. On the Ollama row, choose a model and click
  **Pull qwen3:4b**. Progress shows in the **Jobs** panel, where you can cancel it. When the pull
  finishes, the model appears in the picker. With models already installed, use
  **Pull another model**.

| Model | Download | When to choose it |
|---|---|---|
| `qwen3:4b` (default) | about 2.5 GB | Most laptops. Enough for one selection at a time. |
| `qwen3:8b` | about 5.2 GB | When `qwen3:4b` keeps misreading your phrases, and you have the memory to spare. Slower. |

Sizes are the download sizes listed on [ollama.com/library/qwen3](https://ollama.com/library/qwen3)
(checked 2026-10-05). The library page marks Qwen 3 as supporting tools, which gmnspy uses.
Ollama doesn't publish memory requirements per model. As a rough guide, you need at least the
download size free in memory, plus some overhead, to run a model comfortably. If your machine
starts swapping, use the smaller model.

The Workbench only pulls into an Ollama on this machine, and only when the Workbench itself is
bound to this machine (the default, `127.0.0.1`). Otherwise, pull from a terminal.

## Use it in the Workbench

1. Start the Workbench: `uv run gmnspy app ./my-network`.
2. Choose **Ollama (local)** in the provider picker next to the utterance box, then pick a model.
   The picker lists the models Ollama has installed.
3. That choice applies to this session. Click **Make default** to save it to your user config.

Or set it in a config file:

```toml
# ~/.config/gmnspy/config.toml (or ./gmnspy.toml for one project)
[select]
provider = "ollama"
model = "qwen3:4b"
```

From a terminal:

```bash
uv run gmnspy select "I-40 EB between South Miami Boulevard and Airport Boulevard" ./my-network --provider ollama --model qwen3:4b
```

## Ollama on another machine

A GPU workstation on your network can run the model for everyone. Point gmnspy at it, either in
**Models… → Ollama server** or in the config file:

```toml
[llm.ollama]
base_url = "http://gpu-box.example:11434"
```

An address that isn't this machine counts as **remote**: your utterances now leave your computer.
So the `"auto"` quality settings turn **off**, the same as for a cloud provider, and the
Workbench won't pull models there (run `ollama pull` on that server). If you trust that
server with your network's street names and project notes, opt back in:

```toml
[llm.quality]
grounding = "on"        # send street names and route numbers
project_context = "on"  # send GMNSPY.md / the ## gmnspy section
match_retry = "on"      # after a miss, retry with the closest real names
```

Ollama only listens on `127.0.0.1` unless it is told otherwise. Ollama's
[FAQ](https://docs.ollama.com/faq) explains how to expose it with `OLLAMA_HOST`.

## Troubleshooting

**"could not reach Ollama at http://localhost:11434" / connection refused.** Ollama isn't running,
or isn't installed. Open the app (macOS/Windows), or run `ollama serve` (Linux), then
`uv run gmnspy llm test ollama`. In the Workbench, click **Check again**. If you changed
`llm.ollama.base_url`, check the address and port.

**"model not found" / the model shows "(not installed)".** Pull it: `ollama pull qwen3:4b`,
`uv run gmnspy llm pull qwen3:4b`, or **Pull** in the Workbench. Model names must match what
`ollama list` prints, including the tag after the colon.

**Slow answers.** Without a supported GPU, Ollama runs on the CPU, and each selection can take
many seconds. `ollama ps` shows whether a loaded model is on the GPU or CPU. Use `qwen3:4b` rather
than a larger model. If requests time out, raise `llm.ollama.timeout_s` (default 120 seconds).

**A model without tool support.** gmnspy asks for a tool call first. If Ollama answers that the
model "does not support tools", gmnspy automatically retries the same model in JSON mode,
constrained to the same schema. You don't need to do anything.

**More misreadings than a hosted model.** Small models make more mistakes. Try, in order:

1. Give the model another attempt after an invalid reply:

    ```toml
    [llm.quality]
    max_repairs = 2
    ```

2. Switch to `qwen3:8b`.
3. Add a `GMNSPY.md` with your local names ("the Beltline" is I 440). See
   [Project notes](workbench.md#project-notes).

## See also

- [Explore networks in the GMNSpy Workbench](workbench.md#language-models-natural-language-selection) — every provider, keys, quality settings.
- [Ollama documentation](https://docs.ollama.com) — install, the CLI, and the API.
