import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useSortable } from "@web/core/utils/sortable_owl";
import { useService } from "@web/core/utils/hooks";

import { Component, onWillStart, proxy, signal, useProps } from "@odoo/owl";

export const FAVORITE_LIMIT = 12;
export const RECENT_VISIBLE_LIMIT = 3;
export const AUTOMATION_LIMIT = 6;
const ATTENTION_VISIBLE_LIMIT = 3;
const EXCLUDED_FAVORITE_MENU_XMLIDS = new Set([
    "ai_home.menu_ai_home_root",
    "base.menu_management",
    "base.menu_administration",
]);

export function splitDashboardItems(items) {
    return {
        attention: items.filter((item) => item.section === "attention"),
        automations: items.filter((item) => item.section === "automation"),
        recent: items.filter((item) => item.section === "recent"),
    };
}

export function buildFavoriteSlots(favorites) {
    return [
        ...favorites.slice(0, FAVORITE_LIMIT),
        ...Array(Math.max(0, FAVORITE_LIMIT - favorites.length)).fill(null),
    ];
}

export function compactFavoriteIds(favoriteIds) {
    return buildFavoriteSlots(favoriteIds.filter((id) => id !== null && id !== undefined));
}

export function moveFavoriteToSlot(favoriteIds, draggedId, targetIndex) {
    const compactIds = compactFavoriteIds(favoriteIds).filter((id) => id !== null);
    const sourceIndex = compactIds.findIndex((id) => String(id) === String(draggedId));
    const numericTargetIndex = Number(targetIndex);
    if (
        sourceIndex < 0 ||
        !Number.isInteger(numericTargetIndex) ||
        numericTargetIndex < 0
    ) {
        return buildFavoriteSlots(compactIds);
    }
    const [movedId] = compactIds.splice(sourceIndex, 1);
    compactIds.splice(Math.min(numericTargetIndex, compactIds.length), 0, movedId);
    return buildFavoriteSlots(compactIds);
}

export function insertFavoriteAtSlot(favoriteIds, appId, targetIndex) {
    const compactIds = compactFavoriteIds(favoriteIds).filter((id) => id !== null);
    if (
        compactIds.some((id) => String(id) === String(appId)) ||
        compactIds.length >= FAVORITE_LIMIT
    ) {
        return buildFavoriteSlots(compactIds);
    }
    const numericTargetIndex = Number(targetIndex);
    const boundedTargetIndex = Number.isInteger(numericTargetIndex)
        ? Math.max(0, Math.min(numericTargetIndex, compactIds.length))
        : compactIds.length;
    compactIds.splice(boundedTargetIndex, 0, appId);
    return buildFavoriteSlots(compactIds);
}

export class WorkDashboard extends Component {
    static template = "ai_home.WorkDashboard";
    props = useProps();
    favoritesRootRef = signal.ref();

