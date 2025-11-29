'use strict';

const GROUP_TYPE_LABELS = {
    core: 'Core',
    computing: 'Computing',
};

const LIMIT_META = [
    { key: 'core_group_slot_cap', label: 'Core group slot cap', icon: 'fa-layer-group', accent: 'primary' },
    { key: 'computing_group_slot_cap', label: 'Computing group slot cap', icon: 'fa-microchip', accent: 'info' },
    { key: 'semester_slot_cap', label: 'Semester slot cap', icon: 'fa-building-columns', accent: 'warning' },
];

const CONSTRAINT_LABELS = {
    core_group_slot_cap: 'Core Group Slot Cap',
    computing_group_slot_cap: 'Computing Group Slot Cap',
    semester_slot_cap: 'Semester Lab Slot Cap',
};

const state = {
    snapshot: null,
    telemetry: defaultTelemetry(),
    filters: {
        groupType: 'all',
        breach: 'all',
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
            showWarning('Slot cap telemetry was not generated for the latest snapshot. Run the solver with telemetry enabled.');
        }
    } catch (error) {
        showError(error.message || 'Failed to load slot cap telemetry.');
        console.error(error);
    }
}

function defaultTelemetry() {
    return {
        generated_at: null,
        summary: {
            groups_monitored: 0,
            groups_over_limit: 0,
            semesters_over_limit: 0,
            core_over_limit: 0,
            computing_over_limit: 0,
        },
        limits: {},
        core_groups: [],
        computing_groups: [],
        semesters: [],
        constraints: {},
        metadata: {},
    };
}

async function loadTelemetry() {
    const response = await fetch('/api/slot-caps', { cache: 'no-store' });
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
            groups_monitored: raw.summary?.groups_monitored ?? 0,
            groups_over_limit: raw.summary?.groups_over_limit ?? 0,
            semesters_over_limit: raw.summary?.semesters_over_limit ?? 0,
            core_over_limit: raw.summary?.core_over_limit ?? 0,
            computing_over_limit: raw.summary?.computing_over_limit ?? 0,
        },
        limits: raw.limits || {},
        core_groups: Array.isArray(raw.core_groups) ? raw.core_groups : [],
        computing_groups: Array.isArray(raw.computing_groups) ? raw.computing_groups : [],
        semesters: Array.isArray(raw.semesters) ? raw.semesters : [],
        constraints: raw.constraints || {},
        metadata: raw.metadata || {},
    };
}

