import { registry } from "@web/core/registry";
import { WritingToolsPlugin } from "./writing_plugin";

// The simple email editor (no drag-and-drop builder).
registry.category("basic-editor-plugins").add(WritingToolsPlugin.id, WritingToolsPlugin);
