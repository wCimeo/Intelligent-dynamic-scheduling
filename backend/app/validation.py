from collections import defaultdict
from datetime import date


def _minutes(value):
    hour,minute=map(int,value.split(':')[:2])
    return hour*60+minute


def _duration(shift):
    return _minutes(shift['end_time'])-_minutes(shift['start_time'])


def _available(shift,day):
    start,end=_minutes(shift['start_time']),_minutes(shift['end_time'])
    return any(_minutes(window['start_time'])<=start and end<=_minutes(window['end_time']) for window in day.get('windows',[]))


def _conflict(code,message,severity='hard',**context):
    return {'rule_code':code,'message':message,'severity':severity,**{key:value for key,value in context.items() if value is not None}}


def validate_assignments(snapshot,assignments):
    shifts={shift['shift_key']:shift for shift in snapshot.get('shifts',[])}
    shifts_by_date=defaultdict(list)
    for shift in shifts.values(): shifts_by_date[shift['work_date']].append(shift)
    employees={employee['id']:employee for employee in snapshot.get('employees',[])}
    rules=snapshot.get('rules',{})
    conflicts=[]
    warnings=[]
    employee_shift_keys=defaultdict(set)
    coverage=defaultdict(int)
    employee_minutes=defaultdict(int)
    evening_counts=defaultdict(int)
    assignment_minutes=0
    assignment_count=0

    for assignment in assignments:
        shift=shifts.get(assignment.get('shift_key'))
        employee=employees.get(str(assignment.get('employee_id')))
        if not shift:
            conflicts.append(_conflict('UNKNOWN_SHIFT','安排引用了不存在的班次',shift_key=assignment.get('shift_key')))
            continue
        if not shift.get('enabled',True):
            conflicts.append(_conflict('DISABLED_SHIFT','已关闭班次不能保留人员安排',employee_id=str(assignment.get('employee_id')),shift_key=shift['shift_key']))
        if not employee:
            conflicts.append(_conflict('EMPLOYEE_INACTIVE','安排中的员工不存在或当前不可参与排班',employee_id=str(assignment.get('employee_id')),shift_key=shift['shift_key']))
            continue
        demand=next((item for item in shift.get('demands',[]) if item['position_id']==str(assignment.get('position_id'))),None)
        if not demand:
            conflicts.append(_conflict('POSITION_NOT_IN_SHIFT','岗位不属于该班次需求',employee_id=employee['id'],shift_key=shift['shift_key'],position_id=str(assignment.get('position_id'))))
            continue
        coverage[(shift['shift_key'],demand['position_id'])]+=1
        employee_shift_keys[(employee['id'],shift['shift_key'])].add(demand['position_id'])
        if not set(demand.get('skill_ids',[])).issubset(set(employee.get('skills',[]))):
            conflicts.append(_conflict('SKILL_MISMATCH','员工未具备岗位要求的全部技能',employee_id=employee['id'],shift_key=shift['shift_key'],position_id=demand['position_id']))
        day=next((item for item in employee.get('availability',[]) if item['date']==shift['work_date']),None)
        if not day or not _available(shift,day):
            conflicts.append(_conflict('UNAVAILABLE','班次未完整落入员工当天可用时间',employee_id=employee['id'],shift_key=shift['shift_key'],position_id=demand['position_id']))
        employee_minutes[employee['id']]+=_duration(shift)
        assignment_minutes+=_duration(shift)
        assignment_count+=1
        if shift.get('evening'): evening_counts[employee['id']]+=1

    for (employee_id,shift_key),positions in employee_shift_keys.items():
        if len(positions)>1:
            conflicts.append(_conflict('MULTIPLE_POSITIONS','同一员工在同一班次承担了多个岗位',employee_id=employee_id,shift_key=shift_key))

    required_positions=0
    for shift in shifts.values():
        if not shift.get('enabled',True): continue
        for demand in shift.get('demands',[]):
            required=demand['required_count']
            required_positions+=required
            actual=coverage[(shift['shift_key'],demand['position_id'])]
            if actual<required:
                conflicts.append(_conflict('POSITION_SHORTAGE',f"岗位缺少 {required-actual} 人",
                    shift_key=shift['shift_key'],position_id=demand['position_id'],date=shift['work_date']))
            elif actual>required:
                conflicts.append(_conflict('EXTRA_ASSIGNMENT',f"岗位多安排 {actual-required} 人",
                    shift_key=shift['shift_key'],position_id=demand['position_id'],date=shift['work_date']))

    for employee_id,employee in employees.items():
        limit=min(int(employee.get('weekly_limit_minutes',10080)),int(rules.get('weekly_minutes_limit',10080)))
        if employee_minutes[employee_id]>limit:
            conflicts.append(_conflict('WEEKLY_MINUTES_EXCEEDED',f"周工时超过上限 {employee_minutes[employee_id]-limit} 分钟",employee_id=employee_id))
        for work_date in snapshot.get('week_dates',[]):
            day_shifts=[assignment for assignment in assignments if str(assignment.get('employee_id'))==employee_id and shifts.get(assignment.get('shift_key')) and shifts[assignment['shift_key']]['work_date']==work_date]
            if len(day_shifts)>int(rules.get('daily_shift_limit',1)):
                conflicts.append(_conflict('DAILY_SHIFT_LIMIT','每日班次数超过规则上限',employee_id=employee_id,date=work_date))
        employee_shifts=[shift for shift in shifts.values() if (employee_id,shift['shift_key']) in employee_shift_keys]
        for index,first in enumerate(employee_shifts):
            first_date=date.fromisoformat(first['work_date'])
            for second in employee_shifts[index+1:]:
                second_date=date.fromisoformat(second['work_date'])
                if first_date==second_date:
                    if _minutes(first['start_time'])<_minutes(second['end_time']) and _minutes(second['start_time'])<_minutes(first['end_time']):
                        conflicts.append(_conflict('TIME_OVERLAP','同一员工的班次时间重叠',employee_id=employee_id,date=first['work_date']))
                elif first_date<second_date:
                    rest=(second_date-first_date).days*1440+_minutes(second['start_time'])-_minutes(first['end_time'])
                    if rest<int(rules.get('min_rest_minutes',600)):
                        conflicts.append(_conflict('INSUFFICIENT_REST','相邻班次休息时间不足',employee_id=employee_id,date=second['work_date']))
        worked_dates=sorted(set(shifts[shift_key]['work_date'] for employee_shift,shift_key in employee_shift_keys if employee_shift==employee_id))
        maximum=int(rules.get('consecutive_days_limit',6))
        for index in range(max(0,len(snapshot.get('week_dates',[]))-maximum)):
            window=snapshot['week_dates'][index:index+maximum+1]
            if all(work_date in worked_dates for work_date in window):
                conflicts.append(_conflict('CONSECUTIVE_DAYS_EXCEEDED','连续工作天数超过规则上限',employee_id=employee_id,date=window[-1]))

    preference_total=0
    preference_satisfied=0
    for employee in employees.values():
        assigned_template_dates={(shifts[item['shift_key']]['work_date'],shifts[item['shift_key']].get('template_id')) for item in assignments if str(item.get('employee_id'))==employee['id'] and item.get('shift_key') in shifts}
        for preference in employee.get('preferences',[]):
            preference_total+=1
            satisfied=(preference['work_date'],preference['template_id']) in assigned_template_dates
            if preference['kind']=='PREFER':
                if satisfied: preference_satisfied+=1
                else: warnings.append(_conflict('PREFERENCE_UNMET','希望安排的班次未满足','soft',employee_id=employee['id'],date=preference['work_date']))
            else:
                if satisfied: warnings.append(_conflict('PREFERENCE_AVOIDED','安排了员工希望避开的班次','soft',employee_id=employee['id'],date=preference['work_date']))
                else: preference_satisfied+=1

    minutes=[employee_minutes[employee_id] for employee_id in employees]
    metrics={
        'required_positions':required_positions,'assignment_count':assignment_count,
        'coverage_gap':max(0,required_positions-assignment_count),
        'assignment_minutes':assignment_minutes,
        'preference_total':preference_total,'preference_satisfied':preference_satisfied,
        'preference_rate':round(preference_satisfied/preference_total*100,1) if preference_total else None,
        'employee_minutes':{employee_id:employee_minutes[employee_id] for employee_id in employees},
        'evening_counts':{employee_id:evening_counts[employee_id] for employee_id in employees},
        'min_minutes':min(minutes) if minutes else 0,'max_minutes':max(minutes) if minutes else 0
    }
    return {'valid':len(conflicts)==0,'hard_conflicts':conflicts,'soft_warnings':warnings,'metrics':metrics,
        'input_revision':snapshot.get('draft_revision',0)}


