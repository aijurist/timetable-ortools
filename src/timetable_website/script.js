// Global variables
let csvData = [];
let courses = {};
let teachers = {};
let selectedCourses = {};
let currentTimetable = {};
let timeSlots = {};

// Time slot mappings - matching the visualizer structure
const TIME_SLOTS = {
    // Theory/Regular slots (0-10)
    0: '8:00 - 8:50',   1: '9:00 - 9:50',   2: '10:00 - 10:50',  3: '11:00 - 11:50',
    4: '12:00 - 12:50', 5: '1:00 - 1:50',  6: '2:00 - 2:50',    7: '3:00 - 3:50',
    8: '4:00 - 4:50',   9: '5:00 - 5:50',  10: '6:00 - 6:50',
    
    // Lab slots (20-31) - 50-minute sessions
    20: '8:00 - 8:50',   21: '8:50 - 9:40',   22: '9:50 - 10:40',  23: '10:40 - 11:30',
    24: '11:50 - 12:40', 25: '12:40 - 1:30', 26: '1:50 - 2:40',   27: '2:40 - 3:30',
    28: '3:50 - 4:40',   29: '4:40 - 5:30',  30: '5:30 - 6:20',   31: '6:20 - 7:10'
};

const DAYS = {
    'monday': 1, 'tuesday': 2, 'wednesday': 3, 'thursday': 4, 'friday': 5, 'saturday': 6,
    'mon': 1, 'tue': 2, 'wed': 3, 'thu': 4, 'fri': 5, 'sat': 6,
    'thur': 4  // Handle the 'thur' variation in data
};

const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

// Macroblock structure mapping based on actual university schedule patterns
const MACROBLOCK_PATTERNS = {
    // Tuesday patterns  
    2: {
        0: 'a1', 1: 'b1', 2: 'c1', 3: 'd1', 4: 'e1', 5: 'f1', 6: 'g1', 7: 'a2', 8: 'b2', 9: 'c2', 10: '--', 11: '--'
    },
    // Wednesday patterns
    3: {
        0: 'd2', 1: 'e2', 2: 'f2', 3: 'g2', 4: 'ta1', 5: 'tb1', 6: 'tc1', 7: 'td1', 8: 'te1', 9: 'tf1', 10: '--', 11: '--'
    },
    // Thursday patterns
    4: {
        0: 'tg1', 1: 'taa2', 2: 'tbb2', 3: 'tcc2', 4: 'v1', 5: 'v2', 6: 'a1', 7: 'b1', 8: 'c1', 9: 'd1', 10: '--', 11: '--'
    },
    // Friday patterns
    5: {
        0: 'e1', 1: 'f1', 2: 'g1', 3: 'ta2', 4: 'tb2', 5: 'tc2', 6: 'td2', 7: 'te2', 8: 'tf2', 9: 'tg2', 10: '--', 11: '--'
    },
    // Saturday patterns
    6: {
        0: 'a2', 1: 'b2', 2: 'c2', 3: 'taa1', 4: 'tbb1', 5: 'tcc1', 6: 'd2', 7: 'e2', 8: 'f2', 9: 'g2', 10: '--', 11: '--'
    }
};

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    showLoadingSpinner();
    loadCSVData();
    setupEventListeners();
});

// Setup event listeners
function setupEventListeners() {
    document.getElementById('clearAll').addEventListener('click', clearAllSelections);
    document.getElementById('generateTimetable').addEventListener('click', generateTimetable);
    document.getElementById('closeModal').addEventListener('click', closeModal);
    document.getElementById('closeConflictModal').addEventListener('click', closeConflictModal);
    document.getElementById('cancelSelection').addEventListener('click', closeModal);
    document.getElementById('confirmSelection').addEventListener('click', confirmTeacherSelection);
    document.getElementById('cancelConflict').addEventListener('click', closeConflictModal);
    document.getElementById('resolveConflict').addEventListener('click', resolveConflict);
    
    // Close modals when clicking outside
    window.addEventListener('click', function(event) {
        const modal = document.getElementById('courseModal');
        const conflictModal = document.getElementById('conflictModal');
        if (event.target === modal) {
            closeModal();
        }
        if (event.target === conflictModal) {
            closeConflictModal();
        }
    });
}

// Load and parse CSV data
async function loadCSVData() {
    try {
        // Since we can't directly load CSV in a static environment, we'll embed the data
        const csvText = await loadCSVFromFile();
        parseCSVData(csvText);
        processCourseData();
        renderCourseSelection();
        initializeTimetable();
        hideLoadingSpinner();
    } catch (error) {
        console.error('Error loading CSV data:', error);
        hideLoadingSpinner();
        alert('Error loading course data. Please refresh the page.');
    }
}

