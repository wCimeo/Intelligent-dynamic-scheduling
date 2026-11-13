from typing import Literal
from datetime import date,time,datetime,timedelta
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)

class AccountName(Input):
    username: str = Field(min_length=4, max_length=32, pattern=r'^[A-Za-z0-9_]+$')
    @field_validator('username')
    @classmethod
    def normalize(cls, value):
        return value.lower()

class Login(AccountName):
    password: str = Field(min_length=1, max_length=128)

class Register(Login):
    name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=12, max_length=128)
    password_confirmation: str
    @model_validator(mode='after')
    def confirm(self):
        if self.password != self.password_confirmation:
            raise ValueError('两次密码不一致')
        if not self.name.strip():
            raise ValueError('姓名不能为空')
        return self

class ChangePassword(Input):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)
    confirmation: str
    @model_validator(mode='after')
    def confirm(self):
        if self.new_password != self.confirmation:
            raise ValueError('两次密码不一致')
        if self.new_password == self.old_password:
            raise ValueError('新密码不能与旧密码相同')
        return self

class EmployeeInput(Input):
    employee_no: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=1, max_length=64)
    employment_type: Literal['FULL_TIME','PART_TIME'] = 'FULL_TIME'
    weekly_limit_minutes: int = Field(default=2400, gt=0, le=10080)
    @field_validator('name')
    @classmethod
    def name_required(cls,value):
        if not value.strip(): raise ValueError('姓名不能为空')
        return value.strip()

class EmployeeUpdate(Input):
    employee_no: str | None = Field(default=None,min_length=1,max_length=32,pattern=r'^[A-Za-z0-9_-]+$')
    name: str | None = Field(default=None,min_length=1,max_length=64)
    employment_type: Literal['FULL_TIME','PART_TIME'] | None = None
    weekly_limit_minutes: int | None = Field(default=None,gt=0,le=10080)
    expected_revision: int = Field(ge=1)
    @field_validator('name')
    @classmethod
    def clean_name(cls,value):
        if value is None: return None
        value=value.strip()
        if not value: raise ValueError('姓名不能为空')
        return value
    @model_validator(mode='after')
    def has_change(self):
        if all(getattr(self,field) is None for field in ('employee_no','name','employment_type','weekly_limit_minutes')):
            raise ValueError('请至少修改一个字段')
        return self

class EmployeeStatusChange(Input):
    status: Literal['ACTIVE','INACTIVE']
    expected_revision: int = Field(ge=1)

class QualificationInput(Input):
    code: str = Field(min_length=1,max_length=32,pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=1,max_length=64)
    @field_validator('code')
    @classmethod
    def normalize_code(cls,value):
        return value.strip().lower()
    @field_validator('name')
    @classmethod
    def clean_name(cls,value):
        value=value.strip()
        if not value: raise ValueError('名称不能为空')
        return value

class QualificationUpdate(Input):
    name: str = Field(min_length=1,max_length=64)
    active: bool
    expected_revision: int = Field(ge=1)
    @field_validator('name')
    @classmethod
    def clean_name(cls,value):
        value=value.strip()
        if not value: raise ValueError('名称不能为空')
        return value

class QualificationSkillSet(Input):
    skill_ids: list[int] = Field(default_factory=list,max_length=100)
    expected_revision: int = Field(ge=1)
    @field_validator('skill_ids')
    @classmethod
    def unique_positive_ids(cls,value):
        if any(item<=0 for item in value): raise ValueError('技能编号必须为正整数')
        if len(set(value))!=len(value): raise ValueError('技能不能重复选择')
        return value

class ShiftDemandInput(Input):
    position_id: int = Field(gt=0)
    required_count: int = Field(ge=0,le=100)

class ShiftTemplateInput(Input):
    code: str = Field(min_length=1,max_length=32,pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=1,max_length=32)
    start_time: time
    end_time: time
    demands: list[ShiftDemandInput] = Field(min_length=1,max_length=100)
    @field_validator('code')
    @classmethod
    def normalize_code(cls,value):
        return value.strip().lower()
    @field_validator('name')
    @classmethod
    def clean_name(cls,value):
        value=value.strip()
        if not value: raise ValueError('班次名称不能为空')
        return value
    @model_validator(mode='after')
    def validate_times_and_demands(self):
        if self.end_time<=self.start_time: raise ValueError('结束时间必须晚于开始时间')
        ids=[item.position_id for item in self.demands]
        if len(set(ids))!=len(ids): raise ValueError('同一岗位不能重复配置')
        return self

