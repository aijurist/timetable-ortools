'use strict';

const CONSTRAINT_LABELS = {
    group_non_overlap: 'Department Group Non-Overlap',
    teacher_overlap: 'Teacher Overlap Guard',
};

const state = {
    snapshot: null,
    telemetry: defaultTelemetry(),
    filters: {
        groupDepartment: 'all',
        groupSearch: '',
        teacherDay: 'all',
        teacherSearch: '',
    },
};

document.addEventListener('DOMContentLoaded', () => {
    bootstrapTelemetryDashboard();
});

async function bootstrapTelemetryDashboard() {
    try {
        await loadTelemetry();
        renderAll();
        attachEvents();
        if (!state.telemetry.generated_at) {
            showWarning('Overlap telemetry was not generated for the latest snapshot. Re-run the solver with telemetry enabled.');
        }
    } catch (error) {
        showError(error.message || 'Failed to load overlap telemetry.');
        console.error(error);
    }
}

function defaultTelemetry() {
    return {
        generated_at: null,
        group_summary: {
            dept_semesters: 0,
            conflict_windows: 0,
            departments_impacted: 0,
        },
        group_conflicts: [],
        teacher_summary: {
            teachers_with_conflicts: 0,
            conflict_windows: 0,
        },
        teacher_conflicts: [],
        constraints: {},
        metadata: {},
    };
}

async function loadTelemetry() {
    const response = await fetch('/api/overlaps', { cache: 'no-store' });
    await ensureOk(response);
    const payload = await response.json();
    state.snapshot = payload.snapshot || null;
    state.telemetry = normalizeTelemetry(payload.data || {});
    hideBanner();
}

function normalizeTelemetry(raw = {}) {
    return {
        generated_at: raw.generated_at || null,
        group_summary: {
            dept_semesters: raw.group_summary?.dept_semesters ?? 0,
            conflict_windows: raw.group_summary?.conflict_windows ?? 0,
            departments_impacted: raw.group_summary?.departments_impacted ?? 0,
        },
        group_conflicts: Array.isArray(raw.group_conflicts) ? raw.group_conflicts : [],
        teacher_summary: {
            teachers_with_conflicts: raw.teacher_summary?.teachers_with_conflicts ?? 0,
            conflict_windows: raw.teacher_summary?.conflict_windows ?? 0,
        },
        teacher_conflicts: Array.isArray(raw.teacher_conflicts) ? raw.teacher_conflicts : [],
        constraints: raw.constraints || {},
        metadata: raw.metadata || {},
    };
}

