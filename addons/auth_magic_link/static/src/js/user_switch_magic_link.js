/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { UserSwitch } from "@web/core/user_switch/user_switch";
import { getLastConnectedUsers } from "@web/core/user";

function getPasswordSubmit(form) {
    return form?.querySelector(".oe_login_buttons > button[type='submit']") || null;
}

function getNativeChooseUser(customChooser) {
    return [...document.querySelectorAll("a, button")].find((element) =>
        element !== customChooser &&
        !element.classList.contains("o_auth_magic_choose_user") &&
        element.textContent.trim().toLowerCase() === "choose a user"
    ) || null;
}

function syncAlerts(form, magic) {
    for (const alert of form.querySelectorAll(".o_auth_form_alert")) {
        const belongsToMagic = alert.classList.contains("o_auth_magic_alert");
        alert.classList.toggle("d-none", belongsToMagic !== magic);
    }
}

function syncChooseUser(form, magic) {
    const customChooser = form.querySelector(".o_auth_magic_choose_user");
    if (!customChooser) {
        return;
    }
    const nativeChooser = getNativeChooseUser(customChooser);
    customChooser.classList.toggle("d-none", !magic || !nativeChooser);
}

function setAuthView(form, view) {
    if (!form) {
        return;
    }

    const magic = view === "magic";
    for (const element of form.querySelectorAll(".o_auth_password_field")) {
        element.classList.toggle("d-none", magic);
    }
    for (const element of form.querySelectorAll(".o_auth_magic_link_field, .o_auth_email_submit")) {
        element.classList.toggle("d-none", !magic);
    }

    const passwordSubmit = getPasswordSubmit(form);
    if (passwordSubmit) {
        passwordSubmit.classList.toggle("d-none", magic);
        passwordSubmit.textContent = "Sign in";
        passwordSubmit.disabled = magic;
    }

    const loginInput = form.querySelector("#login");
    const passwordInput = form.querySelector("#password");
    const passwordTypeInput = form.querySelector(".o_auth_password_type");
    for (const input of [loginInput, passwordInput, passwordTypeInput]) {
        if (input) {
            input.disabled = magic;
        }
    }

    const emailInput = form.querySelector("#email_login");
    if (emailInput) {
        emailInput.disabled = !magic;
    }

    form.dataset.authActiveView = magic ? "magic" : "password";
    syncAlerts(form, magic);
    syncChooseUser(form, magic);

    const toggle = form.querySelector(".o_auth_method_toggle");
    if (toggle) {
        toggle.dataset.authView = magic ? "magic" : "password";
        toggle.textContent = magic ? "Sign in with password" : "Sign in using magic link";
    }
}

function initializeAuthForm() {
    const form = document.querySelector("form.oe_login_form");
    if (!form) {
        return;
    }

    const passwordSubmit = getPasswordSubmit(form);
    if (passwordSubmit) {
        passwordSubmit.textContent = "Sign in";
    }

    const toggle = form.querySelector(".o_auth_method_toggle");
    if (toggle && !toggle.dataset.authInitialized) {
        const initialView = toggle.dataset.authView === "magic" ? "magic" : "password";
        toggle.dataset.authInitialized = "1";
        setAuthView(form, initialView);
        toggle.addEventListener("click", () => {
            setAuthView(form, toggle.dataset.authView === "password" ? "magic" : "password");
        });

        const customChooser = form.querySelector(".o_auth_magic_choose_user");
        customChooser?.addEventListener("click", () => {
            const nativeChooser = getNativeChooseUser(customChooser);
            nativeChooser?.click();
        });

        // The native UserSwitch is an Owl component outside the login form and can
        // render after this script. Only mirror its availability; never move its DOM.
        const observer = new MutationObserver(() => {
            syncChooseUser(form, form.dataset.authActiveView === "magic");
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeAuthForm, { once: true });
} else {
    initializeAuthForm();
}

patch(UserSwitch.prototype, {
    async fillForm(login = "") {
        const loginInput = this.form?.querySelector("input#login");
        const passwordInput = this.form?.querySelector("input#password");
        const emailInput = this.form?.querySelector("input#email_login");

        if (loginInput) {
            loginInput.value = login;
        }
        if (passwordInput) {
            passwordInput.value = "";
        }
        if (emailInput) {
            emailInput.value = "";
            if (login) {
                const known = getLastConnectedUsers().find((entry) => entry.login === login);
                emailInput.value = known?.email || "";
            }
        }

        this.toggleFormDisplay();
    },
});