class ShiftTemplateUpdate(ShiftTemplateInput):
    active: bool
    expected_revision: int = Field(ge=1)

class PeriodInput(Input):
    week_start: date
    @field_validator('week_start')
    @classmethod
    def monday_required(cls,value):
        if value.weekday()!=0: raise ValueError('排班周期必须从周一开始')
        return value

class DraftCreate(Input):
    source_version_id: int | None = Field(default=None,gt=0)
    source_period_id: int | None = Field(default=None,gt=0)
    @model_validator(mode='after')
    def one_source(self):
        if self.source_version_id is not None and self.source_period_id is not None:
            raise ValueError('只能选择一个复制来源')
        return self

class VersionShiftInput(Input):
    shift_key: str | None = Field(default=None,min_length=1,max_length=36,pattern=r'^[A-Za-z0-9_-]+$')
    template_id: int | None = Field(default=None,gt=0)
    work_date: date
    name: str = Field(min_length=1,max_length=32)
    start_time: time
    end_time: time
    enabled: bool = True
    demands: list[ShiftDemandInput] = Field(default_factory=list,max_length=100)
    @field_validator('name')
    @classmethod
    def clean_name(cls,value):
        value=value.strip()
        if not value: raise ValueError('班次名称不能为空')
        return value
    @model_validator(mode='after')
    def validate_shift(self):
        if self.end_time<=self.start_time: raise ValueError('结束时间必须晚于开始时间')
        ids=[item.position_id for item in self.demands]
        if len(set(ids))!=len(ids): raise ValueError('同一岗位不能重复配置')
        return self

class VersionShiftsUpdate(Input):
    expected_revision: int = Field(ge=1)
    shifts: list[VersionShiftInput] = Field(max_length=100)

class TimeWindowInput(Input):
    start_time: time
    end_time: time
    @model_validator(mode='after')
    def valid_time(self):
        if self.end_time<=self.start_time: raise ValueError('结束时间必须晚于开始时间')
        return self

class AvailabilityWindowInput(TimeWindowInput):
    weekday: int = Field(ge=1,le=7)

class WeeklyAvailabilityUpdate(Input):
    expected_revision: int = Field(ge=0)
    effective_from: date
    windows: list[AvailabilityWindowInput] = Field(default_factory=list,max_length=100)
    @field_validator('effective_from')
    @classmethod
    def monday_required(cls,value):
        if value.weekday()!=0: raise ValueError('常规可用时间必须从周一开始生效')
        return value
    @model_validator(mode='after')
    def no_overlap(self):
        for weekday in range(1,8):
            windows=sorted((window for window in self.windows if window.weekday==weekday),key=lambda item:item.start_time)
            for previous,current in zip(windows,windows[1:]):
                if current.start_time<previous.end_time: raise ValueError('同一天的可工作时间不能重叠')
        return self

class AvailabilityOverrideUpdate(Input):
    expected_revision: int = Field(ge=0)
    mode: Literal['REPLACE','BLOCK']
    windows: list[TimeWindowInput] = Field(default_factory=list,max_length=50)
    @model_validator(mode='after')
    def valid_windows(self):
        if self.mode=='BLOCK' and not self.windows: raise ValueError('扣除不可用时间至少需要一个时段')
        ordered=sorted(self.windows,key=lambda item:item.start_time)
        for previous,current in zip(ordered,ordered[1:]):
            if current.start_time<previous.end_time: raise ValueError('不可用时段不能重叠')
        return self

class PreferenceItemInput(Input):
    work_date: date
    template_id: int = Field(gt=0)
    kind: Literal['PREFER','AVOID']
    weight: int = Field(default=3,ge=1,le=5)

class PreferenceUpdate(Input):
    expected_revision: int = Field(ge=0)
    items: list[PreferenceItemInput] = Field(default_factory=list,max_length=200)
    submit: bool = False
    @model_validator(mode='after')
    def unique_items(self):
        keys=[(item.work_date,item.template_id) for item in self.items]
        if len(set(keys))!=len(keys): raise ValueError('同一天同一班次只能设置一个偏好')
        return self

