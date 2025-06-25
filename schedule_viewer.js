// Global variables
let labData = [];
let theoryData = [];
let allData = [];

// Time slots for display
const timeSlots = [
    "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
    "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50",
    "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
];

const labSessions = {
    'L1': '8:00 - 9:40',
    'L2': '10:00 - 11:40', 
    'L3': '11:50 - 1:20',
    'L4': '1:20 - 3:00',
    'L5': '3:00 - 4:40',
    'L6': '5:10 - 6:50'
};

// Extended time slots to include all possible times (properly ordered)
const allTimeSlots = [
    // Morning theory slots
    "8:00 - 8:50", "8:50 - 9:40", "8:00 - 9:40",      // 8 AM
    "9:00 - 9:50",                                      // 9 AM  
    "10:00 - 10:50", "10:50 - 11:40", "10:00 - 11:40", // 10 AM
    "11:00 - 11:50", "11:40 - 12:30", "11:50 - 12:30", "11:50 - 1:20", // 11 AM
    "12:00 - 12:50", "12:30 - 1:20",                   // 12 PM
    // Afternoon slots
    "1:00 - 1:50", "1:20 - 2:10", "1:20 - 3:00",      // 1 PM
    "2:00 - 2:50", "2:10 - 3:00",                      // 2 PM
    "3:00 - 3:50", "3:50 - 4:40", "3:00 - 4:40",      // 3 PM
    "4:00 - 4:50",                                      // 4 PM
    "5:00 - 5:50", "5:10 - 6:00", "5:10 - 6:50",      // 5 PM
    "6:00 - 6:50"                                       // 6 PM
];

// Default days - will be dynamically updated based on data
let days = ['tuesday', 'wed', 'thur', 'fri', 'sat'];

// Day pattern mappings
const dayPatternMappings = {
    'Monday-Friday': ['monday', 'tuesday', 'wed', 'thur', 'fri'],
    'Tuesday-Saturday': ['tuesday', 'wed', 'thur', 'fri', 'saturday']
};

// Group color mapping
const groupColors = {
    1: 'group-g1',
    2: 'group-g2', 
    3: 'group-g3',
    4: 'group-g4',
    5: 'group-g5',
    6: 'group-g6',
    7: 'group-g7',
    8: 'group-g8',
    9: 'group-g9',
    10: 'group-g10'
};

// Department color mapping
const deptColors = {
    'Computer Science & Engineering': 'dept-cs',
    'Computer Science & Engineering (Cyber Security)': 'dept-cy',
    'Information Technology': 'dept-it',
    'Artificial Intelligence & Data Science': 'dept-ai',
    'Artificial Intelligence & Machine Learning': 'dept-ai',
    'Computer Science & Business Systems': 'dept-cb',
    'Computer Science & Design': 'dept-cd'
};

// Helper functions for color assignment
function getGroupClass(groupName) {
    if (!groupName) return '';
    
    // Extract group number from group name (e.g., "Computer Science & Engineering_S3_G1" -> 1)
    const match = groupName.match(/_G(\d+)$/);
    if (match) {
        const groupNum = parseInt(match[1]);
        return groupColors[groupNum] || '';
    }
    return '';
}

function getDeptClass(department) {
    return deptColors[department] || '';
}

function getSemesterFromGroupName(groupName) {
    if (!groupName) return '';
    
    // Extract semester from group name (e.g., "Computer Science & Engineering_S3_G1" -> 3)
    const match = groupName.match(/_S(\d+)_/);
    if (match) {
        return `S${match[1]}`;
    }
    return '';
}

