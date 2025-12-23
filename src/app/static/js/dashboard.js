'use strict';

const DAY_ORDER = ['monday', 'tuesday', 'wed', 'thur', 'fri', 'saturday'];
const DAY_LABELS = {
    monday: 'Monday',
    tuesday: 'Tuesday',
    wed: 'Wednesday',
    thur: 'Thursday',
    fri: 'Friday',
    saturday: 'Saturday',
};

const state = {
    sessions: [],
    rooms: [],
    unassigned: [],
    metrics: null,
    snapshot: null,
    solverMetrics: null,
    warmStart: null,
};

const charts = {};

const $ = (selector) => document.querySelector(selector);

document.addEventListener('DOMContentLoaded', () => {
    bootstrapDashboard();
});

async function bootstrapDashboard() {
    try {
        await loadPayloads();
        populateFilters();
        populateRoomFilters();
        attachEvents();
        renderAll();
    } catch (error) {
        showError(error.message || 'Something went wrong while loading the dashboard');
        console.error(error);
    }
}

async function loadPayloads() {
    const [scheduleRes, metricsRes, roomsRes, solverRes, warmStartRes] = await Promise.all([
        fetch('/api/schedule'),
        fetch('/api/metrics'),
        fetch('/api/rooms'),
        fetch('/api/solver-metrics', { cache: 'no-store' }),
        fetch('/api/warm-start', { cache: 'no-store' }),
    ]);

    await handleResponseError(scheduleRes);
    await handleResponseError(metricsRes);
    await handleResponseError(roomsRes);
    await handleResponseError(solverRes);
    await handleResponseError(warmStartRes);

    const scheduleJson = await scheduleRes.json();
    const metricsJson = await metricsRes.json();
    const roomsJson = await roomsRes.json();
    const solverJson = await solverRes.json();
    const warmStartJson = await warmStartRes.json();

    state.snapshot = scheduleJson.snapshot;
    state.metrics = metricsJson;
    state.sessions = normalizeSessions(scheduleJson.data || {});
    state.rooms = roomsJson.rooms || [];
    state.unassigned = roomsJson.unassigned || [];
    state.solverMetrics = solverJson.data || null;
    state.warmStart = warmStartJson.data || null;

    updateSnapshotBanner();
    updateHighlights();
}

function normalizeSessions(payload) {
    const labs = (payload.lab_entries || []).map((entry) => normalizeEntry(entry, 'lab'));
    const theory = (payload.theory_entries || []).map((entry) => normalizeEntry(entry, 'theory'));
    const combined = [...theory, ...labs];
    combined.sort((a, b) => {
        if (a.dayIndex === b.dayIndex) {
            return a.timeKey - b.timeKey;
        }
        return a.dayIndex - b.dayIndex;
    });
    return combined;
}

function normalizeEntry(entry, fallbackType) {
    const scheduleType = (entry.schedule_type || fallbackType || 'theory').toLowerCase();
    const day = (entry.day || '').toLowerCase();
    const dayIndex = DAY_ORDER.indexOf(day);
    const timeLabel = entry.time_slot || entry.time_range || entry.session_name || 'Unscheduled';
    const { hour, minute } = parseTimeLabel(timeLabel);
    return {
        scheduleType,
        sessionType: entry.session_type || scheduleType,
        courseCode: entry.course_code || '—',
        courseName: entry.course_name || 'Untitled course',
        department: entry.department || 'Unknown department',
        semester: entry.semester ?? '—',
        groupName: entry.group_name || '',
        groupIndex: entry.group_index ?? '',
        teacherName: entry.teacher_name || 'TBA',
        staffCode: entry.staff_code || '',
        roomNumber: entry.room_number || 'TBD',
        roomId: entry.room_id || '',
        block: entry.block || 'Unassigned block',
        day,
        dayLabel: DAY_LABELS[day] || 'Unscheduled',
        dayIndex: dayIndex >= 0 ? dayIndex : 99,
        dayPattern: entry.day_pattern || '',
        timeLabel,
        hour,
        minute,
        timeKey: hour * 60 + minute,
        sessionNumber: entry.session_number ?? '',
        slotIndex: entry.slot_index ?? '',
        studentCount: entry.student_count ?? entry.total_students ?? '',
        raw: entry,
    };
}

