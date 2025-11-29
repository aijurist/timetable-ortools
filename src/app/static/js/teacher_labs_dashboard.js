'use strict';

const FLAG_META = {
    over_daily: { label: 'Over daily cap', className: 'danger' },
    early_late: { label: 'Early + late', className: 'warning' },
    triple_block: { label: 'Early-buffer-late', className: 'info' },
    long_run: { label: 'Consecutive streak', className: 'secondary' },
};

const state = {
    snapshot: null,
    telemetry: defaultTelemetry(),
    filters: {
        teacherFlag: 'all',
        teacherSearch: '',
        eventType: 'all',
        daySearch: '',
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
            showWarning('Teacher telemetry was not generated for the latest snapshot. Re-run the solver to capture data.');
        }
    } catch (error) {
        showError(error.message || 'Failed to load teacher telemetry.');
        console.error(error);
    }
}

function defaultTelemetry() {
    return {
        generated_at: null,
        policies: {
            max_daily_sessions: null,
            max_consecutive_sessions: null,
            early_sessions: [],
            buffer_sessions: [],
            late_sessions: [],
        },
        summary: {
            teachers_in_schedule: 0,
            days_monitored: 0,
            days_over_daily_cap: 0,
            teachers_over_daily_cap: 0,
            early_late_conflicts: 0,
            triple_blocks: 0,
            teachers_long_consecutive: 0,
            long_consecutive_windows: 0,
        },
        teachers: [],
        constraints: {},
        metadata: {},
    };
}

async function loadTelemetry() {
    const response = await fetch('/api/teacher-labs', { cache: 'no-store' });
    await ensureOk(response);
    const payload = await response.json();
    state.snapshot = payload.snapshot || null;
    state.telemetry = normalizeTelemetry(payload.data || {});
    hideBanner();
}

function normalizeTelemetry(raw = {}) {
    const fallback = defaultTelemetry();
    return {
        generated_at: raw.generated_at || null,
        policies: {
            max_daily_sessions: raw.policies?.max_daily_sessions ?? fallback.policies.max_daily_sessions,
            max_consecutive_sessions: raw.policies?.max_consecutive_sessions ?? fallback.policies.max_consecutive_sessions,
            early_sessions: Array.isArray(raw.policies?.early_sessions) ? raw.policies.early_sessions : [],
            buffer_sessions: Array.isArray(raw.policies?.buffer_sessions) ? raw.policies.buffer_sessions : [],
            late_sessions: Array.isArray(raw.policies?.late_sessions) ? raw.policies.late_sessions : [],
        },
        summary: {
            teachers_in_schedule: raw.summary?.teachers_in_schedule ?? 0,
            days_monitored: raw.summary?.days_monitored ?? 0,
            days_over_daily_cap: raw.summary?.days_over_daily_cap ?? 0,
            teachers_over_daily_cap: raw.summary?.teachers_over_daily_cap ?? 0,
            early_late_conflicts: raw.summary?.early_late_conflicts ?? 0,
            triple_blocks: raw.summary?.triple_blocks ?? 0,
            teachers_long_consecutive: raw.summary?.teachers_long_consecutive ?? 0,
            long_consecutive_windows: raw.summary?.long_consecutive_windows ?? 0,
        },
        teachers: Array.isArray(raw.teachers) ? raw.teachers : [],
        constraints: raw.constraints || {},
        metadata: raw.metadata || fallback.metadata,
    };
}