function attachEvents() {
    document.getElementById('groupDeptFilter')?.addEventListener('change', (event) => {
        state.filters.groupDepartment = event.target.value;
        renderGroupConflicts();
    });

    document.getElementById('groupSearch')?.addEventListener('input', debounce((event) => {
        state.filters.groupSearch = event.target.value.toLowerCase();
        renderGroupConflicts();
    }, 200));

    document.getElementById('teacherDayFilter')?.addEventListener('change', (event) => {
        state.filters.teacherDay = event.target.value;
        renderTeacherConflicts();
    });

    document.getElementById('teacherSearch')?.addEventListener('input', debounce((event) => {
        state.filters.teacherSearch = event.target.value.toLowerCase();
        renderTeacherConflicts();
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

    document.getElementById('downloadTelemetry')?.addEventListener('click', () => {
        const payload = {
            snapshot: state.snapshot,
            data: state.telemetry,
        };
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        const filename = state.snapshot?.folder ? `overlap_${state.snapshot.folder}.json` : 'overlap_telemetry.json';
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        URL.revokeObjectURL(url);
    });
}

function renderAll() {
    updateSnapshotBanner();
    renderPolicyNote();
    renderSummary();
    renderGroupFilters();
    renderGroupConflicts();
    renderTeacherFilters();
    renderTeacherConflicts();
    renderConstraints();
}

function renderPolicyNote() {
    const container = document.getElementById('policyNote');
    if (!container) return;
    const note = state.telemetry.metadata?.policy_note;
    if (!note) {
        container.classList.add('d-none');
        container.textContent = '';
        return;
    }
    container.textContent = note;
    container.classList.remove('d-none');
}

function updateSnapshotBanner() {
    setText('snapshotLabel', state.snapshot?.folder || '—');
}

function renderSummary() {
    const groupSummary = state.telemetry.group_summary || {};
    const teacherSummary = state.telemetry.teacher_summary || {};
    setText('summaryDeptBuckets', groupSummary.dept_semesters ?? 0);
    setText('summaryGroupWindows', groupSummary.conflict_windows ?? 0);
    setText('summaryDeptImpacted', groupSummary.departments_impacted ?? 0);
    setText('summaryTeacherConflictTeachers', teacherSummary.teachers_with_conflicts ?? 0);
    setText('summaryTeacherWindows', teacherSummary.conflict_windows ?? 0);
    setText('telemetryTimestamp', formatTimestamp(state.telemetry.generated_at));
}

function renderGroupFilters() {
    const select = document.getElementById('groupDeptFilter');
    if (!select) return;
    const departments = new Set((state.telemetry.group_conflicts || []).map((conflict) => conflict.department).filter(Boolean));
    const sorted = Array.from(departments).sort((a, b) => `${a}`.localeCompare(`${b}`));
    const current = state.filters.groupDepartment;
    select.innerHTML = ['<option value="all">All departments</option>', ...sorted.map((dept) => `<option value="${dept}">${dept}</option>`)].join('');
    select.value = sorted.includes(current) ? current : 'all';
    state.filters.groupDepartment = select.value;
}

function renderTeacherFilters() {
    const select = document.getElementById('teacherDayFilter');
    if (!select) return;
    const days = new Set((state.telemetry.teacher_conflicts || []).map((conflict) => conflict.day).filter(Boolean));
    const sorted = Array.from(days).sort((a, b) => `${a}`.localeCompare(`${b}`));
    const current = state.filters.teacherDay;
    select.innerHTML = ['<option value="all">All days</option>', ...sorted.map((day) => `<option value="${day}">${day}</option>`)].join('');
    select.value = sorted.includes(current) ? current : 'all';
    state.filters.teacherDay = select.value;
}

function renderGroupConflicts() {
    const tbody = document.getElementById('groupConflictTableBody');
    if (!tbody) return;
    const conflicts = (state.telemetry.group_conflicts || [])
        .slice()
        .sort((a, b) => {
            if (a.department === b.department) {
                if ((a.semester ?? 0) === (b.semester ?? 0)) {
                    if (a.day === b.day) {
                        return (a.slot_index ?? 0) - (b.slot_index ?? 0);
                    }
                    return (a.day || '').localeCompare(b.day || '');
                }
                return (a.semester ?? 0) - (b.semester ?? 0);
            }
            return (a.department || '').localeCompare(b.department || '');
        })
        .filter(filterGroupConflict);

    if (!conflicts.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-muted">No group overlaps detected for the current filters.</td></tr>';
    } else {
        tbody.innerHTML = conflicts
            .map((conflict) => `
                <tr>
                    <td>
                        <div>${conflict.department || '—'}</div>
                        <div class="small text-muted">Semester ${conflict.semester ?? '—'}</div>
                    </td>
                    <td>${conflict.day || '—'}</td>
                    <td>
                        <div class="fw-semibold">${conflict.slot_label || 'Slot'} </div>
                        <div class="small text-muted">Index ${conflict.slot_index ?? '—'}</div>
                    </td>
                    <td>${formatGroups(conflict.groups)}</td>
                    <td>${formatConflictStatus(conflict)}</td>
                    <td>${formatActivities(conflict.activities)}</td>
                </tr>`)
            .join('');
    }

    setText('groupConflictCount', conflicts.length);
}

function filterGroupConflict(conflict) {
    const { groupDepartment, groupSearch } = state.filters;
    if (groupDepartment !== 'all' && conflict.department !== groupDepartment) {
        return false;
    }
    if (groupSearch) {
        const haystack = [
            conflict.department,
            conflict.semester,
            conflict.day,
            conflict.slot_label,
            ...(conflict.groups || []),
            ...(conflict.activities || []).map((activity) => `${activity.course_code || ''} ${activity.group_id || ''} ${activity.label || ''}`),
        ]
            .filter(Boolean)
            .join(' ')
            .toLowerCase();
        if (!haystack.includes(groupSearch)) {
            return false;
        }
    }
    return true;
}

function renderTeacherConflicts() {
    const tbody = document.getElementById('teacherConflictTableBody');
    if (!tbody) return;
    const conflicts = (state.telemetry.teacher_conflicts || [])
        .slice()
        .sort((a, b) => {
            if (a.teacher_id === b.teacher_id) {
                if (a.day === b.day) {
                    return (a.slot_index ?? 0) - (b.slot_index ?? 0);
                }
                return (a.day || '').localeCompare(b.day || '');
            }
            return (a.teacher_name || a.teacher_id || '').localeCompare(b.teacher_name || b.teacher_id || '');
        })
        .filter(filterTeacherConflict);

    if (!conflicts.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center py-4 text-muted">No teacher overlaps detected for the current filters.</td></tr>';
    } else {
        tbody.innerHTML = conflicts
            .map((conflict) => `
                <tr>
                    <td>
                        <div class="fw-semibold">${conflict.teacher_name || conflict.teacher_id}</div>
                        <div class="small text-muted">${conflict.teacher_id || '—'}</div>
                    </td>
                    <td>${conflict.day || '—'}</td>
                    <td>
                        <div class="fw-semibold">${conflict.slot_label || 'Slot'}</div>
                        <div class="small text-muted">Index ${conflict.slot_index ?? '—'}</div>
                    </td>
                    <td>${formatConflictStatus(conflict)}</td>
                    <td>${formatActivities(conflict.activities)}</td>
                </tr>`)
            .join('');
    }

    setText('teacherConflictCount', conflicts.length);
}

function filterTeacherConflict(conflict) {
    const { teacherDay, teacherSearch } = state.filters;
    if (teacherDay !== 'all' && conflict.day !== teacherDay) {
        return false;
    }
    if (teacherSearch) {
        const haystack = [
            conflict.teacher_name,
            conflict.teacher_id,
            conflict.day,
            conflict.slot_label,
            ...(conflict.activities || []).map((activity) => `${activity.group_id || ''} ${activity.department || ''} ${activity.course_code || ''}`),
        ]
            .filter(Boolean)
            .join(' ')
            .toLowerCase();
        if (!haystack.includes(teacherSearch)) {
            return false;
        }
    }
    return true;
}

function formatGroups(groups = []) {
    if (!groups || !groups.length) {
        return '<span class="text-muted small">No groups recorded</span>';
    }
    const chips = groups
        .slice(0, 4)
        .map((group) => `<span class="slot-chip">${group}</span>`)
        .join('');
    const remainder = groups.length > 4 ? `<span class="slot-chip muted">+${groups.length - 4} more</span>` : '';
    return `<div class="slot-chip-group">${chips}${remainder}</div>`;
}

function formatActivities(activities = []) {
    if (!activities.length) {
        return '<span class="text-muted small">No activities recorded</span>';
    }
    const chips = activities
        .slice(0, 4)
        .map((activity) => {
            const label = activity.label || activity.course_code || activity.kind || 'Session';
            const prefix = activity.kind === 'lab' ? 'Lab' : 'Theory';
            const suffix = activity.group_id ? ` · ${activity.group_id}` : '';
            return `<span class="slot-chip">${prefix}: ${label}${suffix}</span>`;
        })
        .join('');
    const remainder = activities.length > 4 ? `<span class="slot-chip muted">+${activities.length - 4} more</span>` : '';
    return `<div class="slot-chip-group">${chips}${remainder}</div>`;
}

function formatConflictStatus(conflict) {
    if (!conflict) {
        return '<span class="text-muted small">No metadata</span>';
    }
    const label = conflict.conflict_type?.replace(/_/g, ' ') || 'Conflict window';
    const detail = conflict.status_detail || 'Multiple assignments share this window';
    return `<div class="d-flex flex-column gap-1">
        <span class="badge bg-warning-subtle text-dark">${label}</span>
        <span class="text-muted small">${detail}</span>
    </div>`;
}

function renderConstraints() {
    const panel = document.getElementById('constraintPanel');
    if (!panel) return;
    const constraints = state.telemetry.constraints || {};

    const cards = Object.entries(CONSTRAINT_LABELS).map(([key, label]) => {
        const constraint = constraints[key];
        if (!constraint) {
            return `
                <div class="col-12 col-lg-4">
                    <div class="constraint-card">
                        <div class="constraint-title">${label}</div>
                        <div class="text-muted small">Constraint telemetry missing.</div>
                    </div>
                </div>`;
        }
        const statusClass = constraint.status === 'ok' ? 'success' : constraint.status === 'warning' ? 'warning' : 'info';
        const detailsHtml = formatDetailList(constraint.details);
        return `
            <div class="col-12 col-lg-4">
                <div class="constraint-card">
                    <div class="constraint-title d-flex justify-content-between align-items-start">
                        <span>${constraint.name || label}</span>
                        <span class="status-pill ${statusClass}">${constraint.status || 'n/a'}</span>
                    </div>
                    <div class="constraint-meta small text-muted">
                        Priority ${constraint.priority ?? '—'} · ${constraint.enabled ? 'Enabled' : 'Disabled'}
                    </div>
                    ${detailsHtml}
                </div>
            </div>`;
    }).join('');

    panel.innerHTML = cards;
}

function formatDetailList(details) {
    if (!details || typeof details !== 'object') {
        return '<div class="text-muted small">No additional metadata.</div>';
    }
    const entries = Object.entries(details);
    if (!entries.length) {
        return '<div class="text-muted small">No additional metadata.</div>';
    }
    const rows = entries.slice(0, 8).map(([key, value]) => `
        <div class="detail-row">
            <span class="detail-key">${formatLabel(key)}</span>
            <span class="detail-value">${formatValue(value)}</span>
        </div>`);
    return `<div class="detail-list">${rows.join('')}</div>`;
}

function formatTimestamp(timestamp) {
    if (!timestamp) {
        return 'Telemetry not generated';
    }
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

function formatLabel(label) {
    if (!label) return '';
    return `${label}`
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatValue(value) {
    if (Array.isArray(value)) {
        if (!value.length) {
            return '—';
        }
        return value.slice(0, 4).join(', ') + (value.length > 4 ? ` (+${value.length - 4})` : '');
    }
    if (typeof value === 'object' && value !== null) {
        return JSON.stringify(value);
    }
    if (value === null || value === undefined || value === '') {
        return '—';
    }
    return `${value}`;
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

function showError(message) {
    const banner = document.getElementById('alertBanner');
    if (!banner) return;
    banner.classList.remove('d-none', 'alert-warning');
    banner.classList.add('alert-danger');
    banner.textContent = message;
}

function showWarning(message) {
    const banner = document.getElementById('alertBanner');
    if (!banner) return;
    banner.classList.remove('d-none', 'alert-danger');
    banner.classList.add('alert-warning');
    banner.textContent = message;
}

function hideBanner() {
    const banner = document.getElementById('alertBanner');
    if (!banner) return;
    banner.classList.add('d-none');
}
