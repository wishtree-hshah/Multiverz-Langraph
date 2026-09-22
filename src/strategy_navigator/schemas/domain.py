"""domain_agent stage I/O.

The prompt (``prompts/_mongo/1.md``, Mongo ``prompt_list`` id ``1``) asks the
LLM for ten "profile-image matching attributes" per agent, used by the
backend's ``AgentProfileImageMatcherService`` to pick a library avatar
(``previewUrl`` is assigned server-side from these — we never generate it
ourselves). The enums below are copied verbatim from the backend's own source
of truth, ``challenges-backend/.../enums/agentProfileImage.enum.ts`` — the
callback DTO (``ReceiveDomainSpecificAgentDto``) validates against exactly
these values, and when ``AGENT_IMAGE_MATCHER_ENABLED=true`` the backend
strict-rejects (``{success: false}``, no HTTP error) any agent missing
``gender``/``country``/``personaType``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from strategy_navigator.schemas.common import CamelModel, DocumentRef, ProjectContext


class DomainAgentRequest(CamelModel):
    session_id: str
    project: ProjectContext
    documents: list[DocumentRef] = []
    min_agents: int = 3
    max_agents: int = 6
    callback_url: str | None = None


class AgentGender(StrEnum):
    MALE = "male"
    FEMALE = "female"


class AgentPersonaType(StrEnum):
    CORPORATE = "corporate"
    ACADEMIC = "academic"
    STARTUP = "startup"
    GOVERNMENT = "government"
    CREATIVE = "creative"


class AgentAgeGroup(StrEnum):
    YOUNG = "young"
    MID = "mid"
    SENIOR = "senior"


class AgentAttireStyle(StrEnum):
    FORMAL = "formal"
    BUSINESS_CASUAL = "business-casual"
    TECHNICAL = "technical"
    CREATIVE = "creative"


class AgentIndustryAlignment(StrEnum):
    HEALTHCARE = "healthcare"
    FINANCE = "finance"
    TECHNOLOGY = "technology"
    EDUCATION = "education"
    PUBLIC_SECTOR = "public-sector"
    RETAIL = "retail"
    MANUFACTURING = "manufacturing"
    ENERGY = "energy"
    MEDIA = "media"
    CROSS_INDUSTRY = "cross-industry"
    EDTECH = "edtech"
    BANKING = "banking"
    DIPLOMACY = "diplomacy"
    FASHION = "fashion"
    ECONOMICS = "economics"
    FINTECH = "fintech"
    PUBLIC_POLICY = "public policy"
    PHOTOGRAPHY = "photography"
    PUBLIC_HEALTH = "public health"
    HEALTHTECH = "healthtech"
    CONSULTING = "consulting"
    FOREIGN_AFFAIRS = "foreign affairs"
    ART = "art"
    LAW = "law"
    LITERATURE = "literature"
    ADVERTISING = "advertising"
    DIPLOMAT = "diplomat"
    CREATIVE_AGENCY = "creative agency"
    BIO_ENGINEERING = "bio-engineering"
    ROBOTIC = "robotic"
    MEDICINE = "medicine"
    NGO = "ngo"
    DESIGN = "design"
    ENVIRONMENTAL_SCIENCE = "environmental science"
    SOFTWARE = "software"
    ARCHITECTURE = "architecture"
    E_COMMERCE = "e-commerce"
    PHILOSOPHY = "philosophy"
    CLEANTECH = "cleantech"
    FILM = "film"
    MUSIC = "music"
    MARINE_BIOLOGY = "marine biology"
    AGRITECH = "agritech"
    TOURISM = "tourism"
    INDIGENOUS_STUDIES = "indigenous studies"
    HOSPITALITY = "hospitality"
    ENVIRONMENTAL_POLICY = "environmental policy"
    HISTORY = "history"
    ASTRONOMY = "astronomy"
    TEXTILE_DESIGN = "textile design"


class AgentSetting(StrEnum):
    OFFICE = "office"
    LAB = "lab"
    FIELD = "field"
    STUDIO = "studio"
    REMOTE = "remote"
    CONFERENCE = "conference"
    NEUTRAL = "neutral"
    CLASS = "class"
    RESEARCH_LAB = "research lab"
    FACTORY = "factory"
    OUTDOOR = "outdoor"
    CO_WORKING_SPACE = "co-working space"
    BOARDROOM = "boardroom"
    LECTURE_HALL = "lecture hall"
    TECH_HUB = "tech hub"
    MANAGER = "manager"
    GOVERMENT_BUILDING = "government building"
    GALLERY = "gallery"
    LIBRARY = "library"
    SEMINAR_ROOM = "seminar room"
    HIGH_RISE_OFFICE = "high-rise office"
    PARLIAMENT = "parliament"
    BUILDING = "building"
    CAMPUS = "campus"
    SET = "set"
    WORKSHOP = "workshop"


class AgentArchetypeTag(StrEnum):
    STRATEGIST = "strategist"
    OPERATOR = "operator"
    ANALYST = "analyst"
    INNOVATOR = "innovator"
    ADVISOR = "advisor"
    RESEARCHER = "researcher"
    LECTURER = "lecturer"
    FOUNDER = "founder"
    EXECUTIVE = "executive"
    DIPLOMAT = "diplomat"
    ARTIST = "artist"
    SCHOLAR = "scholar"
    STATESPERSON = "statesperson"
    STORYTELLER = "storyteller"
    CREATIVES = "creatives"
    LEADER = "leader"
    ACTIVIST = "activist"
    CIVIL_SERVANT = "civil servant"
    DESIGNER = "designer"
    MANAGER = "manager"
    DISRUPTOR = "disruptor"
    CREATOR = "creator"
    THEORIST = "theorist"
    DIRECTOR = "director"
    POLICYMAKER = "policymaker"
    PRODUCER = "producer"
    MAKER = "maker"


class AgentFacialExpression(StrEnum):
    NEUTRAL = "neutral"
    CONFIDENT = "confident"
    SMILING = "smiling"
    SERIOUS = "serious"


class AgentRegion(StrEnum):
    NORTH_AMERICA = "north-america"
    SOUTH_AMERICA = "south-america"
    EUROPE = "europe"
    AFRICA = "africa"
    MIDDLE_EAST = "middle-east"
    SOUTH_ASIA = "south-asia"
    EAST_ASIA = "east-asia"
    SOUTHEAST_ASIA = "southeast-asia"
    OCEANIA = "oceania"
    GLOBAL = "global"


class DomainAgentPersona(CamelModel):
    name: str
    designation: str
    persona: str | None = None
    description: str
    stakeholder: str | None = None
    core_mission: str | None = None
    summary: list[str] = []
    # --- profile-image matching attributes (see module docstring) ---
    country: str | None = None
    gender: AgentGender | None = None
    persona_type: AgentPersonaType | None = None
    age_group: AgentAgeGroup | None = None
    region: AgentRegion | None = None
    attire_style: AgentAttireStyle | None = None
    industry_alignment: AgentIndustryAlignment | None = None
    setting: AgentSetting | None = None
    archetype_tag: AgentArchetypeTag | None = None
    facial_expression: AgentFacialExpression | None = None


class DomainAgentOutput(CamelModel):
    personas: list[DomainAgentPersona] = Field(min_length=1)


class DomainAgentCallback(CamelModel):
    session_id: str
    project_id: int
    agents: list[DomainAgentPersona]
    execution_id: str | None = None
    token_usage: list[dict] | None = None
    error_message: str | None = None
