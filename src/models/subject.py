from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime, date, time

class DayOfWeek(str, Enum):
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"

class RoomType(str, Enum):
    CLASSROOM = "CLASSROOM"
    LAB = "LAB"

class ScheduledComponentType(str, Enum):
    LECTURE = "LECTURE"
    TUTORIAL = "TUTORIAL"
    PRACTICAL = "PRACTICAL"

class ScheduledPeriodDetail(BaseModel):
    """
    Represents the detailed schedule for a single, specific teaching period
    (e.g., one lecture of Data Structures, one lab session for Mobile App Dev).
    This is the most granular piece of the scheduled output.
    """
    course_id: str = Field(..., description="Unique course code, e.g., 'CS19601'")
    course_name: str = Field(..., description="Full name of the course")
    component_type: ScheduledComponentType = Field(..., description="Type of this period: LECTURE, TUTORIAL, or PRACTICAL")
    
    staff_id: str = Field(..., description="Unique identifier for the primary staff member teaching this period")
    staff_name: str = Field(..., description="Name of the primary staff member")
    assistant_staff_id: Optional[str] = Field(None, description="Staff ID of the assistant, if applicable (e.g., for labs)")
    assistant_staff_name: Optional[str] = Field(None, description="Name of the assistant staff member, if applicable")

    day_of_week: DayOfWeek = Field(..., description="The day of the week this period occurs")
    start_time: time = Field(..., description="Start time of this period")
    end_time: time = Field(..., description="End time of this period")
    room_id: str = Field(..., description="Unique room identifier, e.g., 'SJT-501'")
    room_name: Optional[str] = Field(None, description="Name or common identifier of the room")
    room_type: RoomType = Field(..., description="The type of room allocated")

    student_group_identifier: Optional[str] = Field(None, description="Identifier for the specific student group/batch, e.g., 'SectionA_Theory', 'Batch1_Lab'")
    scheduled_instance_id: Optional[str] = Field(None, description="A unique ID for this specific scheduled period instance")
    department_code: Optional[str] = Field(None, description="Department offering the course")
    semester: Optional[int] = Field(None, description="Semester for which this is scheduled")


    @property
    def duration_minutes(self) -> int:
        start_dt = datetime.combine(date.today(), self.start_time)
        end_dt = datetime.combine(date.today(), self.end_time)
        return int((end_dt - start_dt).total_seconds() / 60)