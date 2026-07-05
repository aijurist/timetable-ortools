"""
app.schemas
===========
Central re-export of all Pydantic V2 schemas.
Import from here throughout the codebase to keep references stable.
"""

from app.schemas.common import PaginatedResponse

from app.schemas.user import (
    UserCreate,
    UserUpdate,
    UserResponse,
)

from app.schemas.scenario import (
    ScenarioCreate,
    ScenarioUpdate,
    ScenarioResponse,
    ScenarioListResponse,
)

from app.schemas.course import (
    CourseCreate,
    CourseUpdate,
    CourseResponse,
    CourseListResponse,
)

from app.schemas.room import (
    RoomCreate,
    RoomUpdate,
    RoomResponse,
    RoomListResponse,
)

from app.schemas.faculty import (
    FacultyCreate,
    FacultyUpdate,
    FacultyAvailabilityUpdate,
    FacultyResponse,
    FacultyListResponse,
)

from app.schemas.constraint import (
    ConstraintDefinitionResponse,
    ConstraintDefinitionListResponse,
    ScenarioRuleCreate,
    ScenarioRuleUpdate,
    ScenarioRuleResponse,
    ScenarioRuleListResponse,
)

from app.schemas.schedule import (
    ScheduledSessionResponse,
    ScheduleListResponse,
)

from app.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentSessionResponse,
    AgentSessionListResponse,
    AgentMessageResponse,
    AgentMessageListResponse,
    TokenResponse,
    RefreshRequest,
)

from app.schemas.exam import (
    ExamScenarioCreate,
    ExamScenarioUpdate,
    ExamScenarioResponse,
    ExamScenarioListResponse,
    ExamSlotCreate,
    ExamSlotUpdate,
    ExamSlotResponse,
    ExamSlotListResponse,
    ExamAssignmentResponse,
    ExamAssignmentListResponse,
)

from app.schemas.study_material import (
    CourseNoteCreate,
    CourseNoteUpdate,
    CourseNoteResponse,
    CourseNoteListResponse,
    ExamPaperCreate,
    ExamPaperUpdate,
    ExamPaperResponse,
    ExamPaperListResponse,
    StudyGuideCreate,
    StudyGuideUpdate,
    StudyGuideResponse,
    StudyGuideListResponse,
)

from app.schemas.reservation import (
    ReservationCreate,
    ReservationApprove,
    ReservationStatusUpdate,
    ReservationResponse,
    ReservationListResponse,
)

from app.schemas.analytics import (
    AnalyticsSnapshotResponse,
    AnalyticsSnapshotListResponse,
    FacultyWorkloadRow,
    WorkloadMetricsResponse,
    RoomUtilizationRow,
    RoomUtilizationResponse,
    GenerateSnapshotRequest,
    GenerateSnapshotResponse,
)

from app.schemas.time_grid import (
    SlotDefinition,
    TimeGridCreate,
    TimeGridUpdate,
    TimeGridSlotPatch,
    TimeGridResponse,
    TimeGridListResponse,
)

from app.schemas.institution import (
    InstitutionCreate,
    InstitutionUpdate,
    InstitutionResponse,
    InstitutionListResponse,
    InstitutionStatsResponse,
    DepartmentCreate,
    DepartmentUpdate,
    DepartmentResponse,
    DepartmentListResponse,
    AcademicTermCreate,
    AcademicTermUpdate,
    AcademicTermResponse,
    AcademicTermListResponse,
)

from app.schemas.curriculum import (
    SchedulingTargetCreate,
    SchedulingTargetUpdate,
    SchedulingTargetResponse,
    SchedulingTargetListResponse,
    OfferingBucketCreate,
    OfferingBucketUpdate,
    OfferingBucketResponse,
    OfferingBucketListResponse,
    CourseOfferingCreate,
    CourseOfferingUpdate,
    CourseOfferingResponse,
    CourseOfferingListResponse,
    TargetRequirementCreate,
    TargetRequirementResponse,
    TargetRequirementListResponse,
)

from app.schemas.solver_job import (
    SolverJobResponse,
    SolverJobListResponse,
    JobConflictResponse,
    JobConflictListResponse,
)

from app.schemas.student import (
    StudentAdminCreate,
    StudentAdminUpdate,
    StudentAdminResponse,
    StudentAdminListResponse,
    StudentProfileCreate,
    StudentProfileUpdate,
    StudentProfileResponse,
    StudentProfileListResponse,
    StudentRegistrationCreate,
    StudentRegistrationResponse,
    StudentRegistrationListResponse,
    StudentWishlistCreate,
    StudentWishlistUpdate,
    StudentWishlistResponse,
    StudentWishlistListResponse,
)

