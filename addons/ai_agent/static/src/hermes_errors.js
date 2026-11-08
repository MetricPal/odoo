import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { odooExceptionTitleMap, WarningDialog } from "@web/core/errors/error_dialogs";

// Hermes errors are ordinary warnings for the person (what went wrong, what to do), not server errors.
for (const name of ["HermesUnavailable", "HermesRejected", "HermesUncertain"]) {
    const exception = `odoo.addons.ai_agent.services.hermes.${name}`;
    odooExceptionTitleMap.set(exception, _t("Hermes"));
    registry.category("error_dialogs").add(exception, WarningDialog);
}
