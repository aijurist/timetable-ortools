export const KUTTY_SHARED_MODE = "kutty_25x2";
export const KUTTY_REMAINDER_MODE = "kutty_remainder_full_slot";
let pinnedBundleId = "";

function truthy(value) {
    return value === true || value === 1 || ["1", "true", "yes"].includes(String(value || "").toLowerCase());
}

function pairedInstanceIds(session) {
    return [session?.course_instance_id, session?.partner_instance_id]
        .map((value) => String(value || "").trim())
        .filter(Boolean)
        .sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
}

export function bundleIdentity(session) {
    if (session?.bundle_id) return String(session.bundle_id);
    const instances = pairedInstanceIds(session);
    return instances.length === 2 ? `section-pair:${instances.join("+")}` : "";
}

export function isKuttyShared(session) {
    return (
        (session?.delivery_mode === KUTTY_SHARED_MODE && Boolean(bundleIdentity(session))) ||
        (truthy(session?.is_co_scheduled) && pairedInstanceIds(session).length === 2)
    );
}

export function isKuttyRemainder(session) {
    return session?.delivery_mode === KUTTY_REMAINDER_MODE && Boolean(session?.bundle_id);
}

export function teacherKey(session) {
    return String(session?.teacher_id || session?.staff_code || session?.teacher_name || "");
}

export function sessionSectionIndex(session) {
    const direct = session?.section_id ?? session?.section_index;
    if (direct !== undefined && direct !== null && String(direct).trim() !== "") {
        const parsed = Number(direct);
        if (Number.isInteger(parsed) && parsed >= 0) return parsed;
    }
    const instance = String(session?.course_instance_id || "");
    const match = instance.match(/__s(\d+)$/i);
    return match ? Number(match[1]) : null;
}

export function sessionSectionLabel(session) {
    let index = sessionSectionIndex(session);
    if (index === null) return "";
    let label = "";
    do {
        label = String.fromCharCode(65 + (index % 26)) + label;
        index = Math.floor(index / 26) - 1;
    } while (index >= 0);
    return label;
}

export function kuttyOccurrenceKey(session) {
    const slot = session?.slot_index ?? session?.time_slot ?? session?.time_label ?? "unscheduled";
    return `${bundleIdentity(session) || "bundle"}|${session?.day || "day"}|${slot}`;
}

function halfOrder(session) {
    const explicit = Number(session?.half_index || session?.bundle_half || 0);
    if (explicit === 1 || explicit === 2) return explicit;
    const instances = pairedInstanceIds(session);
    return instances.indexOf(String(session?.course_instance_id || "")) + 1 || 99;
}

export function groupCellSessions(sessions) {
    const blocks = [];
    const shared = new Map();

    (sessions || []).forEach((session, index) => {
        if (!isKuttyShared(session)) {
            blocks.push({ kind: "standard", key: `standard-${index}`, sessions: [session] });
            return;
        }
        const key = kuttyOccurrenceKey(session);
        if (!shared.has(key)) {
            const block = { kind: "kutty", key, sessions: [] };
            shared.set(key, block);
            blocks.push(block);
        }
        shared.get(key).sessions.push(session);
    });

    shared.forEach((block) => {
        block.sessions.sort((left, right) => halfOrder(left) - halfOrder(right));
    });
    return blocks;
}

export function expandKuttyOccurrenceMatches(scope, directMatches) {
    const matchSet = new Set(directMatches || []);
    const occurrenceKeys = new Set((directMatches || []).filter(isKuttyShared).map(kuttyOccurrenceKey));
    return (scope || []).filter(
        (entry) => matchSet.has(entry) || (isKuttyShared(entry) && occurrenceKeys.has(kuttyOccurrenceKey(entry))),
    );
}

export function countPhysicalSessions(entries) {
    const keys = new Set();
    (entries || []).forEach((entry, index) => {
        if (isKuttyShared(entry)) {
            keys.add(`kutty:${kuttyOccurrenceKey(entry)}`);
        } else {
            keys.add(`standard:${entry?.schedule_type || "session"}:${index}`);
        }
    });
    return keys.size;
}

