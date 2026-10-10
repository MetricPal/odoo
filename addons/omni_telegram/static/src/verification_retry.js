import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

export function verificationRetry(env, action) {
    const notification = useService("notification");
    const orm = useService("orm");
    const actions = useService("action");
    const dialog = useService("dialog");
    const { model, record_id: id, method, message, details } = action.params;
    // This action can only repeat the two read-only provider checks.
    if (!Number.isInteger(id) || id <= 0 || !(
        (model === "omni.account" && method === "action_verify_telegram_bot") ||
        (model === "omni.channel" && method === "action_setup_verify_webhook")
    )) return;
    let busy = false;
    const close = notification.add(message, {
        title: _t("Verification interrupted"), type: "warning", sticky: true,
        buttons: [
            { name: _t("Retry"), primary: true, onClick: async () => {
                if (busy) return;
                busy = true;
                try {
                    const result = await orm.call(model, method, [[id]]);
                    close();
                    if (result) await actions.doAction(result);
                    if (result?.tag === "display_notification" && result.params?.type === "success") {
                        await actions.doAction("soft_reload");
                    }
                } finally { busy = false; }
            } },
            { name: _t("Details"), onClick: () => dialog.add(AlertDialog, {
                title: _t("Verification details"), body: details,
            }) },
        ],
    });
}
registry.category("actions").add("omni_telegram.verification_retry", verificationRetry);
