import time
from collections import defaultdict
from datetime import date,timedelta
from ortools.sat.python import cp_model


def _minutes(value):
    hour,minute=map(int,value.split(':')[:2])
    return hour*60+minute


def _shift_minutes(shift):
    return _minutes(shift['end_time'])-_minutes(shift['start_time'])


def _inside_available(shift,day):
    start,end=_minutes(shift['start_time']),_minutes(shift['end_time'])
    return any(_minutes(window['start_time'])<=start and end<=_minutes(window['end_time']) for window in day.get('windows',[]))


def _base_result(status,issues,started):
    return {'status':status,'issues':issues,'assignments':[],
        'metrics':{'assignment_count':0,'required_minutes':0,'employee_minutes':{},
            'evening_counts':{},'preference_satisfied':0,'preference_total':0},
        'solve_ms':round((time.perf_counter()-started)*1000)}


def solve_snapshot(snapshot,time_limit_seconds=30):
    started=time.perf_counter()
    shifts=[shift for shift in snapshot.get('shifts',[]) if shift.get('enabled',True)]
    employees=snapshot.get('employees',[])
    rules=snapshot.get('rules',{})
    demands=[]
    issues=[]
    available_by_employee={employee['id']:{day['date']:day for day in employee.get('availability',[])} for employee in employees}
    employee_skills={employee['id']:set(employee.get('skills',[])) for employee in employees}
    candidate_map={}

    for shift in shifts:
        for demand in shift.get('demands',[]):
            if demand['required_count']<=0: continue
            candidates=[]
            for employee in employees:
                day=available_by_employee[employee['id']].get(shift['work_date'])
                if set(demand.get('skill_ids',[])).issubset(employee_skills[employee['id']]) and day and _inside_available(shift,day):
                    candidates.append(employee['id'])
            if len(candidates)<demand['required_count']:
                issues.append({'code':'QUALIFIED_AVAILABLE_SHORTAGE','work_date':shift['work_date'],
                    'shift_name':shift['name'],'position_name':demand['position_name'],
                    'required':demand['required_count'],'available':len(candidates)})
            candidate_map[(shift['id'],demand['position_id'])]=set(candidates)
            demands.append((shift,demand,candidates))

    for locked in snapshot.get('locked_assignments',[]):
        if locked['employee_id'] not in candidate_map.get((locked['version_shift_id'],locked['position_id']),set()):
            issues.append({'code':'LOCKED_ASSIGNMENT_UNAVAILABLE','message':'锁定安排中的员工当前不再满足技能或可用时间',
                'employee_id':locked['employee_id'],'shift_key':locked.get('shift_key'),'position_id':locked['position_id']})

    if not demands:
        issues.append({'code':'NO_ENABLED_DEMAND','message':'草稿中没有需要安排的启用岗位需求'})
    if issues:
        return _base_result('INFEASIBLE',issues,started)

    model=cp_model.CpModel()
    x={}
    for shift,demand,candidates in demands:
        for employee_id in candidates:
            x[(employee_id,shift['id'],demand['position_id'])]=model.NewBoolVar(
                f"x_{employee_id}_{shift['id']}_{demand['position_id']}")

    for locked in snapshot.get('locked_assignments',[]):
        variable=x.get((locked['employee_id'],locked['version_shift_id'],locked['position_id']))
        if variable is not None: model.Add(variable==1)

    for shift,demand,candidates in demands:
        model.Add(sum(x[(employee_id,shift['id'],demand['position_id'])] for employee_id in candidates)==demand['required_count'])

    shifts_by_date=defaultdict(list)
    shifts_by_id={shift['id']:shift for shift in shifts}
    for shift in shifts:
        shifts_by_date[shift['work_date']].append(shift)
    for shift in shifts:
        for employee in employees:
            model.Add(sum(value for (employee_id,shift_id,position_id),value in x.items() if employee_id==employee['id'] and shift_id==shift['id'])<=1)

    daily_limit=int(rules.get('daily_shift_limit',1))
    for employee in employees:
        for work_date in sorted(shifts_by_date):
            model.Add(sum(value for (employee_id,shift_id,position_id),value in x.items()
                if employee_id==employee['id'] and shifts_by_id[shift_id]['work_date']==work_date)<=daily_limit)

    for employee in employees:
        employee_id=employee['id']
        limit=min(int(employee.get('weekly_limit_minutes',10080)),int(rules.get('weekly_minutes_limit',10080)))
        model.Add(sum(value*_shift_minutes(shifts_by_id[shift_id]) for (candidate_id,shift_id,position_id),value in x.items() if candidate_id==employee_id)<=limit)
        employee_shifts=[shift for shift in shifts if any((employee_id,shift['id'],demand['position_id']) in x for demand in shift.get('demands',[]))]
        for index,first in enumerate(employee_shifts):
            first_expr=sum(value for (candidate_id,shift_id,position_id),value in x.items() if candidate_id==employee_id and shift_id==first['id'])
            for second in employee_shifts[index+1:]:
                second_expr=sum(value for (candidate_id,shift_id,position_id),value in x.items() if candidate_id==employee_id and shift_id==second['id'])
                first_date=date.fromisoformat(first['work_date'])
                second_date=date.fromisoformat(second['work_date'])
                if first_date==second_date:
                    if _minutes(first['start_time'])<_minutes(second['end_time']) and _minutes(second['start_time'])<_minutes(first['end_time']):
                        model.Add(first_expr+second_expr<=1)
                elif first_date<second_date:
                    rest=(second_date-first_date).days*1440+_minutes(second['start_time'])-_minutes(first['end_time'])
                    if rest<int(rules.get('min_rest_minutes',600)):
                        model.Add(first_expr+second_expr<=1)

    worked={}
    week_start=date.fromisoformat(snapshot['week_start'])
    dates=[(week_start+timedelta(days=offset)).isoformat() for offset in range(7)]
    for employee in employees:
        employee_id=employee['id']
        for work_date in dates:
            worked[(employee_id,work_date)]=model.NewBoolVar(f"worked_{employee_id}_{work_date}")
            day_expr=sum(value for (candidate_id,shift_id,position_id),value in x.items()
                if candidate_id==employee_id and shifts_by_id[shift_id]['work_date']==work_date)
            model.Add(worked[(employee_id,work_date)]<=day_expr)
            for shift in shifts_by_date.get(work_date,[]):
                shift_expr=sum(value for (candidate_id,shift_id,position_id),value in x.items()
                    if candidate_id==employee_id and shift_id==shift['id'])
                model.Add(worked[(employee_id,work_date)]>=shift_expr)
        maximum=int(rules.get('consecutive_days_limit',6))
        for start in range(max(0,len(dates)-maximum)):
            model.Add(sum(worked[(employee_id,work_date)] for work_date in dates[start:start+maximum+1])<=maximum)

    objective=[]
    preference_satisfied=[]
    preference_total=0
    preference_weight=int((rules.get('weights') or {}).get('preference',30))
    shift_by_date_template={}
    for shift in shifts:
        if shift.get('template_id'):
            shift_by_date_template[(shift['work_date'],shift['template_id'])]=shift
    for employee in employees:
        employee_id=employee['id']
        for preference in employee.get('preferences',[]):
            shift=shift_by_date_template.get((preference['work_date'],preference['template_id']))
            if not shift: continue
            assigned=sum(value for (candidate_id,shift_id,position_id),value in x.items()
                if candidate_id==employee_id and shift_id==shift['id'])
            satisfaction=model.NewBoolVar(f"preference_{employee_id}_{preference['id']}")
            preference_total+=1
            if preference['kind']=='PREFER':
                model.Add(satisfaction<=assigned)
            else:
                model.Add(satisfaction+assigned<=1)
            preference_satisfied.append(satisfaction)
            objective.append(preference_weight*int(preference['weight'])*satisfaction)

    candidate_employee_ids={employee_id for employee_id,shift_id,position_id in x}
    if candidate_employee_ids:
        total_required_minutes=sum(demand['required_count']*_shift_minutes(shift) for shift,demand,candidates in demands)
        target_minutes=total_required_minutes//len(candidate_employee_ids)
        hours_weight=int((rules.get('weights') or {}).get('hours_balance',20))
        max_minutes=max(total_required_minutes,1)
        for employee_id in candidate_employee_ids:
            minutes_expr=sum(value*_shift_minutes(shifts_by_id[shift_id]) for (candidate_id,shift_id,position_id),value in x.items() if candidate_id==employee_id)
            deviation=model.NewIntVar(0,max_minutes*2,f'hours_deviation_{employee_id}')
            deviation_hours=model.NewIntVar(0,max_minutes*2,f'hours_deviation_hours_{employee_id}')
            model.AddAbsEquality(deviation,minutes_expr-target_minutes)
            model.AddDivisionEquality(deviation_hours,deviation,60)
            objective.append(-hours_weight*deviation_hours)

        evening_demand=sum(demand['required_count'] for shift,demand,candidates in demands if shift.get('evening'))
        target_evening=evening_demand//len(candidate_employee_ids)
        evening_weight=int((rules.get('weights') or {}).get('evening_balance',10))
        for employee_id in candidate_employee_ids:
            evening_expr=sum(value for (candidate_id,shift_id,position_id),value in x.items()
                if candidate_id==employee_id and shifts_by_id[shift_id].get('evening'))
            deviation=model.NewIntVar(0,max(evening_demand,len(demands)),f'evening_deviation_{employee_id}')
            model.AddAbsEquality(deviation,evening_expr-target_evening)
            objective.append(-evening_weight*deviation)

    model.Maximize(sum(objective))
    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=max(1,min(int(time_limit_seconds),120))
    solver.parameters.num_search_workers=4
    status=solver.Solve(model)
    if status==cp_model.INFEASIBLE:
        return _base_result('INFEASIBLE',[{'code':'CONSTRAINTS_INFEASIBLE','message':'在现有人员、时间与规则约束下无可行方案'}],started)
    if status==cp_model.UNKNOWN:
        return _base_result('UNKNOWN',[{'code':'SOLVER_TIMEOUT','message':'求解达到时间上限，未能在限时内找到方案'}],started)
    if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
        return _base_result('FAILED',[{'code':'SOLVER_ERROR','message':'求解器未返回可用结果'}],started)

    employee_by_id={employee['id']:employee for employee in employees}
    assignments=[]
    for (employee_id,shift_id,position_id),variable in x.items():
        if solver.Value(variable):
            shift=shifts_by_id[shift_id]
            demand=next(item for item in shift['demands'] if item['position_id']==position_id)
            assignments.append({'version_shift_id':shift_id,'employee_id':employee_id,'position_id':position_id,
                'employee_name':employee_by_id[employee_id]['name'],'position_name':demand['position_name'],
                'work_date':shift['work_date'],'shift_name':shift['name']})
    employee_minutes={}
    evening_counts={}
    for employee_id in employee_by_id:
        employee_minutes[employee_id]=sum(_shift_minutes(shifts_by_id[item['version_shift_id']]) for item in assignments if item['employee_id']==employee_id)
        evening_counts[employee_id]=sum(1 for item in assignments if item['employee_id']==employee_id and shifts_by_id[item['version_shift_id']].get('evening'))
    satisfied=sum(solver.Value(variable) for variable in preference_satisfied)
    return {
        'status':'OPTIMAL' if status==cp_model.OPTIMAL else 'FEASIBLE',
        'issues':[],
        'assignments':assignments,
        'metrics':{
            'assignment_count':len(assignments),
            'required_minutes':sum(_shift_minutes(shifts_by_id[item['version_shift_id']]) for item in assignments),
            'employee_minutes':employee_minutes,
            'evening_counts':evening_counts,
            'preference_satisfied':satisfied,
            'preference_total':preference_total,
            'min_minutes':min(employee_minutes.values()) if employee_minutes else 0,
            'max_minutes':max(employee_minutes.values()) if employee_minutes else 0
        },
        'solve_ms':round((time.perf_counter()-started)*1000)
    }


