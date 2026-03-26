import { useCallback, useEffect, useMemo, useState } from "react";
import { DndContext, type DragEndEvent, PointerSensor, closestCenter, useSensor, useSensors } from "@dnd-kit/core";
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
    ApiError,
    createCategory,
    createCategoryGroup,
    deactivateCategory,
    deleteCategoryGroup,
    fetchAllCategories,
    fetchCategoryGroups,
    reactivateCategory,
    renameCategoryGroup,
    reorderCategoriesInGroup,
    reorderCategoryGroups,
    updateCategory,
} from "../api";
import LoadingOverlay from "../components/LoadingOverlay";
import StatusMessage from "../components/StatusMessage";
import { formatYearMonth } from "../format";
import { useStatus } from "../hooks";
import type { Category, CategoryGroup } from "../types";

interface PendingDeactivation {
    categoryId: string;
    categoryName: string;
    affectedMonths: string[];
}

// --- Sortable wrappers (dnd-kit) ----------------------------------------------

function SortableGroupRow({
    group,
    titleBar,
    children,
}: {
    group: CategoryGroup;
    titleBar: React.ReactNode;
    children: React.ReactNode;
}) {
    // Each group is itself a sortable item in the "groups" SortableContext.
    // `titleBar` renders inside the flex header (drag handle + name + buttons);
    // `children` are siblings below the header so the table layout isn't collapsed
    // by flex sizing. System groups (Unassigned) opt out of dnd-kit entirely —
    // they're pinned to the bottom and don't participate in user reordering.
    const sortable = useSortable({
        id: `group:${group.groupId}`,
        disabled: group.system,
    });
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = sortable;
    return (
        <section
            ref={setNodeRef}
            style={{
                transform: CSS.Transform.toString(transform),
                transition,
                opacity: isDragging ? 0.5 : 1,
            }}
            className="category-group-block"
        >
            <header className="category-group-header">
                {group.system ? (
                    <span className="drag-handle drag-handle-disabled" title="System group — fixed position">
                        🔒
                    </span>
                ) : (
                    <button className="drag-handle" title="Drag to reorder group" {...attributes} {...listeners}>
                        ⋮⋮
                    </button>
                )}
                {titleBar}
            </header>
            {children}
        </section>
    );
}

function SortableCategoryRow({ category, children }: { category: Category; children: React.ReactNode }) {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        // Cross-group drag works because each category's id is globally unique
        // and dnd-kit tracks container membership in the onDragEnd handler.
        id: `cat:${category.categoryId}`,
    });
    return (
        <tr
            ref={setNodeRef}
            style={{
                transform: CSS.Transform.toString(transform),
                transition,
                opacity: isDragging ? 0.5 : 1,
            }}
            className={category.active ? "" : "faded"}
        >
            <td className="drag-handle-cell">
                <button className="drag-handle" title="Drag to reorder" {...attributes} {...listeners}>
                    ⋮⋮
                </button>
            </td>
            {children}
        </tr>
    );
}

// --- Page ----------------------------------------------------------------------

