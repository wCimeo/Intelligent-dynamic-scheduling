from datetime import date, timedelta

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AuditEvent, StoreSetting, User, now
from .schemas import StoreSettingUpdate


class SettingsProblem(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


ACTION_LABELS = {
    'account.password_changed': '修改密码',
    'account.created_by_manager': '管理员创建账号',
    'account.reviewed': '审核注册账号',
    'account.status_changed': '变更账号状态',
    'account.password_reset': '重置账号密码',
    'employee.created': '创建员工档案',
    'employee.updated': '更新员工资料',
    'employee.skills_changed': '更新员工技能',
    'employee.status_changed': '变更员工状态',
    'skill.created': '创建技能', 'skill.updated': '更新技能',
    'position.created': '创建岗位', 'position.updated': '更新岗位',
    'position.skills_changed': '更新岗位技能',
    'shift_template.created': '创建班次模板', 'shift_template.updated': '更新班次模板',
    'schedule_period.created': '创建排班周期',
    'schedule_draft.created': '创建排班草稿',
    'schedule_draft.updated': '更新排班草稿',
    'assignments.replaced': '更新人员安排',
    'rule_version.created': '创建排班规则',
    'solver_task.created': '创建求解任务',
    'schedule.published': '发布班表',
    'schedule.restored_to_draft': '历史版本恢复为草稿',
    'schedule.draft_discarded': '废弃排班草稿',
    'leave.requested': '提交请假申请', 'leave.approved': '批准请假', 'leave.rejected': '拒绝请假',
    'leave.withdrawn': '撤回请假申请',
    'swap.requested': '发起换班', 'swap.target_accepted': '接收人接受换班',
    'swap.target_rejected': '接收人拒绝换班', 'swap.withdrawn': '撤回换班',
    'swap.approved': '批准换班', 'swap.rejected': '拒绝换班',
    'adjustment.candidates_generated': '生成调班方案', 'adjustment.applied': '应用调班方案',
    'publication.confirmed': '确认班表版本',
    'settings.updated': '更新基础设置',
    'demo.seed_created': '生成演示数据',
}


def _ensure_settings(session):
    item = session.get(StoreSetting, 1)
    if not item:
        item = StoreSetting(id=1, store_name='校园咖啡门店', timezone='Asia/Shanghai',
            demo_mode=False, solver_time_limit_seconds=30, row_version=1)
        session.add(item)
        session.flush()
    return item


def setting_data(item, public=False):
    data = {'store_name': item.store_name, 'timezone': item.timezone, 'demo_mode': item.demo_mode, 'revision': item.row_version}
    if not public:
        data.update({'solver_time_limit_seconds': item.solver_time_limit_seconds,
            'updated_by': str(item.updated_by) if item.updated_by else None,
            'updated_at': item.updated_at.isoformat() + 'Z'})
    return data


def register_settings_routes(app, *, db_dependency, business_user_dependency, manager_dependency, envelope, timestamp):
    @app.exception_handler(SettingsProblem)
    async def settings_problem(request, exc):
        return JSONResponse(envelope(request, message=exc.message, code=exc.code), status_code=exc.status)

    @app.get('/api/v1/settings/public')
    def public_settings(request: Request, user=Depends(business_user_dependency), session: Session = Depends(db_dependency)):
        item = _ensure_settings(session)
        session.commit()
        return envelope(request, setting_data(item, public=True))

    @app.get('/api/v1/settings')
    def settings(request: Request, manager=Depends(manager_dependency), session: Session = Depends(db_dependency)):
        item = _ensure_settings(session)
        session.commit()
        return envelope(request, setting_data(item))

    @app.patch('/api/v1/settings')
    def update_settings(body: StoreSettingUpdate, request: Request, manager=Depends(manager_dependency),
                        session: Session = Depends(db_dependency)):
        item = session.scalar(select(StoreSetting).where(StoreSetting.id == 1).with_for_update())
        if not item:
            item = _ensure_settings(session)
        if item.row_version != body.expected_revision:
            raise SettingsProblem(409, 'VERSION_CONFLICT', '设置已变化，请刷新后重试')
        before = {'store_name': item.store_name, 'demo_mode': item.demo_mode,
            'solver_time_limit_seconds': item.solver_time_limit_seconds}
        item.store_name = body.store_name
        item.demo_mode = body.demo_mode
        item.solver_time_limit_seconds = body.solver_time_limit_seconds
        item.updated_by = manager.id
        item.updated_at = now()
        item.row_version += 1
        session.add(AuditEvent(actor_id=manager.id, action='settings.updated', entity_id=item.id,
            summary={'before': before, 'after': {'store_name': item.store_name, 'demo_mode': item.demo_mode,
                'solver_time_limit_seconds': item.solver_time_limit_seconds}}))
        session.commit()
        return envelope(request, setting_data(item), '基础设置已更新')

    @app.get('/api/v1/audit-events')
    def audit_feed(request: Request, category: str = Query('', max_length=32), actor_search: str = Query('', max_length=64),
                   entity_id: int | None = Query(None, ge=1), date_from: date | None = None, date_to: date | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                   manager=Depends(manager_dependency), session: Session = Depends(db_dependency)):
        query = select(AuditEvent, User).outerjoin(User, AuditEvent.actor_id == User.id)
        if category:
            query = query.where(AuditEvent.action.like(f'{category}.%'))
        if actor_search:
            query = query.where(User.username.contains(actor_search, autoescape=True) |
                User.display_name.contains(actor_search, autoescape=True))
        if entity_id is not None:
            query = query.where(AuditEvent.entity_id == entity_id)
        if date_from:
            query = query.where(AuditEvent.created_at >= date_from)
        if date_to:
            query = query.where(AuditEvent.created_at < date_to + timedelta(days=1))
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        rows = session.execute(query.order_by(AuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
        items = [{
            'id': str(event.id), 'actor_id': str(event.actor_id) if event.actor_id else None,
            'actor_name': actor.display_name if actor else None, 'actor_username': actor.username if actor else None,
            'action': event.action, 'category': event.action.split('.')[0],
            'action_label': ACTION_LABELS.get(event.action, event.action),
            'entity_id': str(event.entity_id) if event.entity_id else None,
            'summary': event.summary, 'created_at': timestamp(event.created_at),
        } for event, actor in rows]
        return envelope(request, {'items': items, 'total': total, 'page': page, 'page_size': page_size})
