// Combined Schedule Viewer powered by FastAPI schedule API
import {
    bundleIdentity,
    buildSessionHoverDetails,
    buildTeacherSchedule,
    countPhysicalSessions,
    escapeHtml,
    expandKuttyOccurrenceMatches,
    groupCellSessions,
    isKuttyShared,
    renderKuttySessionCard,
    sessionGroupNumber,
    sessionSectionIndex,
    sessionSectionLabel,
    teacherKey,
    updateBundlePanel,
} from "./kutty_schedule.mjs?v=20260714b";

let labData = [];
let theoryData = [];
let allData = [];

const timeSlots = [
    "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
    "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:10 - 4:00",
    "4:10 - 5:00"
];

const labSlots = [
    "8:00 - 8:50", "8:50 - 9:40", "10:00 - 10:50", "10:50 - 11:40",
    "11:40 - 12:30", "12:30 - 1:20", "1:20 - 2:10", "2:10 - 3:00",
    "3:10 - 4:00", "4:00 - 4:50"
];

const labSessions = {
    L1: "8:00 - 9:40",
    L2: "10:00 - 11:40",
    L3: "11:40 - 1:20",
    L4: "1:20 - 3:00",
    L5: "3:10 - 4:50"
};

const allTimeSlots = Array.from(new Set([
    ...timeSlots,
    ...labSlots,
    ...Object.values(labSessions),
])).sort();

let days = ["tuesday", "wed", "thur", "fri", "saturday"];

const dayPatternMappings = {
    "Monday-Friday": ["monday", "tuesday", "wed", "thur", "fri"],
    "Tuesday-Saturday": ["tuesday", "wed", "thur", "fri", "saturday"]
};

const groupColors = {
    1: "group-g1",
    2: "group-g2",
    3: "group-g3",
    4: "group-g4",
    5: "group-g5",
    6: "group-g6",
    7: "group-g7",
    8: "group-g8",
    9: "group-g9",
    10: "group-g10"
};

const deptColors = {
    "Computer Science & Engineering": "dept-cs",
    "Computer Science & Engineering (Cyber Security)": "dept-cy",
    "Information Technology": "dept-it",
    "Artificial Intelligence & Data Science": "dept-ai",
    "Artificial Intelligence & Machine Learning": "dept-ai",
    "Computer Science & Business Systems": "dept-cb",
    "Computer Science & Design": "dept-cd"
};

function getDeptClass(department) {
    return deptColors[department] || "";
}

function getSemesterFromGroupName(groupName) {
    if (!groupName) return "";
    const match = groupName.match(/_S(\d+)_/);
    if (match) {
        return `S${match[1]}`;
    }
    return "";
}

async function loadData() {
    try {
        const response = await fetch("/api/schedule");
        if (!response.ok) {
            throw new Error(`Failed to load schedule: ${response.status} ${response.statusText}`);
        }
        const payload = await response.json();
        const schedule = payload.data || {};
        labData = schedule.lab_entries || [];
        theoryData = schedule.theory_entries || [];
        allData = [...labData, ...theoryData];

        initializeFilters();
        updateSummaryStats();
        renderContent();
    } catch (error) {
        console.error("Error loading schedule data", error);
        document.getElementById("mainContent").innerHTML = `
            <div class="alert alert-danger text-center">
                <i class="fas fa-exclamation-triangle me-2"></i>
                Error loading schedule data. Please verify the scheduler output.
                <br><small>Error: ${error.message}</small>
            </div>
        `;
    }
}

