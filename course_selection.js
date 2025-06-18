// Global variables
let courseData = [];
let selectedCourses = new Map(); // Map: groupKey -> courseInstance
let groupedCourses = {};
let currentFilters = {
    department: '',
    semester: '',
    search: ''
};

// Load and process course data
async function loadCourseData() {
    try {
        // Get the latest folder path from the server
        const folderResponse = await fetch('/api/latest-folder');
        const folderData = await folderResponse.json();
        
        if (folderData.error) {
            throw new Error(folderData.error);
        }
        
        const latestFolder = folderData.latestFolder;
        console.log('Course selection using latest schedule folder:', latestFolder);
        
        // Load theory data (contains course information)
        const theoryResponse = await fetch(`${latestFolder}/combined_theory_schedule.json`);
        const theoryData = await theoryResponse.json();
        
        // Process and group courses
        processCourseData(theoryData);
        populateFilterOptions();
        renderCourseSelection();
        
    } catch (error) {
        console.error('Error loading course data:', error);
        document.getElementById('courseContainer').innerHTML = `
            <div class="alert alert-danger text-center">
                <i class="fas fa-exclamation-triangle me-2"></i>
                Error loading course data. Please ensure the data files are available.
                <br><small>Error: ${error.message}</small>
            </div>
        `;
    }
}

// Process course data and group by department, semester, and group
function processCourseData(theoryData) {
    // Group courses by department -> semester -> group -> courses
    groupedCourses = {};
    
    theoryData.forEach(course => {
        const dept = course.department;
        const semester = course.semester;
        const groupName = course.group_name;
        
        if (!dept || !semester || !groupName) return;
        
        // Create nested structure
        if (!groupedCourses[dept]) {
            groupedCourses[dept] = {};
        }
        if (!groupedCourses[dept][semester]) {
            groupedCourses[dept][semester] = {};
        }
        if (!groupedCourses[dept][semester][groupName]) {
            groupedCourses[dept][semester][groupName] = [];
        }
        
        // Add course if not already present (avoid duplicates)
        const existingCourse = groupedCourses[dept][semester][groupName].find(
            c => c.course_instance_id === course.course_instance_id
        );
        
        if (!existingCourse) {
            groupedCourses[dept][semester][groupName].push(course);
        }
    });
    
    console.log('Grouped courses:', groupedCourses);
    console.log('Available departments:', Object.keys(groupedCourses));
    console.log('Available semesters:', [...new Set(Object.values(groupedCourses).flatMap(deptData => Object.keys(deptData)))]);
    
    // Debug: Log some sample course data to verify structure
    Object.keys(groupedCourses).slice(0, 2).forEach(dept => {
        console.log(`Sample dept: "${dept}"`);
        Object.keys(groupedCourses[dept]).slice(0, 2).forEach(sem => {
            console.log(`  Sample semester: "${sem}"`);
            Object.keys(groupedCourses[dept][sem]).slice(0, 1).forEach(group => {
                console.log(`    Sample group: "${group}", courses: ${groupedCourses[dept][sem][group].length}`);
            });
        });
    });
}

// Populate filter dropdown options
function populateFilterOptions() {
    const departmentFilter = document.getElementById('departmentFilter');
    const semesterFilter = document.getElementById('semesterFilter');
    
    // Clear existing options (keep the "All" option)
    departmentFilter.innerHTML = '<option value="">All Departments</option>';
    semesterFilter.innerHTML = '<option value="">All Semesters</option>';
    
    // Get unique departments and semesters
    const departments = [...new Set(Object.keys(groupedCourses))].sort();
    const semesters = [...new Set(
        Object.values(groupedCourses)
            .flatMap(deptData => Object.keys(deptData))
    )].sort((a, b) => parseInt(a) - parseInt(b));
    
    // Populate department options
    console.log('Populating department filter with:', departments);
    departments.forEach(dept => {
        const option = document.createElement('option');
        option.value = dept;
        option.textContent = dept;
        departmentFilter.appendChild(option);
    });
    
    // Populate semester options
    console.log('Populating semester filter with:', semesters);
    semesters.forEach(semester => {
        const option = document.createElement('option');
        option.value = semester;
        option.textContent = `Semester ${semester}`;
        semesterFilter.appendChild(option);
    });
}

