# @ntdev204/laris-cli

Terminal client for LARIS.

    npm i -g @ntdev204/laris-cli
    laris login --server https://your-laris-server/v1     # saves the address in ~/.laris/config.yaml
    cd my-project && laris init && laris

Needs Node 18+ and internet on first run. No Python or compiler is required: the first run installs a private
Python when your machine has none that fits (set `LARIS_NO_DOWNLOAD=1` to forbid it, `LARIS_PYTHON` to choose one).
If `laris` is not found afterwards, add the output of `npm prefix -g` to your PATH (Windows: that folder;
Linux/macOS: its `bin` subfolder) and open a new terminal.

The model, the system prompt, rules, workflows and the knowledge brain run on the LARIS server and are
never downloaded. Your documents, vault, skills and conversations stay in your project folder and in
`~/.laris` (global settings, API key, personal instructions, skills).