// Simulate loading CSV data (in a real environment, this would be a fetch call)
async function loadCSVFromFile() {
    try {
        // Try to fetch from the server API endpoint first
        const response = await fetch('/api/csv-data');
        if (response.ok) {
            return await response.text();
        } else {
            throw new Error('Failed to fetch CSV from server');
        }
    } catch (error) {
        console.warn('Could not fetch CSV from server, using fallback data:', error);
        
        // Fallback to embedded data if server is not available
        return `day,slot_index,time_interval,slot_type,macroblock,teacher_id,first_name,last_name,staff_code,room_id,room_number,block,room_type,capacity,course_id,course_code,course_name,course_instance_id,student_count,semester,course_dept,teacher_shift,daily_shift_pattern,lab_session,lab_session_slot,practical_hours,room_capacity,display_course_code,total_instance_students,is_batched,batch_number,batch_info,num_batches,students_per_batch,lab_capacity_category
wed,0,8:00 - 8:50,Lecture,d2,187,Mr.,Dr. Kumar P,IT03,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,95,70,5,Computer Science & Engineering,shift1,S2→S1→--→S1→S1,,,0,,,,,False,,,,
sat,6,2:00 - 2:50,Lecture,d2,187,Mr.,Dr. Kumar P,IT03,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,95,70,5,Computer Science & Engineering,shift1,S2→S1→--→S1→S1,,,0,,,,,False,,,,
fri,6,2:00 - 2:50,Lecture,td2,187,Mr.,Dr. Kumar P,IT03,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,95,70,5,Computer Science & Engineering,shift1,S2→S1→--→S1→S1,,,0,,,,,False,,,,
wed,22,9:50 - 10:40,Practical,LAB_L2_1,187,Mr.,Dr. Kumar P,IT03,171,KFR03,K Block,Lab,35,1868,CS23533,Foundations of Artificial Intelligence,95,35,5,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L2,1,2,35.0,CS23533 S1 B1,70.0,True,1.0,Batch 1,2.0,35.0,35-capacity
wed,23,10:40 - 11:30,Practical,LAB_L2_2,187,Mr.,Dr. Kumar P,IT03,171,KFR03,K Block,Lab,35,1868,CS23533,Foundations of Artificial Intelligence,95,35,5,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L2,2,2,35.0,CS23533 S1 B1,70.0,True,1.0,Batch 1,2.0,35.0,35-capacity
sat,24,11:50 - 12:40,Practical,LAB_L3_1,187,Mr.,Dr. Kumar P,IT03,175,TLFL2,Techlounge,Lab,35,1868,CS23533,Foundations of Artificial Intelligence,95,35,5,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L3,1,2,35.0,CS23533 S1 B2,70.0,True,2.0,Batch 2,2.0,35.0,35-capacity
sat,25,12:40 - 1:30,Practical,LAB_L3_2,187,Mr.,Dr. Kumar P,IT03,175,TLFL2,Techlounge,Lab,35,1868,CS23533,Foundations of Artificial Intelligence,95,35,5,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L3,2,2,35.0,CS23533 S1 B2,70.0,True,2.0,Batch 2,2.0,35.0,35-capacity
tuesday,7,3:00 - 3:50,Lecture,a2,187,Mr.,Dr. Kumar P,IT03,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,109,70,5,Computer Science & Engineering,shift2,S2→S1→--→S1→S1,,,0,,,,,False,,,,
sat,0,8:00 - 8:50,Lecture,a2,187,Mr.,Dr. Kumar P,IT03,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,109,70,5,Computer Science & Engineering,shift1,S2→S1→--→S1→S1,,,0,,,,,False,,,,
fri,3,11:00 - 11:50,Lecture,ta2,187,Mr.,Dr. Kumar P,IT03,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,109,70,5,Computer Science & Engineering,shift1,S2→S1→--→S1→S1,,,0,,,,,False,,,,
tuesday,7,3:00 - 3:50,Lecture,a2,192,Mrs.,Jananee V,CS182,2,A103,A Block,Classroom,70,1544,CS23332,Database Management Systems,220,70,3,Computer Science & Engineering,shift2,S2→--→--→S1→S1,,,0,,,,,False,,,,
sat,0,8:00 - 8:50,Lecture,a2,192,Mrs.,Jananee V,CS182,2,A103,A Block,Classroom,70,1544,CS23332,Database Management Systems,220,70,3,Computer Science & Engineering,shift1,S2→--→--→S1→S1,,,0,,,,,False,,,,
fri,3,11:00 - 11:50,Lecture,ta2,192,Mrs.,Jananee V,CS182,2,A103,A Block,Classroom,70,1544,CS23332,Database Management Systems,220,70,3,Computer Science & Engineering,shift1,S2→--→--→S1→S1,,,0,,,,,False,,,,
wed,28,3:50 - 4:40,Practical,LAB_L5_1,192,Mrs.,Jananee V,CS182,189,TLSL2,Techlounge,Lab,70,1544,CS23332,Database Management Systems,220,70,3,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L5,1,4,70.0,CS23332,70.0,False,,,1.0,70.0,70-capacity
wed,29,4:40 - 5:30,Practical,LAB_L5_2,192,Mrs.,Jananee V,CS182,189,TLSL2,Techlounge,Lab,70,1544,CS23332,Database Management Systems,220,70,3,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L5,2,4,70.0,CS23332,70.0,False,,,1.0,70.0,70-capacity
tuesday,6,2:00 - 2:50,Lecture,g1,195,Ms.,Jaeyalakshmi M,CS203,1,A102,A Block,Classroom,70,1544,CS23332,Database Management Systems,293,70,5,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,False,,,,
fri,2,10:00 - 10:50,Lecture,g1,195,Ms.,Jaeyalakshmi M,CS203,1,A102,A Block,Classroom,70,1544,CS23332,Database Management Systems,293,70,5,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,False,,,,
thur,0,8:00 - 8:50,Lecture,tg1,195,Ms.,Jaeyalakshmi M,CS203,1,A102,A Block,Classroom,70,1544,CS23332,Database Management Systems,293,70,5,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,False,,,,
tuesday,6,2:00 - 2:50,Lecture,g1,196,Mr.,Dr.P.Shanmugam,CS251,2,A103,A Block,Classroom,70,1543,CS23331,Design and Analysis of Algorithms,214,70,3,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,False,,,,
fri,2,10:00 - 10:50,Lecture,g1,196,Mr.,Dr.P.Shanmugam,CS251,2,A103,A Block,Classroom,70,1543,CS23331,Design and Analysis of Algorithms,214,70,3,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,False,,,,
thur,0,8:00 - 8:50,Lecture,tg1,196,Mr.,Dr.P.Shanmugam,CS251,2,A103,A Block,Classroom,70,1543,CS23331,Design and Analysis of Algorithms,214,70,3,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,False,,,,
wed,22,9:50 - 10:40,Practical,LAB_L2_1,196,Mr.,Dr.P.Shanmugam,CS251,178,TLFL5,Techlounge,Lab,35,1543,CS23331,Design and Analysis of Algorithms,214,35,3,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L2,1,2,35.0,CS23331 B1,70.0,True,1.0,Batch 1,2.0,35.0,35-capacity
wed,23,10:40 - 11:30,Practical,LAB_L2_2,196,Mr.,Dr.P.Shanmugam,CS251,178,TLFL5,Techlounge,Lab,35,1543,CS23331,Design and Analysis of Algorithms,214,35,3,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L2,2,2,35.0,CS23331 B1,70.0,True,1.0,Batch 1,2.0,35.0,35-capacity
sat,22,9:50 - 10:40,Practical,LAB_L2_1,196,Mr.,Dr.P.Shanmugam,CS251,174,TLFL1,Techlounge,Lab,35,1543,CS23331,Design and Analysis of Algorithms,214,35,3,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L2,1,2,35.0,CS23331 B2,70.0,True,2.0,Batch 2,2.0,35.0,35-capacity
sat,23,10:40 - 11:30,Practical,LAB_L2_2,196,Mr.,Dr.P.Shanmugam,CS251,174,TLFL1,Techlounge,Lab,35,1543,CS23331,Design and Analysis of Algorithms,214,35,3,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L2,2,2,35.0,CS23331 B2,70.0,True,2.0,Batch 2,2.0,35.0,35-capacity
tuesday,2,10:00 - 10:50,Lecture,c1,222,Mr.,Dr.K.Ananthajothi,CS255,5,A109,A Block,Classroom,70,1553,CS23511,Theory of Computation,253,70,5,Computer Science & Engineering,shift1,S1→S1→S2→--→S1,,,0,,,,,False,,,,
thur,8,4:00 - 4:50,Lecture,c1,222,Mr.,Dr.K.Ananthajothi,CS255,5,A109,A Block,Classroom,70,1553,CS23511,Theory of Computation,253,70,5,Computer Science & Engineering,shift2,S1→S1→S2→--→S1,,,0,,,,,False,,,,
wed,6,2:00 - 2:50,Lecture,tc1,222,Mr.,Dr.K.Ananthajothi,CS255,5,A109,A Block,Classroom,70,1553,CS23511,Theory of Computation,253,70,5,Computer Science & Engineering,shift1,S1→S1→S2→--→S1,,,0,,,,,False,,,,
sat,5,1:00 - 1:50,Tutorial,tcc1,222,Mr.,Dr.K.Ananthajothi,CS255,1,A102,A Block,Classroom,70,1553,CS23511,Theory of Computation,253,70,5,Computer Science & Engineering,shift1,S1→S1→S2→--→S1,,,0,,,,,False,,,,
tuesday,6,2:00 - 2:50,Lecture,g1,202,Mr.,Dr. N. Duraimurugan,CS208,3,A104/105,A Block,Classroom,140,1555,CS23531,Web Programming,261,70,5,Computer Science & Engineering,shift1,S1→--→--→--→--,,,0,,,,,False,,,,
thur,28,3:50 - 4:40,Practical,LAB_L5_1,202,Mr.,Dr. N. Duraimurugan,CS208,189,TLSL2,Techlounge,Lab,70,1555,CS23531,Web Programming,261,70,5,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L5,1,4,70.0,CS23531,70.0,False,,,1.0,70.0,70-capacity
thur,29,4:40 - 5:30,Practical,LAB_L5_2,202,Mr.,Dr. N. Duraimurugan,CS208,189,TLSL2,Techlounge,Lab,70,1555,CS23531,Web Programming,261,70,5,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L5,2,4,70.0,CS23531,70.0,False,,,1.0,70.0,70-capacity
tuesday,30,5:30 - 6:20,Practical,LAB_L6_1,244,Dr.,Madhusudhanan S,CS320,158,DG03,D Block,Lab,70,1555,CS23531,Web Programming,267,70,5,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L6,1,4,70.0,CS23531,70.0,False,,,1.0,70.0,70-capacity
tuesday,31,6:20 - 7:10,Practical,LAB_L6_2,244,Dr.,Madhusudhanan S,CS320,158,DG03,D Block,Lab,70,1555,CS23531,Web Programming,267,70,5,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L6,2,4,70.0,CS23531,70.0,False,,,1.0,70.0,70-capacity`;
    }
}

