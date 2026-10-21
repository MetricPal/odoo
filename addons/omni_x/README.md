# Omnichannel X

Adds an X account to the **Social** app. X charges for every API call, so this
connector is built around a spending cap.

- **Outgoing**, each after approval: posts (up to 280 characters, up to 4
  images) and replies.
- **Incoming**: **Sync activity** reads your latest 10 posts and 10 mentions.
- **Cost**: prices per action, as published for X's pay-per-use API in 2026
  (third-party summary, see the plan doc): about $0.015 per post, $0.20 for a
  post that contains a link, $0.005 per post read (a sync is priced at $0.10).
  The constants are in `providers/api.py`; update them there if X changes its
  prices.
- **Budget**: every X account starts with a $20 monthly budget (plan decision
  3). Publishing and syncing check it first and stop at the cap; the account
  shows what was spent this month. An account manager can change the budget.
- **Connect**: sign in with X (OAuth 2.0 with PKCE; client ID and secret from
  the developer portal; redirect URL shown on the account). Access tokens last
  two hours and are renewed with the refresh token.
- DMs are not offered.
