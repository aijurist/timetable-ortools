# Timetable Management Website for 5th Semester Computer Science Students

This is a comprehensive timetable management website that allows 5th semester Computer Science students to:

1. **Select Courses**: Choose from available 5th semester CS courses
2. **Choose Teachers**: For each course, select from available teachers 
3. **Build Timetable**: Real-time timetable generation as courses are selected
4. **Conflict Detection**: Automatic detection of scheduling conflicts
5. **Alternative Recommendations**: Get alternative teacher suggestions when conflicts arise

## Features

### Course Selection
- Interactive course cards showing course details
- Displays available teachers per course
- Shows course types (Lecture, Lab/Practical, Tutorial)
- Visual feedback for selected courses

### Teacher Selection
- Modal dialog for choosing teachers
- Display teacher information and schedules
- One teacher per course restriction

### Conflict Resolution
- Real-time conflict detection when selecting teachers
- Visual conflict highlighting in timetable
- Alternative teacher recommendations
- Conflict resolution modal with options

### Timetable Display
- Clean, responsive timetable grid (Monday-Saturday)
- Color-coded class types:
  - **Blue**: Lectures
  - **Green**: Lab/Practical sessions
  - **Orange**: Tutorials
  - **Red**: Conflicts
- Time slot mapping for both regular (0-9) and lab slots (20-31)
- Detailed slot information on hover

## File Structure

```
timetable_website/
├── index.html          # Main HTML structure
├── styles.css          # Modern responsive CSS styling
├── script.js           # Main JavaScript application logic
├── data.js             # Data loading and processing utilities
├── server.py           # Python HTTP server for CSV data
└── README.md           # This file
```

## How to Run

### Method 1: With Python Server (Recommended)
This method loads the full CSV data from the actual schedule file.

1. **Navigate to the website directory:**
   ```bash
   cd timetable_scheduler/src/timetable_website/
   ```

2. **Run the Python server:**
   ```bash
   python server.py
   ```

3. **Open your browser and visit:**
   ```
   http://localhost:8000
   ```

### Method 2: Direct File Opening (Fallback Data)
This method uses embedded sample data if the server is not available.

1. **Simply open `index.html` in your web browser**
2. The application will use fallback data for demonstration

## Data Source

The website reads schedule data from:
```
timetable_scheduler/output/lab_schedule_20250529_125226/combined_theory_lab_schedule.csv
```

This CSV file contains:
- Course information (codes, names, semesters)
- Teacher details (names, staff codes)
- Schedule slots (days, times, room information)
- Lab session information (batches, capacities)

## Usage Instructions

### 1. Course Selection
- Browse available 5th semester CS courses in the left panel
- Click on a course card to open teacher selection modal
- Each course shows number of available teachers

### 2. Teacher Selection
- In the modal, view available teachers for the course
- Each teacher option shows their schedule slots
- Click "Select" next to your preferred teacher
- Click "Confirm Selection" to add to your timetable

### 3. Conflict Handling
- If a conflict is detected, you'll see a conflict modal
- Review the conflicting schedules
- Choose from alternative teachers if available
- Or cancel the selection to try a different course

### 4. Timetable Management
- Your selected courses appear in the right panel timetable
- Use the "Clear All" button to start over
- The "Generate Timetable" button provides a summary view

### 5. Visual Indicators
- **Selected courses**: Green border on course cards
- **Conflicts**: Red highlighting in timetable
- **Course types**: Color-coded legend provided

## Technical Details

### Time Slots
- **Regular slots (0-9)**: 8:00 AM to 5:50 PM (50-minute periods)
- **Lab slots (20-31)**: Extended lab sessions with different timing

### Day Mapping
- Monday = 1, Tuesday = 2, ..., Saturday = 6

### Conflict Detection
- Based on matching day and slot_index values
- Prevents overlapping class schedules
- Suggests alternative teachers when possible

### Browser Support
- Modern browsers with ES6+ support
- Responsive design for desktop and mobile
- Uses CSS Grid and Flexbox for layout

## Course Types Available

The system supports multiple 5th semester CS courses including:
- **CS23533**: Foundations of Artificial Intelligence
- **CS23332**: Database Management Systems  
- **CS23331**: Design and Analysis of Algorithms
- **CS23511**: Theory of Computation
- **CS23531**: Web Programming
- **CS23532**: Computer Networks
- **CS23334**: Fundamentals of Data Science
- **CS23512**: Fundamentals of Mobile Computing
- **CS23333**: Object Oriented Programming Using JAVA

Each course may have multiple teachers and both lecture and lab components.

---

**Note**: This website is designed specifically for 5th semester Computer Science & Engineering students. The data is filtered to show only semester "5" courses from the CSV file. 