function initializeFilters() {
    const departments = [...new Set(allData.map((item) => item.department))]
        .filter(Boolean)
        .sort();
    const departmentSelect = document.getElementById("departmentFilter");
    departments.forEach((dept) => {
        const option = document.createElement("option");
        option.value = dept;
        option.textContent = dept;
        departmentSelect.appendChild(option);
    });

    const semesters = [...new Set(allData.map((item) => item.semester))]
        .filter((value) => value !== undefined && value !== null)
        .sort((a, b) => a - b);
    const semesterSelect = document.getElementById("semesterFilter");
    semesters.forEach((sem) => {
        const option = document.createElement("option");
        option.value = sem;
        option.textContent = `Semester ${sem}`;
        semesterSelect.appendChild(option);
    });

    const groups = [...new Set(allData.map((item) => item.group_name).filter(Boolean))].sort();
    const groupSelect = document.getElementById("groupFilter");
    groups.forEach((group) => {
        const option = document.createElement("option");
        option.value = group;
        option.textContent = group.replace(/_/g, " ");
        groupSelect.appendChild(option);
    });

    updateDaysFromData();
    updateCohortFilterMode();

    document.getElementById("viewType").addEventListener("change", renderContent);
    document.getElementById("departmentFilter").addEventListener("change", () => {
        updateSectionOptions();
        renderContent();
    });
    document.getElementById("semesterFilter").addEventListener("change", () => {
        updateCohortFilterMode();
        renderContent();
    });
    document.getElementById("dayFilter").addEventListener("change", renderContent);
    document.getElementById("sessionTypeFilter").addEventListener("change", renderContent);
    document.getElementById("groupFilter").addEventListener("change", renderContent);
    document.getElementById("sectionFilter").addEventListener("change", renderContent);
    document.getElementById("dayPatternFilter").addEventListener("change", renderContent);

    document.getElementById("courseSearch").addEventListener("input", debounce(renderContent, 300));
    document.getElementById("teacherSearch").addEventListener("input", debounce(renderContent, 300));
    document.getElementById("roomSearch").addEventListener("input", debounce(renderContent, 300));
}

function isSectionMode() {
    return document.getElementById("semesterFilter").value === "3";
}

function updateCohortFilterMode() {
    const sectionMode = isSectionMode();
    document.getElementById("groupFilterField").classList.toggle("d-none", sectionMode);
    document.getElementById("sectionFilterField").classList.toggle("d-none", !sectionMode);
    document.getElementById("groupLegendCard").classList.toggle("d-none", sectionMode);
    if (sectionMode) {
        document.getElementById("groupFilter").value = "";
        updateSectionOptions();
    } else {
        document.getElementById("sectionFilter").value = "";
    }
}

function updateSectionOptions() {
    const department = document.getElementById("departmentFilter").value;
    const select = document.getElementById("sectionFilter");
    const previous = select.value;
    select.innerHTML = "";
    if (!department) {
        select.add(new Option("Select department first", ""));
        select.disabled = true;
        return;
    }
    select.disabled = false;
    select.add(new Option("All Sections", ""));
    const indices = [...new Set(
        allData
            .filter((item) => item.department === department && Number(item.semester) === 3)
            .map(sessionSectionIndex)
            .filter((value) => value !== null),
    )].sort((left, right) => left - right);
    indices.forEach((index) => {
        const label = sessionSectionLabel({ section_id: index });
        select.add(new Option(`Section ${label}`, String(index)));
    });
    select.value = indices.includes(Number(previous)) ? previous : "";
}

function updateDaysFromData() {
    const allDaysInData = [...new Set(allData.map((item) => item.day))];
    const dayOrder = ["monday", "tuesday", "wed", "thur", "fri", "saturday"];
    days = dayOrder.filter((day) => allDaysInData.includes(day));
}

function updateSummaryStats() {
    const totalSessions = countPhysicalSessions(allData);
    const labSessionsCount = labData.length;
    const theorySessionsCount = countPhysicalSessions(theoryData);
    const teacherIds = allData.map((item) => item.teacher_id || item.teacher_name).filter(Boolean);
    const teachers = new Set(teacherIds).size;
    const rooms = new Set(allData.map((item) => item.room_id || item.room_number).filter(Boolean)).size;

    document.getElementById("totalSessions").textContent = totalSessions;
    document.getElementById("labSessions").textContent = labSessionsCount;
    document.getElementById("theorySessions").textContent = theorySessionsCount;
    document.getElementById("totalTeachers").textContent = teachers;
    document.getElementById("totalRooms").textContent = rooms;
}