function attachEvents() {
    document.getElementById('groupTypeFilter')?.addEventListener('change', (event) => {
        state.filters.groupType = event.target.value;
        renderGroupTable();
    });

    document.getElementById('breachFilter')?.addEventListener('change', (event) => {
        state.filters.breach = event.target.value;
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
        const filename = state.snapshot?.folder ? `slot_caps_${state.snapshot.folder}.json` : 'slot_caps_telemetry.json';
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
    renderLimitCards();
    renderGroupTable();
    renderSemesters();
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
    const label = state.snapshot?.folder || '—';
    document.getElementById('snapshotLabel').textContent = label;
}

function renderSummary() {
    const summary = state.telemetry.summary || {};
    setText('summaryGroupsMonitored', summary.groups_monitored ?? 0);
    setText('summaryGroupsBreached', summary.groups_over_limit ?? 0);
    setText('summarySemestersBreached', summary.semesters_over_limit ?? 0);
    setText('telemetryTimestamp', formatTimestamp(state.telemetry.generated_at));
}

function renderLimitCards() {
    const container = document.getElementById('limitCards');
    if (!container) return;
    const limits = state.telemetry.limits || {};

    if (!Object.keys(limits).length) {
        container.innerHTML = '<div class="col-12"><div class="empty-hint">No slot-cap configuration detected in the telemetry payload.</div></div>';
        return;
    }

    const cards = LIMIT_META.map((config) => {
        const data = limits[config.key] || {};
        const slotLimit = data.slot_limit ?? '—';
        const penalty = data.penalty_weight ? `${data.penalty_weight}` : '—';
        const extraFields = Object.entries(data)
            .filter(([key]) => key !== 'slot_limit' && key !== 'penalty_weight')
            .map(([key, value]) => `<div class="small text-muted text-truncate"><span class="fw-semibold">${formatLabel(key)}:</span> ${formatValue(value)}</div>`) || [];
        return `
            <div class="col-12 col-md-4">
                <div class="limit-card border-${config.accent}">
                    <div class="limit-icon bg-${config.accent}">
                        <i class="fas ${config.icon}"></i>
                    </div>
                    <div>
                        <div class="limit-label">${config.label}</div>
                        <div class="limit-value">${slotLimit}</div>
                        <div class="limit-meta">Penalty weight: ${penalty}</div>
                        ${extraFields.join('')}
                    </div>
                </div>
            </div>`;
    }).join('');

    container.innerHTML = cards;
}

function renderGroupTable() {
    const tbody = document.getElementById('groupTableBody');
    if (!tbody) return;
    const groups = buildGroupRecords();
    const filtered = filterGroups(groups);

    if (!filtered.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center py-4 text-muted">No groups satisfy the current filters.</td></tr>';
    } else {
        tbody.innerHTML = filtered.map((group) => {
            return `
                <tr>
                    <td><span class="badge bg-light text-dark">${GROUP_TYPE_LABELS[group.type] || 'Group'}</span></td>
                    <td>${group.department || '—'}</td>
                    <td>${group.semester ?? '—'}</td>
                    <td>${group.group_id}</td>
                    <td>${group.slots_used}</td>
                    <td>${group.slot_limit ?? '—'}</td>
                    <td>${statusPill(group)}</td>
                    <td>${formatStatusDetail(group)}</td>
                    <td>${formatSlots(group.slots)}</td>
                </tr>`;
        }).join('');
    }

    setText('groupCount', filtered.length);
}

function renderSemesters() {
    const tbody = document.getElementById('semesterTableBody');
    if (!tbody) return;
    const semesters = state.telemetry.semesters || [];
    const sorted = semesters.slice().sort((a, b) => {
        if (a.department === b.department) {
            return (a.semester ?? 0) - (b.semester ?? 0);
        }
        return (a.department || '').localeCompare(b.department || '');
    });

    if (!sorted.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-muted">No semester telemetry available.</td></tr>';
    } else {
        tbody.innerHTML = sorted.map((entry) => `
            <tr>
                <td>${entry.department || '—'}</td>
                <td>${entry.semester ?? '—'}</td>
                <td>${entry.slots_used}</td>
                <td>${entry.slot_limit ?? '—'}</td>
                <td>${statusPill(entry)}</td>
                <td>${formatStatusDetail(entry)}</td>
                <td>${formatSlots(entry.slots)}</td>
            </tr>
        `).join('');
    }

    setText('semesterCount', sorted.length);
}

function renderConstraints() {
    const panel = document.getElementById('constraintPanel');
    if (!panel) return;
    const constraints = state.telemetry.constraints || {};

    if (!Object.keys(constraints).length) {
        panel.innerHTML = '<div class="col-12"><div class="empty-hint">No constraint metadata was persisted with this telemetry payload.</div></div>';
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

function buildGroupRecords() {
    const core = state.telemetry.core_groups.map((item) => ({ ...item, type: 'core' }));
    const computing = state.telemetry.computing_groups.map((item) => ({ ...item, type: 'computing' }));
    return [...core, ...computing];
}

function filterGroups(groups) {
    const { groupType, breach, search } = state.filters;
    return groups.filter((group) => {
        if (groupType !== 'all' && group.type !== groupType) return false;
        if (breach === 'breached' && !group.breached) return false;
        if (breach === 'healthy' && group.breached) return false;
        if (search) {
            const haystack = [
                group.group_id,
                group.department,
                group.semester,
                ...(group.slots || []),
            ]
                .filter(Boolean)
                .join(' ')
                .toLowerCase();
            if (!haystack.includes(search)) return false;
        }
        return true;
    });
}

function formatSlots(slots = []) {
    if (!slots.length) {
        return '<span class="text-muted small">No slots recorded</span>';
    }
    const chips = slots.slice(0, 4).map((slot) => `<span class="slot-chip">${slot}</span>`).join('');
    const remainder = slots.length > 4 ? `<span class="slot-chip muted">+${slots.length - 4} more</span>` : '';
    return `<div class="slot-chip-group">${chips}${remainder}</div>`;
}

function formatDetailList(details) {
    if (!details || typeof details !== 'object') {
        return '<div class="text-muted small">No additional metadata.</div>';
    }
    const entries = Object.entries(details);
    if (!entries.length) {
        return '<div class="text-muted small">No additional metadata.</div>';
    }
    const rows = entries.slice(0, 8).map(([key, value]) => {
        return `<div class="detail-row"><span class="detail-key">${formatLabel(key)}</span><span class="detail-value">${formatValue(value)}</span></div>`;
    });
    return `<div class="detail-list">${rows.join('')}</div>`;
}

function statusPill(entry) {
    const status = entry?.status || (entry?.breached ? 'breached' : 'healthy');
    const label = entry?.status_label || (status === 'breached' ? 'Over limit' : status === 'healthy' ? 'Within limit' : 'No cap');
    let cls = 'status-pill secondary';
    if (status === 'breached') cls = 'status-pill danger';
    else if (status === 'healthy') cls = 'status-pill success';
    else if (status === 'unbounded') cls = 'status-pill info';
    return `<span class="${cls}">${label}</span>`;
}

function formatStatusDetail(entry = {}) {
    if (entry.status_detail) {
        return `<span class="text-muted small">${entry.status_detail}</span>`;
    }
    if (entry.slot_limit == null) {
        return '<span class="text-muted small">No cap configured</span>';
    }
    return `<span class="text-muted small">${entry.slots_used ?? 0}/${entry.slot_limit} slots</span>`;
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
        return value.slice(0, 4).join(', ') + (value.length > 4 ? ` (+${value.length - 4} more)` : '');
    }
    if (typeof value === 'object' && value !== null) {
        return JSON.stringify(value);
    }
    if (value === null || value === undefined || value === '') {
        return '—';
    }
    return `${value}`;
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

function debounce(fn, delay = 200) {
    let timeout;
    return (...args) => {
        clearTimeout(timeout);
        timeout = setTimeout(() => fn(...args), delay);
    };
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
