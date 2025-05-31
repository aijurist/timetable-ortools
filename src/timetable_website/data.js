// Data loader for CSV schedule data
class TimetableDataLoader {
    constructor() {
        this.csvData = [];
        this.courses = {};
        this.teachers = {};
    }

    // Load CSV data from file
    async loadCSVData() {
        try {
            const response = await fetch('../output/lab_schedule_20250529_125226/combined_theory_lab_schedule.csv');
            const csvText = await response.text();
            return csvText;
        } catch (error) {
            console.error('Error loading CSV file:', error);
            // Fallback to embedded data for demo
            return this.getFallbackData();
        }
    }

    // Parse CSV text into structured data
    parseCSV(csvText) {
        const lines = csvText.trim().split('\n');
        const headers = lines[0].split(',');
        
        this.csvData = [];
        for (let i = 1; i < lines.length; i++) {
            if (!lines[i].trim()) continue;
            
            const values = this.parseCSVLine(lines[i]);
            const row = {};
            
            headers.forEach((header, index) => {
                row[header.trim()] = values[index] ? values[index].trim() : '';
            });
            
            this.csvData.push(row);
        }
        
        return this.csvData;
    }

    // Parse CSV line handling quoted values
    parseCSVLine(line) {
        const values = [];
        let current = '';
        let inQuotes = false;
        
        for (let i = 0; i < line.length; i++) {
            const char = line[i];
            
            if (char === '"') {
                inQuotes = !inQuotes;
            } else if (char === ',' && !inQuotes) {
                values.push(current);
                current = '';
            } else {
                current += char;
            }
        }
        
        values.push(current);
        return values;
    }

    // Process course data for 5th semester CS students
    processCourseData() {
        this.courses = {};
        this.teachers = {};
        
        this.csvData.forEach(row => {
            const courseCode = row.course_code;
            const courseName = row.course_name;
            const teacherId = row.teacher_id;
            const teacherName = `${row.first_name} ${row.last_name}`.trim();
            const staffCode = row.staff_code;
            const semester = row.semester;
            const slotType = row.slot_type;
            
            // Only process 5th semester courses
            if (semester !== '5') return;
            
            // Initialize course if not exists
            if (!this.courses[courseCode]) {
                this.courses[courseCode] = {
                    code: courseCode,
                    name: courseName,
                    teachers: {},
                    semester: semester,
                    hasLab: false,
                    hasLecture: false,
                    hasTutorial: false
                };
            }
            
            // Add teacher to course
            if (!this.courses[courseCode].teachers[teacherId]) {
                this.courses[courseCode].teachers[teacherId] = {
                    id: teacherId,
                    name: teacherName,
                    staffCode: staffCode,
                    slots: []
                };
            }
            
            // Add slot information
            const slot = {
                day: row.day.toLowerCase(),
                slotIndex: parseInt(row.slot_index) || 0,
                timeInterval: row.time_interval,
                slotType: slotType,
                macroblock: row.macroblock,
                roomNumber: row.room_number,
                block: row.block,
                roomType: row.room_type,
                capacity: parseInt(row.capacity) || 0,
                labSession: row.lab_session,
                labSessionSlot: row.lab_session_slot,
                practicalHours: parseFloat(row.practical_hours) || 0,
                isBatched: row.is_batched === 'True',
                batchNumber: row.batch_number,
                batchInfo: row.batch_info
            };
            
            this.courses[courseCode].teachers[teacherId].slots.push(slot);
            
            // Mark course types
            if (slotType === 'Lecture') {
                this.courses[courseCode].hasLecture = true;
            } else if (slotType === 'Practical') {
                this.courses[courseCode].hasLab = true;
            } else if (slotType === 'Tutorial') {
                this.courses[courseCode].hasTutorial = true;
            }
            
            // Store teacher info globally
            this.teachers[teacherId] = {
                id: teacherId,
                name: teacherName,
                staffCode: staffCode
            };
        });
        
        return {
            courses: this.courses,
            teachers: this.teachers
        };
    }

    // Get 5th semester CS courses
    getFifthSemesterCourses() {
        const fifthSemCourses = {};
        
        Object.entries(this.courses).forEach(([code, course]) => {
            if (course.semester === '5') {
                fifthSemCourses[code] = course;
            }
        });
        
        return fifthSemCourses;
    }

    // Get teachers for a specific course
    getCourseTeachers(courseCode) {
        const course = this.courses[courseCode];
        return course ? course.teachers : {};
    }