function getFilteredData() {
    let filtered = [...allData];

    const department = document.getElementById("departmentFilter").value;
    const semester = document.getElementById("semesterFilter").value;
    const day = document.getElementById("dayFilter").value;
    const sessionType = document.getElementById("sessionTypeFilter").value;
    const group = document.getElementById("groupFilter").value;
    const section = document.getElementById("sectionFilter").value;
    const dayPattern = document.getElementById("dayPatternFilter").value;
    const courseSearch = document.getElementById("courseSearch").value.toLowerCase();
    const teacherSearch = document.getElementById("teacherSearch").value.toLowerCase();
    const roomSearch = document.getElementById("roomSearch").value.toLowerCase();

    if (department) {
        filtered = filtered.filter((item) => item.department === department);
    }
    if (semester) {
        filtered = filtered.filter((item) => String(item.semester) === semester);
    }
    if (day) {
        filtered = filtered.filter((item) => item.day === day);
    }
    if (sessionType) {
        filtered = filtered.filter((item) => item.schedule_type === sessionType);
    }
    if (isSectionMode() && section) {
        filtered = filtered.filter((item) => String(sessionSectionIndex(item)) === section);
    } else if (!isSectionMode() && group) {
        filtered = filtered.filter((item) => item.group_name === group);
    }
    if (dayPattern) {
        filtered = filtered.filter((item) => item.day_pattern === dayPattern);
    }
    const structuralScope = filtered;
    if (courseSearch || teacherSearch || roomSearch) {
        const directMatches = structuralScope.filter((item) => {
            const matchesCourse = !courseSearch ||
                (item.course_code || "").toLowerCase().includes(courseSearch) ||
                (item.course_name || "").toLowerCase().includes(courseSearch);
            const matchesTeacher = !teacherSearch ||
                (item.teacher_name || "").toLowerCase().includes(teacherSearch) ||
                String(item.staff_code || item.teacher_id || "").toLowerCase().includes(teacherSearch);
            const matchesRoom = !roomSearch ||
                (item.room_number || "").toLowerCase().includes(roomSearch);
            return matchesCourse && matchesTeacher && matchesRoom;
        });
        filtered = expandKuttyOccurrenceMatches(structuralScope, directMatches);
    }

    return filtered;
}

function renderContent() {
    const viewType = document.getElementById("viewType").value;
    const filteredData = getFilteredData();
    updateBundlePanel(filteredData);

    if (isSectionMode() && document.getElementById("departmentFilter").value) {
        renderSectionView(filteredData);
        return;
    }

    switch (viewType) {
        case "department":
            renderDepartmentView(filteredData);
            break;
        case "semester":
            renderSemesterView(filteredData);
            break;
        case "room":
            renderRoomView(filteredData);
            break;
        case "teacher":
            renderTeacherView(filteredData);
            break;
        case "day":
            renderDayView(filteredData);
            break;
    }
}

function renderSectionView(data) {
    const sections = new Map();
    data.forEach((session) => {
        const index = sessionSectionIndex(session);
        if (index === null) return;
        if (!sections.has(index)) sections.set(index, []);
        sections.get(index).push(session);
    });
    let html = "";
    [...sections.entries()]
        .sort(([left], [right]) => left - right)
        .forEach(([index, rows]) => {
            const label = sessionSectionLabel({ section_id: index });
            html += `
                <article class="card schedule-card mb-4">
                    <header class="card-header changer-section-header">
                        <h5 class="mb-0">Section ${escapeHtml(label)}</h5>
                        <span>${countPhysicalSessions(rows)} sessions</span>
                    </header>
                    <div class="card-body">
                        ${generateScheduleTable(rows)}
                    </div>
                </article>
            `;
        });
    document.getElementById("mainContent").innerHTML = html || emptyState();
}