export function buildTeacherSchedule(entries, selectedTeacherKey) {
    const owned = (entries || []).filter((entry) => teacherKey(entry) === selectedTeacherKey);
    const ownedEntries = new Set(owned);
    const sharedKeys = new Set(owned.filter(isKuttyShared).map(kuttyOccurrenceKey));
    return (entries || []).filter(
        (entry) => ownedEntries.has(entry) || (isKuttyShared(entry) && sharedKeys.has(kuttyOccurrenceKey(entry))),
    );
}

export function renderKuttySessionCard(sessions, options = {}) {
    const halves = [...(sessions || [])].sort(
        (left, right) => halfOrder(left) - halfOrder(right),
    );
    const representative = halves[0] || {};
    const sectionLabel = sessionSectionLabel(representative);
    const focusTeacher = String(options.focusTeacherKey || "");
    const room = representative.room_number || "TBD";
    const block = representative.block ? ` · ${representative.block}` : "";

    const halfMarkup = [1, 2].map((halfIndex) => {
        const half = halves.find((entry) => halfOrder(entry) === halfIndex) || halves[halfIndex - 1];
        if (!half) {
            return '<div class="paired-session-half paired-session-missing">Missing paired half</div>';
        }
        const isFocused = focusTeacher && teacherKey(half) === focusTeacher;
        const staffIdentifier = half.staff_code || half.teacher_id || "TBA";
        const groupNumber = sessionGroupNumber(half);
        const hoverDetails = buildSessionHoverDetails(half, room, block);
        return `
            <div class="paired-session-half${isFocused ? " paired-session-focus" : ""}"
                 title="${escapeHtml(hoverDetails)}">
                ${!sectionLabel && groupNumber ? `
                    <span class="group-number group-g${escapeHtml(groupNumber)}-badge kutty-group-chip"
                          tabindex="0"
                          aria-label="${escapeHtml(hoverDetails)}">G${escapeHtml(groupNumber)}</span>
                ` : ""}
                <strong>${escapeHtml(half.course_code_display || half.course_code || "Course")}</strong>
                <span>${escapeHtml(half.course_name || "-")}</span>
                <small>${escapeHtml(half.teacher_name || "Staff TBA")} · ${escapeHtml(staffIdentifier)}</small>
            </div>
        `;
    });

    return `
        <div class="paired-session-block schedule-session-card bundle-session"
             data-bundle-id="${escapeHtml(bundleIdentity(representative))}">
            <span class="paired-mode">25 + 25</span>
            ${sectionLabel ? `<span class="section-number" title="Section ${escapeHtml(sectionLabel)}">${escapeHtml(sectionLabel)}</span>` : ""}
            ${halfMarkup[0]}
            ${halfMarkup[1]}
            <span class="paired-room"><i class="fas fa-door-open"></i> ${escapeHtml(room + block)}</span>
        </div>
    `;
}

export function sessionGroupNumber(session) {
    const direct = Number(session?.group_index);
    if (Number.isInteger(direct) && direct > 0) return String(direct);
    const match = String(session?.group_name || session?.group_id || "").match(/(?:_G|\bG)(\d+)$/i);
    return match ? match[1] : "";
}