// Parse CSV data
function parseCSVData(csvText) {
    const lines = csvText.trim().split('\n');
    const headers = lines[0].split(',');
    
    csvData = [];
    for (let i = 1; i < lines.length; i++) {
        const values = lines[i].split(',');
        const row = {};
        headers.forEach((header, index) => {
            row[header] = values[index] || '';
        });
        csvData.push(row);
    }
}

// Process course data
function processCourseData() {
    courses = {};
    teachers = {};
    
    csvData.forEach(row => {
        const courseCode = row.course_code;
        const courseName = row.course_name;
        const teacherId = row.teacher_id;
        const teacherName = `${row.first_name} ${row.last_name}`;
        const staffCode = row.staff_code;
        const semester = row.semester;
        const courseInstanceId = row.course_instance_id;
        const isBatched = row.is_batched === 'True';
        const batchNumber = row.batch_number;
        const batchInfo = row.batch_info;
        
        // Only process 5th semester courses
        if (semester !== '5') return;
        
        // Initialize course if not exists
        if (!courses[courseCode]) {
            courses[courseCode] = {
                code: courseCode,
                name: courseName,
                teachers: {},
                semester: semester,
                hasLab: false,
                hasLecture: false,
                isBatched: false
            };
        }
        
        // Add teacher to course
        if (!courses[courseCode].teachers[teacherId]) {
            courses[courseCode].teachers[teacherId] = {
                id: teacherId,
                name: teacherName,
                staffCode: staffCode,
                slots: [],
                courseInstances: {},
                isBatched: false
            };
        }
        
        // Add slot information
        const slot = {
            day: row.day,
            slotIndex: parseInt(row.slot_index),
            timeInterval: row.time_interval,
            slotType: row.slot_type,
            roomNumber: row.room_number,
            block: row.block,
            roomType: row.room_type,
            courseInstanceId: courseInstanceId,
            isBatched: isBatched,
            batchNumber: batchNumber,
            batchInfo: batchInfo,
            labSession: row.lab_session,
            macroblock: row.macroblock
        };
        
        courses[courseCode].teachers[teacherId].slots.push(slot);
        
        // Organize by course instances for better grouping
        if (!courses[courseCode].teachers[teacherId].courseInstances[courseInstanceId]) {
            courses[courseCode].teachers[teacherId].courseInstances[courseInstanceId] = {
                instanceId: courseInstanceId,
                slots: [],
                isBatched: false,
                batches: {}
            };
        }
        
        courses[courseCode].teachers[teacherId].courseInstances[courseInstanceId].slots.push(slot);
        
        // If this slot is batched, mark the instance as batched
        if (isBatched) {
            courses[courseCode].teachers[teacherId].courseInstances[courseInstanceId].isBatched = true;
            courses[courseCode].teachers[teacherId].isBatched = true;
            courses[courseCode].isBatched = true;
        }
        
        // For batched courses, organize by batch
        if (isBatched && batchNumber) {
            if (!courses[courseCode].teachers[teacherId].courseInstances[courseInstanceId].batches[batchNumber]) {
                courses[courseCode].teachers[teacherId].courseInstances[courseInstanceId].batches[batchNumber] = {
                    batchNumber: batchNumber,
                    batchInfo: batchInfo,
                    slots: []
                };
            }
            courses[courseCode].teachers[teacherId].courseInstances[courseInstanceId].batches[batchNumber].slots.push(slot);
        }
        
        // Update course flags
        if (slot.slotType.toLowerCase() === 'lecture') {
            courses[courseCode].hasLecture = true;
        } else if (slot.slotType.toLowerCase() === 'practical') {
            courses[courseCode].hasLab = true;
        }
        
        // Store teacher info globally
        teachers[teacherId] = {
            id: teacherId,
            name: teacherName,
            staffCode: staffCode
        };
    });
}

// Render course selection interface
function renderCourseSelection() {
    const container = document.getElementById('courseSelection');
    container.innerHTML = '';
    
    Object.values(courses).forEach(course => {
        const courseCard = createCourseCard(course);
        container.appendChild(courseCard);
    });
}