function renderDepartmentView(data) {
    const departments = [...new Set(data.map((item) => item.department))]
        .filter(Boolean)
        .sort();
    let html = "";

    departments.forEach((dept) => {
        const deptData = data.filter((item) => item.department === dept);
        const semesters = [...new Set(deptData.map((item) => item.semester))]
            .filter((value) => value !== undefined && value !== null)
            .sort((a, b) => a - b);
        const deptDayPattern = deptData.length > 0 ? deptData[0].day_pattern : "";

        html += `
            <div class="card mb-4">
                <div class="card-header" style="background: var(--header-bg); color: white;">
                    <h5 class="mb-0">
                        <i class="fas fa-building me-2"></i>
                        ${dept}
                        <span class="badge bg-light text-dark ms-2">${countPhysicalSessions(deptData)} sessions</span>
                        ${deptDayPattern ? `<span class="badge bg-info ms-2">${deptDayPattern}</span>` : ""}
                    </h5>
                </div>
                <div class="card-body">
        `;

        semesters.forEach((semester) => {
            const semesterData = deptData.filter((item) => item.semester === semester);
            html += `
                <h6 class="text-primary mb-3">
                    <i class="fas fa-graduation-cap me-1"></i>
                    Semester ${semester} (${countPhysicalSessions(semesterData)} sessions)
                </h6>
                ${generateScheduleTable(semesterData)}
                <hr>
            `;
        });

        html += `
                </div>
            </div>
        `;
    });

    document.getElementById("mainContent").innerHTML = html || emptyState();
}

function renderSemesterView(data) {
    const semesters = [...new Set(data.map((item) => item.semester))]
        .filter((value) => value !== undefined && value !== null)
        .sort((a, b) => a - b);
    let html = "";

    semesters.forEach((semester) => {
        const semesterData = data.filter((item) => item.semester === semester);
        const departments = [...new Set(semesterData.map((item) => item.department))]
            .filter(Boolean)
            .sort();

        html += `
            <div class="card mb-4">
                <div class="card-header" style="background: var(--header-bg); color: white;">
                    <h5 class="mb-0">
                        <i class="fas fa-graduation-cap me-2"></i>
                        Semester ${semester}
                        <span class="badge bg-light text-dark ms-2">${countPhysicalSessions(semesterData)} sessions</span>
                    </h5>
                </div>
                <div class="card-body">
        `;

        departments.forEach((dept) => {
            const deptData = semesterData.filter((item) => item.department === dept);
            html += `
                <h6 class="text-success mb-3">
                    <i class="fas fa-building me-1"></i>
                    ${dept} (${countPhysicalSessions(deptData)} sessions)
                </h6>
                ${generateScheduleTable(deptData)}
                <hr>
            `;
        });

        html += `
                </div>
            </div>
        `;
    });

    document.getElementById("mainContent").innerHTML = html || emptyState();
}

function renderRoomView(data) {
    const rooms = [...new Set(data.map((item) => `${item.room_number || "TBD"} (${item.block || "Unknown"})`))].sort();
    let html = "";

    rooms.forEach((roomInfo) => {
        const [roomNumber, block] = roomInfo.split(" (");
        const blockName = block ? block.replace(")", "") : "";
        const roomData = data.filter((item) => item.room_number === roomNumber && item.block === blockName);

        if (roomData.length === 0) return;

        const isLab = roomData[0].schedule_type === "lab";
        const capacity = roomData[0].capacity || "N/A";

        html += `
            <div class="card mb-4">
                <div class="card-header" style="background: ${isLab ? 'var(--secondary-color)' : 'var(--success-color)'}; color: white;">
                    <h5 class="mb-0">
                        <i class="fas ${isLab ? 'fa-flask' : 'fa-chalkboard'} me-2"></i>
                        ${roomNumber} - ${blockName}
                        <span class="badge bg-light text-dark ms-2">Capacity: ${capacity}</span>
                        <span class="badge bg-light text-dark ms-2">${countPhysicalSessions(roomData)} sessions</span>
                    </h5>
                </div>
                <div class="card-body">
                    ${generateScheduleTable(roomData)}
                </div>
            </div>
        `;
    });

    document.getElementById("mainContent").innerHTML = html || emptyState();
}