// Apply filters to course display
function applyFilters() {
    console.log('Applying filters:', currentFilters);
    
    // First, get total counts before filtering
    const allCourseOptions = document.querySelectorAll('.course-option');
    const totalCourses = allCourseOptions.length;
    console.log('Total courses found:', totalCourses);
    
    let visibleDepts = 0;
    let visibleSemesters = 0;
    let visibleCourses = 0;
    
    // Reset all visibility first
    document.querySelectorAll('.dept-card, .semester-section, .group-section, .course-option').forEach(element => {
        element.classList.remove('hidden');
    });
    
    const departmentCards = document.querySelectorAll('.dept-card');
    
    departmentCards.forEach(deptCard => {
        const deptNameElement = deptCard.querySelector('.dept-header h4');
        // Extract department name - the HTML structure is: <i class="fas fa-building me-2"></i>${dept}
        // So we need to remove the icon (FontAwesome icon doesn't create text content)
        let deptName = deptNameElement ? deptNameElement.textContent.trim() : '';
        
        const shouldShowDept = !currentFilters.department || deptName === currentFilters.department;
        
        console.log(`Checking department: "${deptName}", filter: "${currentFilters.department}", shouldShow: ${shouldShowDept}`);
        
        if (!shouldShowDept) {
            deptCard.classList.add('hidden');
            return;
        }
        
        let deptHasVisibleContent = false;
        const semesterSections = deptCard.querySelectorAll('.semester-section');
        
        semesterSections.forEach(semesterSection => {
            const semesterTitleElement = semesterSection.querySelector('.semester-title');
            const semesterTitle = semesterTitleElement ? semesterTitleElement.textContent : '';
            const semesterNumber = semesterTitle.match(/Semester (\w+)/)?.[1];
            const shouldShowSemester = !currentFilters.semester || semesterNumber === currentFilters.semester;
            
            console.log(`Checking semester: "${semesterTitle}", number: "${semesterNumber}", filter: "${currentFilters.semester}", shouldShow: ${shouldShowSemester}`);
            
            if (!shouldShowSemester) {
                semesterSection.classList.add('hidden');
                return;
            }
            
            let semesterHasVisibleContent = false;
            const groupSections = semesterSection.querySelectorAll('.group-section');
            
            groupSections.forEach(groupSection => {
                let groupHasVisibleContent = false;
                const courseOptions = groupSection.querySelectorAll('.course-option');
                
                courseOptions.forEach(courseOption => {
                    const courseCode = courseOption.querySelector('.course-code')?.textContent.toLowerCase() || '';
                    const courseName = courseOption.querySelector('.course-name')?.textContent.toLowerCase() || '';
                    const teacherName = courseOption.querySelector('.teacher-name')?.textContent.toLowerCase() || '';
                    
                    const searchTerm = currentFilters.search.toLowerCase();
                    const matchesSearch = !searchTerm || 
                        courseCode.includes(searchTerm) || 
                        courseName.includes(searchTerm) || 
                        teacherName.includes(searchTerm);
                    
                    if (matchesSearch) {
                        courseOption.classList.remove('hidden');
                        groupHasVisibleContent = true;
                        visibleCourses++;
                    } else {
                        courseOption.classList.add('hidden');
                    }
                });
                
                if (groupHasVisibleContent) {
                    groupSection.classList.remove('hidden');
                    semesterHasVisibleContent = true;
                } else {
                    groupSection.classList.add('hidden');
                }
            });
            
            if (semesterHasVisibleContent) {
                semesterSection.classList.remove('hidden');
                deptHasVisibleContent = true;
                visibleSemesters++;
            } else {
                semesterSection.classList.add('hidden');
            }
        });
        
        if (deptHasVisibleContent) {
            deptCard.classList.remove('hidden');
            visibleDepts++;
        } else {
            deptCard.classList.add('hidden');
        }
    });
    
    // Update filter status
    updateFilterStatus(visibleDepts, visibleSemesters, visibleCourses, totalCourses);
}