class ProxiedWeeklyAvailabilityUpdate(WeeklyAvailabilityUpdate):
    reason: str = Field(min_length=1,max_length=255)
    @field_validator('reason')
    @classmethod
    def clean_reason(cls,value):
        value=value.strip()
        if not value: raise ValueError('请填写代录原因')
        return value

class ProxiedAvailabilityOverrideUpdate(AvailabilityOverrideUpdate):
    reason: str = Field(min_length=1,max_length=255)

class AvailabilityOverrideDelete(Input):
    expected_revision: int = Field(ge=1)

class ProxiedAvailabilityOverrideDelete(AvailabilityOverrideDelete):
    reason: str = Field(min_length=1,max_length=255)

class ProxiedPreferenceUpdate(PreferenceUpdate):
    reason: str = Field(min_length=1,max_length=255)

class RuleWeights(Input):
    preference: int = Field(default=30,ge=0,le=100)
    hours_balance: int = Field(default=20,ge=0,le=100)
    evening_balance: int = Field(default=10,ge=0,le=100)

class RuleVersionInput(Input):
    effective_week: date
    daily_shift_limit: int = Field(ge=1,le=10)
    weekly_minutes_limit: int = Field(ge=1,le=10080)
    consecutive_days_limit: int = Field(ge=1,le=14)
    min_rest_minutes: int = Field(ge=0,le=1440)
    weights: RuleWeights = Field(default_factory=RuleWeights)
    @field_validator('effective_week')
    @classmethod
    def monday_required(cls,value):
        if value.weekday()!=0: raise ValueError('规则生效周必须从周一开始')
        return value

class SolverTaskCreate(Input):
    period_id: int = Field(gt=0)
    draft_version_id: int = Field(gt=0)
    expected_draft_revision: int = Field(ge=1)
    base_published_version_id: int | None = Field(default=None,gt=0)
    rule_version_id: int | None = Field(default=None,gt=0)
    time_limit_seconds: int | None = Field(default=None,ge=1,le=120)

class AssignmentInput(Input):
    shift_key: str = Field(min_length=1,max_length=36,pattern=r'^[A-Za-z0-9_-]+$')
    employee_id: int = Field(gt=0)
    position_id: int = Field(gt=0)
    locked: bool = False

class AssignmentReplace(Input):
    expected_revision: int = Field(ge=1)
    items: list[AssignmentInput] = Field(default_factory=list,max_length=500)
    @model_validator(mode='after')
    def unique_employee_shift(self):
        keys=[(item.shift_key,item.employee_id) for item in self.items]
        if len(set(keys))!=len(keys): raise ValueError('同一员工在一个班次只能承担一个岗位')
        return self

class AssignmentValidation(Input):
    expected_revision: int = Field(ge=1)

class PublishRequest(Input):
    expected_draft_revision: int = Field(ge=1)
    expected_period_revision: int = Field(ge=1)
    base_published_version_id: int | None = Field(default=None,gt=0)
    expected_input_revision: int = Field(ge=0)

class CopyVersionToDraft(Input):
    expected_period_revision: int = Field(ge=1)

class DiscardVersion(Input):
    expected_revision: int = Field(ge=1)

class LeaveWindow(Input):
    start_date: date
    start_time: time
    end_date: date
    end_time: time
    @model_validator(mode='after')
    def valid_window(self):
        start=datetime.combine(self.start_date,self.start_time)
        end=datetime.combine(self.end_date,self.end_time)
        if end<=start: raise ValueError('请假结束时间必须晚于开始时间')
        if end-start>timedelta(days=31): raise ValueError('单次请假不能超过31天')
        return self

class LeaveCreate(LeaveWindow):
    reason: str = Field(min_length=1,max_length=500)
    @field_validator('reason')
    @classmethod
    def clean_reason(cls,value):
        value=value.strip()
        if not value: raise ValueError('请填写请假原因')
        return value

class LeaveReview(Input):
    decision: Literal['APPROVE','REJECT']
    expected_revision: int = Field(ge=1)
    note: str = Field(default='',max_length=500)
    @model_validator(mode='after')
    def reject_note(self):
        if self.decision=='REJECT' and not self.note.strip(): raise ValueError('拒绝请假时请填写审批说明')
        return self