function renderTeacherView(data) {
    const teacherSearch = document.getElementById("teacherSearch").value.toLowerCase();
    const teacherMap = new Map();
    data.forEach((item) => {
        const key = teacherKey(item);
        if (!key || teacherMap.has(key)) return;
        const name = item.teacher_name || "Unknown";
        const staffCode = item.staff_code || item.teacher_id || "";
        const haystack = `${name} ${staffCode}`.toLowerCase();
        if (teacherSearch && !haystack.includes(teacherSearch)) return;
        teacherMap.set(key, { key, name, staffCode });
    });
    const teachers = [...teacherMap.values()].sort((left, right) => left.name.localeCompare(right.name));
    let html = "";

    teachers.forEach(({ key, name: teacherName, staffCode }) => {
        const ownedData = data.filter((item) => teacherKey(item) === key);
        const teacherData = buildTeacherSchedule(data, key);

        const labSessions = ownedData.filter((item) => item.schedule_type === "lab").length;
        const theorySessions = countPhysicalSessions(
            ownedData.filter((item) => item.schedule_type === "theory")
        );

        html += `
            <div class="card mb-4">
                <div class="card-header" style="background: var(--header-bg); color: white;">
                    <h5 class="mb-0">
                        <i class="fas fa-user me-2"></i>
                        ${teacherName} ${staffCode ? `(${staffCode})` : ""}
                        <span class="badge bg-info ms-2">${labSessions} Labs</span>
                        <span class="badge bg-success ms-2">${theorySessions} Theory</span>
                    </h5>
                </div>
                <div class="card-body">
                    ${generateScheduleTable(teacherData, { focusTeacherKey: key })}
                </div>
            </div>
        `;
    });

    document.getElementById("mainContent").innerHTML = html || emptyState();
}

function renderDayView(data) {
    let html = "";

    days.forEach((day) => {
        const dayData = data.filter((item) => item.day === day);
        if (dayData.length === 0) return;

        const labCount = dayData.filter((item) => item.schedule_type === "lab").length;
        const theoryCount = countPhysicalSessions(
            dayData.filter((item) => item.schedule_type === "theory"),
        );

        html += `
            <div class="card mb-4">
                <div class="day-header">
                    <i class="fas fa-calendar-day me-2"></i>
                    ${day.charAt(0).toUpperCase() + day.slice(1)}
                    <div class="mt-2">
                        <span class="badge bg-info me-2">${labCount} Labs</span>
                        <span class="badge bg-success">${theoryCount} Theory</span>
                    </div>
                </div>
                <div class="card-body">
                    ${generateScheduleTable(dayData)}
                </div>
            </div>
        `;
    });

    document.getElementById("mainContent").innerHTML = html || emptyState();
}

