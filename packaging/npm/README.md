# @ntdev204/laris-cli

Terminal client for LARIS.

    npm i -g @ntdev204/laris-cli
    laris login --server https://your-laris-server/v1     # saves the address in ~/.laris/config.yaml
    cd my-project && laris init && laris

Needs Node 22 or newer. The terminal interface (Ink and React) runs on Node; the engine behind it is a
self-contained program: no Python, no compiler and no internet are needed to start it. `laris --plain`
starts the plain-text mode of the engine when the interface cannot run, and `laris -p "task"` runs one task
without an interface. If `laris` is not found after installing, add the output of `npm prefix -g`
to your PATH (Windows: that folder; Linux/macOS: its `bin` subfolder) and open a new terminal.

The model, the system prompt, rules, workflows and the knowledge brain run on the LARIS server and are
never downloaded. Your documents, vault, skills and conversations stay in your project folder and in
`~/.laris` (global settings, API key, personal instructions, skills).