export default function CategoriesPage() {
    const [groups, setGroups] = useState<CategoryGroup[]>([]);
    const [categories, setCategories] = useState<Category[]>([]);
    const [newName, setNewName] = useState("");
    const [newGroupId, setNewGroupId] = useState<string>("");
    const [newGroupName, setNewGroupName] = useState("");
    const [editingId, setEditingId] = useState<string | null>(null);
    const [editName, setEditName] = useState("");
    const [editGroupId, setEditGroupId] = useState<string>("");
    const [editingGroupId, setEditingGroupId] = useState<string | null>(null);
    const [editGroupName, setEditGroupName] = useState("");
    // Groups can be collapsed to make group-level reordering easier. State is keyed
    // by groupId; not persisted across reloads.
    const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

    const toggleGroupCollapsed = (groupId: string) => {
        setCollapsedGroups((prev) => {
            const next = new Set(prev);
            if (next.has(groupId)) next.delete(groupId);
            else next.add(groupId);
            return next;
        });
    };
    const { status, showLoading, showError, showSuccess, clear } = useStatus();

    const [pending, setPending] = useState<PendingDeactivation | null>(null);
    const [deactivateExplanation, setDeactivateExplanation] = useState("");

    const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

    const load = useCallback(async () => {
        showLoading("Loading...");
        try {
            const [g, c] = await Promise.all([fetchCategoryGroups(), fetchAllCategories()]);
            setGroups(g);
            setCategories(c);
            // Default the new-category group selector to the first group when none picked yet.
            if (g.length > 0 && !newGroupId) setNewGroupId(g[0].groupId);
            clear();
        } catch (err) {
            showError(err);
        }
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        load();
    }, [load]);

    // Groups have a single lifecycle state now — they either exist or they don't.
    // Just sort by order.
    // System groups (Unassigned) always sort last regardless of their numeric `order`,
    // matching the backend's `list_all` semantics. A new regular group with a high
    // synthetic order shouldn't render after Unassigned.
    const activeGroups = useMemo(
        () =>
            [...groups].sort((a, b) => {
                if (a.system !== b.system) return a.system ? 1 : -1;
                return a.order - b.order;
            }),
        [groups],
    );

    // Only active categories appear inside the group tables. Inactive ones live in a
    // dedicated section at the bottom so they aren't double-rendered.
    const categoriesByGroup = useMemo(() => {
        const map = new Map<string, Category[]>();
        for (const cat of categories) {
            if (!cat.active) continue;
            const arr = map.get(cat.groupId) ?? [];
            arr.push(cat);
            map.set(cat.groupId, arr);
        }
        for (const arr of map.values()) {
            arr.sort((a, b) => a.orderInGroup - b.orderInGroup || a.name.localeCompare(b.name));
        }
        return map;
    }, [categories]);

    const handleCreateGroup = async () => {
        if (!newGroupName.trim()) return;
        try {
            await createCategoryGroup(newGroupName.trim());
            setNewGroupName("");
            showSuccess("Group created");
            setTimeout(clear, 3000);
            load();
        } catch (err) {
            showError(err);
        }
    };

    const handleRenameGroup = async (groupId: string) => {
        if (!editGroupName.trim()) return;
        try {
            await renameCategoryGroup(groupId, editGroupName.trim());
            setEditingGroupId(null);
            load();
        } catch (err) {
            showError(err);
        }
    };

    const handleDeleteGroup = async (group: CategoryGroup) => {
        if (!confirm(`Delete group "${group.name}"? This can't be undone.`)) return;
        try {
            await deleteCategoryGroup(group.groupId);
            load();
        } catch (err) {
            if (err instanceof ApiError && err.status === 409) {
                // Backend blocks delete when the group still has categories pointing at it.
                showError(`"${group.name}" still has categories. Move them to another group first.`);
                return;
            }
            showError(err);
        }
    };

    const handleCreateCategory = async () => {
        if (!newName.trim()) {
            showError("Category name is required");
            return;
        }
        if (!newGroupId) {
            showError("Pick a group for the new category");
            return;
        }
        try {
            // Backend defaults initialTarget to $0. The user can set a real value
            // later by editing the row's amount on the Budget page.
            await createCategory(newName.trim(), newGroupId);
            setNewName("");
            showSuccess("Category created");
            setTimeout(clear, 3000);
            load();
        } catch (err) {
            showError(err);
        }
    };

    const handleSaveCategoryEdit = async (cat: Category) => {
        const trimmedName = editName.trim();
        if (!trimmedName) return;
        // Send only the fields that actually changed so the backend's update path
        // doesn't emit a redundant nameHistory entry or no-op move.
        const updates: { name?: string; groupId?: string } = {};
        if (trimmedName !== cat.name) updates.name = trimmedName;
        if (editGroupId && editGroupId !== cat.groupId) updates.groupId = editGroupId;
        if (!updates.name && !updates.groupId) {
            setEditingId(null);
            return;
        }
        try {
            await updateCategory(cat.categoryId, updates);
            setEditingId(null);
            load();
        } catch (err) {
            showError(err);
        }
    };

    const handleDeactivateCategory = async (cat: Category) => {
        if (!confirm(`Deactivate "${cat.name}"?`)) return;
        try {
            await deactivateCategory(cat.categoryId);
            showSuccess(`Deactivated "${cat.name}"`);
            setTimeout(clear, 3000);
            load();
        } catch (err) {
            if (err instanceof ApiError && err.status === 409) {
                try {
                    const body = JSON.parse(err.responseBody);
                    if (Array.isArray(body.affectedMonths) && body.affectedMonths.length > 0) {
                        setPending({
                            categoryId: cat.categoryId,
                            categoryName: cat.name,
                            affectedMonths: body.affectedMonths,
                        });
                        setDeactivateExplanation("");
                        return;
                    }
                } catch {
                    // fall through
                }
            }
            showError(err);
        }
    };

    const handleConfirmDeactivate = async () => {
        if (!pending) return;
        const explanation = deactivateExplanation.trim();
        if (!explanation) {
            showError("Explanation is required to drop pin rows");
            return;
        }
        try {
            await deactivateCategory(pending.categoryId, { confirm: true, explanation });
            showSuccess(
                `Deactivated "${pending.categoryName}"; dropped ${pending.affectedMonths.length} future pin${pending.affectedMonths.length !== 1 ? "s" : ""}`,
            );
            setTimeout(clear, 4000);
            setPending(null);
            load();
        } catch (err) {
            showError(err);
        }
    };

    const handleReactivateCategory = async (cat: Category) => {
        try {
            await reactivateCategory(cat.categoryId);
            load();
        } catch (err) {
            showError(err);
        }
    };

    // --- Drag handlers -----------------------------------------------------

    // Both groups and categories live in the same DndContext so cross-container
    // drags work. We disambiguate via the id prefix ("group:" / "cat:").
    const handleDragEnd = async (event: DragEndEvent) => {
        const { active, over } = event;
        if (!over || active.id === over.id) return;

        const activeId = String(active.id);
        const overId = String(over.id);

        // Group ↔ group: reorder within activeGroups. System groups are not draggable
        // (their useSortable is disabled), so they won't appear as active or over here.
        if (activeId.startsWith("group:") && overId.startsWith("group:")) {
            const oldIndex = activeGroups.findIndex((g) => `group:${g.groupId}` === activeId);
            const newIndex = activeGroups.findIndex((g) => `group:${g.groupId}` === overId);
            if (oldIndex < 0 || newIndex < 0) return;
            // Optimistically rewrite each non-system group's `order` to match its new
            // index. Without this the sort inside `activeGroups` (which keys on `order`)
            // snaps the array back to the pre-drag arrangement.
            const reordered = arrayMove(activeGroups, oldIndex, newIndex);
            let nextOrder = 0;
            const updated = reordered.map((g) => (g.system ? g : { ...g, order: nextOrder++ }));
            setGroups(updated);
            try {
                // Only send non-system groups to the reorder endpoint — system groups
                // are pinned and the backend pushes them to the end regardless.
                await reorderCategoryGroups(updated.filter((g) => !g.system).map((g) => g.groupId));
                // Skip reloading on success: optimistic state already matches the write.
            } catch (err) {
                showError(err);
                load();
            }
            return;
        }

        // Helper: apply a target-group ordering optimistically. Updates `groupId` and
        // `orderInGroup` for every cat in `reorderedIds` (which is the full intended
        // order within `targetGroupId` after the drag).
        const applyCatReorder = (targetGroupId: string, reorderedIds: string[]) => {
            const idIndex = new Map(reorderedIds.map((id, i) => [id, i] as const));
            setCategories((prev) =>
                prev.map((c) => {
                    const newPos = idIndex.get(c.categoryId);
                    if (newPos === undefined) return c;
                    return { ...c, groupId: targetGroupId, orderInGroup: newPos };
                }),
            );
        };

        // Cat ↔ cat (same or different group).
        if (activeId.startsWith("cat:") && overId.startsWith("cat:")) {
            const activeCatId = activeId.slice(4);
            const overCatId = overId.slice(4);
            const activeCat = categories.find((c) => c.categoryId === activeCatId);
            const overCat = categories.find((c) => c.categoryId === overCatId);
            if (!activeCat || !overCat) return;
            const targetGroupId = overCat.groupId;

            const targetCats = (categoriesByGroup.get(targetGroupId) ?? []).filter((c) => c.categoryId !== activeCatId);
            const insertAt = targetCats.findIndex((c) => c.categoryId === overCatId);
            const reorderedIds = [
                ...targetCats.slice(0, insertAt).map((c) => c.categoryId),
                activeCatId,
                ...targetCats.slice(insertAt).map((c) => c.categoryId),
            ];

            applyCatReorder(targetGroupId, reorderedIds);

            try {
                await reorderCategoriesInGroup(targetGroupId, reorderedIds);
            } catch (err) {
                showError(err);
                load();
            }
            return;
        }

        // Cat dropped onto a group header — move to that group at the end.
        if (activeId.startsWith("cat:") && overId.startsWith("group:")) {
            const activeCatId = activeId.slice(4);
            const targetGroupId = overId.slice(6);
            const targetCats = (categoriesByGroup.get(targetGroupId) ?? []).filter((c) => c.categoryId !== activeCatId);
            const reorderedIds = [...targetCats.map((c) => c.categoryId), activeCatId];

            applyCatReorder(targetGroupId, reorderedIds);

            try {
                await reorderCategoriesInGroup(targetGroupId, reorderedIds);
            } catch (err) {
                showError(err);
                load();
            }
        }
    };

    // --- Render ------------------------------------------------------------

    return (
        <div className="page">
            <h1>Categories</h1>
            <LoadingOverlay message={status.message} visible={status.type === "loading"} />
            <StatusMessage message={status.type !== "loading" ? status.message : ""} type={status.type} />

            {pending && (
                <div className="deactivation-warning">
                    <p>
                        <strong>"{pending.categoryName}"</strong> has pinned amounts in:
                    </p>
                    <ul>
                        {pending.affectedMonths.map((m) => (
                            <li key={m}>{formatYearMonth(m)}</li>
                        ))}
                    </ul>
                    <p>Confirming will delete those pins (each one becomes an audit log entry).</p>
                    <input
                        type="text"
                        className="explanation-inline"
                        value={deactivateExplanation}
                        onChange={(e) => setDeactivateExplanation(e.target.value)}
                        placeholder="Explanation (required)"
                        maxLength={1000}
                    />
                    <div className="warning-actions">
                        <button className="primary-btn" onClick={handleConfirmDeactivate}>
                            Drop pins & deactivate
                        </button>
                        <button className="small-btn" onClick={() => setPending(null)}>
                            Cancel
                        </button>
                    </div>
                </div>
            )}

            <div className="add-form inline">
                <input
                    type="text"
                    placeholder="New group name"
                    value={newGroupName}
                    onChange={(e) => setNewGroupName(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === "Enter") handleCreateGroup();
                    }}
                />
                <button className="primary-btn" onClick={handleCreateGroup}>
                    Add Group
                </button>
            </div>

            <div className="add-form inline">
                <input
                    type="text"
                    placeholder="New category name"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === "Enter") handleCreateCategory();
                    }}
                />
                <select value={newGroupId} onChange={(e) => setNewGroupId(e.target.value)}>
                    <option value="">Select group…</option>
                    {activeGroups
                        .filter((g) => !g.system)
                        .map((g) => (
                            <option key={g.groupId} value={g.groupId}>
                                {g.name}
                            </option>
                        ))}
                </select>
                <button className="primary-btn" onClick={handleCreateCategory}>
                    Add Category
                </button>
            </div>

            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
                <SortableContext
                    items={activeGroups.map((g) => `group:${g.groupId}`)}
                    strategy={verticalListSortingStrategy}
                >
                    {activeGroups.map((group) => {
                        const groupCats = categoriesByGroup.get(group.groupId) ?? [];
                        return (
                            <SortableGroupRow
                                key={group.groupId}
                                group={group}
                                titleBar={
                                    editingGroupId === group.groupId ? (
                                        <>
                                            <input
                                                type="text"
                                                value={editGroupName}
                                                onChange={(e) => setEditGroupName(e.target.value)}
                                                autoFocus
                                                onKeyDown={(e) => {
                                                    if (e.key === "Enter") handleRenameGroup(group.groupId);
                                                    if (e.key === "Escape") setEditingGroupId(null);
                                                }}
                                            />
                                            <button
                                                className="small-btn"
                                                onClick={() => handleRenameGroup(group.groupId)}
                                            >
                                                Save
                                            </button>
                                            <button
                                                className="small-btn"
                                                onClick={() => setEditingGroupId(null)}
                                            >
                                                Cancel
                                            </button>
                                        </>
                                    ) : (
                                        <>
                                            <h2 className="category-group-name">{group.name}</h2>
                                            <button
                                                className="small-btn"
                                                onClick={() => toggleGroupCollapsed(group.groupId)}
                                                title={
                                                    collapsedGroups.has(group.groupId)
                                                        ? "Expand group"
                                                        : "Collapse group"
                                                }
                                            >
                                                {collapsedGroups.has(group.groupId) ? "▶ Expand" : "▼ Collapse"}
                                            </button>
                                            {!group.system && (
                                                <>
                                                    <button
                                                        className="small-btn"
                                                        onClick={() => {
                                                            setEditingGroupId(group.groupId);
                                                            setEditGroupName(group.name);
                                                        }}
                                                    >
                                                        Rename
                                                    </button>
                                                    <button
                                                        className="small-btn delete-btn"
                                                        onClick={() => handleDeleteGroup(group)}
                                                    >
                                                        Delete
                                                    </button>
                                                </>
                                            )}
                                        </>
                                    )
                                }
                            >
                                {collapsedGroups.has(group.groupId) ? (
                                    <p className="category-group-collapsed-hint">
                                        {groupCats.length} categor{groupCats.length === 1 ? "y" : "ies"} hidden
                                    </p>
                                ) : (
                                <table className="data-table category-group-table">
                                    <thead>
                                        <tr>
                                            <th></th>
                                            <th>Name</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <SortableContext
                                        items={groupCats.map((c) => `cat:${c.categoryId}`)}
                                        strategy={verticalListSortingStrategy}
                                    >
                                        <tbody>
                                            {groupCats.length === 0 && (
                                                <tr>
                                                    <td colSpan={3} className="empty">
                                                        No categories in this group yet
                                                    </td>
                                                </tr>
                                            )}
                                            {groupCats.map((cat) => (
                                                <SortableCategoryRow key={cat.categoryId} category={cat}>
                                                    <td>
                                                        {editingId === cat.categoryId ? (
                                                            <span className="edit-actions">
                                                                <input
                                                                    type="text"
                                                                    value={editName}
                                                                    onChange={(e) => setEditName(e.target.value)}
                                                                    autoFocus
                                                                    onKeyDown={(e) => {
                                                                        if (e.key === "Enter")
                                                                            handleSaveCategoryEdit(cat);
                                                                        if (e.key === "Escape") setEditingId(null);
                                                                    }}
                                                                />
                                                                <select
                                                                    value={editGroupId}
                                                                    title="Move to group on Save"
                                                                    onChange={(e) => setEditGroupId(e.target.value)}
                                                                >
                                                                    {activeGroups.map((g) => (
                                                                        <option key={g.groupId} value={g.groupId}>
                                                                            {g.name}
                                                                        </option>
                                                                    ))}
                                                                </select>
                                                            </span>
                                                        ) : (
                                                            cat.name
                                                        )}
                                                    </td>
                                                    <td className="actions">
                                                        {editingId === cat.categoryId ? (
                                                            <>
                                                                <button
                                                                    className="small-btn"
                                                                    onClick={() => handleSaveCategoryEdit(cat)}
                                                                >
                                                                    Save
                                                                </button>
                                                                <button
                                                                    className="small-btn"
                                                                    onClick={() => setEditingId(null)}
                                                                >
                                                                    Cancel
                                                                </button>
                                                            </>
                                                        ) : cat.active ? (
                                                            <>
                                                                <button
                                                                    className="small-btn"
                                                                    onClick={() => {
                                                                        setEditingId(cat.categoryId);
                                                                        setEditName(cat.name);
                                                                        setEditGroupId(cat.groupId);
                                                                    }}
                                                                >
                                                                    Edit
                                                                </button>
                                                                <button
                                                                    className="small-btn delete-btn"
                                                                    onClick={() => handleDeactivateCategory(cat)}
                                                                >
                                                                    Deactivate
                                                                </button>
                                                            </>
                                                        ) : (
                                                            <button
                                                                className="small-btn"
                                                                onClick={() => handleReactivateCategory(cat)}
                                                            >
                                                                Reactivate
                                                            </button>
                                                        )}
                                                    </td>
                                                </SortableCategoryRow>
                                            ))}
                                        </tbody>
                                    </SortableContext>
                                </table>
                                )}
                            </SortableGroupRow>
                        );
                    })}
                </SortableContext>
            </DndContext>

            {categories.some((c) => !c.active) && (
                <section className="inactive-categories">
                    <h2>Deactivated categories</h2>
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>Group</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {categories
                                .filter((c) => !c.active)
                                .sort((a, b) => a.name.localeCompare(b.name))
                                .map((cat) => {
                                    // The "(deactivated)" suffix annotates the category itself
                                    // (per Issue #1 fix). The group cell shows the plain group
                                    // name — or a fallback when the row hasn't been assigned to a
                                    // group yet (e.g. pre-migration legacy rows or future
                                    // "Unassigned" sentinel).
                                    const grp = groups.find((g) => g.groupId === cat.groupId);
                                    const groupLabel = !cat.groupId
                                        ? "—"
                                        : grp
                                          ? grp.name
                                          : `<missing: ${cat.groupId}>`;
                                    return (
                                        <tr key={cat.categoryId} className="faded">
                                            <td>{cat.name} (deactivated)</td>
                                            <td>{groupLabel}</td>
                                            <td className="actions">
                                                <button
                                                    className="small-btn"
                                                    onClick={() => handleReactivateCategory(cat)}
                                                >
                                                    Reactivate
                                                </button>
                                            </td>
                                        </tr>
                                    );
                                })}
                        </tbody>
                    </table>
                </section>
            )}
        </div>
    );
}