function parseTimeLabel(label) {
    if (!label) {
        return { hour: 99, minute: 0 };
    }
    const parts = label.split('-');
    const start = parts[0]?.trim();
    if (!start) {
        return { hour: 99, minute: 0 };
    }
    const [hourStr, minuteStr] = start.split(':');
    const hour = parseInt(hourStr, 10) || 0;
    const minute = parseInt(minuteStr, 10) || 0;
    return { hour, minute };
}

function populateFilters() {
    fillSelect($('#departmentFilter'), getUniqueValues('department', true), true);
    fillSelect($('#semesterFilter'), getUniqueValues('semester', true), true);
    fillSelect($('#groupFilter'), getUniqueValues('groupName', true), true);

    const daySelect = $('#dayFilter');
    if (daySelect) {
        const options = ['<option value="">All days</option>']
            .concat(DAY_ORDER.map((day) => `<option value="${day}">${DAY_LABELS[day]}</option>`));
        daySelect.innerHTML = options.join('');
    }
}

function populateRoomFilters() {
    const blockSelect = $('#blockFilter');
    const blocks = [...new Set(state.rooms.map((room) => room.block).filter(Boolean))].sort();
    blockSelect.innerHTML = '<option value="">All blocks</option>' +
        blocks.map((block) => `<option value="${block}">${block}</option>`).join('');
}

function fillSelect(select, values, useDefaultLabel) {
    if (!select) return;
    let options = '';
    if (useDefaultLabel) {
        options += '<option value="">All</option>';
    }
    options += values
        .filter((value) => value !== '' && value !== null && value !== undefined)
        .map((value) => `<option value="${value}">${value}</option>`)
        .join('');
    select.innerHTML = options;
}

function getUniqueValues(key, sorted = false) {
    const values = [...new Set(state.sessions.map((session) => session[key]).filter(Boolean))];
    if (sorted) {
        values.sort((a, b) => {
            if (typeof a === 'number' && typeof b === 'number') return a - b;
            return `${a}`.localeCompare(`${b}`);
        });
    }
    return values;
}

function attachEvents() {
    ['departmentFilter', 'semesterFilter', 'groupFilter', 'dayFilter', 'sessionTypeFilter'].forEach((id) => {
        const element = document.getElementById(id);
        if (element) {
            element.addEventListener('change', renderScheduleTable);
        }
    });
    $('#searchInput')?.addEventListener('input', debounce(renderScheduleTable, 250));
    $('#resetFilters')?.addEventListener('click', resetFilters);

    ['blockFilter', 'roomTypeFilter'].forEach((id) => {
        document.getElementById(id)?.addEventListener('change', renderRooms);
    });
    $('#roomSearch')?.addEventListener('input', debounce(renderRooms, 250));
}

function resetFilters() {
    ['departmentFilter', 'semesterFilter', 'groupFilter', 'dayFilter', 'sessionTypeFilter'].forEach((id) => {
        const element = document.getElementById(id);
        if (element) element.value = '';
    });
    $('#searchInput').value = '';
    renderScheduleTable();
}

function renderAll() {
    renderStats();
    renderCharts();
    renderScheduleTable();
    renderRooms();
    renderUnassignedSessions();
}

function renderStats() {
    if (!state.metrics) return;
    const totals = state.metrics.totals || {};
    $('#statSessions').textContent = totals.sessions ?? 0;
    $('#statTheory').textContent = totals.theory ?? 0;
    $('#statLab').textContent = totals.labs ?? 0;
    $('#statDepartments').textContent = totals.departments ?? 0;
    $('#statTeachers').textContent = totals.teachers ?? 0;
    $('#statRooms').textContent = totals.rooms_used ?? 0;
}

function renderCharts() {
    if (!state.metrics) return;

    renderChart('dayChart', state.metrics.day_distribution, {
        label: 'Sessions',
        backgroundColor: '#4c6ef5',
    });

    renderChart('departmentChart', state.metrics.department_load.slice(0, 8), {
        label: 'Sessions',
        backgroundColor: '#7b61ff',
        indexAxis: 'y',
    });

    renderChart('slotChart', state.metrics.slot_distribution.slice(0, 8), {
        label: 'Sessions',
        backgroundColor: '#2ec4b6',
    });
}