function generateScheduleTable(data, options = {}) {
    if (data.length === 0) {
        return '<div class="alert alert-info">No sessions found for the selected filters.</div>';
    }

    const daysInData = [...new Set(data.map((item) => item.day))];
    const dayOrder = ["monday", "tuesday", "wed", "thur", "fri", "saturday"];
    const currentDays = dayOrder.filter((day) => daysInData.includes(day));

    const dayPatterns = [...new Set(data.map((item) => item.day_pattern).filter(Boolean))];
    const scheduleGrid = {};

    currentDays.forEach((day) => {
        scheduleGrid[day] = {};
        allTimeSlots.forEach((slot) => {
            scheduleGrid[day][slot] = [];
        });
        timeSlots.forEach((slot) => {
            if (!scheduleGrid[day][slot]) {
                scheduleGrid[day][slot] = [];
            }
        });
    });

    data.forEach((item) => {
        const day = item.day;
        let timeKey;

        if (item.schedule_type === "lab") {
            timeKey = labSessions[item.session_name] || item.time_range || item.time_slot;
        } else {
            timeKey = item.time_slot || item.time_range;
        }

        if (!timeKey) {
            timeKey = item.session_name || "Unscheduled";
        }

        if (scheduleGrid[day]) {
            if (!scheduleGrid[day][timeKey]) {
                scheduleGrid[day][timeKey] = [];
            }
            scheduleGrid[day][timeKey].push(item);
        }
    });

    let html = "";

    if (dayPatterns.length > 0) {
        html += `
            <div class="alert alert-info mb-3">
                <i class="fas fa-calendar-week me-2"></i>
                <strong>Day Pattern${dayPatterns.length > 1 ? 's' : ''}:</strong>
                ${dayPatterns.join(', ')}
                <span class="ms-3">
                    <i class="fas fa-calendar-day me-1"></i>
                    <strong>Days:</strong> ${currentDays.map((d) => d.charAt(0).toUpperCase() + d.slice(1)).join(', ')}
                </span>
            </div>
        `;
    }

    html += `
        <div class="table-responsive">
            <table class="table table-bordered schedule-table">
                <thead>
                    <tr>
                        <th>Time</th>
    `;

    currentDays.forEach((day) => {
        html += `<th>${day.charAt(0).toUpperCase() + day.slice(1)}</th>`;
    });

    html += `
                    </tr>
                </thead>
                <tbody>
    `;

    const usedTheorySlots = new Set();
    const usedLabSlots = new Set();

    Object.values(scheduleGrid).forEach((daySchedule) => {
        Object.keys(daySchedule).forEach((timeSlot) => {
            if (daySchedule[timeSlot].length > 0) {
                const hasTheorySession = daySchedule[timeSlot].some((session) => session.schedule_type === "theory");
                const hasLabSession = daySchedule[timeSlot].some((session) => session.schedule_type === "lab");

                if (hasTheorySession) {
                    usedTheorySlots.add(timeSlot);
                }
                if (hasLabSession) {
                    usedLabSlots.add(timeSlot);
                }
            }
        });
    });

    const sortedTheorySlots = Array.from(usedTheorySlots).sort((a, b) => parseTimeSlot(a) - parseTimeSlot(b));
    const sortedLabSlots = Array.from(usedLabSlots).sort((a, b) => parseTimeSlot(a) - parseTimeSlot(b));
    const sortedTimeSlots = [...sortedTheorySlots, ...sortedLabSlots];

    sortedTimeSlots.forEach((timeSlot, index) => {
        if (index === sortedTheorySlots.length && sortedLabSlots.length > 0) {
            html += `
                <tr class="table-section-divider">
                    <td colspan="${currentDays.length + 1}" class="text-center" style="background-color: #f8f9fa; font-weight: bold; padding: 10px;">
                        <i class="fas fa-flask me-2"></i>LAB SESSIONS
                    </td>
                </tr>
            `;
        }

        if (index === 0 && sortedTheorySlots.length > 0) {
            html += `
                <tr class="table-section-header">
                    <td colspan="${currentDays.length + 1}" class="text-center" style="background-color: #e8f4fd; font-weight: bold; padding: 10px;">
                        <i class="fas fa-chalkboard me-2"></i>THEORY SESSIONS
                    </td>
                </tr>
            `;
        }

        const rowSessions = currentDays.flatMap((day) => scheduleGrid[day][timeSlot] || []);
        html += `<tr><td class="time-cell"><strong>${formatTimeHeader(timeSlot, rowSessions)}</strong></td>`;

        currentDays.forEach((day) => {
            const sessions = scheduleGrid[day][timeSlot] || [];
            html += "<td>";

            groupCellSessions(sessions).forEach((block) => {
                html += block.kind === "kutty"
                    ? renderKuttySessionCard(block.sessions, options)
                    : renderStandardSession(block.sessions[0]);
            });

            html += "</td>";
        });

        html += "</tr>";
    });

    html += `
                </tbody>
            </table>
        </div>
    `;

    return html;
}