// Update filter status message
function updateFilterStatus(visibleDepts, visibleSemesters, visibleCourses, totalCourses) {
    const filterStatus = document.getElementById('filterStatus');
    
    if (!currentFilters.department && !currentFilters.semester && !currentFilters.search) {
        filterStatus.textContent = `Showing all courses (${totalCourses} total)`;
        filterStatus.className = 'ms-3 text-muted';
    } else {
        const statusParts = [];
        if (currentFilters.department) statusParts.push(`Department: ${currentFilters.department}`);
        if (currentFilters.semester) statusParts.push(`Semester: ${currentFilters.semester}`);
        if (currentFilters.search) statusParts.push(`Search: "${currentFilters.search}"`);
        
        filterStatus.textContent = `Filtered: ${visibleCourses}/${totalCourses} courses (${statusParts.join(', ')})`;
        filterStatus.className = 'ms-3 text-primary';
    }
}

// Clear all filters
function clearAllFilters() {
    currentFilters = {
        department: '',
        semester: '',
        search: ''
    };
    
    document.getElementById('departmentFilter').value = '';
    document.getElementById('semesterFilter').value = '';
    document.getElementById('courseSearch').value = '';
    
    // Remove all hidden classes
    document.querySelectorAll('.hidden').forEach(element => {
        element.classList.remove('hidden');
    });
    
    updateFilterStatus(
        document.querySelectorAll('.dept-card').length,
        document.querySelectorAll('.semester-section').length,
        document.querySelectorAll('.course-option').length,
        document.querySelectorAll('.course-option').length
    );
}

// Render course selection interface
function renderCourseSelection() {
    const container = document.getElementById('courseContainer');
    let html = '';
    
    // Sort departments
    const departments = Object.keys(groupedCourses).sort();
    
    departments.forEach(dept => {
        html += `
            <div class="card dept-card">
                <div class="dept-header">
                    <h4 class="mb-0">
                        <i class="fas fa-building me-2"></i>
                        ${dept}
                    </h4>
                </div>
                <div class="card-body p-0">
        `;
        
        // Sort semesters
        const semesters = Object.keys(groupedCourses[dept]).sort((a, b) => parseInt(a) - parseInt(b));
        
        semesters.forEach((semester, semIndex) => {
            html += `
                <div class="semester-section">
                    <h5 class="semester-title">
                        <i class="fas fa-graduation-cap me-2"></i>
                        Semester ${semester}
                    </h5>
            `;
            
            // Sort groups
            const groups = Object.keys(groupedCourses[dept][semester]).sort();
            
            groups.forEach(groupName => {
                const courses = groupedCourses[dept][semester][groupName];
                const groupKey = `${dept}_${semester}_${groupName}`;
                
                html += `
                    <div class="group-section" data-group-key="${groupKey}">
                        <div class="group-title">
                            <i class="fas fa-users"></i>
                            <span>${groupName.replace(/_/g, ' ')}</span>
                            <span class="group-stats">${courses.length} course${courses.length > 1 ? 's' : ''}</span>
                        </div>
                `;
                
                // Render courses in this group
                courses.forEach((course, courseIndex) => {
                    const courseId = `course_${groupKey}_${courseIndex}`;
                    const isSelected = selectedCourses.has(groupKey) && 
                                     selectedCourses.get(groupKey).course_instance_id === course.course_instance_id;
                    
                    html += `
                        <div class="course-option ${isSelected ? 'selected' : ''}" data-course-id="${courseId}">
                            <label class="w-100 mb-0" style="cursor: pointer;">
                                <input type="radio" 
                                       name="group_${groupKey}" 
                                       value="${course.course_instance_id}"
                                       data-group-key="${groupKey}"
                                       data-course-data='${JSON.stringify(course)}'
                                       ${isSelected ? 'checked' : ''}
                                       onchange="handleCourseSelection(this)">
                                
                                <div class="course-details">
                                    <div class="course-info">
                                        <div class="course-code">${course.course_code}</div>
                                        <div class="course-name">${course.course_name}</div>
                                        <div class="course-meta">
                                            <span><i class="fas fa-clock me-1"></i>
                                                ${course.lecture_hours || 0}L + ${course.tutorial_hours || 0}T
                                            </span>
                                            <span><i class="fas fa-users me-1"></i>
                                                ${course.student_count} students
                                            </span>
                                        </div>
                                    </div>
                                    <div class="teacher-info">
                                        <div class="teacher-name">${course.teacher_name}</div>
                                        <div class="staff-code">${course.staff_code}</div>
                                    </div>
                                </div>
                            </label>
                        </div>
                    `;
                });
                
                html += `</div>`; // Close group-section
            });
            
            html += `</div>`; // Close semester-section
        });
        
        html += `
                </div>
            </div>
        `; // Close card
    });
    
    container.innerHTML = html;
    updateSelectionSummary();
    
    // Restore course-taken states for any previously selected courses
    setTimeout(() => {
        restoreCourseStates();
        
        updateFilterStatus(
            document.querySelectorAll('.dept-card').length,
            document.querySelectorAll('.semester-section').length,
            document.querySelectorAll('.course-option').length,
            document.querySelectorAll('.course-option').length
        );
    }, 100);
}