// Create course card element
function createCourseCard(course) {
    const card = document.createElement('div');
    card.className = 'course-card';
    card.dataset.courseCode = course.code;
    
    const courseTypes = [];
    if (course.hasLecture) courseTypes.push('Lecture');
    if (course.hasLab) courseTypes.push('Lab');
    
    card.innerHTML = `
        <div class="course-header">
            <div class="course-title">${course.name}</div>
            <div class="course-code">${course.code}</div>
        </div>
        <div class="course-details">
            <div>Semester: ${course.semester}</div>
            <div>Type: ${courseTypes.join(', ')}</div>
            <div>Teachers: ${Object.keys(course.teachers).length}</div>
        </div>
        ${selectedCourses[course.code] ? `
            <div class="course-teacher">
                <strong>Selected:</strong> ${selectedCourses[course.code].teacher.name}
            </div>
        ` : ''}
    `;
    
    if (selectedCourses[course.code]) {
        card.classList.add('selected');
    }
    
    card.addEventListener('click', () => openCourseModal(course));
    
    return card;
}

// Open course modal for teacher selection
function openCourseModal(course) {
    const modal = document.getElementById('courseModal');
    const modalTitle = document.getElementById('modalTitle');
    const teacherOptions = document.getElementById('teacherOptions');
    const courseCode = document.getElementById('courseCode');
    const courseCredits = document.getElementById('courseCredits');
    const courseType = document.getElementById('courseType');
    
    modalTitle.textContent = course.name;
    courseCode.textContent = course.code;
    courseCredits.textContent = '3-4'; // Default, can be extracted from data if available
    
    // Determine course type
    let types = [];
    if (course.hasLecture) types.push('Lecture');
    if (course.hasLab) types.push('Lab/Practical');
    if (course.hasTutorial) types.push('Tutorial');
    courseType.textContent = types.join(', ');
    
    // Clear previous options
    teacherOptions.innerHTML = '';
    
    // Create teacher options with instance selection
    Object.values(course.teachers).forEach(teacher => {
        const optionContainer = createTeacherOption(teacher, course.code);
        teacherOptions.appendChild(optionContainer);
    });
    
    // Reset modal state
    document.getElementById('confirmSelection').disabled = true;
    modal.dataset.courseCode = course.code;
    modal.style.display = 'block';
}

// Create teacher option with instance selection
function createTeacherOption(teacher, courseCode) {
    const optionContainer = document.createElement('div');
    optionContainer.className = 'teacher-option-container';
    
    // Create main teacher option
    const teacherOption = document.createElement('div');
    teacherOption.className = 'teacher-option';
    teacherOption.dataset.teacherId = teacher.id;
    
    // Count total instances for this teacher
    const totalInstances = Object.keys(teacher.courseInstances).length;
    const totalSlots = teacher.slots.length;
    
    teacherOption.innerHTML = `
        <div class="teacher-name">${teacher.name}</div>
        <div class="teacher-code">ID: ${teacher.id}</div>
        <div class="teacher-instances">
            ${totalInstances} course instance${totalInstances !== 1 ? 's' : ''} • 
            ${totalSlots} time slot${totalSlots !== 1 ? 's' : ''}
        </div>
    `;
    
    optionContainer.appendChild(teacherOption);
    
    // If teacher has multiple instances, show instance selection
    if (totalInstances > 1) {
        const instanceSelection = document.createElement('div');
        instanceSelection.className = 'instance-selection';
        instanceSelection.style.display = 'none';
        
        instanceSelection.innerHTML = '<h5>Select Course Instance:</h5>';
        
        Object.values(teacher.courseInstances).forEach(instance => {
            const instanceDiv = document.createElement('div');
            instanceDiv.className = 'instance-details';
            
            // Show instance information
            let instanceInfo = `<strong>Instance ${instance.instanceId}</strong><br>`;
            instanceInfo += `${instance.slots.length} slots`;
            
            if (instance.isBatched && Object.keys(instance.batches).length > 0) {
                instanceInfo += ` • Batched (${Object.keys(instance.batches).length} batches)`;
            }
            
            // Show schedule summary
            const scheduleSummary = getInstanceScheduleSummary(instance);
            if (scheduleSummary) {
                instanceInfo += `<br><small>${scheduleSummary}</small>`;
            }
            
            instanceDiv.innerHTML = instanceInfo;
            
            const instanceOption = document.createElement('div');
            instanceOption.className = 'instance-option';
            instanceOption.dataset.instanceId = instance.instanceId;
            instanceOption.innerHTML = `
                <input type="radio" name="instance_${teacher.id}" id="instance_${teacher.id}_${instance.instanceId}" value="${instance.instanceId}">
                <label for="instance_${teacher.id}_${instance.instanceId}">${instanceInfo}</label>
            `;
            
            instanceSelection.appendChild(instanceOption);
            
            // If this instance has batches, show batch selection
            if (instance.isBatched && Object.keys(instance.batches).length > 0) {
                const batchSelection = document.createElement('div');
                batchSelection.className = 'batch-selection';
                batchSelection.style.display = 'none';
                batchSelection.innerHTML = '<h6>Select Batch:</h6>';
                
                Object.values(instance.batches).forEach(batch => {
                    const batchOption = document.createElement('div');
                    batchOption.className = 'batch-option';
                    batchOption.innerHTML = `
                        <input type="radio" name="batch_${teacher.id}_${instance.instanceId}" id="batch_${teacher.id}_${instance.instanceId}_${batch.batchNumber}" value="${batch.batchNumber}">
                        <label for="batch_${teacher.id}_${instance.instanceId}_${batch.batchNumber}">${batch.batchInfo || `Batch ${batch.batchNumber}`}</label>
                    `;
                    batchSelection.appendChild(batchOption);
                });
                
                instanceOption.appendChild(batchSelection);
                
                // Show batch selection when instance is selected
                instanceOption.querySelector('input[type="radio"]').addEventListener('change', function() {
                    if (this.checked) {
                        batchSelection.style.display = 'block';
                    }
                });
            }
        });
        
        optionContainer.appendChild(instanceSelection);
    } else {
        // Single instance - check if it needs batch selection
        const singleInstance = Object.values(teacher.courseInstances)[0];
        if (singleInstance && singleInstance.isBatched && Object.keys(singleInstance.batches).length > 0) {
            const batchSelection = document.createElement('div');
            batchSelection.className = 'batch-selection';
            batchSelection.style.display = 'none';
            batchSelection.innerHTML = '<h6>Select Batch:</h6>';
            
            Object.values(singleInstance.batches).forEach(batch => {
                const batchOption = document.createElement('div');
                batchOption.className = 'batch-option';
                batchOption.innerHTML = `
                    <input type="radio" name="batch_${teacher.id}_${singleInstance.instanceId}" id="batch_${teacher.id}_${singleInstance.instanceId}_${batch.batchNumber}" value="${batch.batchNumber}">
                    <label for="batch_${teacher.id}_${singleInstance.instanceId}_${batch.batchNumber}">${batch.batchInfo || `Batch ${batch.batchNumber}`}</label>
                `;
                batchSelection.appendChild(batchOption);
            });
            
            optionContainer.appendChild(batchSelection);
        }
    }
    
    // Add click handler
    teacherOption.addEventListener('click', () => selectTeacher(optionContainer, teacher.id));
    
    return optionContainer;
}

