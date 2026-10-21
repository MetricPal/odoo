# Omnichannel Messenger

Private Facebook Page conversations in the Omnichannel inbox.

1. **Create channel** › Channel type **Facebook Messenger** › team.
2. **Credentials**: paste a Page access token (Meta app › Messenger › Settings ›
   Access tokens; needs `pages_messaging`) and click **Connect Page**. Meta
   confirms it is a Page token; it is kept in the encrypted vault.
3. **Connect & verify**: enter your public HTTPS webhook URL and the app secret,
   **Save webhook**, then paste the URL and verify token into the Meta app's
   Messenger webhook settings and subscribe the Page to `messages`. When Meta
   has verified the callback, **Enable receiving**.
4. Messages arrive in the inbox. Replies are drafted, approved and sent like
   other channels.

Rules:
- Only text messages to the Page are received; the Page's own echoes,
  attachments, reactions and read receipts are ignored.
- A reply is sent only within 24 hours of the person's last message, checked
  against Meta's conversation record just before sending (Messenger's standard
  messaging window). Message tags and sponsored messages are not used.
- An uncertain send is reported as "unknown" and never retried automatically.

The webhook handshake (GET) is answered by Omnichannel's inbound route, shared
with WhatsApp. Facebook Page posts and comments are in the Social app
(`omni_facebook`).