// Load and parse data
async function loadData() {
    try {
        // Get the latest folder path from the server
        console.log('Fetching latest folder from API...');
        const folderResponse = await fetch('/api/latest-folder');
        
        if (!folderResponse.ok) {
            throw new Error(`API request failed: ${folderResponse.status} ${folderResponse.statusText}`);
        }
        
        const folderResponseText = await folderResponse.text();
        console.log('Raw API response:', folderResponseText);
        
        const folderData = JSON.parse(folderResponseText);
        console.log('Parsed API response:', folderData);
        
        if (folderData.error) {
            throw new Error(folderData.error);
        }
        
        const latestFolder = folderData.latestFolder;
        console.log('Using latest schedule folder:', latestFolder);
        
        // Load lab data
        const labResponse = await fetch(`${latestFolder}/combined_lab_schedule.json`);
        if (!labResponse.ok) {
            throw new Error(`Failed to load lab schedule: ${labResponse.status} ${labResponse.statusText}`);
        }
        labData = await labResponse.json();
        
        // Load theory data
        const theoryResponse = await fetch(`${latestFolder}/combined_theory_schedule.json`);
        if (!theoryResponse.ok) {
            throw new Error(`Failed to load theory schedule: ${theoryResponse.status} ${theoryResponse.statusText}`);
        }
        theoryData = await theoryResponse.json();
        
        // Combine data
        allData = [...labData, ...theoryData];
        
        // Show success message with folder info
        console.log(`Successfully loaded ${labData.length} lab sessions and ${theoryData.length} theory sessions from ${latestFolder}`);
        
        // Initialize UI
        initializeFilters();
        updateSummaryStats();
        renderContent();
        
    } catch (error) {
        console.error('Error loading data:', error);
        document.getElementById('mainContent').innerHTML = `
            <div class="alert alert-danger text-center">
                <i class="fas fa-exclamation-triangle me-2"></i>
                Error loading schedule data. Please ensure the data files are available.
                <br><small>Error: ${error.message}</small>
                <br><small class="text-muted">Try refreshing the page or check if the timetable scheduler has been run recently.</small>
            </div>
        `;
    }
}

// Initialize filter dropdowns
function initializeFilters() {
    // Department filter
    const departments = [...new Set(allData.map(item => item.department))].sort();
    const departmentSelect = document.getElementById('departmentFilter');
    departments.forEach(dept => {
        const option = document.createElement('option');
        option.value = dept;
        option.textContent = dept;
        departmentSelect.appendChild(option);
    });

    // Semester filter
    const semesters = [...new Set(allData.map(item => item.semester))].sort((a, b) => a - b);
    const semesterSelect = document.getElementById('semesterFilter');
    semesters.forEach(sem => {
        const option = document.createElement('option');
        option.value = sem;
        option.textContent = `Semester ${sem}`;
        semesterSelect.appendChild(option);
    });

    // Group filter
    const groups = [...new Set(allData.map(item => item.group_name).filter(Boolean))].sort();
    const groupSelect = document.getElementById('groupFilter');
    groups.forEach(group => {
        const option = document.createElement('option');
        option.value = group;
        option.textContent = group.replace(/_/g, ' ');
        groupSelect.appendChild(option);
    });

    // Update global days array based on available day patterns in data
    updateDaysFromData();

    // Add event listeners
    document.getElementById('viewType').addEventListener('change', renderContent);
    document.getElementById('departmentFilter').addEventListener('change', renderContent);
    document.getElementById('semesterFilter').addEventListener('change', renderContent);
    document.getElementById('dayFilter').addEventListener('change', renderContent);
    document.getElementById('sessionTypeFilter').addEventListener('change', renderContent);
    document.getElementById('groupFilter').addEventListener('change', renderContent);
    document.getElementById('dayPatternFilter').addEventListener('change', renderContent);
    
    // Add search filters
    document.getElementById('courseSearch').addEventListener('input', debounce(renderContent, 300));
    document.getElementById('teacherSearch').addEventListener('input', debounce(renderContent, 300));
    document.getElementById('roomSearch').addEventListener('input', debounce(renderContent, 300));
}

// Update days array based on available day patterns in the data
function updateDaysFromData() {
    const dayPatterns = [...new Set(allData.map(item => item.day_pattern).filter(Boolean))];
    const allDaysInData = [...new Set(allData.map(item => item.day))];
    
    // Use all unique days found in the data, ordered properly
    const dayOrder = ['monday', 'tuesday', 'wed', 'thur', 'fri', 'saturday'];
    days = dayOrder.filter(day => allDaysInData.includes(day));
    
    console.log('Available day patterns:', dayPatterns);
    console.log('Available days in data:', allDaysInData);
    console.log('Updated days array:', days);
}

// Update summary statistics
function updateSummaryStats() {
    const totalSessions = allData.length;
    const labSessionsCount = labData.length;
    const theorySessionsCount = theoryData.length;
    const teachers = new Set(allData.map(item => item.teacher_id)).size;
    const rooms = new Set(allData.map(item => item.room_id)).size;

    document.getElementById('totalSessions').textContent = totalSessions;
    document.getElementById('labSessions').textContent = labSessionsCount;
    document.getElementById('theorySessions').textContent = theorySessionsCount;
    document.getElementById('totalTeachers').textContent = teachers;
    document.getElementById('totalRooms').textContent = rooms;
}

