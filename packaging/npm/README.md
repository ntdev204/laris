# @ntdev204/laris-cli

Terminal client for LARIS.

    npm i -g @ntdev204/laris-cli
    laris login --server https://your-laris-server/v1     # saves the address in ~/.laris/config.yaml
    cd my-project && laris init && laris

The model, the system prompt, rules, workflows and the knowledge brain run on the LARIS server and are
never downloaded. Your documents, vault, skills and conversations stay in your project folder and in
`~/.laris` (global settings, API key, personal instructions, skills).