    setup() {
        this.menuService = useService("menu");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.state = proxy({
            items: [],
            favoriteIds: this.loadFavoriteIds(),
            showAllAttention: false,
            showAllApps: false,
            showAllRecent: false,
        });
        this.favoriteDropSlotIndex = null;
        this.draggedFavoriteOrigin = null;
        this.reservedFavoriteEmptySlot = null;
        useSortable({
            ref: this.favoritesRootRef,
            elements:
                ".o_ai_home_sortable_item.o_is_draggable, " +
                ".o_ai_home_favorite_item.o_is_empty",
            groups: ".o_ai_home_sortable_group",
            connectGroups: true,
            enable: () =>
                this.favoriteCount > 1 ||
                (this.state.showAllApps && this.hasFavoriteCapacity),
            ignore: ".o_ai_home_favorite_toggle, .o_is_empty",
            cursor: "grabbing",
            touchDelay: 150,
            placeholderClasses: ["o_ai_home_favorite_placeholder"],
            followingElementClasses: ["o_ai_home_favorite_dragging"],
            onDragStart: ({ element }) => {
                this.favoriteDropSlotIndex = null;
                this.draggedFavoriteOrigin = element.dataset.favoriteOrigin;
            },
            onElementEnter: ({ element }) => {
                this.favoriteDropSlotIndex = element.closest(
                    ".o_ai_home_favorite_grid"
                )
                    ? Number(element.dataset.slotIndex)
                    : null;
            },
            onGroupEnter: ({ group }) => {
                if (group.dataset.sortableGroup === "favorites") {
                    this.reserveFavoriteEmptySlot(group);
                } else {
                    this.favoriteDropSlotIndex = null;
                    this.releaseFavoriteEmptySlot();
                }
            },
            onGroupLeave: ({ group }) => {
                if (group.dataset.sortableGroup === "favorites") {
                    this.releaseFavoriteEmptySlot();
                }
            },
            onDrop: (params) => this.handleFavoriteDrop(params),
            onDragEnd: () => {
                this.releaseFavoriteEmptySlot();
                this.favoriteDropSlotIndex = null;
                this.draggedFavoriteOrigin = null;
            },
        });

        onWillStart(async () => {
            this.state.items = await this.orm.call(
                "ai.home.item",
                "get_dashboard_items",
                []
            );
            this.normalizeFavoriteIds();
        });
    }

    get favoriteStorageKey() {
        return `ai_home.favorite_apps.${user.userId || "anonymous"}`;
    }

    get accessibleApps() {
        return this.menuService
            .getApps()
            .filter((app) => !EXCLUDED_FAVORITE_MENU_XMLIDS.has(app.xmlid) && app.actionID);
    }

    get sections() {
        return splitDashboardItems(this.state.items);
    }

    get attentionItems() {
        return this.state.showAllAttention
            ? this.sections.attention
            : this.sections.attention.slice(0, ATTENTION_VISIBLE_LIMIT);
    }

    get automationItems() {
        return this.sections.automations.slice(0, AUTOMATION_LIMIT);
    }

    get recentItems() {
        return this.state.showAllRecent
            ? this.sections.recent
            : this.sections.recent.slice(0, RECENT_VISIBLE_LIMIT);
    }

    get favoriteApps() {
        const appsById = new Map(this.accessibleApps.map((app) => [String(app.id), app]));
        return (this.state.favoriteIds || []).map(
            (id) => (id === null ? null : appsById.get(String(id))) || null
        );
    }

    get favoriteSlots() {
        return buildFavoriteSlots(this.favoriteApps);
    }

    get nonFavoriteApps() {
        return this.accessibleApps.filter((app) => !this.isFavorite(app));
    }

    get favoriteCount() {
        return this.favoriteApps.filter(Boolean).length;
    }

    get hasFavoriteCapacity() {
        return this.favoriteCount < FAVORITE_LIMIT;
    }

    loadFavoriteIds() {
        try {
            const storedValue = browser.localStorage.getItem(this.favoriteStorageKey);
            if (storedValue === null) {
                return null;
            }
            const storedIds = JSON.parse(storedValue);
            return Array.isArray(storedIds) ? storedIds.slice(0, FAVORITE_LIMIT) : null;
        } catch {
            return null;
        }
    }

    normalizeFavoriteIds() {
        const accessibleIds = new Set(this.accessibleApps.map((app) => String(app.id)));
        const hasStoredPreference = Array.isArray(this.state.favoriteIds);
        const seenIds = new Set();
        const normalizedIds = (this.state.favoriteIds || []).flatMap((id) => {
            const normalizedId = String(id);
            if (id === null || !accessibleIds.has(normalizedId) || seenIds.has(normalizedId)) {
                return [];
            }
            seenIds.add(normalizedId);
            return [id];
        });
        if (!hasStoredPreference) {
            normalizedIds.push(...this.accessibleApps.slice(0, 10).map((app) => app.id));
        }
        this.state.favoriteIds = buildFavoriteSlots(normalizedIds);
    }