export function buildSessionHoverDetails(session, room = "TBD", block = "") {
    const groupNumber = sessionGroupNumber(session);
    const sectionLabel = sessionSectionLabel(session);
    const teacherIdentifier = session?.staff_code || session?.teacher_id || "TBA";
    const partnerIdentifier = session?.partner_teacher_id ? ` (${session.partner_teacher_id})` : "";
    const lines = [
        sectionLabel ? `Section: ${sectionLabel}` : "",
        groupNumber ? `Group: G${groupNumber}` : "",
        `Course: ${session?.course_code_display || session?.course_code || "Course"}${session?.course_name ? ` — ${session.course_name}` : ""}`,
        `Staff: ${session?.teacher_name || "Staff TBA"} (${teacherIdentifier})`,
        `Time: ${session?.half_time || session?.time_slot || session?.time_label || session?.time_range || "Scheduled slot"}`,
        `Room: ${room}${block}`,
        session?.course_instance_id ? `Instance: ${session.course_instance_id}` : "",
        session?.partner_course_code
            ? `Partner: ${session.partner_course_code} — ${session?.partner_teacher_name || "Staff TBA"}${partnerIdentifier}`
            : "",
        session?.bundle_label ? `Bundle: ${session.bundle_label}` : "",
        bundleIdentity(session) ? `Pair ID: ${bundleIdentity(session)}` : "",
    ];
    return lines.filter(Boolean).join("\n");
}

export function updateBundlePanel(entries) {
    const summaries = collectBundleSummaries(entries);
    if (pinnedBundleId && !summaries.some((summary) => summary.bundleId === pinnedBundleId)) {
        pinnedBundleId = "";
        clearBundleHighlight();
    }
    const panel = ensureBundlePanel();
    const content = panel.querySelector("[data-bundle-panel-content]");
    const count = document.querySelector("[data-bundle-count]");
    count.textContent = String(summaries.length);

    if (!summaries.length) {
        content.innerHTML = '<div class="bundle-panel-empty">No Kutty bundles in this view.</div>';
        clearBundleHighlight();
        return;
    }

    content.innerHTML = summaries.map((summary) => `
        <button type="button" class="bundle-panel-item" data-panel-bundle-id="${escapeHtml(summary.bundleId)}">
            <span class="bundle-panel-label">${escapeHtml(summary.coursePair)}</span>
            <span class="bundle-panel-staff">${escapeHtml(summary.staffPair)}</span>
            <span class="bundle-panel-instances">${escapeHtml(summary.instancePair)}</span>
            <code>${escapeHtml(summary.bundleId)}</code>
        </button>
    `).join("");

    content.querySelectorAll("[data-panel-bundle-id]").forEach((item) => {
        const itemBundleId = item.dataset.panelBundleId || "";
        const activate = () => highlightBundle(itemBundleId);
        item.addEventListener("mouseenter", activate);
        item.addEventListener("pointerenter", activate);
        item.addEventListener("focus", activate);
        item.addEventListener("mouseleave", restorePinnedHighlight);
        item.addEventListener("pointerleave", restorePinnedHighlight);
        item.addEventListener("blur", restorePinnedHighlight);
        item.addEventListener("click", () => {
            pinnedBundleId = pinnedBundleId === itemBundleId ? "" : itemBundleId;
            restorePinnedHighlight();
        });
    });
}

export function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function ensureBundlePanel() {
    let panel = document.getElementById("bundleSidePanel");
    if (panel) return panel;

    document.body.insertAdjacentHTML("beforeend", `
        <button type="button" class="bundle-panel-toggle" id="bundlePanelToggle"
                aria-controls="bundleSidePanel" aria-expanded="false">
            <i class="fas fa-link"></i>
            Bundles <span data-bundle-count>0</span>
        </button>
        <aside class="bundle-side-panel" id="bundleSidePanel" aria-hidden="true">
            <div class="bundle-panel-header">
                <div>
                    <strong>Kutty bundles</strong>
                    <small>Hover an instance pair to highlight its timetable sessions.</small>
                </div>
                <button type="button" class="bundle-panel-close" aria-label="Close bundle panel">×</button>
            </div>
            <div class="bundle-panel-content" data-bundle-panel-content></div>
        </aside>
    `);

    panel = document.getElementById("bundleSidePanel");
    const toggle = document.getElementById("bundlePanelToggle");
    const close = panel.querySelector(".bundle-panel-close");
    const setOpen = (open) => {
        panel.classList.toggle("is-open", open);
        panel.setAttribute("aria-hidden", String(!open));
        toggle.setAttribute("aria-expanded", String(open));
        if (!open) {
            pinnedBundleId = "";
            clearBundleHighlight();
        }
    };
    toggle.addEventListener("click", () => setOpen(!panel.classList.contains("is-open")));
    close.addEventListener("click", () => setOpen(false));
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && panel.classList.contains("is-open")) setOpen(false);
    });
    return panel;
}

