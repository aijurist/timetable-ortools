// Combined Schedule Viewer powered by FastAPI schedule API
let labData = [];
let theoryData = [];
let allData = [];

const timeSlots = [
    "8:00 - 8:50", "8:55 - 9:45", "9:50 - 10:40", "10:45 - 11:35",
    "11:40 - 12:30", "12:35 - 1:20", "1:50 - 2:40", "3:20 - 4:10",
    "4:15 - 5:05", "5:10 - 6:00", "6:10 - 7:00"
];

const labSessions = {
    L1: "8:00 - 9:40",
    L2: "9:50 - 11:30",
    L3: "11:40 - 1:20",
    L4: "1:50 - 3:20",
    L5: "3:30 - 5:10",
    L6: "5:20 - 7:00"
};

const allTimeSlots = [
    "8:00 - 8:50", "8:55 - 9:45", "8:00 - 9:40",
    "8:50 - 9:40", "9:50 - 10:40", "9:50 - 11:30",
    "10:45 - 11:35", "10:40 - 11:30", "11:40 - 12:30",
    "11:40 - 1:20", "12:35 - 1:20", "12:30 - 1:20",
    "1:50 - 2:40", "1:50 - 3:20", "2:40 - 3:20",
    "3:20 - 4:10", "3:30 - 5:10", "4:15 - 5:05",
    "4:20 - 5:10", "5:10 - 6:00", "5:20 - 7:00",
    "6:10 - 7:00", "5:10 - 7:00"
];

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

function getGroupClass(groupName) {
    if (!groupName) return "";
    const match = groupName.match(/_G(\d+)$/);
    if (match) {
        const groupNum = parseInt(match[1], 10);
        return groupColors[groupNum] || "";
    }
    return "";
}

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

    document.getElementById("viewType").addEventListener("change", renderContent);
    document.getElementById("departmentFilter").addEventListener("change", renderContent);
    document.getElementById("semesterFilter").addEventListener("change", renderContent);
    document.getElementById("dayFilter").addEventListener("change", renderContent);
    document.getElementById("sessionTypeFilter").addEventListener("change", renderContent);
    document.getElementById("groupFilter").addEventListener("change", renderContent);
    document.getElementById("dayPatternFilter").addEventListener("change", renderContent);

    document.getElementById("courseSearch").addEventListener("input", debounce(renderContent, 300));
    document.getElementById("teacherSearch").addEventListener("input", debounce(renderContent, 300));
    document.getElementById("roomSearch").addEventListener("input", debounce(renderContent, 300));
}

function updateDaysFromData() {
    const allDaysInData = [...new Set(allData.map((item) => item.day))];
    const dayOrder = ["monday", "tuesday", "wed", "thur", "fri", "saturday"];
    days = dayOrder.filter((day) => allDaysInData.includes(day));
}

function updateSummaryStats() {
    const totalSessions = allData.length;
    const labSessionsCount = labData.length;
    const theorySessionsCount = theoryData.length;
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
    if (group) {
        filtered = filtered.filter((item) => item.group_name === group);
    }
    if (dayPattern) {
        filtered = filtered.filter((item) => item.day_pattern === dayPattern);
    }
    if (courseSearch) {
        filtered = filtered.filter(
            (item) =>
                (item.course_code || "").toLowerCase().includes(courseSearch) ||
                (item.course_name || "").toLowerCase().includes(courseSearch)
        );
    }
    if (teacherSearch) {
        filtered = filtered.filter((item) => (item.teacher_name || "").toLowerCase().includes(teacherSearch));
    }
    if (roomSearch) {
        filtered = filtered.filter((item) => (item.room_number || "").toLowerCase().includes(roomSearch));
    }

    return filtered;
}

function renderContent() {
    const viewType = document.getElementById("viewType").value;
    const filteredData = getFilteredData();

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
                        <span class="badge bg-light text-dark ms-2">${deptData.length} sessions</span>
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
                    Semester ${semester} (${semesterData.length} sessions)
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
                        <span class="badge bg-light text-dark ms-2">${semesterData.length} sessions</span>
                    </h5>
                </div>
                <div class="card-body">
        `;

        departments.forEach((dept) => {
            const deptData = semesterData.filter((item) => item.department === dept);
            html += `
                <h6 class="text-success mb-3">
                    <i class="fas fa-building me-1"></i>
                    ${dept} (${deptData.length} sessions)
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
                        <span class="badge bg-light text-dark ms-2">${roomData.length} sessions</span>
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
    const teachers = [...new Set(data.map((item) => `${item.teacher_name || "Unknown"}|${item.staff_code || item.teacher_id || ""}`))].sort();
    let html = "";

    teachers.forEach((teacherInfo) => {
        const [teacherName, staffCode] = teacherInfo.split("|");
        const teacherData = data.filter((item) => item.teacher_name === teacherName);

        const labSessions = teacherData.filter((item) => item.schedule_type === "lab").length;
        const theorySessions = teacherData.filter((item) => item.schedule_type === "theory").length;

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
                    ${generateScheduleTable(teacherData)}
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
        const theoryCount = dayData.filter((item) => item.schedule_type === "theory").length;

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

function generateScheduleTable(data) {
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
                        <th style="width: 120px;">Time</th>
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

        html += `<tr><td class="time-header"><strong>${timeSlot}</strong></td>`;

        currentDays.forEach((day) => {
            const sessions = scheduleGrid[day][timeSlot] || [];
            html += "<td>";

            sessions.forEach((session) => {
                const isLab = session.schedule_type === "lab";
                const isBatched = session.is_batched;
                const batchLabel = session.batch_label || session.batch_info;
                const batchNumber = session.batch_number;
                const sessionClass = isLab ? "lab-session" : "theory-session";
                const batchClass = isBatched ? "batched-session" : "";

                const groupClass = getGroupClass(session.group_name);
                const deptClass = getDeptClass(session.department);
                const semester = getSemesterFromGroupName(session.group_name) || `S${session.semester}`;
                const groupNumber = session.group_name ? session.group_name.match(/_G(\d+)$/)?.[1] || "" : "";

                html += `
                    <div class="${sessionClass} ${batchClass} ${deptClass}" title="
                        Course: ${session.course_name}
                        Teacher: ${session.teacher_name}
                        Room: ${session.room_number} (${session.block})
                        Department: ${session.department}
                        Group: ${session.group_name}
                        Semester: ${semester}
                        ${isLab ? 'Capacity: ' + (session.capacity || 'NA') : ''}
                        ${isLab && (batchLabel || batchNumber) ? 'Batch: ' + (batchLabel || `Batch ${batchNumber}`) : ''}
                    ">
                        <div class="session-header">
                            <div class="session-code">${session.course_code_display || session.course_code}</div>
                            ${groupNumber ? `<div class="group-number ${groupClass}">G${groupNumber}</div>` : ""}
                        </div>
                        <div class="session-teacher">${session.teacher_name}</div>
                        <div class="session-room">${session.room_number || 'TBD'}</div>
                        ${isLab && (batchLabel || batchNumber) ? `<div class="batch-label">${batchLabel || `Batch ${batchNumber}`}</div>` : ""}
                        <div class="semester-indicator">${semester}</div>
                    </div>
                `;
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