function renderChart(canvasId, dataPoints = [], overrides = {}) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const labels = dataPoints.map((item) => formatLabel(item.label));
    const values = dataPoints.map((item) => item.value);
    const axis = overrides.indexAxis || 'x';
    const datasetLabel = overrides.label || 'Sessions';
    const backgroundColor = overrides.backgroundColor || '#4c6ef5';

    if (charts[canvasId]) {
        const chart = charts[canvasId];
        chart.data.labels = labels;
        if (chart.data.datasets[0]) {
            chart.data.datasets[0].data = values;
            chart.data.datasets[0].label = datasetLabel;
            chart.data.datasets[0].backgroundColor = backgroundColor;
        }
        chart.options.indexAxis = axis;
        chart.update('none');
        return;
    }

    const ctx = canvas.getContext('2d');
    charts[canvasId] = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: datasetLabel,
                    data: values,
                    backgroundColor,
                    borderRadius: 12,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: axis,
            scales: {
                x: { grid: { display: false } },
                y: { beginAtZero: true, grid: { color: 'rgba(0,0,0,0.05)' } },
            },
            plugins: { legend: { display: false } },
        },
    });
}

function renderScheduleTable() {
    const tbody = $('#scheduleTableBody');
    if (!tbody) return;
    const filtered = getFilteredSessions();

    if (!filtered.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-5 text-muted">No sessions match the current filters.</td></tr>';
    } else {
        const rows = filtered
            .map((session) => {
                const badgeClass = session.scheduleType === 'lab' ? 'badge-lab' : 'badge-theory';
                return `
                <tr>
                    <td>${session.dayLabel}</td>
                    <td>${session.timeLabel}</td>
                    <td>
                        <div class="fw-semibold">${session.courseCode} · ${session.courseName}</div>
                        <div class="text-muted small">${session.sessionType}${session.sessionNumber ? ` · #${session.sessionNumber}` : ''}</div>
                    </td>
                    <td>
                        <div>${session.department}</div>
                        <div class="text-muted small">${session.groupName || '—'}</div>
                    </td>
                    <td>
                        <div>${session.teacherName}</div>
                        <div class="text-muted small">${session.staffCode}</div>
                    </td>
                    <td>
                        <div>${session.roomNumber}</div>
                        <div class="text-muted small">${session.block}</div>
                    </td>
                    <td><span class="${badgeClass}">${session.scheduleType === 'lab' ? 'Lab' : 'Theory'}</span></td>
                </tr>`;
            })
            .join('');
        tbody.innerHTML = rows;
    }

    $('#resultCount').textContent = filtered.length;
}

function getFilteredSessions() {
    const department = $('#departmentFilter')?.value;
    const semester = $('#semesterFilter')?.value;
    const group = $('#groupFilter')?.value;
    const day = $('#dayFilter')?.value;
    const sessionType = $('#sessionTypeFilter')?.value;
    const search = $('#searchInput')?.value?.toLowerCase() || '';

    return state.sessions.filter((session) => {
        if (department && session.department !== department) return false;
        if (semester && `${session.semester}` !== semester) return false;
        if (group && session.groupName !== group) return false;
        if (day && session.day !== day) return false;
        if (sessionType && session.scheduleType !== sessionType) return false;
        if (search) {
            const haystack = [
                session.courseCode,
                session.courseName,
                session.teacherName,
                session.roomNumber,
                session.groupName,
            ]
                .join(' ')
                .toLowerCase();
            if (!haystack.includes(search)) return false;
        }
        return true;
    });
}

function renderRooms() {
    const grid = $('#roomGrid');
    if (!grid) return;
    const block = $('#blockFilter')?.value;
    const roomType = $('#roomTypeFilter')?.value;
    const search = $('#roomSearch')?.value?.toLowerCase() || '';

    let rooms = state.rooms;
    if (block) rooms = rooms.filter((room) => room.block === block);
    if (roomType) rooms = rooms.filter((room) => room.room_type === roomType);
    if (search) {
        rooms = rooms.filter((room) => `${room.room_number} ${room.block}`.toLowerCase().includes(search));
    }

    if (!rooms.length) {
        grid.innerHTML = '<div class="placeholder">No rooms match the selected filters.</div>';
        return;
    }

    const cards = rooms
        .map((room) => {
            const sessionHtml = room.sessions
                .map(
                    (session) => `
                    <div class="session-pill">
                        <strong>${DAY_LABELS[session.day] || 'Day TBD'}</strong>
                        <span class="text-muted">${session.time_label || ''}</span>
                        <div>${session.course_code || ''} · ${session.course_name || ''}</div>
                        <div class="text-muted small">${session.group_name || ''}</div>
                    </div>`
                )
                .join('');
            return `
                <div class="room-card">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <h6 class="mb-0">${room.room_number}</h6>
                        <span class="badge bg-light text-dark text-uppercase">${room.room_type || 'unknown'}</span>
                    </div>
                    <div class="room-meta mb-3">
                        ${room.block} · Utilization ${room.utilization}%
                    </div>
                    <div>${sessionHtml || '<div class="text-muted small">No sessions scheduled.</div>'}</div>
                </div>`;
        })
        .join('');

    grid.innerHTML = cards;
}

function renderUnassignedSessions() {
    const container = $('#unassignedSessions');
    if (!container) return;
    if (!state.unassigned.length) {
        container.textContent = 'All sessions have assigned rooms. ✅';
        return;
    }
    container.innerHTML = state.unassigned
        .map((session) => {
            const label = `${DAY_LABELS[session.day] || 'TBD'} · ${session.time_label || ''} · ${session.course_code || ''}`;
            return `<span class="unassigned-pill">${label}</span>`;
        })
        .join('');
}

function updateSnapshotBanner() {
    if (!state.snapshot) return;
    $('#snapshotLabel').textContent = state.snapshot.folder;
    const generatedAt = state.snapshot.generated_at ? new Date(state.snapshot.generated_at) : null;
    $('#lastUpdated').textContent = generatedAt ? generatedAt.toLocaleString() : 'Unknown';

    const solverEl = document.getElementById('solverStatus');
    if (solverEl) {
        const status = state.solverMetrics?.solver?.status;
        const wallTime = state.solverMetrics?.solver?.wall_time;
        const objective = state.solverMetrics?.solver?.objective_value;
        const bits = [];
        if (status) bits.push(`Solver: ${status}`);
        if (typeof objective === 'number') bits.push(`obj ${objective}`);
        if (typeof wallTime === 'number') bits.push(`${wallTime.toFixed(2)}s`);
        solverEl.textContent = bits.join(' · ');
    }

    const warmEl = document.getElementById('warmStartStatus');
    if (warmEl) {
        if (!state.warmStart?.available) {
            warmEl.textContent = '';
        } else {
            const lab = state.warmStart?.counts?.lab ?? 0;
            const theory = state.warmStart?.counts?.theory ?? 0;
            warmEl.textContent = `Warm-start: lab ${lab} · theory ${theory}`;
        }
    }
}

function updateHighlights() {
    if (!state.metrics) return;
    const day = state.metrics.highlights?.busiest_day;
    const slot = state.metrics.highlights?.peak_slot;
    $('#highlightDay').textContent = day?.label ? `${formatLabel(day.label)} (${day.value})` : '—';
    $('#highlightSlot').textContent = slot?.label ? `${slot.label} (${slot.value})` : '—';
}

function formatLabel(label) {
    if (!label) return '—';
    if (DAY_LABELS[label.toLowerCase()]) return DAY_LABELS[label.toLowerCase()];
    return label.toString();
}

function showError(message) {
    const alert = $('#alertBanner');
    if (!alert) return;
    alert.textContent = message;
    alert.classList.remove('d-none');
}

async function handleResponseError(response) {
    if (response.ok) return;
    const detail = await response.text();
    throw new Error(`Request failed (${response.status}): ${detail}`);
}

function debounce(fn, delay) {
    let timeout;
    return function debounced(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => fn.apply(this, args), delay);
    };
}