    // Check if teacher has conflicts with existing schedule
    checkTeacherConflicts(courseCode, teacherId, existingSelections) {
        const conflicts = [];
        const newSlots = this.courses[courseCode].teachers[teacherId].slots;
        
        Object.entries(existingSelections).forEach(([selectedCourseCode, selectedData]) => {
            if (selectedCourseCode === courseCode) return;
            
            const selectedSlots = selectedData.teacher.slots;
            
            newSlots.forEach(newSlot => {
                selectedSlots.forEach(selectedSlot => {
                    if (this.slotsConflict(newSlot, selectedSlot)) {
                        conflicts.push({
                            newCourse: courseCode,
                            existingCourse: selectedCourseCode,
                            day: newSlot.day,
                            time: newSlot.timeInterval,
                            slotIndex: newSlot.slotIndex,
                            newSlotType: newSlot.slotType,
                            existingSlotType: selectedSlot.slotType
                        });
                    }
                });
            });
        });
        
        return conflicts;
    }

    // Check if two slots conflict
    slotsConflict(slot1, slot2) {
        return slot1.day === slot2.day && slot1.slotIndex === slot2.slotIndex;
    }

    // Find alternative teachers for a course without conflicts
    findAlternativeTeachers(courseCode, existingSelections) {
        const course = this.courses[courseCode];
        if (!course) return [];
        
        const alternatives = [];
        
        Object.values(course.teachers).forEach(teacher => {
            const conflicts = this.checkTeacherConflicts(courseCode, teacher.id, existingSelections);
            if (conflicts.length === 0) {
                alternatives.push(teacher);
            }
        });
        
        return alternatives;
    }

    // Get course statistics
    getCourseStats() {
        const stats = {
            totalCourses: Object.keys(this.courses).length,
            totalTeachers: Object.keys(this.teachers).length,
            courseTypes: {
                lecture: 0,
                lab: 0,
                tutorial: 0
            }
        };
        
        Object.values(this.courses).forEach(course => {
            if (course.hasLecture) stats.courseTypes.lecture++;
            if (course.hasLab) stats.courseTypes.lab++;
            if (course.hasTutorial) stats.courseTypes.tutorial++;
        });
        
        return stats;
    }

