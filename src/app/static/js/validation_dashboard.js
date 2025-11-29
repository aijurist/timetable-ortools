'use strict';

const state = {
    snapshot: null,
    telemetry: defaultTelemetry(),
    filters: {
        roomSearch: '',
    },
};

document.addEventListener('DOMContentLoaded', () => {
    bootstrapValidationDashboard();
});

async function bootstrapValidationDashboard() {
    try {
        await loadTelemetry();
        renderAll();
        attachEvents();
    } catch (error) {
        showError(error.message || 'Failed to load validation telemetry.');
        console.error(error);
    }
}

function defaultTelemetry() {
    return {
        generated_at: null,
        executed_checks: [],
        severity_counts: {},
        room_conflicts: {
            summary: {
                conflict_count: 0,
                rooms_impacted: 0,
                windows_impacted: 0,
                lab_conflicts: 0,
                theory_conflicts: 0,
            },
            conflicts: [],
        },
        ltp_presence: {
            summary: {
                lab_gaps: 0,
                theory_gaps: 0,
            },
            lab_gaps: [],
            theory_gaps: [],
        },
    };
}

async function loadTelemetry() {
    const response = await fetch('/api/validation', { cache: 'no-store' });
    await ensureOk(response);
    const payload = await response.json();
    state.snapshot = payload.snapshot || null;
    state.telemetry = normalizeTelemetry(payload.data || {});
    hideBanner();
}

function normalizeTelemetry(raw = {}) {
    return {
        generated_at: raw.generated_at || null,
        executed_checks: Array.isArray(raw.executed_checks) ? raw.executed_checks : [],
        severity_counts: raw.severity_counts || {},
        room_conflicts: {
            summary: {
                conflict_count: raw.room_conflicts?.summary?.conflict_count ?? 0,
                rooms_impacted: raw.room_conflicts?.summary?.rooms_impacted ?? 0,
                windows_impacted: raw.room_conflicts?.summary?.windows_impacted ?? 0,
                lab_conflicts: raw.room_conflicts?.summary?.lab_conflicts ?? 0,
                theory_conflicts: raw.room_conflicts?.summary?.theory_conflicts ?? 0,
            },
            conflicts: Array.isArray(raw.room_conflicts?.conflicts) ? raw.room_conflicts.conflicts : [],
        },
        ltp_presence: {
            summary: {
                lab_gaps: raw.ltp_presence?.summary?.lab_gaps ?? 0,
                theory_gaps: raw.ltp_presence?.summary?.theory_gaps ?? 0,
            },
            lab_gaps: Array.isArray(raw.ltp_presence?.lab_gaps) ? raw.ltp_presence.lab_gaps : [],
            theory_gaps: Array.isArray(raw.ltp_presence?.theory_gaps) ? raw.ltp_presence.theory_gaps : [],
        },
    };
}

function attachEvents() {
    const search = document.getElementById('roomSearch');
    search?.addEventListener('input', debounce((event) => {
        state.filters.roomSearch = (event.target.value || '').toLowerCase();
        renderRoomConflicts();
    }, 200));

    const refreshButton = document.getElementById('refreshTelemetry');
    refreshButton?.addEventListener('click', async () => {
        if (!refreshButton) return;
        try {
            refreshButton.disabled = true;
            await loadTelemetry();
            renderAll();
        } catch (error) {
            showError(error.message || 'Unable to refresh telemetry.');
        } finally {
            refreshButton.disabled = false;
        }
    });

    const downloadButton = document.getElementById('downloadTelemetry');
    downloadButton?.addEventListener('click', () => {
        const payload = {
            snapshot: state.snapshot,
            data: state.telemetry,
        };
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        const filename = state.snapshot?.folder ? `validation_${state.snapshot.folder}.json` : 'validation_telemetry.json';
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        URL.revokeObjectURL(url);
    });
}

function renderAll() {
    updateSnapshotBanner();
    renderSummary();
    renderRoomConflicts();
    renderLtpTables();
}

function updateSnapshotBanner() {
    setText('snapshotLabel', state.snapshot?.folder || '—');
}

function renderSummary() {
    const roomSummary = state.telemetry.room_conflicts.summary;
    const ltpSummary = state.telemetry.ltp_presence.summary;
    setText('roomConflictCount', roomSummary.conflict_count ?? 0);
    setText('roomLabConflictCount', roomSummary.lab_conflicts ?? 0);
    setText('roomTheoryConflictCount', roomSummary.theory_conflicts ?? 0);
    setText('roomConflictRooms', roomSummary.rooms_impacted ?? 0);
    setText('ltpLabGaps', ltpSummary.lab_gaps ?? 0);
    setText('ltpTheoryGaps', ltpSummary.theory_gaps ?? 0);
    setText('telemetryTimestamp', formatTimestamp(state.telemetry.generated_at));
}

