// Room timetable viewer powered by FastAPI room aggregation API
const timeSlots = [
    "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
    "12:00 - 12:50", "1:20 - 2:10", "2:10 - 3:00", "3:00 - 3:50",
    "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
];

const labSlots = [
    "8:00 - 8:50", "8:50 - 9:40", "10:00 - 10:50", "10:50 - 11:40",
    "11:50 - 12:40", "12:40 - 1:20", "1:20 - 2:10", "2:10 - 3:00",
    "3:00 - 3:50", "3:50 - 4:40", "5:20 - 6:10", "5:10 - 7:00"
];

const labSessions = {
    L1: "8:00 - 9:40",
    L2: "10:00 - 11:40",
    L3: "11:50 - 1:20",
    L4: "1:20 - 3:00",
    L5: "3:00 - 4:40",
    L6: "5:10 - 7:00"
};

const allTimeSlots = Array.from(new Set([
    ...timeSlots,
    ...labSlots,
    ...Object.values(labSessions),
])).sort();

let roomRecords = [];
let unassignedSessions = [];
let dayOrder = ["monday", "tuesday", "wed", "thur", "fri", "saturday"];
let activeBlock = "";

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

function getGroupClass(groupName) {
    if (!groupName) return "";
    const match = groupName.match(/_G(\d+)$/);
    if (match) {
        const groupNum = parseInt(match[1], 10);
        return groupColors[groupNum] || "";
    }
    return "";
}

function getGroupNumber(groupName) {
    if (!groupName) return "";
    const match = groupName.match(/_G(\d+)$/);
    return match ? match[1] : "";
}

async function loadRoomData() {
    try {
        const response = await fetch("/api/rooms");
        if (!response.ok) {
            throw new Error(`Failed to load rooms: ${response.status} ${response.statusText}`);
        }
        const payload = await response.json();
        roomRecords = payload.rooms || [];
        unassignedSessions = payload.unassigned || [];
        dayOrder = payload.day_order || dayOrder;

        initializeFilters();
        updateStats();
        renderRooms();
    } catch (error) {
        console.error("Unable to load room data", error);
        document.getElementById("roomContainer").innerHTML = `
            <div class="alert alert-danger text-center">
                <i class="fas fa-exclamation-triangle me-2"></i>
                Error loading rooms. Please verify scheduler output.
                <br><small>${error.message}</small>
            </div>
        `;
    }
}

function initializeFilters() {
    const blockFilter = document.getElementById("blockFilter");
    blockFilter.innerHTML = "";

    const blocks = [...new Set(roomRecords.map((room) => room.block))]
        .filter(Boolean)
        .sort();

    const addButton = (label, blockValue) => {
        const btn = document.createElement("button");
        btn.className = `block-btn${blockValue === activeBlock ? " active" : ""}`;
        btn.textContent = label;
        btn.dataset.block = blockValue;
        btn.addEventListener("click", (event) => {
            document.querySelectorAll(".block-btn").forEach((button) => button.classList.remove("active"));
            event.currentTarget.classList.add("active");
            activeBlock = blockValue;
            renderRooms();
        });
        blockFilter.appendChild(btn);
    };

    addButton("All Blocks", "");
    blocks.forEach((block) => addButton(block, block));

    document.getElementById("roomTypeFilter").addEventListener("change", renderRooms);
    document.getElementById("roomSearch").addEventListener("input", debounce(renderRooms, 300));
}

function updateStats() {
    const totalRooms = roomRecords.length;
    const labRooms = roomRecords.filter((room) => room.room_type === "lab").length;
    const theoryRooms = roomRecords.filter((room) => room.room_type === "theory").length;
    const avgUtilization = totalRooms
        ? (roomRecords.reduce((sum, room) => sum + (room.utilization || 0), 0) / totalRooms).toFixed(1)
        : "0.0";

    document.getElementById("totalRooms").textContent = totalRooms;
    document.getElementById("labRooms").textContent = labRooms;
    document.getElementById("theoryRooms").textContent = theoryRooms;
    document.getElementById("avgUtilization").textContent = `${avgUtilization}%`;
}

