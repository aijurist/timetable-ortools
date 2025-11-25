'use strict';

const CONSTRAINT_LABELS = {
    group_non_overlap: 'Department Group Non-Overlap',
};

const state = {
    snapshot: null,
    telemetry: defaultTelemetry(),
    filters: {
        department: 'all',
        coverage: 'all',
        search: '',
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
            showWarning('Grouping telemetry was not generated for the latest snapshot. Re-run the solver with telemetry enabled.');
        }
    } catch (error) {
        showError(error.message || 'Failed to load grouping telemetry.');
        console.error(error);
    }
}

function defaultTelemetry() {
    return {
        generated_at: null,
        summary: {
            total_groups: 0,
            departments: 0,
            groups_without_lab_sessions: 0,
            groups_without_theory_slots: 0,
        },
        departments: [],
        constraints: {},
    };
}

async function loadTelemetry() {
    const response = await fetch('/api/grouping', { cache: 'no-store' });
    await ensureOk(response);
    const payload = await response.json();
    state.snapshot = payload.snapshot || null;
    state.telemetry = normalizeTelemetry(payload.data || {});
    hideBanner();
}

function normalizeTelemetry(raw = {}) {
    return {
        generated_at: raw.generated_at || null,
        summary: {
            total_groups: raw.summary?.total_groups ?? 0,
            departments: raw.summary?.departments ?? 0,
            groups_without_lab_sessions: raw.summary?.groups_without_lab_sessions ?? 0,
            groups_without_theory_slots: raw.summary?.groups_without_theory_slots ?? 0,
        },
        departments: Array.isArray(raw.departments) ? raw.departments : [],
        constraints: raw.constraints || {},
    };
}

