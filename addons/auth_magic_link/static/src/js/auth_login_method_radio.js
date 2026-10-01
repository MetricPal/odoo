/** @odoo-module **/

import { registry } from "@web/core/registry";
import { RadioField, radioField } from "@web/views/fields/radio/radio_field";

export class AuthLoginMethodRadio extends RadioField {
    static template = "auth_magic_link.AuthLoginMethodRadio";

    get widgetOptions() {
        return this.props.options || this.props.fieldInfo?.options || {};
    }

    get visibleItems() {
        return this.items;
    }

    get adminEmailReady() {
        return Boolean(this.props.record?.data?.auth_admin_has_valid_email);
    }

    get outboundEmailReady() {
        return Boolean(this.props.record?.data?.auth_outbound_email_ready);
    }

    get emailReady() {
        return this.adminEmailReady && this.outboundEmailReady;
    }

    get oauthReady() {
        const fieldName = this.widgetOptions.oauth_ready_field || "auth_admin_has_active_oauth";
        return Boolean(this.props.record?.data?.[fieldName]);
    }

    isOptionDisabled(value) {
        if (value === "magic_link" || value === "both") {
            return !this.emailReady;
        }
        if (value === "oauth_only") {
            return !this.oauthReady;
        }
        return false;
    }

    async selectLoginMethod(ev) {
        await this.props.record.update({
            [this.props.name]: ev.target.value,
        });
    }

    description(value) {
        return {
            password: "Keeps Odoo's standard username/login and password form unchanged.",
            magic_link: "Users enter their email and receive a short-lived, single-use sign-in link.",
            both: "Users can choose standard password login or an email verification link.",
            oauth_only: "Disables local password and email-link login; users must use an enabled OAuth provider.",
        }[value] || "";
    }

    blocker(value) {
        if (value === "magic_link" || value === "both") {
            const blockers = [];
            if (!this.adminEmailReady) {
                blockers.push("System Administrator needs a valid email address.");
            }
            if (!this.outboundEmailReady) {
                blockers.push("Configure an active outgoing mail server.");
            }
            return blockers.length ? `Not available: ${blockers.join(" ")}` : "";
        }
        if (value === "oauth_only" && !this.oauthReady) {
            return "Not available: The System Administrator is not linked to an enabled OAuth provider.";
        }
        return "";
    }
}

export const authLoginMethodRadio = {
    ...radioField,
    component: AuthLoginMethodRadio,
};

registry.category("fields").add("auth_login_method_radio", authLoginMethodRadio);