from app.schemas.bulk_upload import (
    BulkRowStatus,
    BulkUploadRow,
    BulkUploadPreview,
    BulkImportResult,
    BulkImportRequest,
    BulkUploadPreviewResponse,
)

__all__ = [
    # common
    "PaginatedResponse",
    # user
    "UserCreate", "UserUpdate", "UserResponse",
    # scenario
    "ScenarioCreate", "ScenarioUpdate", "ScenarioResponse", "ScenarioListResponse",
    # course
    "CourseCreate", "CourseUpdate", "CourseResponse", "CourseListResponse",
    # room
    "RoomCreate", "RoomUpdate", "RoomResponse", "RoomListResponse",
    # faculty
    "FacultyCreate", "FacultyUpdate", "FacultyAvailabilityUpdate",
    "FacultyResponse", "FacultyListResponse",
    # constraint
    "ConstraintDefinitionResponse", "ConstraintDefinitionListResponse",
    "ScenarioRuleCreate", "ScenarioRuleUpdate",
    "ScenarioRuleResponse", "ScenarioRuleListResponse",
    # schedule
    "ScheduledSessionResponse", "ScheduleListResponse",
    # agent
    "AgentChatRequest", "AgentChatResponse",
    "AgentSessionResponse", "AgentSessionListResponse",
    "AgentMessageResponse", "AgentMessageListResponse",
    "TokenResponse", "RefreshRequest",
    # exam
    "ExamScenarioCreate", "ExamScenarioUpdate", "ExamScenarioResponse", "ExamScenarioListResponse",
    "ExamSlotCreate", "ExamSlotUpdate", "ExamSlotResponse", "ExamSlotListResponse",
    "ExamAssignmentResponse", "ExamAssignmentListResponse",
    # study material
    "CourseNoteCreate", "CourseNoteUpdate", "CourseNoteResponse", "CourseNoteListResponse",
    "ExamPaperCreate", "ExamPaperUpdate", "ExamPaperResponse", "ExamPaperListResponse",
    "StudyGuideCreate", "StudyGuideUpdate", "StudyGuideResponse", "StudyGuideListResponse",
    # reservation
    "ReservationCreate", "ReservationApprove", "ReservationStatusUpdate",
    "ReservationResponse", "ReservationListResponse",
    # analytics
    "AnalyticsSnapshotResponse", "AnalyticsSnapshotListResponse",
    "FacultyWorkloadRow", "WorkloadMetricsResponse",
    "RoomUtilizationRow", "RoomUtilizationResponse",
    "GenerateSnapshotRequest", "GenerateSnapshotResponse",
    # time_grid
    "SlotDefinition",
    "TimeGridCreate", "TimeGridUpdate", "TimeGridSlotPatch",
    "TimeGridResponse", "TimeGridListResponse",
    # institution
    "InstitutionCreate", "InstitutionUpdate", "InstitutionResponse", "InstitutionListResponse",
    "DepartmentCreate", "DepartmentUpdate", "DepartmentResponse", "DepartmentListResponse",
    "AcademicTermCreate", "AcademicTermUpdate", "AcademicTermResponse", "AcademicTermListResponse",
    # curriculum
    "SchedulingTargetCreate", "SchedulingTargetUpdate", "SchedulingTargetResponse", "SchedulingTargetListResponse",
    "OfferingBucketCreate", "OfferingBucketUpdate", "OfferingBucketResponse", "OfferingBucketListResponse",
    "CourseOfferingCreate", "CourseOfferingUpdate", "CourseOfferingResponse", "CourseOfferingListResponse",
    "TargetRequirementCreate", "TargetRequirementResponse", "TargetRequirementListResponse",
    # solver_job
    "SolverJobResponse", "SolverJobListResponse",
    "JobConflictResponse", "JobConflictListResponse",
    # student
    "StudentAdminCreate", "StudentAdminUpdate", "StudentAdminResponse", "StudentAdminListResponse",
    "StudentProfileCreate", "StudentProfileUpdate", "StudentProfileResponse", "StudentProfileListResponse",
    "StudentRegistrationCreate", "StudentRegistrationResponse", "StudentRegistrationListResponse",
    "StudentWishlistCreate", "StudentWishlistUpdate", "StudentWishlistResponse", "StudentWishlistListResponse",
]

