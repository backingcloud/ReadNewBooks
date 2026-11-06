# GitHub release setup

1. `secrets.env` is included with blank API key values so the app has its expected config file.
2. Add your own WeRead and DeepSeek API keys to `secrets.env` on your computer.
3. `.gitignore` excludes `secrets.env` from Git commits. Keep real keys out of GitHub.
4. Run `启动未读之书.bat` on Windows. A separate Python installation is not required when the bundled runtime is present.
5. API calls use your own accounts and may incur charges.