    // Fallback data for demonstration
    getFallbackData() {
        return `day,slot_index,time_interval,slot_type,macroblock,teacher_id,first_name,last_name,staff_code,room_id,room_number,block,room_type,capacity,course_id,course_code,course_name,course_instance_id,student_count,semester,course_dept,teacher_shift,daily_shift_pattern,lab_session,lab_session_slot,practical_hours,room_capacity,display_course_code,total_instance_students,is_batched,batch_number,batch_info,num_batches,students_per_batch,lab_capacity_category
wed,0,8:00 - 8:50,Lecture,d2,187,Mr.,Dr. Kumar P,IT03,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,95,70,5,Computer Science & Engineering,shift1,S2→S1→--→S1→S1,,,0,,,,,,,,,
sat,6,2:00 - 2:50,Lecture,d2,187,Mr.,Dr. Kumar P,IT03,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,95,70,5,Computer Science & Engineering,shift1,S2→S1→--→S1→S1,,,0,,,,,,,,,
fri,6,2:00 - 2:50,Lecture,td2,187,Mr.,Dr. Kumar P,IT03,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,95,70,5,Computer Science & Engineering,shift1,S2→S1→--→S1→S1,,,0,,,,,,,,,
tuesday,7,3:00 - 3:50,Lecture,a2,187,Mr.,Dr. Kumar P,IT03,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,109,70,5,Computer Science & Engineering,shift2,S2→S1→--→S1→S1,,,0,,,,,,,,,
sat,0,8:00 - 8:50,Lecture,a2,187,Mr.,Dr. Kumar P,IT03,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,109,70,5,Computer Science & Engineering,shift1,S2→S1→--→S1→S1,,,0,,,,,,,,,
fri,3,11:00 - 11:50,Lecture,ta2,187,Mr.,Dr. Kumar P,IT03,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,109,70,5,Computer Science & Engineering,shift1,S2→S1→--→S1→S1,,,0,,,,,,,,,
tuesday,9,5:00 - 5:50,Lecture,c2,188,Mr.,Dr.S.Vinodhkumar,CS69,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,243,70,5,Computer Science & Engineering,shift3,S3→--→--→S1→S1,,,0,,,,,,,,,
sat,2,10:00 - 10:50,Lecture,c2,188,Mr.,Dr.S.Vinodhkumar,CS69,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,243,70,5,Computer Science & Engineering,shift1,S3→--→--→S1→S1,,,0,,,,,,,,,
fri,5,1:00 - 1:50,Lecture,tc2,188,Mr.,Dr.S.Vinodhkumar,CS69,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,243,70,5,Computer Science & Engineering,shift1,S3→--→--→S1→S1,,,0,,,,,,,,,
tuesday,7,3:00 - 3:50,Lecture,a2,192,Mrs.,Jananee V,CS182,2,A103,A Block,Classroom,70,1544,CS23332,Database Management Systems,220,70,3,Computer Science & Engineering,shift2,S2→--→--→S1→S1,,,0,,,,,,,,,
sat,0,8:00 - 8:50,Lecture,a2,192,Mrs.,Jananee V,CS182,2,A103,A Block,Classroom,70,1544,CS23332,Database Management Systems,220,70,3,Computer Science & Engineering,shift1,S2→--→--→S1→S1,,,0,,,,,,,,,
fri,3,11:00 - 11:50,Lecture,ta2,192,Mrs.,Jananee V,CS182,2,A103,A Block,Classroom,70,1544,CS23332,Database Management Systems,220,70,3,Computer Science & Engineering,shift1,S2→--→--→S1→S1,,,0,,,,,,,,,
tuesday,8,4:00 - 4:50,Lecture,b2,192,Mrs.,Jananee V,CS182,1,A102,A Block,Classroom,70,1555,CS23531,Web Programming,270,70,5,Computer Science & Engineering,shift2,S2→--→--→S1→S1,,,0,,,,,,,,,
tuesday,6,2:00 - 2:50,Lecture,g1,195,Ms.,Jaeyalakshmi M,CS203,1,A102,A Block,Classroom,70,1544,CS23332,Database Management Systems,293,70,5,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,,,,,
fri,2,10:00 - 10:50,Lecture,g1,195,Ms.,Jaeyalakshmi M,CS203,1,A102,A Block,Classroom,70,1544,CS23332,Database Management Systems,293,70,5,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,,,,,
thur,0,8:00 - 8:50,Lecture,tg1,195,Ms.,Jaeyalakshmi M,CS203,1,A102,A Block,Classroom,70,1544,CS23332,Database Management Systems,293,70,5,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,,,,,
tuesday,4,12:00 - 12:50,Lecture,e1,195,Ms.,Jaeyalakshmi M,CS203,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,274,70,5,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,,,,,
fri,0,8:00 - 8:50,Lecture,e1,195,Ms.,Jaeyalakshmi M,CS203,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,274,70,5,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,,,,,
wed,8,4:00 - 4:50,Lecture,te1,195,Ms.,Jaeyalakshmi M,CS203,1,A102,A Block,Classroom,70,1868,CS23533,Foundations of Artificial Intelligence,274,70,5,Computer Science & Engineering,shift2,S1→S2→S1→S1→--,,,0,,,,,,,,,
tuesday,6,2:00 - 2:50,Lecture,g1,196,Mr.,Dr.P.Shanmugam,CS251,2,A103,A Block,Classroom,70,1543,CS23331,Design and Analysis of Algorithms,214,70,3,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,,,,,
fri,2,10:00 - 10:50,Lecture,g1,196,Mr.,Dr.P.Shanmugam,CS251,2,A103,A Block,Classroom,70,1543,CS23331,Design and Analysis of Algorithms,214,70,3,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,,,,,
thur,0,8:00 - 8:50,Lecture,tg1,196,Mr.,Dr.P.Shanmugam,CS251,2,A103,A Block,Classroom,70,1543,CS23331,Design and Analysis of Algorithms,214,70,3,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,,,,,
tuesday,4,12:00 - 12:50,Lecture,e1,196,Mr.,Dr.P.Shanmugam,CS251,2,A103,A Block,Classroom,70,1554,CS23512,Fundamentals of Mobile Computing,259,70,5,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,,,,,
fri,0,8:00 - 8:50,Lecture,e1,196,Mr.,Dr.P.Shanmugam,CS251,2,A103,A Block,Classroom,70,1554,CS23512,Fundamentals of Mobile Computing,259,70,5,Computer Science & Engineering,shift1,S1→S2→S1→S1→--,,,0,,,,,,,,,
wed,8,4:00 - 4:50,Lecture,te1,196,Mr.,Dr.P.Shanmugam,CS251,2,A103,A Block,Classroom,70,1554,CS23512,Fundamentals of Mobile Computing,259,70,5,Computer Science & Engineering,shift2,S1→S2→S1→S1→--,,,0,,,,,,,,,
tuesday,2,10:00 - 10:50,Lecture,c1,222,Mr.,Dr.K.Ananthajothi,CS255,5,A109,A Block,Classroom,70,1553,CS23511,Theory of Computation,253,70,5,Computer Science & Engineering,shift1,S1→S1→S2→--→S1,,,0,,,,,,,,,
thur,8,4:00 - 4:50,Lecture,c1,222,Mr.,Dr.K.Ananthajothi,CS255,5,A109,A Block,Classroom,70,1553,CS23511,Theory of Computation,253,70,5,Computer Science & Engineering,shift2,S1→S1→S2→--→S1,,,0,,,,,,,,,
wed,6,2:00 - 2:50,Lecture,tc1,222,Mr.,Dr.K.Ananthajothi,CS255,5,A109,A Block,Classroom,70,1553,CS23511,Theory of Computation,253,70,5,Computer Science & Engineering,shift1,S1→S1→S2→--→S1,,,0,,,,,,,,,
sat,5,1:00 - 1:50,Tutorial,tcc1,222,Mr.,Dr.K.Ananthajothi,CS255,1,A102,A Block,Classroom,70,1553,CS23511,Theory of Computation,253,70,5,Computer Science & Engineering,shift1,S1→S1→S2→--→S1,,,0,,,,,,,,,
tuesday,6,2:00 - 2:50,Lecture,g1,202,Mr.,Dr. N. Duraimurugan,CS208,3,A104/105,A Block,Classroom,140,1555,CS23531,Web Programming,261,70,5,Computer Science & Engineering,shift1,S1→--→--→--→--,,,0,,,,,,,,,
wed,22,9:50 - 10:40,Practical,LAB_L2_1,187,Mr.,Dr. Kumar P,IT03,171,KFR03,K Block,Lab,35,1868,CS23533,Foundations of Artificial Intelligence,95,35,5,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L2,1,2,35.0,CS23533 S1 B1,70.0,True,1.0,Batch 1,2.0,35.0,35-capacity
wed,23,10:40 - 11:30,Practical,LAB_L2_2,187,Mr.,Dr. Kumar P,IT03,171,KFR03,K Block,Lab,35,1868,CS23533,Foundations of Artificial Intelligence,95,35,5,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L2,2,2,35.0,CS23533 S1 B1,70.0,True,1.0,Batch 1,2.0,35.0,35-capacity
wed,28,3:50 - 4:40,Practical,LAB_L5_1,192,Mrs.,Jananee V,CS182,189,TLSL2,Techlounge,Lab,70,1544,CS23332,Database Management Systems,220,70,3,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L5,1,4,70.0,CS23332,70.0,False,,,1.0,70.0,70-capacity
wed,29,4:40 - 5:30,Practical,LAB_L5_2,192,Mrs.,Jananee V,CS182,189,TLSL2,Techlounge,Lab,70,1544,CS23332,Database Management Systems,220,70,3,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L5,2,4,70.0,CS23332,70.0,False,,,1.0,70.0,70-capacity
wed,22,9:50 - 10:40,Practical,LAB_L2_1,195,Ms.,Jaeyalakshmi M,CS203,157,DG02,D Block,Lab,70,1544,CS23332,Database Management Systems,293,70,5,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L2,1,4,70.0,CS23332,70.0,False,,,1.0,70.0,70-capacity
wed,23,10:40 - 11:30,Practical,LAB_L2_2,195,Ms.,Jaeyalakshmi M,CS203,157,DG02,D Block,Lab,70,1544,CS23332,Database Management Systems,293,70,5,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L2,2,4,70.0,CS23332,70.0,False,,,1.0,70.0,70-capacity
wed,22,9:50 - 10:40,Practical,LAB_L2_1,196,Mr.,Dr.P.Shanmugam,CS251,178,TLFL5,Techlounge,Lab,35,1543,CS23331,Design and Analysis of Algorithms,214,35,3,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L2,1,2,35.0,CS23331 B1,70.0,True,1.0,Batch 1,2.0,35.0,35-capacity
wed,23,10:40 - 11:30,Practical,LAB_L2_2,196,Mr.,Dr.P.Shanmugam,CS251,178,TLFL5,Techlounge,Lab,35,1543,CS23331,Design and Analysis of Algorithms,214,35,3,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L2,2,2,35.0,CS23331 B1,70.0,True,1.0,Batch 1,2.0,35.0,35-capacity
thur,24,11:50 - 12:40,Practical,LAB_L3_1,229,Mrs.,Sathiyavathi S,CS238,158,DG03,D Block,Lab,70,1555,CS23531,Web Programming,289,70,5,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L3,1,4,70.0,CS23531,70.0,False,,,1.0,70.0,70-capacity
thur,25,12:40 - 1:30,Practical,LAB_L3_2,229,Mrs.,Sathiyavathi S,CS238,158,DG03,D Block,Lab,70,1555,CS23531,Web Programming,289,70,5,Computer Science & Engineering,combined_shift,Combined→Combined→Combined→Combined→Combined,L3,2,4,70.0,CS23531,70.0,False,,,1.0,70.0,70-capacity`;
    }
}

// Export the data loader
window.TimetableDataLoader = TimetableDataLoader; 