// Handle course selection with group constraints
function handleCourseSelection(radioInput) {
    const groupKey = radioInput.dataset.groupKey;
    const courseData = JSON.parse(radioInput.dataset.courseData);
    
    if (radioInput.checked) {
        // Check if this course CODE is already selected anywhere (regardless of teacher/instance)
        const existingSelection = Array.from(selectedCourses.values()).find(
            selected => selected.course_code === courseData.course_code
        );
        
        if (existingSelection && !selectedCourses.has(groupKey)) {
            // Prevent selection - course code already selected elsewhere
            radioInput.checked = false;
            alert(`Course "${courseData.course_code}" is already selected with teacher "${existingSelection.teacher_name}". You cannot select the same course with a different teacher.`);
            return;
        }
        
        // Add selection
        selectedCourses.set(groupKey, courseData);
        
        // Update visual state for this group and disable all other instances of this course
        updateGroupVisualState(groupKey);
        disableAllInstancesOfCourse(courseData.course_code, groupKey);
        updateSelectionSummary();
        
        console.log(`Selected course: ${courseData.course_code} in group: ${groupKey}`);
    } else {
        // Handle deselection
        if (selectedCourses.has(groupKey)) {
            const deselectedCourse = selectedCourses.get(groupKey);
            selectedCourses.delete(groupKey);
            
            // Re-enable all instances of this course since it's no longer selected
            enableAllInstancesOfCourse(deselectedCourse.course_code);
            resetGroupVisualState(groupKey);
            updateSelectionSummary();
        }
    }
}

// Update visual state for a group after selection
function updateGroupVisualState(groupKey) {
    const groupSection = document.querySelector(`[data-group-key="${groupKey}"]`);
    if (!groupSection) return;
    
    const courseOptions = groupSection.querySelectorAll('.course-option');
    const selectedRadio = groupSection.querySelector('input[type="radio"]:checked');
    
    courseOptions.forEach(option => {
        const radio = option.querySelector('input[type="radio"]');
        
        if (radio === selectedRadio) {
            // Selected course
            option.classList.add('selected');
            option.classList.remove('disabled');
        } else {
            // Other courses in the same group
            option.classList.remove('selected');
            option.classList.add('disabled');
        }
    });
}

// Reset visual state for a group after deselection
function resetGroupVisualState(groupKey) {
    const groupSection = document.querySelector(`[data-group-key="${groupKey}"]`);
    if (!groupSection) return;
    
    const courseOptions = groupSection.querySelectorAll('.course-option');
    
    courseOptions.forEach(option => {
        option.classList.remove('selected', 'disabled');
    });
}