function attachEvents() {
    document.getElementById('teacherFlagFilter')?.addEventListener('change', (event) => {
        state.filters.teacherFlag = event.target.value;
        renderTeacherTable();
    });

    document.getElementById('teacherSearch')?.addEventListener('input', debounce((event) => {
        state.filters.teacherSearch = event.target.value.toLowerCase();
        renderTeacherTable();
    }, 200));

    document.getElementById('eventTypeFilter')?.addEventListener('change', (event) => {
        state.filters.eventType = event.target.value;
        renderDayEvents();
    });

    document.getElementById('daySearch')?.addEventListener('input', debounce((event) => {
        state.filters.daySearch = event.target.value.toLowerCase();
        renderDayEvents();
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
        const filename = state.snapshot?.folder ? `teacher_labs_${state.snapshot.folder}.json` : 'teacher_lab_telemetry.json';
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
    renderPolicies();
    renderTeacherTable();
    renderDayEvents();
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
    setText('snapshotLabel', label);
}

function renderSummary() {
    const summary = state.telemetry.summary || {};
    setText('summaryTeachers', summary.teachers_in_schedule ?? 0);
    setText('summaryDaysOverCap', summary.days_over_daily_cap ?? 0);
    setText('summaryLongRuns', summary.long_consecutive_windows ?? 0);
    setText('telemetryTimestamp', formatTimestamp(state.telemetry.generated_at));
}

function renderPolicies() {
    const container = document.getElementById('policyCards');
    if (!container) return;
    const { policies, summary } = state.telemetry;

    if (!policies || !Object.keys(policies).length) {
        container.innerHTML = '<div class="col-12"><div class="empty-hint">No policy data available.</div></div>';
        return;
    }

    container.innerHTML = `
        <div class="col-12 col-lg-4">
            <div class="limit-card border-primary">
                <div class="limit-icon bg-primary"><i class="fas fa-user-clock"></i></div>
                <div>
                    <div class="limit-label">Daily session cap</div>
                    <div class="limit-value">${policies.max_daily_sessions ?? '—'}</div>
                    <div class="limit-meta">Days observed: ${summary.days_monitored ?? 0}</div>
                    <div class="small text-muted">Over-cap days: <strong>${summary.days_over_daily_cap ?? 0}</strong></div>
                    <div class="small text-muted">Teachers affected: <strong>${summary.teachers_over_daily_cap ?? 0}</strong></div>
                </div>
            </div>
        </div>
        <div class="col-12 col-lg-4">
            <div class="limit-card border-warning">
                <div class="limit-icon bg-warning text-dark"><i class="fas fa-stream"></i></div>
                <div>
                    <div class="limit-label">Consecutive streak limit</div>
                    <div class="limit-value">${policies.max_consecutive_sessions ?? '—'}</div>
                    <div class="limit-meta">Long runs detected: ${summary.long_consecutive_windows ?? 0}</div>
                    <div class="small text-muted">Teachers affected: <strong>${summary.teachers_long_consecutive ?? 0}</strong></div>
                </div>
            </div>
        </div>
        <div class="col-12 col-lg-4">
            <div class="limit-card border-info">
                <div class="limit-icon bg-info text-dark"><i class="fas fa-hourglass-half"></i></div>
                <div>
                    <div class="limit-label">Window policies</div>
                    <div class="limit-meta">Early: ${formatList(policies.early_sessions)}</div>
                    <div class="limit-meta">Buffer: ${formatList(policies.buffer_sessions)}</div>
                    <div class="limit-meta">Late: ${formatList(policies.late_sessions)}</div>
                    <div class="small text-muted">Early+late days: <strong>${summary.early_late_conflicts ?? 0}</strong></div>
                    <div class="small text-muted">Triple blocks: <strong>${summary.triple_blocks ?? 0}</strong></div>
                </div>
            </div>
        </div>`;
}

function renderTeacherTable() {
    const tbody = document.getElementById('teacherTableBody');
    if (!tbody) return;
    const teachers = state.telemetry.teachers || [];
    const filtered = teachers
        .filter(filterTeachers)
        .sort((a, b) => (a.teacher_name || '').localeCompare(b.teacher_name || ''));

    if (!filtered.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-muted">No teachers match the current filters.</td></tr>';
    } else {
        tbody.innerHTML = filtered
            .map((teacher) => {
                const counts = getFlagCounts(teacher);
                const departments = formatList(teacher.departments);
                const flaggedCount = counts.total;
                const longestRun = Math.max(0, ...((teacher.day_usage || []).map((day) => day.longest_run || 0)));
                const highlights = buildTeacherHighlights({
                    overCapDays: counts.over_daily,
                    longRunDays: counts.long_run,
                    earlyLateDays: counts.early_late,
                    tripleDays: counts.triple_block,
                });
                const statusCell = formatTeacherStatus(teacher, counts);

                return `
                    <tr>
                        <td>
                            <div class="fw-semibold">${teacher.teacher_name || teacher.teacher_id}</div>
                            <div class="text-muted small">${teacher.teacher_id}</div>
                        </td>
                        <td>${departments || '—'}</td>
                        <td>${teacher.total_sessions ?? 0}</td>
                        <td>${flaggedCount ? `${flaggedCount} flagged` : 'Healthy'}</td>
                        <td>${statusCell}</td>
                        <td>${longestRun}</td>
                        <td>${highlights}</td>
                    </tr>`;
            })
            .join('');
    }

    setText('teacherCount', filtered.length);
}

function renderDayEvents() {
    const tbody = document.getElementById('dayEventTableBody');
    if (!tbody) return;
    const events = buildDayEvents(state.telemetry.teachers || []);
    const filtered = events.filter(filterDayEvents);

    if (!filtered.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center py-4 text-muted">No day-level events detected for the selected filters.</td></tr>';
    } else {
        tbody.innerHTML = filtered
            .map((event) => {
                return `
                    <tr>
                        <td>
                            <div class="fw-semibold">${event.teacher_name}</div>
                            <div class="text-muted small">${event.teacher_id}</div>
                        </td>
                        <td>${event.day}</td>
                        <td>${formatSessions(event.sessions)}</td>
                        <td>${formatFlagBadges(event.flags)}</td>
                    </tr>`;
            })
            .join('');
    }

    setText('dayEventCount', filtered.length);
}

function filterTeachers(teacher) {
    const flagFilter = state.filters.teacherFlag;
    if (flagFilter === 'over-cap' && !teacher.flags?.over_daily_cap) {
        return false;
    }
    if (flagFilter === 'consecutive' && !teacher.flags?.long_consecutive_run) {
        return false;
    }

    const search = state.filters.teacherSearch;
    if (search) {
        const haystack = [
            teacher.teacher_name,
            teacher.teacher_id,
            ...(teacher.departments || []),
            ...(teacher.courses || []),
            ...(teacher.day_usage?.flatMap((day) => day.sessions?.map((session) => session.group_id || '') || []) || []),
        ]
            .filter(Boolean)
            .join(' ')
            .toLowerCase();
        if (!haystack.includes(search)) {
            return false;
        }
    }

    return true;
}

function filterDayEvents(event) {
    const typeFilter = state.filters.eventType;
    if (typeFilter !== 'all' && !event.flags.includes(typeFilter)) {
        return false;
    }

    const search = state.filters.daySearch;
    if (search) {
        const haystack = [
            event.teacher_name,
            event.teacher_id,
            event.day,
            ...(event.sessions || []).map((session) => `${session.session || ''} ${session.course_code || ''} ${session.group_id || ''}`),
        ]
            .filter(Boolean)
            .join(' ')
            .toLowerCase();
        if (!haystack.includes(search)) {
            return false;
        }
    }

    return true;
}

function buildDayEvents(teachers) {
    const events = [];
    teachers.forEach((teacher) => {
        (teacher.day_usage || []).forEach((day) => {
            const flags = [];
            if (day.flags?.over_daily_cap) flags.push('over_daily');
            if (day.flags?.early_and_late) flags.push('early_late');
            if (day.flags?.triple_block) flags.push('triple_block');
            if (day.flags?.long_consecutive_run) flags.push('long_run');
            if (!flags.length) return;
            events.push({
                teacher_id: teacher.teacher_id,
                teacher_name: teacher.teacher_name || teacher.teacher_id,
                day: day.day,
                sessions: day.sessions || [],
                flags,
            });
        });
    });
    return events;
}

function hasAnyFlag(flags = {}) {
    return Boolean(flags.over_daily_cap || flags.early_and_late || flags.triple_block || flags.long_consecutive_run);
}

function buildTeacherHighlights({ overCapDays, longRunDays, earlyLateDays, tripleDays }) {
    const badges = [];
    if (overCapDays) badges.push(`<span class="badge bg-danger-subtle text-danger">Daily cap ×${overCapDays}</span>`);
    if (longRunDays) badges.push(`<span class="badge bg-warning-subtle text-dark">Consecutive ×${longRunDays}</span>`);
    if (earlyLateDays) badges.push(`<span class="badge bg-info-subtle text-info">Early+late ×${earlyLateDays}</span>`);
    if (tripleDays) badges.push(`<span class="badge bg-secondary-subtle text-secondary">Triple ×${tripleDays}</span>`);
    if (!badges.length) {
        return '<span class="badge bg-success-subtle text-success">Healthy</span>';
    }
    return `<div class="d-flex flex-wrap gap-1">${badges.join('')}</div>`;
}

function getFlagCounts(teacher) {
    if (teacher.flag_counts) {
        const counts = {
            over_daily: teacher.flag_counts.over_daily || 0,
            long_run: teacher.flag_counts.long_run || 0,
            early_late: teacher.flag_counts.early_late || 0,
            triple_block: teacher.flag_counts.triple_block || 0,
        };
        const total = Object.values(counts).reduce((acc, value) => acc + Number(value || 0), 0);
        return { ...counts, total };
    }
    const usage = teacher.day_usage || [];
    const counts = {
        over_daily: usage.filter((day) => day.flags?.over_daily_cap).length,
        long_run: usage.filter((day) => day.flags?.long_consecutive_run).length,
        early_late: usage.filter((day) => day.flags?.early_and_late).length,
        triple_block: usage.filter((day) => day.flags?.triple_block).length,
    };
    const total = Object.values(counts).reduce((acc, value) => acc + Number(value || 0), 0);
    return { ...counts, total };
}

function formatTeacherStatus(teacher, counts = getFlagCounts(teacher)) {
    const status = teacher.status || (counts.total ? 'attention' : 'healthy');
    const label = teacher.status_label || (status === 'healthy' ? 'Healthy' : 'Needs review');
    const detail = teacher.status_detail || (counts.total ? `${counts.total} policy flag(s)` : 'All observed days within limits');
    const cls = status === 'healthy' ? 'status-pill success' : 'status-pill warning';
    return `<div class="d-flex flex-column gap-1">
        <span class="${cls}">${label}</span>
        <span class="text-muted small">${detail}</span>
    </div>`;
}

function formatSessions(sessions = []) {
    if (!sessions.length) {
        return '<span class="text-muted small">No sessions recorded</span>';
    }
    const chips = sessions
        .slice(0, 4)
        .map((session) => `<span class="slot-chip">${session.session || 'Slot'} · ${session.course_code || ''}</span>`)
        .join('');
    const remainder = sessions.length > 4 ? `<span class="slot-chip muted">+${sessions.length - 4} more</span>` : '';
    return `<div class="slot-chip-group">${chips}${remainder}</div>`;
}

function formatFlagBadges(flags = []) {
    if (!flags.length) {
        return '<span class="badge bg-success-subtle text-success">Healthy</span>';
    }
    return flags
        .map((flag) => {
            const meta = FLAG_META[flag] || { label: flag, className: 'secondary' };
            const className = meta.className === 'secondary' ? 'bg-secondary-subtle text-secondary' : `bg-${meta.className}-subtle text-${meta.className}`;
            return `<span class="badge ${className}">${meta.label}</span>`;
        })
        .join(' ');
}

function formatList(values = []) {
    if (!values || !values.length) {
        return '<span class="text-muted">—</span>';
    }
    return values.join(', ');
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

function formatValue(value) {
    if (Array.isArray(value)) {
        if (!value.length) {
            return '—';
        }
        return value.join(', ');
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