// Get schedule summary for an instance
function getInstanceScheduleSummary(instance) {
    const daySlots = {};
    
    instance.slots.forEach(slot => {
        const day = slot.day;
        if (!daySlots[day]) {
            daySlots[day] = [];
        }
        daySlots[day].push(TIME_SLOTS[slot.slotIndex] || `Slot ${slot.slotIndex}`);
    });
    
    const summaryParts = [];
    Object.entries(daySlots).forEach(([day, times]) => {
        summaryParts.push(`${day.substring(0, 3)}: ${times.join(', ')}`);
    });
    
    return summaryParts.slice(0, 2).join(' | ') + (summaryParts.length > 2 ? '...' : '');
}

// Select teacher option
function selectTeacher(optionContainer, teacherId) {
    // Remove previous selection
    const parentContainer = optionContainer.parentNode;
    parentContainer.querySelectorAll('.teacher-option').forEach(opt => {
        opt.classList.remove('selected');
    });
    parentContainer.querySelectorAll('.instance-selection, .batch-selection').forEach(sel => {
        sel.style.display = 'none';
    });
    
    // Select current option
    const teacherOption = optionContainer.querySelector('.teacher-option');
    teacherOption.classList.add('selected');
    
    // Get teacher data to check for batching requirements
    const courseCode = document.getElementById('courseCode').textContent;
    const teacher = courses[courseCode].teachers[teacherId];
    
    // Show instance selection if available
    const instanceSelection = optionContainer.querySelector('.instance-selection');
    if (instanceSelection) {
        instanceSelection.style.display = 'block';
        
        // Debug: Check if instances have batch options
        console.log('Instance selection shown, checking for batch options...');
        Object.values(teacher.courseInstances).forEach(instance => {
            console.log(`Instance ${instance.instanceId}: isBatched=${instance.isBatched}, batches=`, Object.keys(instance.batches || {}));
        });
        
        // Add event listeners to instance radio buttons to show batch selection
        instanceSelection.querySelectorAll('input[type="radio"]').forEach(radio => {
            radio.addEventListener('change', function() {
                console.log('Instance radio changed:', this.value);
                
                // Hide all batch selections first
                instanceSelection.querySelectorAll('.batch-selection').forEach(bs => {
                    bs.style.display = 'none';
                });
                
                // Show batch selection for this instance if it exists
                if (this.checked) {
                    const instanceOption = this.closest('.instance-option');
                    const batchSelection = instanceOption.querySelector('.batch-selection');
                    if (batchSelection) {
                        console.log('Showing batch selection for instance:', this.value);
                        batchSelection.style.display = 'block';
                        
                        // Enable confirm button only when batch is selected
                        document.getElementById('confirmSelection').disabled = true;
                        batchSelection.querySelectorAll('input[type="radio"]').forEach(batchRadio => {
                            batchRadio.addEventListener('change', function() {
                                if (this.checked) {
                                    console.log('Batch selected:', this.value);
                                    document.getElementById('confirmSelection').disabled = false;
                                }
                            });
                        });
                    } else {
                        console.log('No batch selection found for instance:', this.value);
                        document.getElementById('confirmSelection').disabled = false;
                    }
                }
            });
        });
    }
    
    // Show batch selection for single-instance batched courses
    const batchSelection = optionContainer.querySelector('.batch-selection');
    if (batchSelection && !instanceSelection) {
        batchSelection.style.display = 'block';
    }
    
    // Store selected teacher info
    parentContainer.dataset.selectedTeacher = teacherId;
    
    // Check if we need to wait for batch selection
    const needsBatchSelection = batchSelection !== null;
    const hasMultipleInstances = instanceSelection !== null;
    
    // Check if this teacher has batched instances that require selection
    let requiresBatchSelection = false;
    if (!hasMultipleInstances) {
        // Single instance - check if it's batched
        const singleInstance = Object.values(teacher.courseInstances)[0];
        if (singleInstance && singleInstance.isBatched && Object.keys(singleInstance.batches).length > 0) {
            requiresBatchSelection = true;
        }
    }
    
    if (!hasMultipleInstances && !requiresBatchSelection) {
        // Single instance, no batches - can confirm immediately
        document.getElementById('confirmSelection').disabled = false;
    } else if (!hasMultipleInstances && requiresBatchSelection) {
        // Single instance with batches - wait for batch selection
        document.getElementById('confirmSelection').disabled = true;
        
        // Listen for batch selection
        if (batchSelection) {
            batchSelection.querySelectorAll('input[type="radio"]').forEach(radio => {
                radio.addEventListener('change', function() {
                    if (this.checked) {
                        document.getElementById('confirmSelection').disabled = false;
                    }
                });
            });
        }
    } else {
        // Multiple instances - wait for instance selection
        document.getElementById('confirmSelection').disabled = true;
        
        // Listen for instance selection
        instanceSelection.querySelectorAll('input[type="radio"]').forEach(radio => {
            radio.addEventListener('change', function() {
                if (this.checked) {
                    // Check if the selected instance is batched
                    const selectedInstanceId = this.value;
                    const selectedInstance = teacher.courseInstances[selectedInstanceId];
                    
                    if (selectedInstance && selectedInstance.isBatched && Object.keys(selectedInstance.batches).length > 0) {
                        // Instance is batched - still need batch selection
                        document.getElementById('confirmSelection').disabled = true;
                    } else {
                        // Instance is not batched - can confirm
                        document.getElementById('confirmSelection').disabled = false;
                    }
                }
            });
        });
    }
}