// Disable all instances of a course across all groups (except the selected one)
function disableAllInstancesOfCourse(courseCode, selectedGroupKey) {
    const allCourseOptions = document.querySelectorAll('.course-option');
    
    allCourseOptions.forEach(courseOption => {
        const courseCodeElement = courseOption.querySelector('.course-code');
        const radioInput = courseOption.querySelector('input[type="radio"]');
        const currentGroupKey = radioInput ? radioInput.dataset.groupKey : null;
        
        if (courseCodeElement && courseCodeElement.textContent === courseCode && currentGroupKey !== selectedGroupKey) {
            // This is the same course but in a different group - disable it
            courseOption.classList.add('disabled', 'course-taken');
            radioInput.disabled = true;
            
            // Add visual indicator that this course is taken
            if (!courseOption.querySelector('.taken-indicator')) {
                const takenIndicator = document.createElement('div');
                takenIndicator.className = 'taken-indicator';
                takenIndicator.innerHTML = '<i class="fas fa-lock me-1"></i>Already Selected';
                courseOption.appendChild(takenIndicator);
            }
        }
    });
}

// Re-enable all instances of a course across all groups
function enableAllInstancesOfCourse(courseCode) {
    const allCourseOptions = document.querySelectorAll('.course-option');
    
    allCourseOptions.forEach(courseOption => {
        const courseCodeElement = courseOption.querySelector('.course-code');
        const radioInput = courseOption.querySelector('input[type="radio"]');
        
        if (courseCodeElement && courseCodeElement.textContent === courseCode) {
            // This is the same course - re-enable it
            courseOption.classList.remove('disabled', 'course-taken');
            if (radioInput) {
                radioInput.disabled = false;
            }
            
            // Remove taken indicator
            const takenIndicator = courseOption.querySelector('.taken-indicator');
            if (takenIndicator) {
                takenIndicator.remove();
            }
        }
    });
}

// Restore course states after page render (disable courses that are already selected)
function restoreCourseStates() {
    // For each selected course, disable all other instances
    selectedCourses.forEach((courseData, groupKey) => {
        disableAllInstancesOfCourse(courseData.course_code, groupKey);
        updateGroupVisualState(groupKey);
    });
}

// Update selection summary panel
function updateSelectionSummary() {
    const selectionCount = document.getElementById('selectionCount');
    const selectedCoursesContainer = document.getElementById('selectedCourses');
    const submitButton = document.getElementById('submitSelection');
    
    const count = selectedCourses.size;
    
    // Update count
    selectionCount.innerHTML = `<span class="badge bg-primary">${count} course${count !== 1 ? 's' : ''} selected</span>`;
    
    // Update course list
    if (count === 0) {
        selectedCoursesContainer.innerHTML = `
            <div class="text-center text-muted">
                <i class="fas fa-clipboard-list fa-2x mb-2"></i>
                <p>No courses selected yet</p>
            </div>
        `;
        submitButton.disabled = true;
    } else {
        let html = '';
        
        selectedCourses.forEach((course, groupKey) => {
            html += `
                <div class="selected-course" data-group-key="${groupKey}">
                    <div class="selected-course-code">${course.course_code}</div>
                    <div class="selected-course-name">${course.course_name}</div>
                    <small class="text-muted">
                        <i class="fas fa-user me-1"></i>${course.teacher_name}
                        <br>
                        <i class="fas fa-users me-1"></i>${course.group_name.replace(/_/g, ' ')}
                    </small>
                    <button class="btn btn-sm btn-outline-danger mt-2" onclick="removeCourseSelection('${groupKey}')">
                        <i class="fas fa-times"></i> Remove
                    </button>
                </div>
            `;
        });
        
        selectedCoursesContainer.innerHTML = html;
        submitButton.disabled = false;
    }
}

// Remove a course selection
function removeCourseSelection(groupKey) {
    // Get the course data before removing
    const courseData = selectedCourses.get(groupKey);
    if (!courseData) return;
    
    // Remove from selected courses
    selectedCourses.delete(groupKey);
    
    // Uncheck radio button
    const groupSection = document.querySelector(`[data-group-key="${groupKey}"]`);
    if (groupSection) {
        const checkedRadio = groupSection.querySelector('input[type="radio"]:checked');
        if (checkedRadio) {
            checkedRadio.checked = false;
        }
        
        // Reset visual state
        resetGroupVisualState(groupKey);
    }
    
    // Re-enable all instances of this course
    enableAllInstancesOfCourse(courseData.course_code);
    
    updateSelectionSummary();
}