function highlightBundle(bundleId) {
    document.body.classList.add("bundle-inspect-active");
    document.querySelectorAll(".schedule-session-card").forEach((card) => {
        card.classList.toggle("bundle-session-highlight", card.dataset.bundleId === bundleId);
    });
    document.querySelectorAll("[data-panel-bundle-id]").forEach((item) => {
        item.classList.toggle("is-active", item.dataset.panelBundleId === bundleId);
    });
}

function clearBundleHighlight() {
    document.body.classList.remove("bundle-inspect-active");
    document.querySelectorAll(".bundle-session-highlight").forEach((card) => {
        card.classList.remove("bundle-session-highlight");
    });
    document.querySelectorAll(".bundle-panel-item.is-active").forEach((item) => {
        item.classList.remove("is-active");
    });
}

function restorePinnedHighlight() {
    if (pinnedBundleId) {
        highlightBundle(pinnedBundleId);
    } else {
        clearBundleHighlight();
    }
}

function collectBundleSummaries(entries) {
    const bundles = new Map();
    (entries || []).forEach((entry) => {
        if (!isKuttyShared(entry)) return;
        const identity = bundleIdentity(entry);
        if (!identity) return;
        if (!bundles.has(identity)) {
            bundles.set(identity, {
                bundleId: identity,
                courseCodes: normalizeList(entry.bundle_course_codes),
                instanceIds: [],
                instanceByCourse: new Map(),
                staffByCourse: new Map(),
            });
        }
        const summary = bundles.get(identity);
        if (!summary.courseCodes.length && entry.course_code) summary.courseCodes.push(String(entry.course_code));
        registerBundleSide(summary, entry.course_code, entry.course_instance_id, entry.teacher_name, entry.staff_code || entry.teacher_id);
        registerBundleSide(
            summary,
            entry.partner_course_code,
            entry.partner_instance_id,
            entry.partner_teacher_name,
            entry.partner_teacher_id,
        );
    });

    return [...bundles.values()]
        .map((summary) => {
            const courseCodes = unique(summary.courseCodes);
            const orderedInstances = courseCodes.map((code) => summary.instanceByCourse.get(code)).filter(Boolean);
            const remainingInstances = summary.instanceIds.filter((id) => !orderedInstances.includes(id));
            const orderedStaff = courseCodes.map((code) => summary.staffByCourse.get(code)).filter(Boolean);
            return {
                bundleId: summary.bundleId,
                coursePair: courseCodes.join(" + ") || "Paired courses",
                instancePair: [...orderedInstances, ...remainingInstances].join(" + ") || "Paired instances",
                staffPair: unique(orderedStaff).join(" + ") || "Paired staff",
            };
        })
        .sort((left, right) => left.bundleId.localeCompare(right.bundleId));
}

function registerBundleSide(summary, courseCode, instanceId, teacherName, teacherId) {
    const code = String(courseCode || "");
    const instance = String(instanceId || "");
    if (code && !summary.courseCodes.includes(code)) summary.courseCodes.push(code);
    if (instance && !summary.instanceIds.includes(instance)) summary.instanceIds.push(instance);
    if (code && instance) summary.instanceByCourse.set(code, instance);
    if (code && (teacherName || teacherId)) {
        const identifier = teacherId ? ` (${teacherId})` : "";
        summary.staffByCourse.set(code, `${teacherName || "Staff"}${identifier}`);
    }
}

function normalizeList(value) {
    if (Array.isArray(value)) return value.map(String).filter(Boolean);
    if (value === undefined || value === null) return [];
    return String(value)
        .replace(/[()'"\[\]]/g, "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
}

function unique(values) {
    return [...new Set(values)];
}
