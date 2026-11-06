# GitHub release setup

1. `secrets.env` is included with blank API key values so the app has its expected config file.
2. Add your own WeRead and DeepSeek API keys only in your local copy.
3. This public repository tracks `secrets.env` while it is blank. The `.gitignore` rule cannot protect changes to a file already tracked by Git. After adding keys, never commit or push changes to `secrets.env`. For the simplest safe setup, download the source archive from GitHub and extract it before adding keys, or make a private local copy outside a Git checkout.
4. Run `启动未读之书.bat` on Windows. A separate Python installation is not required when the bundled runtime is present.
5. API calls use your own accounts and may incur charges.
