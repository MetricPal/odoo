# Omnichannel Instagram

Manage incoming public activity and private text, publish approved single-photo
posts, and reply from **Social**.

Connect an existing professional Instagram account linked to a Facebook Page,
using that Page's access token. [Create a Meta app](https://developers.facebook.com/apps/).
This version uses Facebook Login, not Instagram Login. Grant `instagram_basic`,
`instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_messages`,
and the relevant Page permissions (`pages_read_engagement`, `pages_manage_metadata`).
App review/Advanced Access and Page task permissions may be required for real users.
The connector derives the Instagram account from the token's linked Page; no bot
ID or database name is requested. Graph API version: `v25.0`.

For photo publishing, set the public HTTPS address of this Odoo server and upload
a JPEG. Do not run a public test post to verify credentials. Connect and sync are
read-only provider operations. Every post or reply has its own review and explicit
execution. Private replies need a recent received message and recipient agreement.

See [Social scope and security](../omni_social/README.md). Account tokens, app
approval, callback reachability and real delivery still need live verification.