// Confirm teacher selection with instance handling
function confirmTeacherSelection() {
    const modal = document.getElementById('courseModal');
    const teacherOptions = document.getElementById('teacherOptions');
    const selectedTeacherId = teacherOptions.dataset.selectedTeacher;
    const courseCode = document.getElementById('courseCode').textContent;
    
    if (!selectedTeacherId) return;
    
    const teacher = courses[courseCode].teachers[selectedTeacherId];
    
    // Check if teacher has multiple instances and get selected instance
    let selectedInstanceId = null;
    const instanceRadios = teacherOptions.querySelectorAll(`input[name="instance_${selectedTeacherId}"]:checked`);
    if (instanceRadios.length > 0) {
        selectedInstanceId = instanceRadios[0].value;
    } else {
        // Check if single instance
        const instanceIds = Object.keys(teacher.courseInstances);
        if (instanceIds.length === 1) {
            selectedInstanceId = instanceIds[0];
        }
    }
    
    // Get selected batches for the selected instance
    const selectedBatches = {};
    if (selectedInstanceId) {
        const batchInputs = teacherOptions.querySelectorAll(`input[name="batch_${selectedTeacherId}_${selectedInstanceId}"]:checked`);
        
        // Debug: Check batch inputs
        console.log('Looking for batch inputs with name:', `batch_${selectedTeacherId}_${selectedInstanceId}`);
        console.log('Found batch inputs:', batchInputs.length);
        console.log('All batch inputs in modal:', teacherOptions.querySelectorAll('input[type="radio"]'));
        
        batchInputs.forEach(input => {
            const batchNumber = input.value;
            if (!selectedBatches[selectedInstanceId]) {
                selectedBatches[selectedInstanceId] = [];
            }
            selectedBatches[selectedInstanceId].push(batchNumber);
        });
    }
    
    // Collect slots for the selected instance(s)
    let allSlots = [];
    
    if (selectedInstanceId) {
        // Single instance selected
        const selectedInstance = teacher.courseInstances[selectedInstanceId];
        if (selectedInstance) {
            if (selectedInstance.isBatched) {
                // For batched instances, include selected batch slots AND non-batched slots
                if (selectedBatches[selectedInstanceId] && selectedBatches[selectedInstanceId].length > 0) {
                    // Add selected batch slots
                    selectedBatches[selectedInstanceId].forEach(batchNumber => {
                        if (selectedInstance.batches[batchNumber]) {
                            allSlots = allSlots.concat(selectedInstance.batches[batchNumber].slots);
                        }
                    });
                    
                    // Also add non-batched slots from the same instance (like lectures)
                    selectedInstance.slots.forEach(slot => {
                        if (!slot.isBatched) {
                            allSlots.push(slot);
                        }
                    });
                } else {
                    // No batch selected for batched instance - this shouldn't happen if UI is working correctly
                    alert('Please select a batch for this lab course.');
                    return;
                }
            } else {
                // Non-batched instance - use all slots
                allSlots = selectedInstance.slots;
            }
        }
    } else {
        // Single instance (no selection needed) or fallback to all slots
        const instanceIds = Object.keys(teacher.courseInstances);
        if (instanceIds.length === 1) {
            const singleInstance = teacher.courseInstances[instanceIds[0]];
            if (singleInstance.isBatched) {
                // For single batched instance, require batch selection
                const singleInstanceId = instanceIds[0];
                const batchInputs = teacherOptions.querySelectorAll(`input[name="batch_${selectedTeacherId}_${singleInstanceId}"]:checked`);
                if (batchInputs.length > 0) {
                    const selectedBatchNumber = batchInputs[0].value;
                    if (singleInstance.batches[selectedBatchNumber]) {
                        allSlots = singleInstance.batches[selectedBatchNumber].slots;
                        
                        // Also add non-batched slots from the same instance (like lectures)
                        singleInstance.slots.forEach(slot => {
                            if (!slot.isBatched) {
                                allSlots.push(slot);
                            }
                        });
                    }
                } else {
                    alert('Please select a batch for this lab course.');
                    return;
                }
            } else {
                allSlots = singleInstance.slots;
            }
        } else {
            allSlots = teacher.slots; // Fallback
        }
    }
    
    // Check for conflicts
    const conflicts = checkScheduleConflicts(courseCode, selectedTeacherId, allSlots);
    
    if (conflicts.length > 0) {
        closeModal();
        showConflictModal(courseCode, selectedTeacherId, conflicts);
        return;
    }
    
    // Create course data with selected teacher and instance
    const courseData = {
        course: courses[courseCode],
        teacher: {
            ...teacher,
            slots: allSlots,
            selectedInstanceId: selectedInstanceId,
            selectedBatches: selectedBatches
        }
    };
    
    // Debug: Log what we're saving
    console.log('Saving course data for', courseCode, ':', {
        teacherId: selectedTeacherId,
        selectedInstanceId: selectedInstanceId,
        selectedBatches: selectedBatches,
        allSlotsCount: allSlots.length,
        allSlots: allSlots.map(slot => `${slot.day} ${slot.timeInterval} ${slot.batchInfo || 'No batch'}`)
    });
    
    // Add to selected courses
    selectedCourses[courseCode] = courseData;
    
    // Update UI
    updateCourseCard(courseCode);
    updateGenerateButton();
    updateTimetable();
    closeModal();
    
    // Create notification message with batch information
    let notificationMessage = `Selected ${teacher.name}`;
    if (selectedInstanceId) {
        notificationMessage += ` (Instance ${selectedInstanceId})`;
    }
    
    // Add batch information if applicable
    if (selectedBatches[selectedInstanceId] && selectedBatches[selectedInstanceId].length > 0) {
        const batchNumbers = selectedBatches[selectedInstanceId];
        notificationMessage += ` - ${batchNumbers.map(num => `Batch ${num}`).join(', ')}`;
    }
    
    notificationMessage += ` for ${courses[courseCode].name}`;
    
    showNotification(notificationMessage, 'success');
}

// Check for schedule conflicts
function checkScheduleConflicts(newCourseCode, newTeacherId, newSlots) {
    const conflicts = [];
    
    // Check against already selected courses
    Object.entries(selectedCourses).forEach(([selectedCourseCode, selectedCourseData]) => {
        if (selectedCourseCode === newCourseCode) return;
        
        const selectedSlots = selectedCourseData.teacher.slots;
        
        newSlots.forEach(newSlot => {
            selectedSlots.forEach(selectedSlot => {
                if (newSlot.day === selectedSlot.day && newSlot.slotIndex === selectedSlot.slotIndex) {
                    conflicts.push({
                        newCourse: newCourseCode,
                        existingCourse: selectedCourseCode,
                        day: newSlot.day,
                        time: newSlot.timeInterval,
                        slotIndex: newSlot.slotIndex
                    });
                }
            });
        });
    });
    
    return conflicts;
}

// Show conflict modal
function showConflictModal(courseCode, teacherId, conflicts) {
    const modal = document.getElementById('conflictModal');
    const conflictDetails = document.getElementById('conflictDetails');
    const alternativeOptions = document.getElementById('alternativeOptions');
    
    // Show conflict details
    conflictDetails.innerHTML = `
        <h4>Conflicts detected:</h4>
        ${conflicts.map(conflict => `
            <div>
                <strong>${conflict.newCourse}</strong> conflicts with <strong>${conflict.existingCourse}</strong><br>
                Time: ${conflict.day} at ${conflict.time}
            </div>
        `).join('<br>')}
    `;
    
    // Show alternative teachers
    alternativeOptions.innerHTML = '';
    const course = courses[courseCode];
    
    Object.values(course.teachers).forEach(teacher => {
        if (teacher.id === teacherId) return; // Skip the conflicting teacher
        
        const alternativeConflicts = checkScheduleConflicts(courseCode, teacher.id, course.teachers[teacher.id].slots);
        if (alternativeConflicts.length === 0) {
            const option = createAlternativeTeacherOption(teacher, courseCode);
            alternativeOptions.appendChild(option);
        }
    });
    
    if (alternativeOptions.children.length === 0) {
        alternativeOptions.innerHTML = '<p>No alternative teachers available without conflicts.</p>';
    }
    
    modal.style.display = 'block';
    modal.dataset.courseCode = courseCode;
    modal.dataset.originalTeacherId = teacherId;
}