function attachEvents() {
    document.getElementById('departmentFilter')?.addEventListener('change', (event) => {
        state.filters.department = event.target.value;
        renderGroupTable();
    });

    document.getElementById('coverageFilter')?.addEventListener('change', (event) => {
        state.filters.coverage = event.target.value;
        renderGroupTable();
    });

    document.getElementById('groupSearch')?.addEventListener('input', debounce((event) => {
        state.filters.search = event.target.value.toLowerCase();
        renderGroupTable();
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
        const filename = state.snapshot?.folder ? `grouping_${state.snapshot.folder}.json` : 'grouping_telemetry.json';
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
    renderDepartmentFilter();
    renderDepartmentTable();
    renderGroupTable();
    renderConstraints();
}

function updateSnapshotBanner() {
    setText('snapshotLabel', state.snapshot?.folder || '—');
}

function renderSummary() {
    const summary = state.telemetry.summary || {};
    setText('summaryTotalGroups', summary.total_groups ?? 0);
    setText('summaryDepartments', summary.departments ?? 0);
    setText('summaryMissingLab', summary.groups_without_lab_sessions ?? 0);
    setText('summaryMissingTheory', summary.groups_without_theory_slots ?? 0);
    setText('telemetryTimestamp', formatTimestamp(state.telemetry.generated_at));
}

function renderDepartmentFilter() {
    const select = document.getElementById('departmentFilter');
    if (!select) return;
    const options = new Set((state.telemetry.departments || []).map((dept) => dept.department).filter(Boolean));
    const sorted = Array.from(options).sort((a, b) => `${a}`.localeCompare(`${b}`));
    const current = state.filters.department;
    select.innerHTML = ['<option value="all">All departments</option>', ...sorted.map((department) => `<option value="${department}">${department}</option>`)].join('');
    select.value = sorted.includes(current) ? current : 'all';
    state.filters.department = select.value;
}

function renderDepartmentTable() {
    const tbody = document.getElementById('departmentTableBody');
    if (!tbody) return;
    const data = (state.telemetry.departments || []).slice().sort((a, b) => {
        if (a.department === b.department) {
            return (a.semester ?? 0) - (b.semester ?? 0);
        }
        return (a.department || '').localeCompare(b.department || '');
    });

    if (!data.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-muted">No department telemetry detected for the current snapshot.</td></tr>';
    } else {
        tbody.innerHTML = data
            .map((entry) => `
                <tr>
                    <td>${entry.department || '—'}</td>
                    <td>${entry.semester ?? '—'}</td>
                    <td>${entry.group_count ?? 0}</td>
                    <td>${entry.lab_sessions ?? 0}</td>
                    <td>${entry.theory_slots ?? 0}</td>
                </tr>`)
            .join('');
    }

    setText('departmentCount', data.length);
}

function renderGroupTable() {
    const tbody = document.getElementById('groupTableBody');
    if (!tbody) return;
    const groups = buildGroupRecords();
    const filtered = filterGroups(groups);

    if (!filtered.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-muted">No groups match the current filters.</td></tr>';
    } else {
        tbody.innerHTML = filtered
            .map((group) => `
                <tr>
                    <td>
                        <div class="fw-semibold">${group.group_id}</div>
                        <div class="small text-muted">Course instances: ${formatList(group.course_instances)}</div>
                    </td>
                    <td>
                        <div>${group.department || '—'}</div>
                        <div class="small text-muted">Semester ${group.semester ?? '—'}</div>
                    </td>
                    <td>
                        <div class="fw-semibold">${group.lab_session_count || 0} sessions</div>
                        ${formatSlots(group.lab_sessions)}
                    </td>
                    <td>
                        <div class="fw-semibold">${group.theory_slot_count || 0} slots</div>
                        ${formatSlots(group.theory_slots)}
                    </td>
                    <td>${formatList(group.teachers)}</td>
                    <td>${formatList(group.course_codes)}</td>
                    <td>${formatGroupFlags(group)}</td>
                </tr>`)
            .join('');
    }

    setText('groupCount', filtered.length);
}

function buildGroupRecords() {
    const records = [];
    (state.telemetry.departments || []).forEach((bucket) => {
        (bucket.groups || []).forEach((group) => {
            records.push({
                ...group,
                department: bucket.department || 'Unassigned',
                semester: bucket.semester,
                missingLab: (group.lab_session_count ?? 0) === 0,
                missingTheory: (group.theory_slot_count ?? 0) === 0,
            });
        });
    });
    return records;
}

function filterGroups(groups) {
    const { department, coverage, search } = state.filters;
    return groups.filter((group) => {
        if (department !== 'all' && group.department !== department) {
            return false;
        }
        if (coverage === 'needs-lab' && !group.missingLab) {
            return false;
        }
        if (coverage === 'needs-theory' && !group.missingTheory) {
            return false;
        }
        if (search) {
            const haystack = [
                group.group_id,
                group.department,
                group.semester,
                ...(group.course_codes || []),
                ...(group.teachers || []),
                ...(group.lab_sessions || []),
                ...(group.theory_slots || []),
            ]
                .filter(Boolean)
                .join(' ')
                .toLowerCase();
            if (!haystack.includes(search)) {
                return false;
            }
        }
        return true;
    });
}

function formatGroupFlags(group) {
    const badges = [];
    if (group.missingLab) {
        badges.push('<span class="badge bg-danger-subtle text-danger">Needs lab coverage</span>');
    }
    if (group.missingTheory) {
        badges.push('<span class="badge bg-warning-subtle text-dark">Needs theory coverage</span>');
    }
    if (!badges.length) {
        return '<span class="badge bg-success-subtle text-success">Healthy</span>';
    }
    return `<div class="d-flex flex-wrap gap-1">${badges.join('')}</div>`;
}

function formatSlots(slots = []) {
    if (!slots || !slots.length) {
        return '<span class="text-muted small">No sessions recorded</span>';
    }
    const chips = slots
        .slice(0, 3)
        .map((slot) => `<span class="slot-chip">${slot}</span>`)
        .join('');
    const remainder = slots.length > 3 ? `<span class="slot-chip muted">+${slots.length - 3} more</span>` : '';
    return `<div class="slot-chip-group">${chips}${remainder}</div>`;
}

function renderConstraints() {
    const panel = document.getElementById('constraintPanel');
    if (!panel) return;
    const constraints = state.telemetry.constraints || {};

    if (!Object.keys(CONSTRAINT_LABELS).length) {
        panel.innerHTML = '<div class="col-12"><div class="empty-hint">No constraint metadata configured.</div></div>';
        return;
    }

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

function formatList(values = []) {
    if (!values || !values.length) {
        return '<span class="text-muted">—</span>';
    }
    return values.join(', ');
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
