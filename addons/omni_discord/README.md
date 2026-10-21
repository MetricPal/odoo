# Omnichannel Discord

A Discord bot as an Omnichannel channel.

1. In the Discord Developer Portal: create an application, add a bot, turn on
   **Message Content Intent**, copy the bot token, and invite the bot to your
   server with permission to read and send messages.
2. **Create channel** › Channel type **Discord** › team. **Credentials**: paste
   the bot token and click **Connect bot** (Discord confirms it is a bot).
3. **Connect & verify**: enter the public inbound URL and the IDs of the server
   channels the bot should read (Developer Mode › Copy Channel ID), **Save**,
   then start the relay with the command shown and **Enable receiving**.
4. Messages arrive in the inbox; replies are reviewed and approved as usual.

The relay (`tools/discord_relay.py`, see ADR 0010) holds Discord's gateway
connection and forwards new text messages, signed with the channel's relay
secret. It never sends to Discord. Keep it running with systemd, Docker or a
terminal multiplexer:

    DISCORD_BOT_TOKEN=... OMNI_RELAY_SECRET=... \
        python3 addons/omni_discord/tools/discord_relay.py --url <inbound URL> --bot <bot ID>

Rules: direct messages and the chosen server channels only; other bots,
attachments and empty messages are ignored. In a server channel the reply
mentions the person it answers and nobody else. Messages sent while the relay
is stopped are not replayed. Discord rate limits are respected (the reply is
retried after Discord's delay); an uncertain send is never repeated.