    saveFavoriteIds() {
        try {
            browser.localStorage.setItem(
                this.favoriteStorageKey,
                JSON.stringify(this.state.favoriteIds)
            );
        } catch {
            this.notification.add(_t("Favorites could not be saved in this browser."), {
                type: "warning",
            });
        }
    }

    isFavorite(app) {
        return (this.state.favoriteIds || []).some((id) => String(id) === String(app.id));
    }

    toggleFavorite(app) {
        const favoriteIds = compactFavoriteIds(this.state.favoriteIds || []).filter(
            (id) => id !== null
        );
        if (this.isFavorite(app)) {
            this.state.favoriteIds = buildFavoriteSlots(
                favoriteIds.filter((id) => String(id) !== String(app.id))
            );
        } else {
            if (favoriteIds.length >= FAVORITE_LIMIT) {
                this.notification.add(_t("Favorites already contains 12 apps."), {
                    type: "warning",
                });
                return;
            }
            this.state.favoriteIds = buildFavoriteSlots([...favoriteIds, app.id]);
        }
        this.saveFavoriteIds();
    }

    reserveFavoriteEmptySlot(group) {
        this.releaseFavoriteEmptySlot();
        if (this.draggedFavoriteOrigin !== "available") {
            return;
        }
        const emptySlots = group.querySelectorAll(".o_ai_home_favorite_item.o_is_empty");
        this.reservedFavoriteEmptySlot = emptySlots[emptySlots.length - 1] || null;
        this.reservedFavoriteEmptySlot?.classList.add("o_is_reserved_empty");
    }

    releaseFavoriteEmptySlot() {
        this.reservedFavoriteEmptySlot?.classList.remove("o_is_reserved_empty");
        this.reservedFavoriteEmptySlot = null;
    }

    handleFavoriteDrop({ element, parent, previous, next }) {
        if (parent?.dataset.sortableGroup !== "favorites") {
            return;
        }
        const fallbackIndex = next?.dataset.slotIndex
            ? Number(next.dataset.slotIndex)
            : Math.min(Number(previous?.dataset.slotIndex || -1) + 1, FAVORITE_LIMIT - 1);
        const targetIndex = Number.isInteger(this.favoriteDropSlotIndex)
            ? this.favoriteDropSlotIndex
            : Number.isInteger(fallbackIndex)
              ? fallbackIndex
              : this.state.favoriteIds.indexOf(null);
        const app = this.accessibleApps.find(
            (candidate) => String(candidate.id) === String(element.dataset.appId)
        );
        if (!app) {
            return;
        }
        const favoriteIds =
            element.dataset.favoriteOrigin === "available"
                ? insertFavoriteAtSlot(this.state.favoriteIds, app.id, targetIndex)
                : moveFavoriteToSlot(this.state.favoriteIds, app.id, targetIndex);
        this.state.favoriteIds = favoriteIds;
        this.saveFavoriteIds();
    }

    openFavoriteSlot(app) {
        if (app) {
            return this.menuService.selectMenu(app);
        }
        this.state.showAllApps = true;
    }

    openApp(app) {
        return this.menuService.selectMenu(app);
    }

    async openDashboardItem(item) {
        this.notification.add(item.subtitle || _t("Dashboard item opened."), {
            title: item.name,
            type: item.tone === "danger" ? "warning" : "info",
        });
        if (item.section === "recent") {
            const markedSeen = await this.orm.call(
                "ai.home.item",
                "mark_recent_seen",
                [item.id]
            );
            if (markedSeen) {
                this.state.items = this.state.items.filter((current) => current.id !== item.id);
            }
        }
    }

    getAppInitial(app) {
        return (app.name || "?").trim().slice(0, 1).toUpperCase();
    }
}

registry.category("actions").add("ai_home.dashboard", WorkDashboard);