function renderStandardSession(session) {
    const isLab = session.schedule_type === "lab";
    const isBatched = session.is_batched;
    const batchLabel = session.batch_label || session.batch_info;
    const batchNumber = session.batch_number;
    const sessionClass = isLab ? "lab-session" : "theory-session";
    const batchClass = isBatched ? "batched-session" : "";
    const groupNumber = sessionGroupNumber(session);
    const sectionLabel = Number(session.semester) === 3 ? sessionSectionLabel(session) : "";
    const deptClass = getDeptClass(session.department);
    const bundleId = bundleIdentity(session);
    const bundleClass = bundleId ? "bundle-session" : "";
    const block = session.block ? ` · ${session.block}` : "";
    const groupDetails = buildSessionHoverDetails(session, session.room_number || "TBD", block);

    return `
        <div class="session-block ${sessionClass} ${batchClass} ${deptClass} ${bundleClass} schedule-session-card"
             data-bundle-id="${escapeHtml(bundleId)}" title="${escapeHtml(groupDetails)}">
            ${sectionLabel
                ? `<span class="section-number" tabindex="0" aria-label="Section ${escapeHtml(sectionLabel)}">${escapeHtml(sectionLabel)}</span>`
                : groupNumber ? `<span class="group-number group-g${escapeHtml(groupNumber)}-badge" tabindex="0"
                aria-label="${escapeHtml(groupDetails)}">G${escapeHtml(groupNumber)}</span>` : ""}
            <span class="session-teacher">${escapeHtml(session.teacher_name || "Staff TBA")}</span>
            <strong class="session-code">${escapeHtml(session.course_code_display || session.course_code || "Course")}</strong>
            <span class="session-course">${escapeHtml(session.course_name || "-")}</span>
            <span class="session-room">${escapeHtml((session.room_number || "TBD") + block)}</span>
            ${isLab && (batchLabel || batchNumber) ? `<span class="session-batch">${escapeHtml(batchLabel || `Batch ${batchNumber}`)}</span>` : ""}
            <small class="session-instance">${escapeHtml(session.course_instance_id || "")}</small>
        </div>
    `;
}

function parseTimeSlot(timeSlot) {
    if (!timeSlot) return 0;
    const startTime = timeSlot.split(" - ")[0].trim();
    const [hoursStr, minutesStr] = startTime.split(":");
    let hours = parseInt(hoursStr, 10);
    const minutes = parseInt(minutesStr || "0", 10);

    if (hours >= 1 && hours <= 7) {
        hours += 12;
    }
    return hours * 60 + minutes;
}

function formatTimeHeader(timeSlot, sessions) {
    if (!(sessions || []).some(isKuttyShared)) return escapeHtml(timeSlot);
    const parts = String(timeSlot || "").split(" - ").map((part) => part.trim());
    if (parts.length !== 2) return escapeHtml(timeSlot);
    const match = parts[0].match(/^(\d{1,2}):(\d{2})$/);
    if (!match) return escapeHtml(timeSlot);
    let hour = Number(match[1]);
    let minute = Number(match[2]) + 25;
    if (minute >= 60) {
        hour = hour % 12 + 1;
        minute -= 60;
    }
    const midpoint = `${hour}:${String(minute).padStart(2, "0")}`;
    return `<span class="kutty-time-half">${escapeHtml(parts[0])} - ${escapeHtml(midpoint)}</span>` +
        '<span class="kutty-time-divider"></span>' +
        `<span class="kutty-time-half">${escapeHtml(midpoint)} - ${escapeHtml(parts[1])}</span>`;
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function emptyState() {
    return `
        <div class="alert alert-warning">
            <i class="fas fa-info-circle me-2"></i>
            No sessions match the selected filters.
        </div>
    `;
}

document.addEventListener("DOMContentLoaded", () => {
    loadData();
});