function getFilteredRooms() {
    const roomType = document.getElementById("roomTypeFilter").value;
    const searchQuery = document.getElementById("roomSearch").value.toLowerCase();

    return roomRecords.filter((room) => {
        if (activeBlock && room.block !== activeBlock) {
            return false;
        }
        if (roomType && room.room_type !== roomType) {
            return false;
        }
        if (searchQuery) {
            const haystack = `${room.room_number || ""} ${room.room_id || ""} ${room.block || ""}`.toLowerCase();
            if (!haystack.includes(searchQuery)) {
                return false;
            }
        }
        return true;
    });
}

function renderRooms() {
    const container = document.getElementById("roomContainer");
    const rooms = getFilteredRooms();

    if (!rooms.length) {
        container.innerHTML = `
            <div class="alert alert-info text-center">
                <i class="fas fa-info-circle me-2"></i>
                No rooms match the selected filters.
            </div>
        `;
        return;
    }

    rooms.sort((a, b) => {
        if ((a.block || "").localeCompare(b.block || "") !== 0) {
            return (a.block || "").localeCompare(b.block || "");
        }
        return (a.room_number || "").localeCompare(b.room_number || "");
    });

    let html = '<div class="room-grid">';

    rooms.forEach((room) => {
        const roomClass = room.room_type === "lab" ? "lab-room" : room.room_type === "theory" ? "theory-room" : "mixed-room";
        const utilization = room.utilization || 0;
        const capacity = room.capacity || "N/A";

        html += `
            <div class="room-card ${roomClass}">
                <div class="room-header">
                    <div class="room-info">
                        <div>
                            <h5 class="mb-0">
                                <i class="fas ${room.room_type === 'lab' ? 'fa-flask' : room.room_type === 'theory' ? 'fa-chalkboard' : 'fa-layer-group'} me-2"></i>
                                ${room.room_number || 'TBD'}
                            </h5>
                            <div class="room-details">
                                <span class="room-badge">
                                    <i class="fas fa-hashtag me-1"></i>ID: ${room.room_id || '—'}
                                </span>
                                <span class="room-badge">
                                    <i class="fas fa-building me-1"></i>${room.block || 'Unknown Block'}
                                </span>
                                <span class="room-badge">
                                    <i class="fas fa-users me-1"></i>Capacity: ${capacity}
                                </span>
                                <span class="room-badge">
                                    <i class="fas fa-calendar me-1"></i>${room.session_count || 0} sessions
                                </span>
                            </div>
                        </div>
                        <div>
                            <div class="text-end">
                                <strong>${utilization.toFixed(1)}%</strong>
                                <div style="font-size: 0.8rem;">Utilization</div>
                            </div>
                            <div class="utilization-bar">
                                <div class="utilization-fill" style="width: ${Math.min(utilization, 100)}%"></div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="card-body p-2">
                    ${generateRoomScheduleTable(room)}
                </div>
            </div>
        `;
    });

    html += "</div>";

    if (unassignedSessions.length) {
        html += renderUnassignedSection();
    }

    container.innerHTML = html;
}