def eligible_employees(snapshot,shift_key,position_id,assignments):
    shift=next((item for item in snapshot.get('shifts',[]) if item['shift_key']==shift_key),None)
    if not shift: return []
    demand=next((item for item in shift.get('demands',[]) if item['position_id']==str(position_id)),None)
    if not demand: return []
    rules=snapshot.get('rules',{})
    shift_lookup={item['shift_key']:item for item in snapshot.get('shifts',[])}
    result=[]
    for employee in snapshot.get('employees',[]):
        reasons=[]
        employee_id=employee['id']
        if not set(demand.get('skill_ids',[])).issubset(set(employee.get('skills',[]))):
            reasons.append({'code':'SKILL_MISSING','message':'未具备岗位要求的全部技能'})
        day=next((item for item in employee.get('availability',[]) if item['date']==shift['work_date']),None)
        if not day or not _available(shift,day):
            reasons.append({'code':'UNAVAILABLE','message':'班次未完整落入当天可用时间'})
        if any(str(item.get('employee_id'))==employee_id and item.get('shift_key')==shift_key for item in assignments):
            reasons.append({'code':'ALREADY_ASSIGNED_SHIFT','message':'已在该班次承担其他岗位'})
        day_assignments=[item for item in assignments if str(item.get('employee_id'))==employee_id and item.get('shift_key') in {candidate['shift_key'] for candidate in snapshot.get('shifts',[]) if candidate['work_date']==shift['work_date']}]
        if len(day_assignments)>=int(rules.get('daily_shift_limit',1)):
            reasons.append({'code':'DAILY_SHIFT_LIMIT','message':'当天班次数已达上限'})
        week_assignments=[item for item in assignments if str(item.get('employee_id'))==employee_id and item.get('shift_key') in shift_lookup]
        current_week_minutes=sum(_duration(shift_lookup[item['shift_key']]) for item in week_assignments)
        if current_week_minutes+_duration(shift)>min(int(employee.get('weekly_limit_minutes',10080)),int(rules.get('weekly_minutes_limit',10080))):
            reasons.append({'code':'WEEKLY_MINUTES_LIMIT','message':'安排后将超过每周工时上限'})
        result.append({'employee_id':employee_id,'employee_no':employee['employee_no'],'name':employee['name'],'eligible':not reasons,'reasons':reasons})
    return result
