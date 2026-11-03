# Submission Contents

This folder is a clean, fixed snapshot of the core code and configuration used for the Perpetual Alpha 2026 PAS Testnet submission.

Included files:

- `pas_pairs_live.py`: hourly pair-reversion execution runner for PAS Testnet.
- `pas_pairs_shadow.py`: public-data signal monitor without order execution.
- `official_score_validation.py`: historical validation using the competition scoring formula.
- `pas_pairs_config.json`: strategy parameters for BTC-EWY and BTC-ETH.
- `pas_pairs_live_config.json`: endpoint and runtime configuration.
- `bot_control.py`: local run/pause control helper.
- `pas_readonly_check.py`: read-only account and market status check.
- `requirements.txt`: Python dependencies.
- `.env.example`: variable names only. No secret is included.
- `README.md`: Korean and English project overview and reproducibility instructions.

Excluded deliberately:

- private keys, API credentials, wallet files, runtime state, logs, and market data;
- collection utilities and exploratory research scripts;
- local automation files tied to a specific Windows machine.

The live runtime remains in the repository root. This submission snapshot is not used by the running bot.