// Clear all selections
function clearAllSelections() {
    if (selectedCourses.size === 0) return;
    
    if (confirm('Are you sure you want to clear all course selections?')) {
        // Get all selected courses before clearing
        const selectedCourseCodes = Array.from(selectedCourses.values()).map(course => course.course_code);
        const groupKeys = Array.from(selectedCourses.keys());
        
        selectedCourses.clear();
        
        // Uncheck all radio buttons and reset visual states
        groupKeys.forEach(groupKey => {
            const groupSection = document.querySelector(`[data-group-key="${groupKey}"]`);
            if (groupSection) {
                const checkedRadio = groupSection.querySelector('input[type="radio"]:checked');
                if (checkedRadio) {
                    checkedRadio.checked = false;
                }
                resetGroupVisualState(groupKey);
            }
        });
        
        // Re-enable all course instances that were disabled
        selectedCourseCodes.forEach(courseCode => {
            enableAllInstancesOfCourse(courseCode);
        });
        
        updateSelectionSummary();
    }
}

// Submit selection
function submitSelection() {
    if (selectedCourses.size === 0) {
        alert('Please select at least one course before submitting.');
        return;
    }
    
    const selectionData = {
        timestamp: new Date().toISOString(),
        selections: Array.from(selectedCourses.entries()).map(([groupKey, course]) => ({
            groupKey,
            courseInstanceId: course.course_instance_id,
            courseCode: course.course_code,
            courseName: course.course_name,
            teacherName: course.teacher_name,
            department: course.department,
            semester: course.semester,
            groupName: course.group_name
        }))
    };
    
    // Show confirmation
    const confirmMessage = `
        You are about to submit your course selection:
        
        ${selectionData.selections.map(s => `• ${s.courseCode} - ${s.courseName}`).join('\n')}
        
        Are you sure you want to proceed?
    `;
    
    if (confirm(confirmMessage)) {
        // Here you would typically send the data to a server
        console.log('Submitting selection:', selectionData);
        
        // For demo purposes, show success message
        alert(`Successfully submitted ${selectionData.selections.length} course selections!\n\nCheck the console for detailed selection data.`);
        
        // Optionally, you could also save to localStorage or download as JSON
        downloadSelectionAsJSON(selectionData);
    }
}

// Download selection as JSON file
function downloadSelectionAsJSON(selectionData) {
    const dataStr = JSON.stringify(selectionData, null, 2);
    const dataBlob = new Blob([dataStr], {type: 'application/json'});
    
    const link = document.createElement('a');
    link.href = URL.createObjectURL(dataBlob);
    link.download = `course_selection_${new Date().toISOString().split('T')[0]}.json`;
    link.click();
}

// Initialize event listeners
function initializeEventListeners() {
    document.getElementById('clearAll').addEventListener('click', clearAllSelections);
    document.getElementById('submitSelection').addEventListener('click', submitSelection);
    
    // Filter event listeners
    document.getElementById('departmentFilter').addEventListener('change', function() {
        currentFilters.department = this.value;
        console.log('Department filter changed to:', this.value);
        applyFilters();
    });
    
    document.getElementById('semesterFilter').addEventListener('change', function() {
        currentFilters.semester = this.value;
        console.log('Semester filter changed to:', this.value);
        applyFilters();
    });
    
    // Debounced search
    let searchTimeout;
    document.getElementById('courseSearch').addEventListener('input', function() {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentFilters.search = this.value;
            applyFilters();
        }, 300);
    });
    
    document.getElementById('clearFilters').addEventListener('click', clearAllFilters);
}

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    console.log('Course Selection System initialized');
    initializeEventListeners();
    loadCourseData();
});

// Export functions for global access
window.handleCourseSelection = handleCourseSelection;
window.removeCourseSelection = removeCourseSelection; 