// Create alternative teacher option
function createAlternativeTeacherOption(teacher, courseCode) {
    const option = document.createElement('div');
    option.className = 'teacher-option';
    option.dataset.teacherId = teacher.id;
    
    option.innerHTML = `
        <div class="teacher-name">${teacher.name}</div>
        <div class="teacher-code">Staff Code: ${teacher.staffCode}</div>
    `;
    
    option.addEventListener('click', () => selectAlternativeTeacher(option, teacher.id));
    
    return option;
}

// Select alternative teacher
function selectAlternativeTeacher(optionElement, teacherId) {
    // Remove previous selection
    optionElement.parentNode.querySelectorAll('.teacher-option').forEach(opt => {
        opt.classList.remove('selected');
    });
    
    // Select current option
    optionElement.classList.add('selected');
    optionElement.parentNode.dataset.selectedAlternative = teacherId;
    
    // Enable resolve button
    document.getElementById('resolveConflict').disabled = false;
}

// Resolve conflict with alternative teacher
function resolveConflict() {
    const modal = document.getElementById('conflictModal');
    const courseCode = modal.dataset.courseCode;
    const teacherId = document.getElementById('alternativeOptions').dataset.selectedAlternative;
    
    if (!teacherId) return;
    
    const course = courses[courseCode];
    const teacher = course.teachers[teacherId];
    
    selectedCourses[courseCode] = {
        course: course,
        teacher: teacher
    };
    
    closeConflictModal();
    closeModal();
    updateCourseCard(courseCode);
    updateGenerateButton();
    updateTimetable();
}

// Update course card after selection
function updateCourseCard(courseCode) {
    const card = document.querySelector(`[data-course-code="${courseCode}"]`);
    if (card) {
        card.classList.add('selected');
        
        // Update card content
        const teacherDiv = card.querySelector('.course-teacher') || document.createElement('div');
        teacherDiv.className = 'course-teacher';
        teacherDiv.innerHTML = `<strong>Selected:</strong> ${selectedCourses[courseCode].teacher.name}`;
        
        if (!card.querySelector('.course-teacher')) {
            card.appendChild(teacherDiv);
        }
    }
}

// Update generate button state
function updateGenerateButton() {
    const button = document.getElementById('generateTimetable');
    const hasSelections = Object.keys(selectedCourses).length > 0;
    button.disabled = !hasSelections;
}

// Initialize timetable structure - matching visualizer grid
function initializeTimetable() {
    const tbody = document.getElementById('timetableBody');
    tbody.innerHTML = '';
    
    // Create comprehensive time grid covering all possible slots
    const timeSlots = [
        { label: '8:00 AM', slot: 0 },
        { label: '9:00 AM', slot: 1 },
        { label: '10:00 AM', slot: 2 },
        { label: '11:00 AM', slot: 3 },
        { label: '12:00 PM', slot: 4 },
        { label: '1:00 PM', slot: 5 },
        { label: '2:00 PM', slot: 6 },
        { label: '3:00 PM', slot: 7 },
        { label: '4:00 PM', slot: 8 },
        { label: '5:00 PM', slot: 9 },
        { label: '6:00 PM', slot: 10 },
        { label: '7:00 PM', slot: 11 }
    ];
    
    timeSlots.forEach(timeSlot => {
        const row = document.createElement('tr');
        const timeCell = document.createElement('td');
        timeCell.textContent = timeSlot.label;
        timeCell.className = 'time-slot';
        row.appendChild(timeCell);
        
        // Add cells for each day
        for (let day = 1; day <= 6; day++) {
            const cell = document.createElement('td');
            cell.className = 'timetable-cell';
            cell.dataset.day = day;
            cell.dataset.slot = timeSlot.slot;
            
            // Get macroblock for this day and slot
            const macroblock = MACROBLOCK_PATTERNS[day] && MACROBLOCK_PATTERNS[day][timeSlot.slot] 
                ? MACROBLOCK_PATTERNS[day][timeSlot.slot] 
                : '--';
            
            cell.innerHTML = `<div class="empty-slot">${macroblock}<br><span class="free-text">Free</span></div>`;
            row.appendChild(cell);
        }
        
        tbody.appendChild(row);
    });
}