function renderRoomConflicts() {
    const tbody = document.getElementById('roomConflictTableBody');
    if (!tbody) return;
    const search = state.filters.roomSearch;
    const conflicts = (state.telemetry.room_conflicts.conflicts || [])
        .filter((conflict) => {
            if (!search) return true;
            const haystack = [
                conflict.room_id,
                conflict.day_label,
                conflict.session,
                conflict.severity,
                ...(conflict.course_instance_ids || []),
            ]
                .filter(Boolean)
                .join(' ')
                .toLowerCase();
            return haystack.includes(search);
        });

    if (!conflicts.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-muted">No room conflicts detected for the current filters.</td></tr>';
        return;
    }

    tbody.innerHTML = conflicts
        .map((conflict) => `
            <tr>
                <td>${conflict.room_id || '—'}</td>
                <td>
                    <div class="fw-semibold">${conflict.day_label || '—'}</div>
                    <div class="small text-muted">Index ${conflict.day_index ?? '—'}</div>
                </td>
                <td>
                    <div class="fw-semibold">${conflict.window_label || '—'}</div>
                    <div class="small text-muted">${formatWindowMeta(conflict)}</div>
                </td>
                <td>${formatImpacted(conflict)}</td>
                <td><span class="status-pill ${conflict.severity === 'error' ? 'danger' : 'warning'}">${conflict.severity || 'info'}</span></td>
            </tr>`)
        .join('');
}

function renderLtpTables() {
    renderGapTable('ltpLabTableBody', state.telemetry.ltp_presence.lab_gaps, (gap) => gap.message || 'Lab hours missing');
    renderGapTable('ltpTheoryTableBody', state.telemetry.ltp_presence.theory_gaps, (gap) => `Expected ${gap.expected_hours ?? '—'} hrs · ${gap.message || 'Theory slots missing'}`);
}

function renderGapTable(targetId, entries, detailResolver) {
    const tbody = document.getElementById(targetId);
    if (!tbody) return;
    if (!entries || !entries.length) {
        const colSpan = targetId === 'ltpTheoryTableBody' ? 3 : 4;
        tbody.innerHTML = `<tr><td colspan="${colSpan}" class="text-center py-4 text-muted">No issues detected.</td></tr>`;
        return;
    }
    tbody.innerHTML = entries
        .map((entry) => {
            if (targetId === 'ltpTheoryTableBody') {
                return `
                    <tr>
                        <td>
                            <div class="fw-semibold">${entry.course_instance_id || '—'}</div>
                            <div class="small text-muted">Group ${entry.group_id || '—'}</div>
                        </td>
                        <td>${entry.expected_hours ?? '—'}</td>
                        <td>${detailResolver(entry)}</td>
                    </tr>`;
            }
            return `
                <tr>
                    <td>${entry.course_instance_id || '—'}</td>
                    <td>${entry.department || '—'}</td>
                    <td>${entry.semester ?? '—'}</td>
                    <td>${detailResolver(entry)}</td>
                </tr>`;
        })
        .join('');
}

function formatImpacted(conflict = {}) {
    const tokens = [];
    (conflict.course_instance_ids || []).forEach((course) => {
        if (course) tokens.push({ label: course, kind: 'course' });
    });
    (conflict.group_ids || []).forEach((group) => {
        if (group) tokens.push({ label: `Group ${group}`, kind: 'group' });
    });
    if (!tokens.length) {
        return '<span class="text-muted small">No course/group metadata</span>';
    }
    const chips = tokens.slice(0, 3)
        .map((token) => `<span class="slot-chip">${token.label}</span>`)
        .join('');
    const remainder = tokens.length > 3 ? `<span class="slot-chip muted">+${tokens.length - 3} more</span>` : '';
    return `<div class="slot-chip-group">${chips}${remainder}</div>`;
}

function formatWindowMeta(conflict = {}) {
    if (conflict.window_type === 'lab') {
        const session = conflict.session || conflict.window_label || 'Unknown session';
        return `Lab session ${session}`;
    }
    if (conflict.window_type === 'theory') {
        const slotLabel = conflict.slot_label
            || (typeof conflict.slot_index === 'number' ? `Slot ${conflict.slot_index}` : conflict.window_label)
            || 'Unknown slot';
        return `Theory slot ${slotLabel}`;
    }
    return conflict.window_label || 'Unknown window';
}

function debounce(fn, delay = 200) {
    let timeout;
    return (...args) => {
        clearTimeout(timeout);
        timeout = setTimeout(() => fn(...args), delay);
    };
}

function ensureOk(response) {
    if (!response.ok) {
        throw new Error(`Request failed (${response.status}) - ${response.statusText}`);
    }
    return response;
}

function setText(id, value) {
    const node = document.getElementById(id);
    if (node) {
        node.textContent = value;
    }
}

function formatTimestamp(timestamp) {
    if (!timestamp) return 'Telemetry not generated';
    try {
        const date = new Date(timestamp);
        if (Number.isNaN(date.getTime())) {
            return timestamp;
        }
        return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
    } catch (error) {
        return timestamp;
    }
}

function showError(message) {
    const banner = document.getElementById('alertBanner');
    if (!banner) return;
    banner.classList.remove('d-none');
    banner.classList.add('alert-danger');
    banner.textContent = message;
}

function hideBanner() {
    const banner = document.getElementById('alertBanner');
    if (!banner) return;
    banner.classList.add('d-none');
}