class LeaveWithdraw(Input):
    expected_revision: int = Field(ge=1)

class SwapCreate(Input):
    mode: Literal['TRANSFER','EXCHANGE']
    target_employee_id: int = Field(gt=0)
    source_shift_key: str = Field(min_length=1,max_length=36,pattern=r'^[A-Za-z0-9_-]+$')
    source_position_id: int = Field(gt=0)
    target_shift_key: str | None = Field(default=None,min_length=1,max_length=36,pattern=r'^[A-Za-z0-9_-]+$')
    target_position_id: int | None = Field(default=None,gt=0)
    note: str = Field(default='',max_length=500)
    @model_validator(mode='after')
    def valid_mode(self):
        if self.mode=='TRANSFER' and (self.target_shift_key is not None or self.target_position_id is not None):
            raise ValueError('单向转交不能指定对方班次')
        if self.mode=='EXCHANGE' and (self.target_shift_key is None or self.target_position_id is None):
            raise ValueError('双向换班必须选择对方班次和岗位')
        return self

class SwapRespond(Input):
    decision: Literal['ACCEPT','REJECT']
    expected_revision: int = Field(ge=1)
    note: str = Field(default='',max_length=500)

class SwapReview(Input):
    decision: Literal['APPROVE','REJECT']
    expected_revision: int = Field(ge=1)
    note: str = Field(default='',max_length=500)
    @model_validator(mode='after')
    def reject_note(self):
        if self.decision=='REJECT' and not self.note.strip(): raise ValueError('拒绝换班时请填写审批说明')
        return self

class SwapWithdraw(Input):
    expected_revision: int = Field(ge=1)

class PublicationConfirm(Input):
    expected_revision: int = Field(ge=1)

class AdjustmentGenerate(Input):
    event_ids: list[int] = Field(min_length=1,max_length=20)
    locked_assignments: list[AssignmentInput] = Field(default_factory=list,max_length=200)
    time_limit_seconds: int = Field(default=20,ge=1,le=90)
    @field_validator('event_ids')
    @classmethod
    def unique_event_ids(cls,value):
        if len(set(value))!=len(value): raise ValueError('调班事件不能重复')
        return value

class AdjustmentApply(Input):
    expected_base_version_id: int = Field(gt=0)
    expected_input_revision: int = Field(ge=0)

class AdjustmentCandidateDiscard(Input):
    expected_revision: int = Field(ge=1)

class StoreSettingUpdate(Input):
    store_name: str = Field(min_length=1,max_length=100)
    demo_mode: bool
    solver_time_limit_seconds: int = Field(ge=1,le=120)
    expected_revision: int = Field(ge=1)
    @field_validator('store_name')
    @classmethod
    def clean_store_name(cls,value):
        value=value.strip()
        if not value: raise ValueError('门店名称不能为空')
        return value

class AIParsedOverride(Input):
    date: date
    mode: Literal['REPLACE','BLOCK']
    windows: list[TimeWindowInput] = Field(default_factory=list,max_length=20)
    needs_confirmation: bool = False
    note: str = Field(default='',max_length=200)
    @model_validator(mode='after')
    def valid_mode(self):
        if self.mode=='BLOCK' and not self.windows: raise ValueError('扣除不可用时间至少需要一个时段')
        ordered=sorted(self.windows,key=lambda item:item.start_time)
        for previous,current in zip(ordered,ordered[1:]):
            if current.start_time<previous.end_time: raise ValueError('不可用时段不能重叠')
        return self

class AIParsedPreference(Input):
    date: date
    template_code: str = Field(min_length=1,max_length=32,pattern=r'^[A-Za-z0-9_-]+$')
    kind: Literal['PREFER','AVOID']
    weight: int = Field(default=3,ge=1,le=5)
    needs_confirmation: bool = False
    note: str = Field(default='',max_length=200)

class AIParseOutput(Input):
    summary: str = Field(min_length=1,max_length=500)
    overrides: list[AIParsedOverride] = Field(default_factory=list,max_length=31)
    preferences: list[AIParsedPreference] = Field(default_factory=list,max_length=100)
    clarifications: list[str] = Field(default_factory=list,max_length=20)