// Get filtered data based on current filter selections
function getFilteredData() {
    let filtered = [...allData];

    const department = document.getElementById('departmentFilter').value;
    const semester = document.getElementById('semesterFilter').value;
    const day = document.getElementById('dayFilter').value;
    const sessionType = document.getElementById('sessionTypeFilter').value;
    const group = document.getElementById('groupFilter').value;
    const dayPattern = document.getElementById('dayPatternFilter').value;
    const courseSearch = document.getElementById('courseSearch').value.toLowerCase();
    const teacherSearch = document.getElementById('teacherSearch').value.toLowerCase();
    const roomSearch = document.getElementById('roomSearch').value.toLowerCase();

    if (department) {
        filtered = filtered.filter(item => item.department === department);
    }
    if (semester) {
        filtered = filtered.filter(item => item.semester == semester);
    }
    if (day) {
        filtered = filtered.filter(item => item.day === day);
    }
    if (sessionType) {
        filtered = filtered.filter(item => item.schedule_type === sessionType);
    }
    if (group) {
        filtered = filtered.filter(item => item.group_name === group);
    }
    if (dayPattern) {
        filtered = filtered.filter(item => item.day_pattern === dayPattern);
    }
    if (courseSearch) {
        filtered = filtered.filter(item => 
            (item.course_code || '').toLowerCase().includes(courseSearch) ||
            (item.course_name || '').toLowerCase().includes(courseSearch)
        );
    }
    if (teacherSearch) {
        filtered = filtered.filter(item => 
            (item.teacher_name || '').toLowerCase().includes(teacherSearch)
        );
    }
    if (roomSearch) {
        filtered = filtered.filter(item => 
            (item.room_number || '').toLowerCase().includes(roomSearch)
        );
    }

    return filtered;
}

// Render content based on selected view type
function renderContent() {
    const viewType = document.getElementById('viewType').value;
    const filteredData = getFilteredData();

    switch (viewType) {
        case 'department':
            renderDepartmentView(filteredData);
            break;
        case 'semester':
            renderSemesterView(filteredData);
            break;
        case 'room':
            renderRoomView(filteredData);
            break;
        case 'teacher':
            renderTeacherView(filteredData);
            break;
        case 'day':
            renderDayView(filteredData);
            break;
    }
}