// Generate and display timetable - matching visualizer approach
function generateTimetable() {
    clearTimetable();
    
    // Create a grid structure like in the visualizers
    const timetableGrid = {};
    
    // Process all selected courses and their instances
    Object.values(selectedCourses).forEach(courseData => {
        const courseCode = courseData.course.code;
        const teacher = courseData.teacher;
        
        // Debug: Log what we're processing
        console.log('Generating timetable for', courseCode, ':', {
            teacherId: teacher.id,
            slotsCount: teacher.slots.length,
            slots: teacher.slots.map(slot => `${slot.day} ${slot.timeInterval} ${slot.batchInfo || 'No batch'}`)
        });
        
        // Use the filtered slots that were set during confirmation, not all teacher slots
        const slotsToProcess = teacher.slots;
        
        slotsToProcess.forEach(slot => {
            const dayNumber = DAYS[slot.day.toLowerCase()];
            const slotIndex = slot.slotIndex;
            
            if (dayNumber && TIME_SLOTS[slotIndex]) {
                // Map lab slots to regular time slots for display
                let displaySlot = slotIndex;
                if (slotIndex >= 20 && slotIndex <= 31) {
                    // Map lab slots to their corresponding time slots
                    const labToRegularMapping = {
                        20: 0, 21: 1,   // 8:00-9:40 maps to 8:00 and 9:00 slots
                        22: 2, 23: 3,   // 9:50-11:30 maps to 10:00 and 11:00 slots  
                        24: 4, 25: 5,   // 11:50-1:30 maps to 12:00 and 1:00 slots
                        26: 6, 27: 7,   // 1:50-3:30 maps to 2:00 and 3:00 slots
                        28: 8, 29: 9,   // 3:50-5:30 maps to 4:00 and 5:00 slots
                        30: 10, 31: 11  // 5:30-7:10 maps to 6:00 and 7:00 slots
                    };
                    displaySlot = labToRegularMapping[slotIndex] || slotIndex;
                }
                
                const gridKey = `${dayNumber}-${displaySlot}`;
                
                if (!timetableGrid[gridKey]) {
                    timetableGrid[gridKey] = [];
                }
                
                // Add course instance with detailed information
                const courseInstance = {
                    courseCode: courseCode,
                    courseName: courseData.course.name,
                    teacherName: teacher.name,
                    teacherId: teacher.id,
                    slotType: slot.slotType,
                    roomNumber: slot.roomNumber,
                    batchInfo: slot.batchInfo,
                    isBatched: slot.isBatched,
                    courseInstanceId: slot.courseInstanceId,
                    studentCount: slot.studentCount,
                    originalSlotIndex: slotIndex,
                    timeInterval: TIME_SLOTS[slotIndex],
                    macroblock: slot.macroblock
                };
                
                // Check if this instance is already added (avoid duplicates)
                const existingInstance = timetableGrid[gridKey].find(instance => 
                    instance.courseCode === courseCode && 
                    instance.teacherId === teacher.id &&
                    instance.courseInstanceId === slot.courseInstanceId
                );
                
                if (!existingInstance) {
                    timetableGrid[gridKey].push(courseInstance);
                }
            }
        });
    });
    
    // Populate the timetable with the grid data
    Object.entries(timetableGrid).forEach(([gridKey, instances]) => {
        const [dayNumber, slotIndex] = gridKey.split('-');
        const cell = document.querySelector(`[data-day="${dayNumber}"][data-slot="${slotIndex}"]`);
        
        if (cell && instances.length > 0) {
            cell.innerHTML = ''; // Clear the cell
            
            instances.forEach((instance, index) => {
                const slotElement = createSlotElement(instance, index);
                cell.appendChild(slotElement);
            });
        }
    });
    
    // Show success message
    showNotification('Timetable generated successfully!', 'success');
}

// Create slot element with comprehensive information like visualizers
function createSlotElement(instance, index) {
    const slotElement = document.createElement('div');
    slotElement.className = `class-slot ${instance.slotType.toLowerCase()}`;
    
    // Add multiple instance indicator if needed
    if (index > 0) {
        slotElement.style.marginTop = '2px';
        slotElement.style.borderTop = '1px solid rgba(255,255,255,0.3)';
    }
    
    // Build comprehensive slot content like in visualizers
    let slotContent = `
        <div class="slot-header">
            <span class="slot-code">${instance.courseCode}</span>
            <span class="slot-type">${instance.slotType}</span>
        </div>
        <div class="slot-teacher">${instance.teacherName}</div>
        <div class="slot-room">${instance.roomNumber}</div>
        <div class="slot-macroblock">Block: ${instance.macroblock || 'N/A'}</div>
    `;
    
    // Add batch information for lab sessions
    if (instance.isBatched && instance.batchInfo) {
        slotContent += `<div class="slot-batch">${instance.batchInfo}</div>`;
    }
    
    // Add course instance information
    if (instance.courseInstanceId) {
        slotContent += `<div class="slot-instance">Instance: ${instance.courseInstanceId}</div>`;
    }
    
    // Add student count for labs
    if (instance.slotType.toLowerCase() === 'practical' && instance.studentCount) {
        slotContent += `<div class="slot-students">Students: ${instance.studentCount}</div>`;
    }
    
    // Add original time if different from display time
    if (instance.originalSlotIndex >= 20) {
        slotContent += `<div class="slot-time">${instance.timeInterval}</div>`;
    }
    
    slotElement.innerHTML = slotContent;
    
    // Add click handler for detailed information
    slotElement.addEventListener('click', () => showSlotDetails(instance));
    
    return slotElement;
}

// Clear timetable
function clearTimetable() {
    const cells = document.querySelectorAll('.timetable-cell');
    cells.forEach(cell => {
        const day = parseInt(cell.dataset.day);
        const slot = parseInt(cell.dataset.slot);
        
        // Get macroblock for this day and slot
        const macroblock = MACROBLOCK_PATTERNS[day] && MACROBLOCK_PATTERNS[day][slot] 
            ? MACROBLOCK_PATTERNS[day][slot] 
            : '--';
        
        cell.innerHTML = `<div class="empty-slot">${macroblock}<br><span class="free-text">Free</span></div>`;
    });
}

// Show slot details with comprehensive information like visualizers
function showSlotDetails(instance) {
    const details = [
        `Course: ${instance.courseName} (${instance.courseCode})`,
        `Teacher: ${instance.teacherName} (ID: ${instance.teacherId})`,
        `Type: ${instance.slotType}`,
        `Time: ${instance.timeInterval}`,
        `Room: ${instance.roomNumber}`
    ];
    
    if (instance.courseInstanceId) {
        details.push(`Course Instance: ${instance.courseInstanceId}`);
    }
    
    if (instance.isBatched && instance.batchInfo) {
        details.push(`Batch: ${instance.batchInfo}`);
    }
    
    if (instance.studentCount) {
        details.push(`Students: ${instance.studentCount}`);
    }
    
    if (instance.originalSlotIndex >= 20) {
        details.push(`Lab Session: Slot ${instance.originalSlotIndex}`);
    }
    
    alert(details.join('\n'));
}

// Clear all selections
function clearAllSelections() {
    if (Object.keys(selectedCourses).length === 0) return;
    
    if (confirm('Are you sure you want to clear all course selections?')) {
        selectedCourses = {};
        renderCourseSelection();
        updateGenerateButton();
        clearTimetable();
        showNotification('All selections cleared!', 'info');
    }
}

// Close modals
function closeModal() {
    document.getElementById('courseModal').style.display = 'none';
    document.getElementById('confirmSelection').disabled = true;
}

function closeConflictModal() {
    document.getElementById('conflictModal').style.display = 'none';
    document.getElementById('resolveConflict').disabled = true;
}

// Show/hide loading spinner
function showLoadingSpinner() {
    document.getElementById('loadingSpinner').style.display = 'flex';
}

function hideLoadingSpinner() {
    document.getElementById('loadingSpinner').style.display = 'none';
}

// Show notification
function showNotification(message, type = 'info') {
    // Remove existing notifications
    const existingNotifications = document.querySelectorAll('.notification');
    existingNotifications.forEach(notif => notif.remove());
    
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    // Remove after 3 seconds
    setTimeout(() => {
        if (notification.parentNode) {
            notification.remove();
        }
    }, 3000);
}

// Update timetable when courses are selected/deselected
function updateTimetable() {
    if (Object.keys(selectedCourses).length > 0) {
        generateTimetable();
    } else {
        clearTimetable();
    }
}

// Add CSS animations for notifications
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInRight {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOutRight {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style); 