def solve_repair_candidates(snapshot,base_assignments,time_limit_seconds=20,max_candidates=3):
    started=time.perf_counter()
    shifts=[shift for shift in snapshot.get('shifts',[]) if shift.get('enabled',True)]
    shift_by_key={shift['shift_key']:shift for shift in shifts}
    shift_by_id={shift['id']:shift for shift in shifts}
    employees=snapshot.get('employees',[])
    employee_by_id={employee['id']:employee for employee in employees}
    employee_skills={employee['id']:set(employee.get('skills',[])) for employee in employees}
    availability={employee['id']:{day['date']:day for day in employee.get('availability',[])} for employee in employees}
    rules=snapshot.get('rules',{})
    demands=[]
    issues=[]
    base=set()
    for item in base_assignments:
        shift=shift_by_key.get(item.get('shift_key'))
        if shift:
            base.add((shift['id'],str(item['employee_id']),str(item['position_id'])))
    for shift in shifts:
        for demand in shift.get('demands',[]):
            if demand['required_count']<=0: continue
            candidates=[]
            for employee in employees:
                day=availability[employee['id']].get(shift['work_date'])
                if set(demand.get('skill_ids',[])).issubset(employee_skills[employee['id']]) and day and _inside_available(shift,day):
                    candidates.append(employee['id'])
            if len(candidates)<demand['required_count']:
                issues.append({'code':'QUALIFIED_AVAILABLE_SHORTAGE','work_date':shift['work_date'],
                    'shift_name':shift['name'],'position_name':demand['position_name'],
                    'required':demand['required_count'],'available':len(candidates)})
            demands.append((shift,demand,candidates))
    if issues or not demands:
        return {'status':'INFEASIBLE','issues':issues or [{'code':'NO_ENABLED_DEMAND'}],
            'candidates':[],'solve_ms':round((time.perf_counter()-started)*1000)}

    model=cp_model.CpModel()
    x={}
    for shift,demand,candidates in demands:
        for employee_id in candidates:
            x[(employee_id,shift['id'],demand['position_id'])]=model.NewBoolVar(f"repair_{employee_id}_{shift['id']}_{demand['position_id']}")
    for shift,demand,candidates in demands:
        model.Add(sum(x[(employee_id,shift['id'],demand['position_id'])] for employee_id in candidates)==demand['required_count'])
    shifts_by_date=defaultdict(list); shifts_by_id={shift['id']:shift for shift in shifts}
    for shift in shifts: shifts_by_date[shift['work_date']].append(shift)
    for shift in shifts:
        for employee in employees:
            model.Add(sum(value for (employee_id,shift_id,position_id),value in x.items()
                if employee_id==employee['id'] and shift_id==shift['id'])<=1)
    for employee in employees:
        for work_date in sorted(shifts_by_date):
            model.Add(sum(value for (employee_id,shift_id,position_id),value in x.items()
                if employee_id==employee['id'] and shifts_by_id[shift_id]['work_date']==work_date)<=int(rules.get('daily_shift_limit',1)))
        limit=min(int(employee.get('weekly_limit_minutes',10080)),int(rules.get('weekly_minutes_limit',10080)))
        model.Add(sum(value*_shift_minutes(shifts_by_id[shift_id]) for (candidate_id,shift_id,position_id),value in x.items()
            if candidate_id==employee['id'])<=limit)
        employee_shifts=[shift for shift in shifts if any((employee['id'],shift['id'],demand['position_id']) in x for demand in shift.get('demands',[]))]
        for index,first in enumerate(employee_shifts):
            first_expr=sum(value for (candidate_id,shift_id,position_id),value in x.items() if candidate_id==employee['id'] and shift_id==first['id'])
            for second in employee_shifts[index+1:]:
                second_expr=sum(value for (candidate_id,shift_id,position_id),value in x.items() if candidate_id==employee['id'] and shift_id==second['id'])
                first_date=date.fromisoformat(first['work_date']); second_date=date.fromisoformat(second['work_date'])
                if first_date==second_date and _minutes(first['start_time'])<_minutes(second['end_time']) and _minutes(second['start_time'])<_minutes(first['end_time']):
                    model.Add(first_expr+second_expr<=1)
                elif first_date<second_date:
                    rest=(second_date-first_date).days*1440+_minutes(second['start_time'])-_minutes(first['end_time'])
                    if rest<int(rules.get('min_rest_minutes',600)): model.Add(first_expr+second_expr<=1)
    week_start=date.fromisoformat(snapshot['week_start'])
    dates=[(week_start+timedelta(days=offset)).isoformat() for offset in range(7)]
    worked={}
    for employee in employees:
        for work_date in dates:
            worked[(employee['id'],work_date)]=model.NewBoolVar(f"repair_worked_{employee['id']}_{work_date}")
            day_expr=sum(value for (candidate_id,shift_id,position_id),value in x.items()
                if candidate_id==employee['id'] and shifts_by_id[shift_id]['work_date']==work_date)
            model.Add(worked[(employee['id'],work_date)]<=day_expr)
            for shift in shifts_by_date.get(work_date,[]):
                shift_expr=sum(value for (candidate_id,shift_id,position_id),value in x.items() if candidate_id==employee['id'] and shift_id==shift['id'])
                model.Add(worked[(employee['id'],work_date)]>=shift_expr)
        maximum=int(rules.get('consecutive_days_limit',6))
        for start in range(max(0,7-maximum)):
            model.Add(sum(worked[(employee['id'],work_date)] for work_date in dates[start:start+maximum+1])<=maximum)

    locked={(item['version_shift_id'],item['employee_id'],item['position_id']) for item in snapshot.get('locked_assignments',[])}
    change_cost=[]
    for (employee_id,shift_id,position_id),variable in x.items():
        edge=(shift_id,employee_id,position_id)
        change_cost.append(10000*(1-variable) if edge in base else 10000*variable)
    for key in locked:
        shift_id,employee_id,position_id=key
        variable=x.get((employee_id,shift_id,position_id))
        if variable is not None: model.Add(variable==1)

    preference_rewards=[]; preference_vars=[]; balance_penalties=[]
    pref_weight=int((rules.get('weights') or {}).get('preference',30))
    shift_by_date_template={(shift['work_date'],shift.get('template_id')):shift for shift in shifts if shift.get('template_id')}
    for employee in employees:
        for preference in employee.get('preferences',[]):
            shift=shift_by_date_template.get((preference['work_date'],preference['template_id']))
            if not shift: continue
            assigned=sum(value for (candidate_id,shift_id,position_id),value in x.items() if candidate_id==employee['id'] and shift_id==shift['id'])
            sat=model.NewBoolVar(f"repair_pref_{employee['id']}_{preference['id']}")
            if preference['kind']=='PREFER': model.Add(sat<=assigned)
            else: model.Add(sat+assigned<=1)
            preference_rewards.append(pref_weight*int(preference['weight'])*sat)
            preference_vars.append(sat)

    candidate_employee_ids={employee_id for employee_id,shift_id,position_id in x}
    if candidate_employee_ids:
        total_minutes=sum(demand['required_count']*_shift_minutes(shift) for shift,demand,candidates in demands)
        target=total_minutes//len(candidate_employee_ids)
        max_minutes=max(total_minutes,1)
        hours_weight=int((rules.get('weights') or {}).get('hours_balance',20))
        evening_total=sum(demand['required_count'] for shift,demand,candidates in demands if shift.get('evening'))
        evening_target=evening_total//len(candidate_employee_ids)
        evening_weight=int((rules.get('weights') or {}).get('evening_balance',10))
        for employee_id in candidate_employee_ids:
            minutes_expr=sum(value*_shift_minutes(shifts_by_id[shift_id]) for (candidate_id,shift_id,position_id),value in x.items() if candidate_id==employee_id)
            dev=model.NewIntVar(0,max_minutes*2,f'repair_hours_dev_{employee_id}')
            dev_hours=model.NewIntVar(0,max_minutes*2,f'repair_hours_dev_h_{employee_id}')
            model.AddAbsEquality(dev,minutes_expr-target); model.AddDivisionEquality(dev_hours,dev,60)
            model.Add(dev_hours<=1000)
            evening_expr=sum(value for (candidate_id,shift_id,position_id),value in x.items() if candidate_id==employee_id and shifts_by_id[shift_id].get('evening'))
            eve_dev=model.NewIntVar(0,max(evening_total,len(demands)),f'repair_evening_dev_{employee_id}')
            model.AddAbsEquality(eve_dev,evening_expr-evening_target)
            balance_penalties.extend([hours_weight*dev_hours,evening_weight*eve_dev])

    model.Minimize(sum(change_cost)-sum(preference_rewards)+sum(balance_penalties))
    solver=cp_model.CpSolver(); solver.parameters.max_time_in_seconds=max(1,min(int(time_limit_seconds),120)); solver.parameters.num_search_workers=4
    candidates=[]; seen=set(); status=None
    for index in range(max_candidates):
        status=solver.Solve(model)
        if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE): break
        assignments=[]
        for key,variable in x.items():
            if solver.Value(variable):
                employee_id,shift_id,position_id=key; shift=shifts_by_id[shift_id]
                demand=next(item for item in shift['demands'] if item['position_id']==position_id)
                assignments.append({'shift_key':shift['shift_key'],'version_shift_id':shift_id,
                    'employee_id':employee_id,'employee_name':employee_by_id[employee_id]['name'],
                    'position_id':position_id,'position_name':demand['position_name']})
        signature=tuple(sorted((item['version_shift_id'],item['employee_id'],item['position_id']) for item in assignments))
        if signature in seen:
            model.Add(sum(variable if not solver.Value(variable) else 1-variable for variable in x.values())>=1)
            continue
        seen.add(signature)
        current_set={(item['version_shift_id'],item['employee_id'],item['position_id']) for item in assignments}
        added=sorted(current_set-base); removed=sorted(base-current_set)
        base_slots=defaultdict(set); candidate_slots=defaultdict(set)
        for shift_id,employee_id,position_id in base:
            base_slots[(shift_id,position_id)].add(employee_id)
        for shift_id,employee_id,position_id in current_set:
            candidate_slots[(shift_id,position_id)].add(employee_id)
        changed_count=0; changed_shifts=set()
        for slot in set(base_slots)|set(candidate_slots):
            before=base_slots.get(slot,set()); after=candidate_slots.get(slot,set())
            if before!=after:
                changed_count+=max(len(before-after),len(after-before))
                changed_shifts.add(slot[0])
        employee_minutes={}
        for employee_id in employee_by_id:
            employee_minutes[employee_id]=sum(_shift_minutes(shifts_by_id[shift_id]) for shift_id,emp,position_id in current_set if emp==employee_id)
        candidates.append({'sequence':len(candidates)+1,'assignments':assignments,
            'metrics':{'changed_count':changed_count,'changed_shift_count':len(changed_shifts),
                'added_count':len(added),'removed_count':len(removed),
                'affected_employee_ids':sorted({emp for shift_id,emp,position_id in added+removed}),
                'preference_total':len(preference_vars),'preference_satisfied':sum(solver.Value(variable) for variable in preference_vars),
                'employee_minutes':employee_minutes,'min_minutes':min(employee_minutes.values()) if employee_minutes else 0,
                'max_minutes':max(employee_minutes.values()) if employee_minutes else 0},
            'change_summary':{'added':[{'shift_key':shift_by_id[shift_id]['shift_key'],'employee_id':emp,'position_id':position_id} for shift_id,emp,position_id in added],
                'removed':[{'shift_key':shift_by_id[shift_id]['shift_key'],'employee_id':emp,'position_id':position_id} for shift_id,emp,position_id in removed]}})
        model.Add(sum(variable if not solver.Value(variable) else 1-variable for variable in x.values())>=1)
    return {'status':'OPTIMAL' if status==cp_model.OPTIMAL else ('FEASIBLE' if candidates else 'INFEASIBLE'),
        'issues':[] if candidates else [{'code':'NO_REPAIR_SOLUTION','message':'没有找到满足硬约束的调班方案'}],
        'candidates':candidates,'solve_ms':round((time.perf_counter()-started)*1000)}