function generateRoomScheduleTable(room) {
    const scheduleGrid = {};
    const usedSlots = new Set();

    dayOrder.forEach((day) => {
        scheduleGrid[day] = {};
    });

    room.sessions.forEach((session) => {
        const day = session.day || "unscheduled";
        const timeSlot = session.time_label || session.time_range || session.session_name || "Unscheduled";
        usedSlots.add(timeSlot);
        if (!scheduleGrid[day]) {
            scheduleGrid[day] = {};
        }
        if (!scheduleGrid[day][timeSlot]) {
            scheduleGrid[day][timeSlot] = [];
        }
        scheduleGrid[day][timeSlot].push(session);
    });

    const sortedSlots = Array.from(new Set([...allTimeSlots, ...usedSlots])).filter((slot) => usedSlots.has(slot));
    sortedSlots.sort((a, b) => parseTimeSlot(a) - parseTimeSlot(b));

    if (!sortedSlots.length) {
        return `
            <div class="alert alert-light mb-0 text-center">
                <i class="fas fa-info-circle me-1"></i>
                No scheduled sessions for this room.
            </div>
        `;
    }

    let html = `
        <div class="table-responsive">
            <table class="table table-bordered schedule-table">
                <thead>
                    <tr>
                        <th class="time-slot">Time</th>
    `;

    dayOrder.forEach((day) => {
        html += `<th>${formatDay(day)}</th>`;
    });

    html += `
                    </tr>
                </thead>
                <tbody>
    `;

    sortedSlots.forEach((slot) => {
        html += `<tr><td class="time-slot">${slot}</td>`;
        dayOrder.forEach((day) => {
            const sessions = scheduleGrid[day]?.[slot] || [];
            html += "<td>";

            if (!sessions.length) {
                html += '<div class="empty-slot">Free</div>';
            } else {
                sessions.forEach((session) => {
                    const isLab = session.schedule_type === "lab";
                    const groupNumber = getGroupNumber(session.group_name);
                    const groupClass = getGroupClass(session.group_name);
                    const semester = session.semester || "";
                    const teacher = session.teacher_name || "Unknown";
                    html += `
                        <div class="session ${isLab ? '' : 'theory-session'}" title="
                            Course: ${session.course_name}
                            Teacher: ${teacher}
                            Department: ${session.department}
                            Group: ${session.group_name}
                        ">
                            <div class="session-header">
                                <div class="session-code">${session.course_code || session.course_name || 'Course'}</div>
                                ${groupNumber ? `<div class="group-number ${groupClass}">G${groupNumber}</div>` : ''}
                            </div>
                            <div class="session-details">${teacher}</div>
                            <div class="session-details">${session.group_name || session.department || ''}</div>
                            <div class="session-details">${semester ? `Sem ${semester}` : ''}</div>
                        </div>
                    `;
                });
            }

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

function renderUnassignedSection() {
    const grouped = unassignedSessions.reduce((acc, session) => {
        const key = session.day || "unscheduled";
        acc[key] = acc[key] || [];
        acc[key].push(session);
        return acc;
    }, {});

    let html = `
        <div class="card mt-4">
            <div class="card-header bg-warning text-dark">
                <i class="fas fa-exclamation-triangle me-2"></i>
                Sessions without assigned rooms (${unassignedSessions.length})
            </div>
            <div class="card-body">
    `;

    Object.entries(grouped).forEach(([day, sessions]) => {
        html += `
            <h6 class="fw-bold">${formatDay(day)}</h6>
            <div class="table-responsive mb-3">
                <table class="table table-sm">
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Course</th>
                            <th>Group</th>
                            <th>Teacher</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        sessions.forEach((session) => {
            html += `
                <tr>
                    <td>${session.time_label || session.session_name || '—'}</td>
                    <td>${session.course_code || ''}</td>
                    <td>${session.group_name || ''}</td>
                    <td>${session.teacher_name || ''}</td>
                </tr>
            `;
        });

        html += `
                    </tbody>
                </table>
            </div>
        `;
    });

    html += "</div></div>";
    return html;
}

function parseTimeSlot(slot) {
    if (!slot) return 0;
    const start = slot.split("-", 1)[0].trim();
    const [hourStr, minuteStr] = start.split(":");
    let hour = parseInt(hourStr, 10);
    const minute = parseInt(minuteStr || "0", 10);
    if (hour >= 1 && hour <= 7) {
        hour += 12;
    }
    return hour * 60 + minute;
}

function formatDay(day) {
    if (!day) return "Unscheduled";
    const normalized = day === "wed" ? "wednesday" : day === "thur" ? "thursday" : day;
    return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function debounce(func, wait) {
    let timeout;
    return function debounced(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

document.addEventListener("DOMContentLoaded", () => {
    loadRoomData();
});
