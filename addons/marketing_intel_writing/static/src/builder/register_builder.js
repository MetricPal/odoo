import { registry } from "@web/core/registry";
import { WritingToolsPlugin } from "@marketing_intel_writing/editor/writing_plugin";

// The email builder (loaded on demand with the mailing editor).
registry.category("mass_mailing-plugins").add(WritingToolsPlugin.id, WritingToolsPlugin);