class AITextInput(Input):
    text: str = Field(min_length=1,max_length=2000)
    @field_validator('text')
    @classmethod
    def clean_text(cls,value):
        value=value.strip()
        if not value: raise ValueError('请输入需求描述')
        return value

class AIConfirmOverride(Input):
    date: date
    mode: Literal['REPLACE','BLOCK']
    windows: list[TimeWindowInput] = Field(default_factory=list,max_length=20)
    @model_validator(mode='after')
    def valid_mode(self):
        if self.mode=='BLOCK' and not self.windows: raise ValueError('扣除不可用时间至少需要一个时段')
        ordered=sorted(self.windows,key=lambda item:item.start_time)
        for previous,current in zip(ordered,ordered[1:]):
            if current.start_time<previous.end_time: raise ValueError('不可用时段不能重叠')
        return self

class AIConfirmPreference(Input):
    date: date
    template_id: int = Field(gt=0)
    kind: Literal['PREFER','AVOID']
    weight: int = Field(default=3,ge=1,le=5)

class AIConfirm(Input):
    expected_revision: int = Field(ge=1)
    overrides: list[AIConfirmOverride] = Field(default_factory=list,max_length=31)
    preferences: list[AIConfirmPreference] = Field(default_factory=list,max_length=100)
    @model_validator(mode='after')
    def unique_items(self):
        override_dates=[item.date for item in self.overrides]
        if len(set(override_dates))!=len(override_dates):
            raise ValueError('日期例外不能重复')
        preference_keys=[(item.date,item.template_id) for item in self.preferences]
        if len(set(preference_keys))!=len(preference_keys):
            raise ValueError('同一天同一班次只能设置一个偏好')
        return self

class AIReject(Input):
    expected_revision: int = Field(ge=1)

class AIExplanationRequest(Input):
    period_id: int = Field(gt=0)
    candidate_id: int | None = Field(default=None,gt=0)
    question: str = Field(min_length=4,max_length=500)
    @field_validator('question')
    @classmethod
    def clean_question(cls,value):
        value=value.strip()
        if len(value)<4: raise ValueError('请完整描述需要解释的问题')
        return value

class AIExplanationOutput(Input):
    title: str = Field(min_length=1,max_length=100)
    conclusion: str = Field(min_length=1,max_length=1000)
    reasons: list[str] = Field(min_length=1,max_length=6)
    evidence: list[str] = Field(min_length=1,max_length=10)
    limitations: list[str] = Field(default_factory=list,max_length=6)
    @field_validator('reasons','evidence','limitations')
    @classmethod
    def clean_items(cls,value):
        cleaned=[]
        for item in value:
            text=item.strip()
            if not text: raise ValueError('解释条目不能为空')
            if len(text)>300: raise ValueError('单条解释不能超过300个字符')
            cleaned.append(text)
        return cleaned

class Review(Input):
    decision: Literal['APPROVE','REJECT']
    expected_revision: int = Field(ge=1)
    employee_id: int | None = None
    new_employee: EmployeeInput | None = None
    note: str = Field(default='', max_length=255)
    @model_validator(mode='after')
    def binding(self):
        if self.decision == 'APPROVE' and ((self.employee_id is None) == (self.new_employee is None)):
            raise ValueError('请选择绑定已有员工或新建员工')
        return self

class PasswordReset(Input):
    expected_revision: int = Field(ge=1)
    request_id: int | None = Field(default=None, gt=0)
    verification_note: str = Field(min_length=1, max_length=255)
    @field_validator('verification_note')
    @classmethod
    def note_required(cls,value):
        value = value.strip()
        if not value:
            raise ValueError('请填写身份核实说明')
        return value

class ManagedAccountCreate(AccountName):
    name: str = Field(min_length=1, max_length=64)
    employee_id: int | None = Field(default=None, gt=0)
    @field_validator('name')
    @classmethod
    def name_required(cls,value):
        value = value.strip()
        if not value:
            raise ValueError('姓名不能为空')
        return value

class AccountStatusChange(Input):
    status: Literal['ACTIVE','DISABLED']
    expected_revision: int = Field(ge=1)
