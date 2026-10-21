/** @odoo-module **/

import { session } from "@web/session";
import { user, getLastConnectedUsers, setLastConnectedUsers } from "@web/core/user";

// The native "Choose a user" list is kept in this browser only. Remember the
// signed-in user's own email next to their login so the magic-link form can be
// prefilled without asking the server about other accounts.
const email = session.user_email;
if (email && user.userId) {
    const users = getLastConnectedUsers();
    if (users.some((entry) => entry.userId === user.userId && entry.email !== email)) {
        setLastConnectedUsers(
            users.map((entry) => (entry.userId === user.userId ? { ...entry, email } : entry))
        );
    }
}
