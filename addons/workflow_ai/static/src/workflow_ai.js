import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { Workflows } from "@workflow_center/workflows";

// Ask agent goes under Actions, after Update record (approved mock, ADR 0012 phase 5).
patch(Workflows.prototype, {
    setup() {
        super.setup();
        const actions = this.blocks.find((block) => block.key === "actions");
        actions.items.splice(1, 0, ["agent", "object_write", _t("Ask agent"), "support_agent",
            _t("An AI agent reads the record and answers"),
            _t("Ask an AI agent about the record, as its department's AI assistant. Write the answer to a field, post it as a note, or follow a Yes or No path. Example: does this leave request follow the policy?"),
            _t("New")]);
    },
});
