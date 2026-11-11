import { Component, onWillDestroy, onWillStart, proxy, signal, t, useProps } from "@odoo/owl";
import { Plugin } from "@html_editor/plugin";
import { toolbarButtonProps } from "@html_editor/main/toolbar/toolbar";
import { useDropdownAutoVisibility } from "@html_editor/toolbar_dropdown_hook";
import { withSequence } from "@html_editor/utils/resource";
import { isContentEditable } from "@html_editor/utils/dom_info";
import { Dialog } from "@web/core/dialog/dialog";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

import { SuggestionRequest, TONES, countChars, toolLabel } from "../writing_client";

const MODEL = "mailing.mailing";
const FIELD = "body_arch";
let toolsPromise = null;

/** What Writing tools offer on email bodies, asked once per page. */
function loadTools(orm) {
    toolsPromise ||= orm.call("mi.writing", "get_tools", [MODEL, FIELD]).catch(() => ({ available: false }));
    return toolsPromise;
}
export function resetToolsCache() {
    toolsPromise = null;
}

/** The "Writing tools" button of the email editor's text toolbar (board 8.2). */
export class WritingToolbarMenu extends Component {
    static template = "marketing_intel_writing.ToolbarMenu";
    static components = { Dropdown, DropdownItem };
    props = useProps({
        ...toolbarButtonProps,
        onSelected: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ tools: { available: false, tools: [] } });
        this.menuRef = signal.ref();
        useDropdownAutoVisibility(this.env.overlayState, this.menuRef);
        onWillStart(async () => {
            this.state.tools = await loadTools(this.orm);
        });
    }
    get tones() { return TONES(); }
    label(tool) { return toolLabel(tool, false, this.state.tools.languages); }
    pick(tool, option) {
        this.props.onSelected({ tool, option, tools: this.state.tools });
    }
}

/** The suggestion for the selected text of an email body, with Use / Try again / Discard. */
export class WritingSuggestionDialog extends Component {
    static template = "marketing_intel_writing.SuggestionDialog";
    static components = { Dialog };
    props = useProps({
        close: t.function(),
        insert: t.function(),
        originalText: t.string(),
        tool: t.string(),
        option: t.any().optional(false),
        tools: t.object(),
        resId: t.any().optional(false),
    });

    setup() {
        this.orm = useService("orm");
        this.state = proxy({
            tool: this.props.tool, option: this.props.option, state: this.props.tool === "custom" ? "custom" : "waiting",
            text: "", warning: "", error: "", customText: "",
        });
        this.request = new SuggestionRequest(this.orm, (result) => Object.assign(this.state, result));
        onWillDestroy(() => this.request.cancel());
        if (this.state.state === "waiting") {
            this.ask();
        }
    }
    get title() { return toolLabel(this.state.tool, this.state.option, this.props.tools.languages); }
    get count() {
        return _t("%(before)s → %(after)s characters",
            { before: countChars(this.props.originalText), after: countChars(this.state.text) });
    }
    ask() {
        Object.assign(this.state, { state: "waiting", text: "", warning: "", error: "" });
        this.request.start({
            resModel: MODEL, field: FIELD, resId: this.props.resId, tool: this.state.tool,
            text: this.props.originalText, option: this.state.option, values: {},
        });
    }
    onCustomKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.askCustom();
        }
    }
    askCustom() {
        const instruction = this.state.customText.trim();
        if (instruction) {
            this.state.option = instruction;
            this.ask();
        }
    }
    use() {
        this.props.insert(this.state.text);
        this.props.close();
    }
    discard() {
        this.request.cancel();
        this.props.close();
    }
}

/** Writing tools on the selected text of an email body, beside Odoo's own Translate button. */
export class WritingToolsPlugin extends Plugin {
    static id = "miWritingTools";
    static dependencies = ["selection", "history", "dom", "split"];
    /** @type {import("plugins").EditorResources} */
    resources = {
        toolbar_groups: withSequence(44, { id: "mi_writing" }),
        toolbar_items: [
            {
                id: "mi_writing",
                groupId: "mi_writing",
                namespaces: ["compact", "expanded"],
                description: _t("Writing tools"),
                isAvailable: (selection) => !selection.isCollapsed,
                isDisabled: this.cannotReplace.bind(this),
                Component: WritingToolbarMenu,
                props: { onSelected: (choice) => this.open(choice) },
            },
        ],
    };

    cannotReplace(selection = this.dependencies.selection.getEditableSelection()) {
        const isEmpty = !selection.toString().replace(/\s+/g, "");
        const locked = this.dependencies.selection
            .getTargetedNodes()
            .find((node) => this.dependencies.split.isUnsplittable(node) || !isContentEditable(node));
        return Boolean(locked || isEmpty);
    }

    open({ tool, option, tools }) {
        const selection = this.dependencies.selection.getEditableSelection();
        const originalText = selection.toString() || "";
        this.services.dialog.add(WritingSuggestionDialog, {
            tool, option, tools, originalText,
            resId: this.config.record?.resId || false,
            insert: (text) => {
                this.dependencies.selection.setSelection(selection);
                this.dependencies.dom.insert(text);
                this.dependencies.history.commit();
            },
        });
    }
}