// Render department-wise view
function renderDepartmentView(data) {
    const departments = [...new Set(data.map(item => item.department))].sort();
    let html = '';

    departments.forEach(dept => {
        const deptData = data.filter(item => item.department === dept);
        const semesters = [...new Set(deptData.map(item => item.semester))].sort((a, b) => a - b);
        const deptDayPattern = deptData.length > 0 ? deptData[0].day_pattern : '';

        html += `
            <div class="card mb-4">
                <div class="card-header" style="background: var(--header-bg); color: white;">
                    <h5 class="mb-0">
                        <i class="fas fa-building me-2"></i>
                        ${dept}
                        <span class="badge bg-light text-dark ms-2">${deptData.length} sessions</span>
                        ${deptDayPattern ? `<span class="badge bg-info ms-2">${deptDayPattern}</span>` : ''}
                    </h5>
                </div>
                <div class="card-body">
        `;

        semesters.forEach(semester => {
            const semesterData = deptData.filter(item => item.semester === semester);
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

    document.getElementById('mainContent').innerHTML = html;
}

// Render semester-wise view
function renderSemesterView(data) {
    const semesters = [...new Set(data.map(item => item.semester))].sort((a, b) => a - b);
    let html = '';

    semesters.forEach(semester => {
        const semesterData = data.filter(item => item.semester === semester);
        const departments = [...new Set(semesterData.map(item => item.department))].sort();

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

        departments.forEach(dept => {
            const deptData = semesterData.filter(item => item.department === dept);
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

    document.getElementById('mainContent').innerHTML = html;
}

// Render room-wise view
function renderRoomView(data) {
    const rooms = [...new Set(data.map(item => `${item.room_number} (${item.block})`))].sort();
    let html = '';

    rooms.forEach(roomInfo => {
        const [roomNumber, block] = roomInfo.split(' (');
        const blockName = block.replace(')', '');
        const roomData = data.filter(item => item.room_number === roomNumber && item.block === blockName);
        
        if (roomData.length === 0) return;

        const isLab = roomData[0].schedule_type === 'lab';
        const capacity = roomData[0].capacity || 'N/A';

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

    document.getElementById('mainContent').innerHTML = html;
}

// Render teacher-wise view
function renderTeacherView(data) {
    const teachers = [...new Set(data.map(item => `${item.teacher_name}|${item.staff_code}`))].sort();
    let html = '';

    teachers.forEach(teacherInfo => {
        const [teacherName, staffCode] = teacherInfo.split('|');
        const teacherData = data.filter(item => item.teacher_name === teacherName);
        
        const labSessions = teacherData.filter(item => item.schedule_type === 'lab').length;
        const theorySessions = teacherData.filter(item => item.schedule_type === 'theory').length;

        html += `
            <div class="card mb-4">
                <div class="card-header" style="background: var(--header-bg); color: white;">
                    <h5 class="mb-0">
                        <i class="fas fa-user me-2"></i>
                        ${teacherName} (${staffCode})
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

    document.getElementById('mainContent').innerHTML = html;
}

// Render day-wise view
function renderDayView(data) {
    let html = '';

    days.forEach(day => {
        const dayData = data.filter(item => item.day === day);
        if (dayData.length === 0) return;

        const labCount = dayData.filter(item => item.schedule_type === 'lab').length;
        const theoryCount = dayData.filter(item => item.schedule_type === 'theory').length;

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

    document.getElementById('mainContent').innerHTML = html;
}

// Generate schedule table
function generateScheduleTable(data) {
    if (data.length === 0) {
        return '<div class="alert alert-info">No sessions found for the selected filters.</div>';
    }

    // Determine which days to use based on the data being displayed
    const daysInData = [...new Set(data.map(item => item.day))];
    const dayOrder = ['monday', 'tuesday', 'wed', 'thur', 'fri', 'saturday'];
    const currentDays = dayOrder.filter(day => daysInData.includes(day));
    
    // Show day pattern information if available
    const dayPatterns = [...new Set(data.map(item => item.day_pattern).filter(Boolean))];
    
    // Create time slot mapping
    const scheduleGrid = {};
    
    // Initialize grid with all possible time slots for the current days
    currentDays.forEach(day => {
        scheduleGrid[day] = {};
        // Use extended time slots that include both theory and lab times
        allTimeSlots.forEach(slot => {
            scheduleGrid[day][slot] = [];
        });
        // Also add any theory slots that might not be in allTimeSlots
        timeSlots.forEach(slot => {
            if (!scheduleGrid[day][slot]) {
                scheduleGrid[day][slot] = [];
            }
        });
    });

    // Fill grid with data
    data.forEach(item => {
        const day = item.day;
        let timeKey;
        
        if (item.schedule_type === 'lab') {
            timeKey = labSessions[item.session_name] || item.time_range;
        } else {
            timeKey = item.time_slot;
        }

        if (scheduleGrid[day] && scheduleGrid[day][timeKey]) {
            scheduleGrid[day][timeKey].push(item);
        } else if (scheduleGrid[day]) {
            // If exact time slot not found, create it
            scheduleGrid[day][timeKey] = [item];
            console.log(`Added new time slot: ${timeKey} for ${item.course_code || item.course_code_display}`);
        }
    });

    // Generate table HTML with day pattern info
    let html = '';
    
    // Add day pattern information header if available
    if (dayPatterns.length > 0) {
        html += `
            <div class="alert alert-info mb-3">
                <i class="fas fa-calendar-week me-2"></i>
                <strong>Day Pattern${dayPatterns.length > 1 ? 's' : ''}:</strong> 
                ${dayPatterns.join(', ')}
                <span class="ms-3">
                    <i class="fas fa-calendar-day me-1"></i>
                    <strong>Days:</strong> ${currentDays.map(d => d.charAt(0).toUpperCase() + d.slice(1)).join(', ')}
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

    currentDays.forEach(day => {
        html += `<th>${day.charAt(0).toUpperCase() + day.slice(1)}</th>`;
    });

    html += `
                    </tr>
                </thead>
                <tbody>
    `;

    // Get all unique time slots from data and separate theory and lab slots
    const usedTheorySlots = new Set();
    const usedLabSlots = new Set();
    
    Object.values(scheduleGrid).forEach(daySchedule => {
        Object.keys(daySchedule).forEach(timeSlot => {
            if (daySchedule[timeSlot].length > 0) {
                const hasTheorySession = daySchedule[timeSlot].some(session => session.schedule_type === 'theory');
                const hasLabSession = daySchedule[timeSlot].some(session => session.schedule_type === 'lab');
                
                if (hasTheorySession) {
                    usedTheorySlots.add(timeSlot);
                }
                if (hasLabSession) {
                    usedLabSlots.add(timeSlot);
                }
            }
        });
    });

    // Sort theory and lab slots separately, then combine (theory first)
    const sortedTheorySlots = Array.from(usedTheorySlots).sort((a, b) => {
        return parseTimeSlot(a) - parseTimeSlot(b);
    });
    
    const sortedLabSlots = Array.from(usedLabSlots).sort((a, b) => {
        return parseTimeSlot(a) - parseTimeSlot(b);
    });
    
    // Combine with theory slots first, then lab slots
    const sortedTimeSlots = [...sortedTheorySlots, ...sortedLabSlots];

    sortedTimeSlots.forEach((timeSlot, index) => {
        // Add section separator between theory and lab slots
        if (index === sortedTheorySlots.length && sortedLabSlots.length > 0) {
            html += `
                <tr class="table-section-divider">
                    <td colspan="${currentDays.length + 1}" class="text-center" style="background-color: #f8f9fa; font-weight: bold; padding: 10px;">
                        <i class="fas fa-flask me-2"></i>LAB SESSIONS
                    </td>
                </tr>
            `;
        }
        
        // Add theory section header if this is the first theory slot
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
        
        currentDays.forEach(day => {
            const sessions = scheduleGrid[day][timeSlot] || [];
            html += '<td>';
            
            sessions.forEach(session => {
                const isLab = session.schedule_type === 'lab';
                const isBatched = session.is_batched;
                const sessionClass = isLab ? 'lab-session' : 'theory-session';
                const batchClass = isBatched ? 'batched-session' : '';
                
                // Get group and department colors
                const groupClass = getGroupClass(session.group_name);
                const deptClass = getDeptClass(session.department);
                const semester = getSemesterFromGroupName(session.group_name) || `S${session.semester}`;
                
                // Extract group number for display
                const groupNumber = session.group_name ? session.group_name.match(/_G(\d+)$/)?.[1] || '' : '';
                
                html += `
                    <div class="${sessionClass} ${batchClass} ${deptClass}" title="
                        Course: ${session.course_name}
                        Teacher: ${session.teacher_name}
                        Room: ${session.room_number} (${session.block})
                        Department: ${session.department}
                        Group: ${session.group_name}
                        Semester: ${semester}
                        ${isLab ? 'Capacity: ' + session.capacity : ''}
                        ${isBatched ? 'Batched: ' + session.batch_info : ''}
                    ">
                        <div class="session-header">
                            <div class="session-code">${session.course_code_display || session.course_code}</div>
                            ${groupNumber ? `<div class="group-number ${groupClass}">G${groupNumber}</div>` : ''}
                        </div>
                        <div class="session-teacher">${session.teacher_name}</div>
                        <div class="session-room">${session.room_number}</div>
                        <div class="semester-indicator">${semester}</div>
                    </div>
                `;
            });
            
            html += '</td>';
        });
        
        html += '</tr>';
    });

    html += `
                </tbody>
            </table>
        </div>
    `;

    return html;
}

// Helper function to parse time slot for chronological sorting
function parseTimeSlot(timeSlot) {
    // Extract the start time from time slot (e.g., "8:00 - 8:50" -> "8:00")
    const startTime = timeSlot.split(' - ')[0].trim();
    
    // Convert time to minutes since midnight for comparison
    const [hours, minutes] = startTime.split(':').map(num => parseInt(num));
    
    // Convert to 24-hour format for proper sorting
    let adjustedHours = hours;
    
    // Handle afternoon times (1:00 - 7:10 are PM times based on the schedule)
    if (hours >= 1 && hours <= 7) {
        // Check if this is actually afternoon time by looking at context
        // Times 1:00 to 7:10 in the schedule are afternoon (13:00 to 19:10)
        adjustedHours = hours + 12;
    }
    // Morning times 8:00 to 12:00 stay as is
    
    return adjustedHours * 60 + minutes;
}

// Debounce function for search performance
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

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    loadData();
}); 