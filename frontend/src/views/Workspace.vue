<script setup lang="ts">
import { ref,reactive,computed,watch,onUnmounted,onMounted } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { Calendar,House,User,UserFilled,Setting,SwitchButton,ArrowRight,Plus,Search,Menu,Key,DocumentCopy,Suitcase,Clock,Tickets,Refresh,Operation,MagicStick,ChatDotRound,Bell,TrendCharts,Document } from '@element-plus/icons-vue'
import { ElMessage,ElMessageBox } from 'element-plus'
import { api,session } from '../api'
import LeavePanel from '../components/LeavePanel.vue'
import SwapPanel from '../components/SwapPanel.vue'
import NotificationPanel from '../components/NotificationPanel.vue'
import AdjustmentPanel from '../components/AdjustmentPanel.vue'
import StatisticsPanel from '../components/StatisticsPanel.vue'
import SystemPanel from '../components/SystemPanel.vue'
import AIParsePanel from '../components/AIParsePanel.vue'
import AIExplanationPanel from '../components/AIExplanationPanel.vue'
const route=useRoute(),router=useRouter(),error=ref(''),busy=ref(false),search=ref(''),rows=ref<any[]>([]),total=ref(0),page=ref(1),dialog=ref(false),menuOpen=ref(false)
const resetFilter=ref('PENDING'),resetTarget=ref<any>(null),resetNote=ref(''),resetResult=ref<any>(null),resetResultVisible=ref(false),copied=ref(false)
const accountFilter=ref(''),accountDialog=ref(false),accountEmployees=ref<any[]>([])
const employeeStatusFilter=ref(''),employeePositionFilter=ref(''),positionOptions=ref<any[]>([])
const profileData=ref<any>(null),qualificationTab=ref('positions'),skills=ref<any[]>([]),positions=ref<any[]>([])
const employeeEditTarget=ref<any>(null),employeeEditSkills=ref<number[]>([]),employeeEditActiveSkills=ref<any[]>([])
const skillDialog=ref(false),skillEditTarget=ref<any>(null),skillForm=reactive({code:'',name:''})
const positionDialog=ref(false),positionEditTarget=ref<any>(null),positionSkillIds=ref<number[]>([]),positionForm=reactive({code:'',name:''})
const demandTab=ref('templates'),demandTemplates=ref<any[]>([]),demandPositions=ref<any[]>([]),planningPeriod=ref<any>(null)
const demandWeekStart=ref(''),templateDialog=ref(false),templateEditTarget=ref<any>(null),templateDemandMap=ref<Record<string,number>>({})
const shiftDialog=ref(false),shiftEditTarget=ref<any>(null),shiftDemandMap=ref<Record<string,number>>({})
const availabilityData=ref<any>(null),weeklyWindows=ref<any[]>([]),weeklyEffectiveFrom=ref(''),availabilityFrom=ref(''),availabilityTo=ref('')
const availabilityTab=ref('weekly')
const periodOptions=ref<any[]>([]),templateOptions=ref<any[]>([]),preferencePeriodId=ref(''),preferenceData=ref<any>(null),preferenceItems=ref<any[]>([])
const preferenceForm=reactive({work_date:'',template_id:'',kind:'PREFER',weight:3}),overrideTarget=ref<any>(null),overrideMode=ref('REPLACE')
const overrideWindows=ref<any[]>([]),overrideDialog=ref(false),managerAvailability=ref<any>(null),managerAvailabilityVisible=ref(false)
const submissionStatus=ref<any>(null)
const ruleVersions=ref<any[]>([]),effectiveRule=ref<any>(null),ruleWeek=ref(''),ruleDialog=ref(false)
const solverPeriods=ref<any[]>([]),solverPeriodId=ref(''),solverPeriod=ref<any>(null),solverTask=ref<any>(null)
let solverPollTimer:number|undefined
const workbenchPeriods=ref<any[]>([]),workbenchPeriodId=ref(''),workbenchPeriod=ref<any>(null),workbenchVersion=ref<any>(null)
const workbenchAssignments=ref<any[]>([]),workbenchValidation=ref<any>(null),workbenchShiftTarget=ref<any>(null),workbenchCandidates=ref<Record<string,any[]>>({})
const workbenchSelections=ref<Record<string,string>>({}),workbenchEmployeeFilter=ref(''),workbenchPositionFilter=ref(''),workbenchDirty=ref(false)
const versionPeriods=ref<any[]>([]),versionPeriodId=ref(''),versionPeriod=ref<any>(null),versionList=ref<any[]>([]),selectedVersion=ref<any>(null)
const versionPublishValidation=ref<any>(null),versionDiff=ref<any>(null),myScheduleFrom=ref(''),myScheduleTo=ref(''),myScheduleItems=ref<any[]>([])
const storeName=ref('团队工作空间')
const user=computed(()=>session.user!)
const restricted=computed(()=>user.value.must_change_password||user.value.status!=='ACTIVE')
const isManager=computed(()=>user.value.role==='MANAGER')
const activeSkills=computed(()=>skills.value.filter((skill:any)=>skill.active))
const employeeHasInactiveSkills=computed(()=>employeeEditTarget.value?.skills?.some((skill:any)=>!skill.active)||false)
const activeDemandPositions=computed(()=>demandPositions.value.filter((position:any)=>position.active))
const hasOverrideForTarget=computed(()=>!!(availabilityData.value?.overrides||[]).find((item:any)=>item.work_date===overrideTarget.value?.date))
const overrideTargetSummary=computed(()=>(overrideTarget.value?.windows||[]).map((window:any)=>`${window.start_time}—${window.end_time}`).join('、')||'不可用')
const workbenchFilteredShifts=computed(()=>{
 const shifts=workbenchVersion.value?.shifts||[]
 return shifts.filter((shift:any)=>{
  const employeeOk=!workbenchEmployeeFilter.value||workbenchAssignments.value.some((item:any)=>item.shift_key===shift.shift_key&&item.employee_id===workbenchEmployeeFilter.value)
  const positionOk=!workbenchPositionFilter.value||shift.demands.some((demand:any)=>demand.position_id===workbenchPositionFilter.value)
  return employeeOk&&positionOk
 })
})
const workbenchEmployeeOptions=computed(()=>{const map=new Map();workbenchAssignments.value.forEach((item:any)=>{if(!map.has(item.employee_id))map.set(item.employee_id,{id:item.employee_id,name:item.employee_name})});return[...map.values()]})
const workbenchPositionOptions=computed(()=>{const map=new Map();(workbenchVersion.value?.shifts||[]).forEach((shift:any)=>shift.demands.forEach((demand:any)=>{if(!map.has(demand.position_id))map.set(demand.position_id,{id:demand.position_id,name:demand.position_name})}));return[...map.values()]})
const names:Record<string,string>={'/':'工作概览','/employees':'人员档案','/qualifications':'岗位与技能','/demand-planning':'班次与需求','/availability':isManager?'时间填报':'时间与偏好','/rules':'排班规则','/scheduling':'自动排班','/workbench':'班表工作台','/versions':'发布与历史','/my-schedule':'我的班表','/leave':isManager?'请假审批':'请假申请','/swaps':isManager?'换班审批':'换班申请','/dynamic-adjustment':'动态调班','/ai-requirements':'智能需求录入','/ai-explanations':'方案解释','/notifications':'通知与确认','/statistics':'统计与导出','/system-audit':'操作记录与设置','/accounts':'账号审核','/password-resets':'密码重置审批','/profile':'个人中心'}
const managerNavGroups=[
 {label:'工作台',items:[
  {to:'/',label:'工作概览',icon:House},{to:'/workbench',label:'班表工作台',icon:Calendar},
  {to:'/scheduling',label:'自动排班',icon:MagicStick},{to:'/versions',label:'发布与历史',icon:DocumentCopy}]},
 {label:'排班准备',items:[
  {to:'/employees',label:'人员档案',icon:User},{to:'/qualifications',label:'岗位与技能',icon:Suitcase},
  {to:'/demand-planning',label:'班次与需求',icon:Clock},{to:'/availability',label:'时间填报',icon:Calendar},
  {to:'/rules',label:'排班规则',icon:Setting}]},
 {label:'申请与协作',items:[
  {to:'/leave',label:'请假审批',icon:Tickets},{to:'/swaps',label:'换班审批',icon:Refresh},
  {to:'/dynamic-adjustment',label:'动态调班',icon:Operation}]},
 {label:'智能与数据',items:[
  {to:'/ai-explanations',label:'方案解释',icon:ChatDotRound},{to:'/notifications',label:'通知与确认',icon:Bell},
  {to:'/statistics',label:'统计与导出',icon:TrendCharts},{to:'/system-audit',label:'操作记录与设置',icon:Document}]},
 {label:'账号安全',items:[
  {to:'/accounts',label:'账号审核',icon:UserFilled},{to:'/password-resets',label:'密码重置审批',icon:Key},
  {to:'/profile',label:'个人中心',icon:Setting}]}
]
const employeeNavGroups=[
 {label:'我的工作',items:[{to:'/',label:'工作概览',icon:House},{to:'/my-schedule',label:'我的班表',icon:Calendar},{to:'/availability',label:'时间与偏好',icon:Clock}]},
 {label:'申请与协作',items:[{to:'/leave',label:'请假申请',icon:Tickets},{to:'/swaps',label:'换班申请',icon:Refresh},{to:'/notifications',label:'通知与确认',icon:Bell}]},
 {label:'智能助手',items:[{to:'/ai-requirements',label:'智能需求录入',icon:MagicStick},{to:'/ai-explanations',label:'方案解释',icon:ChatDotRound}]},
 {label:'查询与账号',items:[{to:'/statistics',label:'统计与导出',icon:TrendCharts},{to:'/rules',label:'排班规则',icon:Document},{to:'/profile',label:'个人中心',icon:Setting}]}
]
const navGroups=computed(()=>isManager.value?managerNavGroups:employeeNavGroups)
const heading=computed(()=>names[route.path]||'工作概览')
const employee=reactive({employee_no:'',name:'',employment_type:'FULL_TIME',weekly_limit_minutes:2400})
const templateForm=reactive({code:'',name:'',start_time:'08:00',end_time:'14:00'})
const ruleForm=reactive({effective_week:'',daily_shift_limit:1,weekly_minutes_limit:2400,consecutive_days_limit:6,min_rest_minutes:600,preference:30,hours_balance:20,evening_balance:10})
const employeeEditForm=reactive({employee_no:'',name:'',employment_type:'FULL_TIME',weekly_limit_minutes:2400})
const employeeWeeklyHours=computed<number>({get:()=>Number((employee.weekly_limit_minutes/60).toFixed(1)),set:(value:number)=>{employee.weekly_limit_minutes=Math.max(1,Math.round(Number(value)*60))}})
const employeeEditWeeklyHours=computed<number>({get:()=>Number((employeeEditForm.weekly_limit_minutes/60).toFixed(1)),set:(value:number)=>{employeeEditForm.weekly_limit_minutes=Math.max(1,Math.round(Number(value)*60))}})
const ruleWeeklyHours=computed<number>({get:()=>Number((ruleForm.weekly_minutes_limit/60).toFixed(1)),set:(value:number)=>{ruleForm.weekly_minutes_limit=Math.max(1,Math.round(Number(value)*60))}})
const accountForm=reactive<{username:string;name:string;employee_id:string|number}>({username:'',name:'',employee_id:''})
const password=reactive({old_password:'',new_password:'',confirmation:''})
const reviewTarget=ref<any>(null),reviewMode=ref('new'),existingId=ref(''),bindingOptions=ref<any[]>([]),note=ref('')
const date=new Intl.DateTimeFormat('zh-CN',{dateStyle:'full',timeZone:'Asia/Shanghai'}).format(new Date())
const statuses:Record<string,string>={PENDING:'待审核',ACTIVE:'已启用',REJECTED:'未通过',DISABLED:'已停用',INACTIVE:'已停用'}
const resetStatuses:Record<string,string>={PENDING:'待处理',PROCESSED:'已处理',REJECTED:'已拒绝'}
demandWeekStart.value=mondayISO(new Date())
availabilityFrom.value=mondayISO(new Date())
availabilityTo.value=addDaysISO(availabilityFrom.value,27)
weeklyEffectiveFrom.value=mondayISO(new Date())
ruleWeek.value=mondayISO(new Date())
myScheduleFrom.value=mondayISO(new Date())
myScheduleTo.value=addDaysISO(myScheduleFrom.value,6)
async function load(){error.value='';rows.value=[];profileData.value=null;if(restricted.value)return;busy.value=true;try{
 if(route.path==='/employees'){const statusQuery=employeeStatusFilter.value?`&status=${employeeStatusFilter.value}`:'';const positionQuery=employeePositionFilter.value?`&position_id=${employeePositionFilter.value}`:'';const [d,p]=await Promise.all([api(`/employees?page=${page.value}&search=${encodeURIComponent(search.value)}${statusQuery}${positionQuery}`),api('/positions?page_size=100')]);rows.value=d.items;total.value=d.total;positionOptions.value=p.items}
 else if(route.path==='/accounts'){const statusQuery=accountFilter.value?`&status=${accountFilter.value}`:'';const d=await api(`/admin/accounts?page=${page.value}${statusQuery}`);rows.value=d.items;total.value=d.total}
 else if(route.path==='/password-resets'){const d=await api(`/admin/password-reset-requests?status=${resetFilter.value}&page=${page.value}`);rows.value=d.items;total.value=d.total}
 else if(route.path==='/qualifications'){const [s,p]=await Promise.all([api('/skills?page_size=100'),api('/positions?page_size=100')]);skills.value=s.items;positions.value=p.items}
 else if(route.path==='/demand-planning'){const [t,p,w]=await Promise.all([api('/shift-templates'),api('/positions?page_size=100'),api(`/periods?from=${demandWeekStart.value}&to=${demandWeekStart.value}`)]);demandTemplates.value=t.items;demandPositions.value=p.items;planningPeriod.value=w.items[0]||null}
 else if(route.path==='/availability'){periodOptions.value=(await api('/period-options')).items;if(!preferencePeriodId.value&&periodOptions.value.length)preferencePeriodId.value=periodOptions.value[0].id;if(isManager.value){if(preferencePeriodId.value)await loadSubmissionStatus();}else{const [availability,templates]=await Promise.all([api(`/me/availability?from=${availabilityFrom.value}&to=${availabilityTo.value}`),api('/shift-template-options')]);availabilityData.value=availability;templateOptions.value=templates.items;initializeWeeklyEditor();if(preferencePeriodId.value)await loadPreferences()}}
 else if(route.path==='/rules'){await loadRulePage()}
 else if(route.path==='/scheduling'){solverPeriods.value=(await api('/periods')).items;if(!solverPeriodId.value)solverPeriodId.value=(solverPeriods.value.find((item:any)=>item.latest_draft)||solverPeriods.value[0])?.id||'';if(solverPeriodId.value)await loadSolverPeriod()}
 else if(route.path==='/workbench'){workbenchPeriods.value=(await api('/periods')).items;if(!workbenchPeriodId.value)workbenchPeriodId.value=(workbenchPeriods.value.find((item:any)=>item.latest_draft)||workbenchPeriods.value[0])?.id||'';if(workbenchPeriodId.value)await loadWorkbenchPeriod()}
 else if(route.path==='/versions'){versionPeriods.value=(await api('/periods')).items;if(!versionPeriodId.value)versionPeriodId.value=(versionPeriods.value.find((item:any)=>item.current_version_id)||versionPeriods.value[0])?.id||'';if(versionPeriodId.value)await loadVersionManagement()}
 else if(route.path==='/my-schedule'){await loadMySchedule()}
 else if(route.path==='/profile'&&user.value.role==='EMPLOYEE'){profileData.value=await api('/me/profile')}
}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
watch(()=>route.path,()=>{page.value=1;search.value='';menuOpen.value=false;load()},{immediate:true})
async function logout(){try{await api('/auth/logout','POST');session.user=null;await router.push('/login')}catch(e){error.value=(e as Error).message}}
async function changePassword(){busy.value=true;try{await api('/auth/change-password','POST',password);session.user=null;ElMessage.success('密码已修改，请重新登录');await router.push('/login')}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function saveEmployee(){busy.value=true;try{await api('/employees','POST',employee);dialog.value=false;ElMessage.success('员工档案已创建');await load()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function openReview(row:any){reviewTarget.value=row;note.value='';reviewMode.value='new';existingId.value='';employee.name=row.name;employee.employee_no='';try{const d=await api('/employees?page_size=100');bindingOptions.value=d.items.filter((e:any)=>!e.bound&&e.status==='ACTIVE')}catch(e){error.value=(e as Error).message}}
async function review(decision:string){busy.value=true;try{const payload:any={decision,expected_revision:reviewTarget.value.revision,note:note.value};if(decision==='APPROVE'){if(reviewMode.value==='existing')payload.employee_id=Number(existingId.value);else payload.new_employee={...employee}}
await api(`/admin/accounts/${reviewTarget.value.id}/review`,'POST',payload,crypto.randomUUID());reviewTarget.value=null;ElMessage.success('审核已保存');await load()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function openCreateAccount(){error.value='';Object.assign(accountForm,{username:'',name:'',employee_id:''});accountDialog.value=true;try{const d=await api('/employees?page_size=100');accountEmployees.value=d.items.filter((e:any)=>!e.bound&&e.status==='ACTIVE')}catch(e){error.value=(e as Error).message}}
async function createAccount(){error.value='';busy.value=true;try{const payload:any={username:accountForm.username,name:accountForm.name};if(accountForm.employee_id!=='')payload.employee_id=Number(accountForm.employee_id);const data=await api('/admin/accounts','POST',payload,crypto.randomUUID());accountDialog.value=false;copied.value=false;resetResult.value=data;resetResultVisible.value=true;await load()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function changeAccountStatus(row:any,target:'ACTIVE'|'DISABLED'){const action=target==='DISABLED'?'停用':'启用';const detail=target==='DISABLED'?'停用后该账号会立即退出所有设备，且不能继续登录。':'启用后该账号可以重新登录。';try{await ElMessageBox.confirm(`${detail}`, `${action}账号“${row.name}”？`, {confirmButtonText:`确认${action}`,cancelButtonText:'取消',type:'warning'})}catch{return}busy.value=true;error.value='';try{const data=await api(`/admin/accounts/${row.id}/status`,'PATCH',{status:target,expected_revision:row.revision});if(row.id===user.value.id&&target==='DISABLED'){session.user=null;ElMessage.success('账号已停用');await router.push('/login');return}ElMessage.success(`账号已${action}`);await load();return data}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
function formatTime(value:string){if(!value)return'—';return new Intl.DateTimeFormat('zh-CN',{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Shanghai'}).format(new Date(value))}
function formatHours(minutes:number){return`${Number((Number(minutes)/60).toFixed(1))} 小时`}
function formatHourValue(minutes:number){return Number((Number(minutes)/60).toFixed(1))}
function openReset(row:any){error.value='';resetTarget.value=row;resetNote.value='';copied.value=false}
async function submitReset(){error.value='';if(!resetNote.value.trim()){error.value='请填写身份核实说明';return}busy.value=true;try{const data=await api(`/admin/accounts/${resetTarget.value.user_id}/reset-password`,'POST',{request_id:Number(resetTarget.value.id),expected_revision:resetTarget.value.account_revision,verification_note:resetNote.value.trim()},crypto.randomUUID());resetTarget.value=null;resetResult.value=data;resetResultVisible.value=true;await load()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function copyPassword(){if(!resetResult.value?.temporary_password)return;try{await navigator.clipboard.writeText(resetResult.value.temporary_password);copied.value=true;ElMessage.success('临时密码已复制')}catch{error.value='浏览器未允许自动复制，请手动选择密码'}}
async function openEditEmployee(row:any){error.value='';busy.value=true;try{const [detail,skillData]=await Promise.all([api(`/employees/${row.id}`),api('/skills?page_size=100')]);employeeEditTarget.value=detail;Object.assign(employeeEditForm,{employee_no:detail.employee_no,name:detail.name,employment_type:detail.employment_type,weekly_limit_minutes:detail.weekly_limit_minutes});employeeEditActiveSkills.value=skillData.items.filter((s:any)=>s.active);employeeEditSkills.value=detail.skills.filter((s:any)=>s.active).map((s:any)=>Number(s.id))}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function saveEmployeeEdit(){error.value='';busy.value=true;try{const updated=await api(`/employees/${employeeEditTarget.value.id}`,'PATCH',{...employeeEditForm,expected_revision:employeeEditTarget.value.revision});await api(`/employees/${employeeEditTarget.value.id}/skills`,'PUT',{skill_ids:employeeEditSkills.value,expected_revision:updated.revision});employeeEditTarget.value=null;ElMessage.success('员工资料与技能已更新');await load()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function changeEmployeeStatus(row:any,target:'ACTIVE'|'INACTIVE'){const action=target==='INACTIVE'?'停用':'启用';try{await ElMessageBox.confirm(target==='INACTIVE'?'停用后该员工不会参与后续排班，历史资料仍会保留。':'启用后该员工可重新参与排班。',`${action}员工“${row.name}”？`,{confirmButtonText:`确认${action}`,cancelButtonText:'取消',type:'warning'})}catch{return}busy.value=true;try{await api(`/employees/${row.id}/status`,'PATCH',{status:target,expected_revision:row.revision});ElMessage.success(`员工已${action}`);await load()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
function openSkillDialog(item:any=null){error.value='';skillEditTarget.value=item;Object.assign(skillForm,{code:item?.code||'',name:item?.name||''});skillDialog.value=true}
async function saveSkill(){error.value='';busy.value=true;try{if(skillEditTarget.value){await api(`/skills/${skillEditTarget.value.id}`,'PATCH',{name:skillForm.name,active:skillEditTarget.value.active,expected_revision:skillEditTarget.value.revision});ElMessage.success('技能已更新')}else{await api('/skills','POST',{code:skillForm.code,name:skillForm.name});ElMessage.success('技能已创建')}skillDialog.value=false;await load()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function toggleSkill(item:any){const action=item.active?'停用':'启用';try{await ElMessageBox.confirm(`${action}后不会删除已有历史关联。`, `${action}技能“${item.name}”？`, {confirmButtonText:`确认${action}`,cancelButtonText:'取消',type:'warning'})}catch{return}busy.value=true;try{await api(`/skills/${item.id}`,'PATCH',{name:item.name,active:!item.active,expected_revision:item.revision});ElMessage.success(`技能已${action}`);await load()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
function openPositionDialog(item:any=null){error.value='';positionEditTarget.value=item;Object.assign(positionForm,{code:item?.code||'',name:item?.name||''});const activeIds=new Set(skills.value.filter((s:any)=>s.active).map((s:any)=>Number(s.id)));positionSkillIds.value=item?item.required_skills.filter((s:any)=>activeIds.has(Number(s.id))).map((s:any)=>Number(s.id)):[];positionDialog.value=true}
async function savePosition(){error.value='';busy.value=true;try{let saved:any;if(positionEditTarget.value){saved=await api(`/positions/${positionEditTarget.value.id}`,'PATCH',{name:positionForm.name,active:positionEditTarget.value.active,expected_revision:positionEditTarget.value.revision})}else{saved=await api('/positions','POST',{code:positionForm.code,name:positionForm.name})}await api(`/positions/${saved.id}/skills`,'PUT',{skill_ids:positionSkillIds.value,expected_revision:saved.revision});positionDialog.value=false;ElMessage.success(positionEditTarget.value?'岗位已更新':'岗位已创建');await load()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function togglePosition(item:any){const action=item.active?'停用':'启用';try{await ElMessageBox.confirm(`${action}后岗位历史要求仍保留，但不应再用于新的排班。`, `${action}岗位“${item.name}”？`, {confirmButtonText:`确认${action}`,cancelButtonText:'取消',type:'warning'})}catch{return}busy.value=true;try{await api(`/positions/${item.id}`,'PATCH',{name:item.name,active:!item.active,expected_revision:item.revision});ElMessage.success(`岗位已${action}`);await load()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
function localDateString(value:Date){const year=value.getFullYear(),month=String(value.getMonth()+1).padStart(2,'0'),day=String(value.getDate()).padStart(2,'0');return`${year}-${month}-${day}`}
function mondayISO(value:Date|string){const dateValue=value instanceof Date?new Date(value.getFullYear(),value.getMonth(),value.getDate()):new Date(`${value}T00:00:00`);const offset=(dateValue.getDay()+6)%7;dateValue.setDate(dateValue.getDate()-offset);return localDateString(dateValue)}
function weekDateLabel(value:string){const d=new Date(`${value}T00:00:00`);const weekday=['周日','周一','周二','周三','周四','周五','周六'][d.getDay()];return`${value} ${weekday}`}
async function changeDemandWeek(value:string){demandWeekStart.value=mondayISO(value);planningPeriod.value=null;await load()}
async function ensurePlanningPeriod(){if(planningPeriod.value)return planningPeriod.value;try{planningPeriod.value=await api('/periods','POST',{week_start:demandWeekStart.value})}catch(e){if((e as any).status!==409)throw e;const existing=await api(`/periods?from=${demandWeekStart.value}&to=${demandWeekStart.value}`);planningPeriod.value=existing.items[0]||null;if(!planningPeriod.value)throw e}return planningPeriod.value}
async function refreshPlanningPeriod(){if(!planningPeriod.value)return;planningPeriod.value=await api(`/periods/${planningPeriod.value.id}`)}
async function generateDemandDraft(){error.value='';busy.value=true;try{const period=await ensurePlanningPeriod();await api(`/periods/${period.id}/drafts`,'POST',{});await refreshPlanningPeriod();demandTab.value='week';ElMessage.success('已按启用模板生成排班输入草稿')}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function copyPreviousDemandWeek(){error.value='';busy.value=true;try{const period=await ensurePlanningPeriod();const previous=mondayISO(new Date(new Date(`${period.week_start}T00:00:00`).getTime()-7*86400000));const source=await api(`/periods?from=${previous}&to=${previous}`);if(!source.items.length)throw new Error('上一周还没有排班周期，无法复制');await api(`/periods/${period.id}/drafts`,'POST',{source_period_id:Number(source.items[0].id)});await refreshPlanningPeriod();demandTab.value='week';ElMessage.success('已复制上一周班次和岗位需求')}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
function openTemplateDialog(item:any=null){error.value='';templateEditTarget.value=item;Object.assign(templateForm,{code:item?.code||'',name:item?.name||'',start_time:item?.start_time||'08:00',end_time:item?.end_time||'14:00'});templateDemandMap.value=Object.fromEntries(activeDemandPositions.value.map((position:any)=>[position.id,item?.demands?.find((demand:any)=>demand.position_id===position.id)?.required_count||0]));templateDialog.value=true}
function templatePayload(item:any,active:boolean,form=templateForm){const demands=activeDemandPositions.value.map((position:any)=>({position_id:Number(position.id),required_count:Number(templateDemandMap.value[position.id]||0)})).filter((demand:any)=>demand.required_count>0);return{code:form.code,name:form.name,start_time:form.start_time,end_time:form.end_time,active,expected_revision:item.revision,demands}}
async function saveTemplate(){error.value='';if(!activeDemandPositions.value.some((position:any)=>Number(templateDemandMap.value[position.id]||0)>0)){error.value='请至少为一个岗位配置大于0的人数';return}busy.value=true;try{if(templateEditTarget.value){await api(`/shift-templates/${templateEditTarget.value.id}`,'PATCH',templatePayload(templateEditTarget.value,templateEditTarget.value.active))}else{await api('/shift-templates','POST',{code:templateForm.code,name:templateForm.name,start_time:templateForm.start_time,end_time:templateForm.end_time,demands:activeDemandPositions.value.map((position:any)=>({position_id:Number(position.id),required_count:Number(templateDemandMap.value[position.id]||0)})).filter((demand:any)=>demand.required_count>0)})}templateDialog.value=false;ElMessage.success(templateEditTarget.value?'班次模板已更新':'班次模板已创建');await load()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function toggleTemplate(item:any){const action=item.active?'停用':'启用';try{await ElMessageBox.confirm('已有排班草稿不会被改写。',`${action}班次模板“${item.name}”？`,{confirmButtonText:`确认${action}`,cancelButtonText:'取消',type:'warning'})}catch{return}busy.value=true;try{templateDemandMap.value=Object.fromEntries(activeDemandPositions.value.map((position:any)=>[position.id,item.demands.find((demand:any)=>demand.position_id===position.id)?.required_count||0]));await api(`/shift-templates/${item.id}`,'PATCH',templatePayload(item,!item.active,{code:item.code,name:item.name,start_time:item.start_time,end_time:item.end_time}));ElMessage.success(`班次模板已${action}`);await load()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
function openShiftDialog(shift:any){error.value='';shiftEditTarget.value=shift;shiftDemandMap.value=Object.fromEntries(activeDemandPositions.value.map((position:any)=>[position.id,shift.demands.find((demand:any)=>demand.position_id===position.id)?.required_count||0]));shiftDialog.value=true}
function shiftInput(shift:any,enabled:boolean,demandsMap:Record<string,number>){return{shift_key:shift.shift_key,template_id:shift.template_id?Number(shift.template_id):null,work_date:shift.work_date,name:shift.name,start_time:shift.start_time,end_time:shift.end_time,enabled,demands:activeDemandPositions.value.map((position:any)=>({position_id:Number(position.id),required_count:Number(demandsMap[position.id]||0)})).filter((demand:any)=>demand.required_count>0)}}
async function persistShift(shift:any,enabled:boolean,demandsMap:Record<string,number>){const draft=planningPeriod.value?.latest_draft;if(!draft)throw new Error('当前周期还没有可编辑草稿');const shifts=draft.shifts.map((item:any)=>item.id===shift.id?shiftInput(item,enabled,demandsMap):shiftInput(item,item.enabled,Object.fromEntries(item.demands.map((demand:any)=>[demand.position_id,demand.required_count]))));await api(`/versions/${draft.id}/shifts`,'PUT',{expected_revision:draft.revision,shifts});await refreshPlanningPeriod()}
async function saveShift(){error.value='';busy.value=true;try{await persistShift(shiftEditTarget.value,shiftEditTarget.value.enabled,shiftDemandMap.value);shiftDialog.value=false;ElMessage.success('班次岗位需求已保存')}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function toggleDraftShift(shift:any){const action=shift.enabled?'关闭':'启用';try{await ElMessageBox.confirm(`${action}只影响当前周草稿，不修改班次模板。`,`${action}${weekDateLabel(shift.work_date)}“${shift.name}”？`,{confirmButtonText:`确认${action}`,cancelButtonText:'取消',type:'warning'})}catch{return}busy.value=true;try{await persistShift(shift,!shift.enabled,Object.fromEntries(shift.demands.map((demand:any)=>[demand.position_id,demand.required_count])));ElMessage.success(`班次已${action}`)}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function closeDraftDate(workDate:string){const draft=planningPeriod.value?.latest_draft;if(!draft)return;try{await ElMessageBox.confirm('当天全部班次将在此周草稿中关闭，模板不会改变。',`关闭 ${weekDateLabel(workDate)} 的全部班次？`,{confirmButtonText:'关闭当天',cancelButtonText:'取消',type:'warning'})}catch{return}busy.value=true;try{const shifts=draft.shifts.map((shift:any)=>shiftInput(shift,shift.work_date===workDate?false:shift.enabled,Object.fromEntries(shift.demands.map((demand:any)=>[demand.position_id,demand.required_count]))));await api(`/versions/${draft.id}/shifts`,'PUT',{expected_revision:draft.revision,shifts});await refreshPlanningPeriod();ElMessage.success('当天班次已全部关闭')}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
function addDaysISO(value:string,days:number){const d=new Date(`${value}T00:00:00`);d.setDate(d.getDate()+days);return localDateString(d)}
function weeklyForDay(day:number){return weeklyWindows.value.filter((window:any)=>Number(window.weekday)===day)}
function cloneWindows(windows:any[]){return windows.map((window:any)=>({weekday:Number(window.weekday),start_time:window.start_time,end_time:window.end_time}))}
function initializeWeeklyEditor(){const profiles=availabilityData.value?.profiles||[];if(!profiles.length){weeklyEffectiveFrom.value=availabilityFrom.value;weeklyWindows.value=[];return}const latest=profiles[profiles.length-1];weeklyEffectiveFrom.value=latest.effective_from;weeklyWindows.value=cloneWindows(latest.windows)}
function newWeeklyVersion(){const profiles=availabilityData.value?.profiles||[];const latest=profiles[profiles.length-1];weeklyEffectiveFrom.value=latest?addDaysISO(latest.effective_from,7):availabilityFrom.value;weeklyWindows.value=latest?cloneWindows(latest.windows):[]}
function addWeeklyWindow(day:number){weeklyWindows.value.push({weekday:day,start_time:'09:00',end_time:'17:00'})}
function removeWeeklyWindow(index:number){weeklyWindows.value.splice(index,1)}
function removeWeeklyWindowItem(item:any){const index=weeklyWindows.value.indexOf(item);if(index>=0)weeklyWindows.value.splice(index,1)}
async function saveWeeklyAvailability(){error.value='';busy.value=true;try{const profiles=availabilityData.value?.profiles||[];const latest=profiles[profiles.length-1];await api('/me/availability/weekly','PUT',{expected_revision:latest?.revision||0,effective_from:weeklyEffectiveFrom.value,windows:weeklyWindows.value});ElMessage.success('常规可用时间已保存');await reloadAvailability()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function reloadAvailability(){availabilityData.value=await api(`/me/availability?from=${availabilityFrom.value}&to=${availabilityTo.value}`);initializeWeeklyEditor()}
async function refreshAvailabilityRange(){busy.value=true;try{await reloadAvailability()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
function openOverride(day:any){error.value='';overrideTarget.value=day;const existing=(availabilityData.value?.overrides||[]).find((item:any)=>item.work_date===day.date);overrideMode.value=existing?.mode||'REPLACE';overrideWindows.value=existing?existing.windows.map((window:any)=>({...window})):day.windows.map((window:any)=>({...window}));overrideDialog.value=true}
function addOverrideWindow(){overrideWindows.value.push({start_time:'09:00',end_time:'10:00'})}
function removeOverrideWindow(index:number){overrideWindows.value.splice(index,1)}
async function saveOverride(){error.value='';busy.value=true;try{const existing=(availabilityData.value?.overrides||[]).find((item:any)=>item.work_date===overrideTarget.value.date);await api(`/me/availability/overrides/${overrideTarget.value.date}`,'PUT',{expected_revision:existing?.revision||0,mode:overrideMode.value,windows:overrideWindows.value});overrideDialog.value=false;ElMessage.success('日期例外已保存');await reloadAvailability()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function deleteOverride(){if(!overrideTarget.value)return;const existing=(availabilityData.value?.overrides||[]).find((item:any)=>item.work_date===overrideTarget.value.date);if(!existing)return;busy.value=true;try{await api(`/me/availability/overrides/${overrideTarget.value.date}`,'DELETE',{expected_revision:existing.revision});overrideDialog.value=false;ElMessage.success('日期例外已删除');await reloadAvailability()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
function preferenceTemplateName(templateId:string){return templateOptions.value.find((item:any)=>item.id===templateId)?.name||templateId}
async function loadPreferences(){if(!preferencePeriodId.value)return;preferenceData.value=await api(`/me/preferences/${preferencePeriodId.value}`);preferenceItems.value=preferenceData.value.items.map((item:any)=>({...item}));const period=periodOptions.value.find((item:any)=>item.id===preferencePeriodId.value);if(period)preferenceForm.work_date=period.week_start}
function changePreferencePeriod(){loadPreferences().catch((e:any)=>error.value=e.message)}
function addPreferenceItem(){if(!preferenceForm.work_date||!preferenceForm.template_id){error.value='请选择日期和班次';return}if(preferenceItems.value.some((item:any)=>item.work_date===preferenceForm.work_date&&item.template_id===preferenceForm.template_id)){error.value='该日期和班次已经设置偏好';return}preferenceItems.value.push({work_date:preferenceForm.work_date,template_id:preferenceForm.template_id,template_name:preferenceTemplateName(preferenceForm.template_id),kind:preferenceForm.kind,weight:preferenceForm.weight})}
function removePreferenceItem(index:number){preferenceItems.value.splice(index,1)}
async function savePreferences(submit:boolean){error.value='';busy.value=true;try{const items=preferenceItems.value.map((item:any)=>({work_date:item.work_date,template_id:Number(item.template_id),kind:item.kind,weight:Number(item.weight)}));preferenceData.value=await api(`/me/preferences/${preferencePeriodId.value}`,'PUT',{expected_revision:preferenceData.value?.revision||0,items,submit});preferenceItems.value=preferenceData.value.items.map((item:any)=>({...item}));ElMessage.success(submit?'个人偏好已提交':'偏好草稿已保存')}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function loadSubmissionStatus(){if(!preferencePeriodId.value){submissionStatus.value=null;return}submissionStatus.value=await api(`/periods/${preferencePeriodId.value}/submission-status`)}
function changeSubmissionPeriod(){loadSubmissionStatus().catch((e:any)=>error.value=e.message)}
async function viewEmployeeAvailability(employee:any){error.value='';busy.value=true;try{managerAvailability.value=await api(`/employees/${employee.employee_id}/availability?from=${availabilityFrom.value}&to=${availabilityTo.value}`);managerAvailabilityVisible.value=true}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function loadRulePage(){effectiveRule.value=null;try{effectiveRule.value=await api(`/rule-versions/effective?week=${ruleWeek.value}`)}catch(e){if((e as any).status!==404)throw e}if(isManager.value){ruleVersions.value=(await api('/rule-versions')).items}}
function changeRuleWeek(){loadRulePage().catch((e:any)=>error.value=e.message)}
function openRuleDialog(){error.value='';const base=effectiveRule.value||ruleForm;ruleWeek.value=mondayISO(ruleWeek.value);Object.assign(ruleForm,{effective_week:ruleWeek.value,daily_shift_limit:base.daily_shift_limit||1,weekly_minutes_limit:base.weekly_minutes_limit||2400,consecutive_days_limit:base.consecutive_days_limit||6,min_rest_minutes:base.min_rest_minutes??600,preference:base.weights?.preference??30,hours_balance:base.weights?.hours_balance??20,evening_balance:base.weights?.evening_balance??10});ruleDialog.value=true}
async function saveRuleVersion(){error.value='';busy.value=true;try{await api('/rule-versions','POST',{effective_week:ruleForm.effective_week,daily_shift_limit:ruleForm.daily_shift_limit,weekly_minutes_limit:ruleForm.weekly_minutes_limit,consecutive_days_limit:ruleForm.consecutive_days_limit,min_rest_minutes:ruleForm.min_rest_minutes,weights:{preference:ruleForm.preference,hours_balance:ruleForm.hours_balance,evening_balance:ruleForm.evening_balance}});ruleDialog.value=false;ElMessage.success('新规则版本已创建');await loadRulePage()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
function clearSolverPoll(){if(solverPollTimer!==undefined){window.clearTimeout(solverPollTimer);solverPollTimer=undefined}}
async function loadSolverPeriod(){if(!solverPeriodId.value){solverPeriod.value=null;solverTask.value=null;return}solverPeriod.value=await api(`/periods/${solverPeriodId.value}`);solverTask.value=null;if(solverPeriod.value.latest_draft){const tasks=await api(`/solver-tasks?draft_version_id=${solverPeriod.value.latest_draft.id}`);solverTask.value=tasks.items[0]||null;if(solverTask.value&&['QUEUED','RUNNING'].includes(solverTask.value.state))scheduleSolverPoll(solverTask.value.id)}}
function changeSolverPeriod(){clearSolverPoll();loadSolverPeriod().catch((e:any)=>error.value=e.message)}
async function startSolver(){error.value='';if(!solverPeriod.value?.latest_draft){error.value='当前周期还没有排班输入草稿';return}busy.value=true;try{const draft=solverPeriod.value.latest_draft;solverTask.value=await api('/solver-tasks','POST',{period_id:Number(solverPeriod.value.id),draft_version_id:Number(draft.id),expected_draft_revision:draft.revision,base_published_version_id:null,rule_version_id:draft.rule_version_id?Number(draft.rule_version_id):null},crypto.randomUUID());scheduleSolverPoll(solverTask.value.id)}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
function scheduleSolverPoll(taskId:string){clearSolverPoll();solverPollTimer=window.setTimeout(async()=>{try{const task=await api(`/solver-tasks/${taskId}`);solverTask.value=task;if(['QUEUED','RUNNING'].includes(task.state)){scheduleSolverPoll(taskId)}else if(solverPeriodId.value){solverPeriod.value=await api(`/periods/${solverPeriodId.value}`)}}catch(e){error.value=(e as Error).message}},800)}
function solverStateLabel(state:string){return({QUEUED:'排队中',RUNNING:'求解中',OPTIMAL:'已证明最优',FEASIBLE:'找到可行方案',INFEASIBLE:'无可行方案',UNKNOWN:'限时未找到方案',FAILED:'求解失败'} as Record<string,string>)[state]||state}
function assignmentsFor(shift:any,demand:any){return workbenchAssignments.value.filter((item:any)=>item.shift_key===shift.shift_key&&item.position_id===demand.position_id)}
function shiftRequired(shift:any){return shift.demands.reduce((total:number,demand:any)=>total+Number(demand.required_count),0)}
function shiftAssigned(shift:any){return workbenchAssignments.value.filter((item:any)=>item.shift_key===shift.shift_key).length}
function candidateLabel(candidate:any){return candidate.eligible?candidate.name:`${candidate.name} · ${candidate.reasons.map((reason:any)=>reason.message).join('、')}`}
async function loadWorkbenchPeriod(){if(!workbenchPeriodId.value){workbenchPeriod.value=null;workbenchVersion.value=null;return}workbenchPeriod.value=await api(`/periods/${workbenchPeriodId.value}`);workbenchVersion.value=null;workbenchAssignments.value=[];workbenchValidation.value=null;workbenchDirty.value=false;if(workbenchPeriod.value.latest_draft){workbenchVersion.value=await api(`/versions/${workbenchPeriod.value.latest_draft.id}`);workbenchAssignments.value=workbenchVersion.value.assignments.map((item:any)=>({...item}))}}
function changeWorkbenchPeriod(){loadWorkbenchPeriod().catch((e:any)=>error.value=e.message)}
async function openWorkbenchShift(shift:any){error.value='';workbenchShiftTarget.value=shift;workbenchSelections.value={};const entries=await Promise.all(shift.demands.map(async(demand:any)=>{const result=await api(`/versions/${workbenchVersion.value.id}/eligible-employees?shift_key=${shift.shift_key}&position_id=${demand.position_id}`);return[demand.position_id,result.items]}));workbenchCandidates.value=Object.fromEntries(entries)}
function addWorkbenchAssignment(demand:any){const employeeId=workbenchSelections.value[demand.position_id];if(!employeeId)return;const candidate=(workbenchCandidates.value[demand.position_id]||[]).find((item:any)=>item.employee_id===employeeId);if(!candidate||!candidate.eligible){error.value='该员工当前不满足此岗位安排条件';return}if(workbenchAssignments.value.some((item:any)=>item.shift_key===workbenchShiftTarget.value.shift_key&&item.employee_id===employeeId)){error.value='该员工已在这个班次承担岗位';return}workbenchAssignments.value.push({shift_key:workbenchShiftTarget.value.shift_key,employee_id:employeeId,employee_name:candidate.name,position_id:demand.position_id,position_name:demand.position_name,locked:false});workbenchSelections.value[demand.position_id]='';workbenchDirty.value=true}
function removeWorkbenchAssignment(item:any){const index=workbenchAssignments.value.findIndex((assignment:any)=>assignment.shift_key===item.shift_key&&assignment.employee_id===item.employee_id);if(index>=0)workbenchAssignments.value.splice(index,1);workbenchDirty.value=true}
function markWorkbenchDirty(){workbenchDirty.value=true}
async function saveWorkbenchAssignments(showMessage=true){if(!workbenchVersion.value)return null;error.value='';busy.value=true;try{const items=workbenchAssignments.value.map((item:any)=>({shift_key:item.shift_key,employee_id:Number(item.employee_id),position_id:Number(item.position_id),locked:!!item.locked}));const saved=await api(`/versions/${workbenchVersion.value.id}/assignments`,'PUT',{expected_revision:workbenchVersion.value.revision,items});workbenchVersion.value=saved;workbenchAssignments.value=saved.assignments.map((item:any)=>({...item}));workbenchDirty.value=false;workbenchValidation.value=await api(`/versions/${saved.id}/validate`,'POST',{expected_revision:saved.revision});if(showMessage)ElMessage.success('人员安排已保存并完成校验');return saved}catch(e){error.value=(e as Error).message;return null}finally{busy.value=false}}
async function validateWorkbench(){if(workbenchDirty.value){const saved=await saveWorkbenchAssignments(false);if(!saved)return}if(!workbenchVersion.value)return;busy.value=true;try{workbenchValidation.value=await api(`/versions/${workbenchVersion.value.id}/validate`,'POST',{expected_revision:workbenchVersion.value.revision})}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function goRegenerateFromWorkbench(){if(workbenchDirty.value){const saved=await saveWorkbenchAssignments(false);if(!saved)return}solverPeriodId.value=workbenchPeriodId.value;await router.push('/scheduling')}
async function saveAndCloseWorkbenchShift(){const saved=await saveWorkbenchAssignments(true);if(saved)workbenchShiftTarget.value=null}
async function loadVersionManagement(){versionPeriod.value=await api(`/periods/${versionPeriodId.value}`);versionList.value=(await api(`/periods/${versionPeriodId.value}/versions`)).items;const target=versionList.value.find((item:any)=>item.id===versionPeriod.value.current_version_id)||versionList.value.find((item:any)=>item.status==='DRAFT')||versionList.value[0];if(target)await selectVersion(target);else selectedVersion.value=null;versionDiff.value=null}
function changeVersionPeriod(){loadVersionManagement().catch((e:any)=>error.value=e.message)}
async function selectVersion(item:any){selectedVersion.value=await api(`/versions/${item.id}`);versionPublishValidation.value=null;versionDiff.value=null;if(selectedVersion.value.status==='DRAFT'){try{versionPublishValidation.value=await api(`/versions/${selectedVersion.value.id}/validate`,'POST',{expected_revision:selectedVersion.value.revision})}catch(e){error.value=(e as Error).message}}}
async function validateSelectedVersion(){if(!selectedVersion.value)return;busy.value=true;try{versionPublishValidation.value=await api(`/versions/${selectedVersion.value.id}/validate`,'POST',{expected_revision:selectedVersion.value.revision});if(versionPublishValidation.value.valid)ElMessage.success('校验通过，可以发布')}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function publishSelectedVersion(){if(!selectedVersion.value||!versionPeriod.value)return;error.value='';busy.value=true;try{if(!versionPublishValidation.value||versionPublishValidation.value.input_revision===undefined){versionPublishValidation.value=await api(`/versions/${selectedVersion.value.id}/validate`,'POST',{expected_revision:selectedVersion.value.revision})}if(!versionPublishValidation.value.valid){error.value='排班仍存在硬冲突，不能发布';return}const result=await api(`/versions/${selectedVersion.value.id}/publish`,'POST',{expected_draft_revision:selectedVersion.value.revision,expected_period_revision:versionPeriod.value.revision,base_published_version_id:versionPeriod.value.current_version_id?Number(versionPeriod.value.current_version_id):null,expected_input_revision:versionPublishValidation.value.input_revision},crypto.randomUUID());ElMessage.success(`版本 ${result.version_no} 已发布`);await loadVersionManagement()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function copySelectedVersion(){if(!selectedVersion.value)return;error.value='';busy.value=true;try{const draft=await api(`/versions/${selectedVersion.value.id}/copy-to-draft`,'POST',{expected_period_revision:versionPeriod.value.revision});await loadVersionManagement();selectedVersion.value=await api(`/versions/${draft.id}`);ElMessage.success('已复制为新的草稿')}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function discardSelectedVersion(){if(!selectedVersion.value)return;busy.value=true;try{await api(`/versions/${selectedVersion.value.id}/discard`,'POST',{expected_revision:selectedVersion.value.revision});ElMessage.success('草稿已废弃');await loadVersionManagement()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function loadVersionDiff(){if(!selectedVersion.value||!versionPeriod.value)return;const currentId=versionPeriod.value.current_version_id;const other=selectedVersion.value.id===currentId?versionList.value.find((item:any)=>item.id!==selectedVersion.value.id):versionList.value.find((item:any)=>item.id===currentId);if(!other){error.value='至少需要两个版本才能比较';return}busy.value=true;try{versionDiff.value=await api(`/versions/${selectedVersion.value.id}/diff?other_version_id=${other.id}`)}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function loadMySchedule(){busy.value=true;try{myScheduleItems.value=(await api(`/me/schedules?from=${myScheduleFrom.value}&to=${myScheduleTo.value}`)).items}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
function versionStatusLabel(status:string){return({DRAFT:'草稿',PUBLISHED:'当前发布',SUPERSEDED:'已被替代',DISCARDED:'已废弃'} as Record<string,string>)[status]||status}
async function loadStoreSettings(){try{const data=await api('/settings/public');storeName.value=data.store_name||'团队工作空间'}catch{}}
onUnmounted(clearSolverPoll)
onMounted(loadStoreSettings)
</script>
<template>
<div class="workspace">
 <aside :class="['sidebar',{opened:menuOpen}]"><router-link class="brand" to="/"><span class="brand-icon"><el-icon><Calendar /></el-icon></span><span>智能排班<small>{{storeName}}</small></span></router-link><nav>
  <div v-for="group in navGroups" :key="group.label" class="nav-group"><div class="nav-label">{{group.label}}</div><router-link v-for="item in group.items" :key="item.to" :to="item.to"><el-icon><component :is="item.icon"/></el-icon>{{item.label}}</router-link></div>
 </nav><div class="sidebar-bottom"><span class="online-dot"></span> 单门店工作空间</div></aside>
 <div class="workspace-main"><header class="topbar"><div class="topbar-left"><el-button class="mobile-menu" text :icon="Menu" aria-label="展开导航" @click="menuOpen=!menuOpen"/><span class="muted">工作空间</span><span class="crumb">/</span>{{heading}}</div><div class="identity"><span class="avatar">{{user.name.slice(0,1)}}</span><span>{{user.name}}<small>{{isManager?'管理员':'员工'}}</small></span><el-button text :icon="SwitchButton" aria-label="退出登录" @click="logout" /></div></header>
 <main class="main-content"><el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="feedback"/>
 <template v-if="user.must_change_password"><div class="page-heading"><div><span class="eyebrow">账号管理</span><h1>设置你的新密码</h1><p class="muted">首次登录需要修改临时密码，完成后即可继续。</p></div></div><section class="panel password-panel"><el-form label-position="top" @submit.prevent="changePassword"><el-form-item label="当前密码"><el-input v-model="password.old_password" type="password" show-password autocomplete="current-password" required/></el-form-item><el-form-item label="新密码"><el-input v-model="password.new_password" type="password" show-password autocomplete="new-password" placeholder="12—128 个字符" required/></el-form-item><el-form-item label="确认新密码"><el-input v-model="password.confirmation" type="password" show-password autocomplete="new-password" required/></el-form-item><el-button type="primary" native-type="submit" :loading="busy">保存新密码</el-button></el-form></section></template>
 <template v-else-if="route.path==='/profile'">
  <div class="page-heading"><div><span class="eyebrow">账号与人员资料</span><h1>个人中心</h1><p class="muted">查看本人岗位技能，并管理登录密码。</p></div></div>
  <div v-if="profileData" class="profile-grid">
   <section class="panel profile-summary">
    <div class="profile-title"><span class="profile-avatar">{{profileData.name.slice(0,1)}}</span><div><h2>{{profileData.name}}</h2><p class="muted">{{profileData.employee_no}} · {{profileData.employment_type==='FULL_TIME'?'全职':'兼职'}}</p></div><el-tag :type="profileData.status==='ACTIVE'?'success':'info'">{{profileData.status==='ACTIVE'?'在岗':'已停用'}}</el-tag></div>
    <div class="profile-facts"><div><span>每周工时上限</span><strong>{{formatHours(profileData.weekly_limit_minutes)}}</strong></div><div><span>已具备技能</span><strong>{{profileData.skills.length}} 项</strong></div><div><span>可胜任岗位</span><strong>{{profileData.qualified_positions.length}} 个</strong></div></div>
   </section>
   <section class="panel"><div class="section-heading"><h2>岗位与技能</h2><el-tag effect="plain">由管理员维护</el-tag></div><p class="field-label">我的技能</p><div class="tag-list"><el-tag v-for="s in profileData.skills" :key="s.id" :type="s.active?'primary':'info'" effect="light">{{s.name}}{{s.active?'':'（已停用）'}}</el-tag><span v-if="!profileData.skills.length" class="muted">尚未配置技能</span></div><p class="field-label skills-position-label">可胜任岗位</p><div class="tag-list"><el-tag v-for="p in profileData.qualified_positions" :key="p.id" type="success" effect="plain">{{p.name}}</el-tag><span v-if="!profileData.qualified_positions.length" class="muted">尚未满足岗位要求</span></div></section>
  </div>
  <el-alert v-else-if="isManager" title="管理员账号不绑定员工档案，因此不参与排班。" type="info" :closable="false" show-icon class="feedback"/>
  <section class="panel password-panel profile-password"><h2>修改登录密码</h2><p class="muted">修改成功后，所有旧会话将退出登录。</p><el-form label-position="top" @submit.prevent="changePassword"><el-form-item label="当前密码"><el-input v-model="password.old_password" type="password" show-password autocomplete="current-password" required/></el-form-item><el-form-item label="新密码"><el-input v-model="password.new_password" type="password" show-password autocomplete="new-password" placeholder="12—128 个字符" required/></el-form-item><el-form-item label="确认新密码"><el-input v-model="password.confirmation" type="password" show-password autocomplete="new-password" required/></el-form-item><el-button type="primary" native-type="submit" :loading="busy">保存新密码</el-button></el-form></section>
 </template>
 <section v-else-if="restricted" class="panel status-panel"><span class="large-symbol">{{user.status==='PENDING'?'◷':'!'}}</span><h1>{{user.status==='PENDING'?'注册已收到，等待审核':'注册暂未通过审核'}}</h1><p class="muted">{{user.review_note||'管理员审核完成后，请重新登录进入工作空间。'}}</p><el-button @click="logout">返回登录</el-button></section>
 <template v-else-if="route.path==='/'"><section class="welcome"><div><span class="eyebrow">{{date}}</span><h1>{{user.name}}，欢迎来到工作空间</h1><p>从人员档案开始，为每一份安排做好准备。</p></div><div class="welcome-mark"><el-icon><Calendar /></el-icon></div></section>
 <div class="home-grid"><section class="panel"><div class="section-heading"><h2>开始准备</h2><el-tag effect="plain">基础资料</el-tag></div><p class="muted">完善人员信息，确认每位成员的账号状态。</p><router-link v-if="isManager" to="/employees" class="action-row"><span class="action-icon"><el-icon><User /></el-icon></span><div><strong>人员档案</strong><small>查看团队成员，录入新员工</small></div><el-icon><ArrowRight /></el-icon></router-link><router-link v-if="isManager" to="/accounts" class="action-row"><span class="action-icon lavender"><el-icon><UserFilled /></el-icon></span><div><strong>账号审核</strong><small>审核注册申请，绑定员工档案</small></div><el-icon><ArrowRight /></el-icon></router-link><router-link v-else to="/profile" class="action-row"><span class="action-icon"><el-icon><User /></el-icon></span><div><strong>个人中心</strong><small>管理你的账号密码</small></div><el-icon><ArrowRight /></el-icon></router-link></section>
 <section class="panel next-panel"><span class="eyebrow">排班工作区</span><h2>准备就绪，有序开始</h2><div class="empty-calendar" aria-hidden="true"><div v-for="i in 21" :class="{'soft-blue':i%5===0}"></div></div><p class="muted">排班工作台将在后续版本开放。<br>当前可以先完成人员和账号准备。</p></section></div></template>
 <template v-else-if="route.path==='/demand-planning'">
  <div class="page-heading">
   <div><span class="eyebrow">排班输入</span><h1>班次与需求</h1><p class="muted">模板定义日常班次；周草稿保存该周实际时间、岗位人数和关闭状态，后续求解直接读取草稿。</p></div>
   <el-button v-if="demandTab==='templates'" type="primary" :icon="Plus" @click="openTemplateDialog()">新增班次模板</el-button>
  </div>
  <section class="panel table-panel qualification-panel">
   <el-tabs v-model="demandTab">
    <el-tab-pane label="班次模板" name="templates">
     <el-table :data="demandTemplates" v-loading="busy" empty-text="尚未创建班次模板">
      <el-table-column prop="name" label="班次名称" min-width="130"/>
      <el-table-column label="时间" min-width="120"><template #default="s">{{s.row.start_time}}—{{s.row.end_time}}</template></el-table-column>
      <el-table-column label="默认岗位需求" min-width="280"><template #default="s"><div class="tag-list compact"><el-tag v-for="demand in s.row.demands" :key="demand.position_id" size="small" :type="demand.position_active?'primary':'info'" effect="light">{{demand.position_name}} × {{demand.required_count}}</el-tag></div></template></el-table-column>
      <el-table-column label="状态" min-width="90"><template #default="s"><el-tag :type="s.row.active?'success':'info'" effect="light">{{s.row.active?'启用':'停用'}}</el-tag></template></el-table-column>
      <el-table-column label="操作" min-width="140"><template #default="s"><el-button link type="primary" @click="openTemplateDialog(s.row)">编辑</el-button><el-button link :type="s.row.active?'danger':'primary'" @click="toggleTemplate(s.row)">{{s.row.active?'停用':'启用'}}</el-button></template></el-table-column>
     </el-table>
    </el-tab-pane>
    <el-tab-pane label="周排班输入" name="week">
     <div class="demand-toolbar">
      <div><span class="field-label">排班周</span><el-date-picker v-model="demandWeekStart" type="date" value-format="YYYY-MM-DD" :clearable="false" @change="changeDemandWeek"/></div>
      <div class="demand-toolbar-actions"><el-button @click="copyPreviousDemandWeek">复制上一周</el-button><el-button type="primary" @click="generateDemandDraft">按模板新建草稿</el-button></div>
     </div>
     <el-alert v-if="!planningPeriod" title="该周还没有排班周期。选择“按模板新建草稿”会同时创建周期并生成周一至周日班次。" type="info" :closable="false" show-icon/>
     <el-alert v-else-if="!planningPeriod.latest_draft" title="周期已创建，但还没有排班输入草稿。请按模板生成或复制上一周。" type="warning" :closable="false" show-icon/>
     <template v-else>
      <div class="metric-grid">
       <div class="metric-card"><span>启用班次</span><strong>{{planningPeriod.latest_draft.metrics.enabled_shifts}}</strong><small>本周开放班次</small></div>
       <div class="metric-card"><span>岗位需求</span><strong>{{planningPeriod.latest_draft.metrics.total_positions}}</strong><small>全部班次合计</small></div>
       <div class="metric-card accent"><span>需求工时</span><strong>{{planningPeriod.latest_draft.metrics.required_hours}}</strong><small>小时</small></div>
      </div>
      <el-table :data="planningPeriod.latest_draft.shifts" v-loading="busy" empty-text="该草稿没有班次">
       <el-table-column label="日期" min-width="150"><template #default="s">{{weekDateLabel(s.row.work_date)}}</template></el-table-column>
       <el-table-column prop="name" label="班次" min-width="100"/>
       <el-table-column label="时间" min-width="110"><template #default="s">{{s.row.start_time}}—{{s.row.end_time}}</template></el-table-column>
       <el-table-column label="岗位人数" min-width="260"><template #default="s"><div class="tag-list compact"><el-tag v-for="demand in s.row.demands" :key="demand.position_id" size="small" :type="demand.position_active?'primary':'info'" effect="light">{{demand.position_name}} × {{demand.required_count}}</el-tag><span v-if="!s.row.demands.length" class="muted">未配置</span></div></template></el-table-column>
       <el-table-column label="状态" min-width="85"><template #default="s"><el-tag :type="s.row.enabled?'success':'info'" effect="light">{{s.row.enabled?'开放':'已关闭'}}</el-tag></template></el-table-column>
       <el-table-column label="操作" min-width="230"><template #default="s"><el-button link type="primary" @click="openShiftDialog(s.row)">调整需求</el-button><el-button link :type="s.row.enabled?'danger':'primary'" @click="toggleDraftShift(s.row)">{{s.row.enabled?'关闭':'启用'}}</el-button><el-button link type="danger" @click="closeDraftDate(s.row.work_date)">关闭当天</el-button></template></el-table-column>
      </el-table>
     </template>
    </el-tab-pane>
   </el-tabs>
  </section>
 </template>
 <template v-else-if="route.path==='/availability'">
  <div class="page-heading"><div><span class="eyebrow">{{isManager?'员工时间填报':'我的工作时间'}}</span><h1>{{isManager?'时间填报进度':'时间与偏好'}}</h1><p class="muted">{{isManager?'查看员工时间填报状态和实际可用时间。':'“不能上班”和“不希望上班”分开设置；日期例外会覆盖对应日期的常规时间。'}}</p></div></div>
  <template v-if="isManager">
   <section class="panel table-panel">
    <div class="table-toolbar"><el-select v-model="preferencePeriodId" class="filter-select wide" placeholder="选择排班周" @change="changeSubmissionPeriod"><el-option v-for="period in periodOptions" :key="period.id" :label="`${period.week_start} 周一`" :value="period.id"/></el-select><el-button @click="changeSubmissionPeriod">刷新进度</el-button><span class="muted">仅统计在岗员工</span></div>
    <div v-if="submissionStatus" class="metric-grid"><div class="metric-card"><span>已提交</span><strong>{{submissionStatus.counts.SUBMITTED}}</strong><small>员工偏好已提交</small></div><div class="metric-card"><span>草稿</span><strong>{{submissionStatus.counts.DRAFT}}</strong><small>尚未提交</small></div><div class="metric-card accent"><span>未填报</span><strong>{{submissionStatus.counts.NOT_SUBMITTED}}</strong><small>需要跟进</small></div></div>
    <el-table :data="submissionStatus?.items||[]" v-loading="busy" empty-text="该周期暂无员工"><el-table-column prop="employee_no" label="员工编号" min-width="110"/><el-table-column prop="name" label="姓名" min-width="120"/><el-table-column label="偏好状态" min-width="110"><template #default="s"><el-tag :type="s.row.status==='SUBMITTED'?'success':s.row.status==='DRAFT'?'warning':'info'" effect="light">{{s.row.status==='SUBMITTED'?'已提交':s.row.status==='DRAFT'?'草稿':'未填报'}}</el-tag></template></el-table-column><el-table-column label="提交时间" min-width="170"><template #default="s">{{formatTime(s.row.submitted_at)}}</template></el-table-column><el-table-column label="操作" min-width="120"><template #default="s"><el-button link type="primary" @click="viewEmployeeAvailability(s.row)">查看可用时间</el-button></template></el-table-column></el-table>
   </section>
  </template>
  <template v-else>
   <section class="panel availability-panel">
    <el-tabs v-model="availabilityTab">
     <el-tab-pane label="常规可用时间" name="weekly">
      <div class="availability-heading"><div><h2>每周常规时间</h2><p class="muted">新的生效日期会关闭上一版本；未配置的时间默认不可用。</p></div><div class="availability-actions"><el-date-picker v-model="weeklyEffectiveFrom" type="date" value-format="YYYY-MM-DD" :clearable="false"/><el-button @click="newWeeklyVersion">新建生效版本</el-button><el-button type="primary" :loading="busy" @click="saveWeeklyAvailability">保存常规时间</el-button></div></div>
      <div class="week-availability"><div v-for="(dayName,index) in ['周一','周二','周三','周四','周五','周六','周日']" :key="dayName" class="weekday-availability"><div class="weekday-name">{{dayName}}<el-button link type="primary" @click="addWeeklyWindow(index+1)">添加时段</el-button></div><div v-for="window in weeklyForDay(index+1)" :key="`${window.start_time}-${window.end_time}-${weeklyWindows.indexOf(window)}`" class="time-window-row"><el-time-picker v-model="window.start_time" value-format="HH:mm" format="HH:mm" :clearable="false"/><span>至</span><el-time-picker v-model="window.end_time" value-format="HH:mm" format="HH:mm" :clearable="false"/><el-button link type="danger" @click="removeWeeklyWindowItem(window)">删除</el-button></div><span v-if="!weeklyForDay(index+1).length" class="muted">默认不可用</span></div></div>
     </el-tab-pane>
     <el-tab-pane label="日期例外" name="exceptions">
      <div class="availability-heading"><div><h2>具体日期例外</h2><p class="muted">替换会覆盖当天全部常规时间；扣除只从常规时间中减去指定时段。</p></div><div class="availability-actions"><el-date-picker v-model="availabilityFrom" type="date" value-format="YYYY-MM-DD" :clearable="false"/><el-date-picker v-model="availabilityTo" type="date" value-format="YYYY-MM-DD" :clearable="false"/><el-button @click="refreshAvailabilityRange">查看</el-button></div></div>
      <el-table :data="availabilityData?.days||[]" v-loading="busy" empty-text="暂无可用时间"><el-table-column label="日期" min-width="160"><template #default="s">{{weekDateLabel(s.row.date)}}</template></el-table-column><el-table-column label="实际可用时间" min-width="280"><template #default="s"><div class="tag-list compact"><el-tag v-for="window in s.row.windows" :key="window.start_time+window.end_time" size="small" effect="light">{{window.start_time}}—{{window.end_time}}</el-tag><span v-if="!s.row.windows.length" class="muted">当天不可用</span></div></template></el-table-column><el-table-column label="来源" min-width="100"><template #default="s"><el-tag :type="s.row.source==='OVERRIDE'?'warning':'info'" effect="plain">{{s.row.source==='OVERRIDE'?(s.row.override_mode==='BLOCK'?'扣除例外':'替换例外'):s.row.source==='REGULAR'?'常规时间':'未配置'}}</el-tag></template></el-table-column><el-table-column label="操作" min-width="110"><template #default="s"><el-button link type="primary" @click="openOverride(s.row)">设置例外</el-button></template></el-table-column></el-table>
     </el-tab-pane>
     <el-tab-pane label="班次偏好" name="preferences">
      <div class="availability-heading"><div><h2>本周班次偏好</h2><p class="muted">偏好用于优化建议，不代表“不能上班”；不能上班请设置日期例外。</p></div><el-select v-model="preferencePeriodId" class="filter-select wide" placeholder="选择排班周" @change="changePreferencePeriod"><el-option v-for="period in periodOptions" :key="period.id" :label="`${period.week_start} 周一`" :value="period.id"/></el-select></div>
      <div v-if="preferenceData" class="preference-status"><el-tag :type="preferenceData.status==='SUBMITTED'?'success':preferenceData.status==='DRAFT'?'warning':'info'">{{preferenceData.status==='SUBMITTED'?'已提交':preferenceData.status==='DRAFT'?'草稿':'未填报'}}</el-tag><span class="muted">保存草稿不会提交；提交后仍可在排班发布前修改。</span></div>
      <div class="preference-add"><el-date-picker v-model="preferenceForm.work_date" type="date" value-format="YYYY-MM-DD" :clearable="false"/><el-select v-model="preferenceForm.template_id" placeholder="选择班次"><el-option v-for="template in templateOptions" :key="template.id" :label="`${template.name} ${template.start_time}—${template.end_time}`" :value="template.id"/></el-select><el-select v-model="preferenceForm.kind"><el-option label="希望安排" value="PREFER"/><el-option label="希望避开" value="AVOID"/></el-select><el-input-number v-model="preferenceForm.weight" :min="1" :max="5"/><el-button @click="addPreferenceItem">添加</el-button></div>
      <el-table :data="preferenceItems" empty-text="尚未添加偏好"><el-table-column label="日期" min-width="150"><template #default="s">{{weekDateLabel(s.row.work_date)}}</template></el-table-column><el-table-column prop="template_name" label="班次" min-width="120"/><el-table-column label="偏好" min-width="100"><template #default="s"><el-tag :type="s.row.kind==='PREFER'?'success':'warning'" effect="light">{{s.row.kind==='PREFER'?'希望安排':'希望避开'}}</el-tag></template></el-table-column><el-table-column prop="weight" label="权重" min-width="80"/><el-table-column label="操作" min-width="90"><template #default="s"><el-button link type="danger" @click="removePreferenceItem(preferenceItems.indexOf(s.row))">移除</el-button></template></el-table-column></el-table>
      <div class="dialog-actions availability-save"><el-button :loading="busy" @click="savePreferences(false)">保存草稿</el-button><el-button type="primary" :loading="busy" @click="savePreferences(true)">提交偏好</el-button></div>
     </el-tab-pane>
    </el-tabs>
   </section>
  </template>
 </template>
 <template v-else-if="route.path==='/scheduling'">
  <div class="page-heading"><div><span class="eyebrow">约束优化</span><h1>自动生成周班表</h1><p class="muted">系统固定当前输入快照，在后台求解人员、技能、时间、工时与规则约束；失败不会覆盖已有方案。</p></div><el-button type="primary" :loading="busy||solverTask?.state==='RUNNING'||solverTask?.state==='QUEUED'" @click="startSolver">{{solverTask&&['OPTIMAL','FEASIBLE'].includes(solverTask.state)?'重新生成':'生成班表'}}</el-button></div>
  <section class="panel solver-toolbar"><div><span class="field-label">选择排班周</span><el-select v-model="solverPeriodId" class="filter-select wide" placeholder="选择周期" @change="changeSolverPeriod"><el-option v-for="period in solverPeriods" :key="period.id" :label="`${period.week_start} 周一`" :value="period.id"/></el-select></div><el-tag v-if="solverPeriod?.latest_draft" effect="plain">输入草稿版本 {{solverPeriod.latest_draft.version_no}} · revision {{solverPeriod.latest_draft.revision}}</el-tag><el-tag v-else type="warning" effect="light">尚无输入草稿</el-tag></section>
  <el-alert v-if="!solverPeriod?.latest_draft" title="请先在“班次与需求”中生成周排班输入草稿，并确认已配置排班规则和员工可用时间。" type="warning" :closable="false" show-icon/>
  <template v-else>
   <section v-if="!solverTask" class="panel solver-empty"><span class="large-symbol">◇</span><h2>准备就绪</h2><p class="muted">点击“生成班表”后，系统将检查岗位需求是否有足够且具备技能、可用时间匹配的员工。</p></section>
   <template v-else>
    <section class="panel solver-status">
     <div class="section-heading"><h2>求解任务</h2><el-tag :type="solverTask.state==='OPTIMAL'||solverTask.state==='FEASIBLE'?'success':solverTask.state==='INFEASIBLE'?'warning':solverTask.state==='FAILED'?'danger':'info'">{{solverStateLabel(solverTask.state)}}</el-tag></div>
     <div class="solver-progress" v-if="solverTask.state==='QUEUED'||solverTask.state==='RUNNING'"><el-progress :indeterminate="true" :percentage="60" :show-text="false"/><p class="muted">正在读取 {{solverTask.input_summary?.employee_count||0}} 名员工、{{solverTask.input_summary?.shift_count||0}} 个班次的输入快照。</p></div>
     <template v-else>
      <div class="metric-grid"><div class="metric-card"><span>岗位安排</span><strong>{{solverTask.metrics?.assignment_count||0}}</strong><small>条人员安排</small></div><div class="metric-card"><span>安排工时</span><strong>{{((solverTask.metrics?.required_minutes||0)/60).toFixed(1)}}</strong><small>小时</small></div><div class="metric-card accent"><span>偏好满足</span><strong>{{solverTask.metrics?.preference_satisfied||0}}</strong><small>共 {{solverTask.metrics?.preference_total||0}} 条有效偏好</small></div></div>
      <p v-if="solverTask.solve_ms" class="muted">求解耗时 {{(solverTask.solve_ms/1000).toFixed(2)}} 秒。</p>
      <el-alert v-for="issue in solverTask.issues" :key="issue.code+issue.work_date+issue.shift_name" :title="issue.message||`${issue.work_date} ${issue.shift_name} ${issue.position_name}：需要 ${issue.required} 人，实际可用 ${issue.available} 人`" type="warning" :closable="false" show-icon/>
     </template>
    </section>
    <section v-if="solverTask.assignments?.length" class="panel table-panel solver-results">
     <div class="section-heading"><h2>生成的岗位安排</h2><span class="muted">后续可在班表工作台手工调整</span></div>
     <el-table :data="solverTask.assignments"><el-table-column label="日期" min-width="150"><template #default="s">{{weekDateLabel(s.row.work_date)}}</template></el-table-column><el-table-column prop="shift_name" label="班次" min-width="100"/><el-table-column prop="position_name" label="岗位" min-width="120"/><el-table-column prop="employee_name" label="员工" min-width="120"/></el-table>
    </section>
   </template>
  </template>
 </template>
 <template v-else-if="route.path==='/workbench'">
  <div class="page-heading"><div><span class="eyebrow">草稿编辑与校验</span><h1>班表工作台</h1><p class="muted">按员工或岗位筛选，点击班次调整人员。业务冲突允许保存，但必须在后续发布前修复。</p></div><div class="workbench-actions"><el-button @click="validateWorkbench">统一校验</el-button><el-button type="primary" :loading="busy" @click="saveWorkbenchAssignments(true)">保存人员安排</el-button><el-button v-if="workbenchVersion" @click="goRegenerateFromWorkbench">重新生成</el-button></div></div>
  <section class="panel solver-toolbar"><div><span class="field-label">选择排班周</span><el-select v-model="workbenchPeriodId" class="filter-select wide" @change="changeWorkbenchPeriod"><el-option v-for="period in workbenchPeriods" :key="period.id" :label="`${period.week_start} 周一`" :value="period.id"/></el-select></div><el-tag v-if="workbenchVersion" effect="plain">版本 {{workbenchVersion.version_no}} · revision {{workbenchVersion.revision}}</el-tag><el-tag v-else type="warning">尚无草稿</el-tag></section>
  <el-alert v-if="!workbenchVersion" title="请先在“班次与需求”中生成排班输入草稿。" type="warning" :closable="false" show-icon/>
  <template v-else>
   <section class="panel table-toolbar workbench-filters"><el-select v-model="workbenchEmployeeFilter" clearable placeholder="按员工筛选"><el-option v-for="employee in workbenchEmployeeOptions" :key="employee.id" :label="employee.name" :value="employee.id"/></el-select><el-select v-model="workbenchPositionFilter" clearable placeholder="按岗位筛选"><el-option v-for="position in workbenchPositionOptions" :key="position.id" :label="position.name" :value="position.id"/></el-select><span v-if="workbenchDirty" class="dirty-note">有未保存修改</span><el-tag :type="workbenchValidation?.valid?'success':'warning'" effect="light">{{workbenchValidation?(workbenchValidation.valid?'校验通过':'存在冲突'):'尚未校验'}}</el-tag></section>
   <section class="panel table-panel">
    <el-table :data="workbenchFilteredShifts" v-loading="busy"><el-table-column label="日期" min-width="150"><template #default="s">{{weekDateLabel(s.row.work_date)}}</template></el-table-column><el-table-column prop="name" label="班次" min-width="100"/><el-table-column label="时间" min-width="110"><template #default="s">{{s.row.start_time}}—{{s.row.end_time}}</template></el-table-column><el-table-column label="岗位与人员" min-width="380"><template #default="s"><div class="position-assignment-list"><div v-for="demand in s.row.demands" :key="demand.position_id" class="position-assignment-row"><span class="position-demand">{{demand.position_name}} {{assignmentsFor(s.row,demand).length}}/{{demand.required_count}}</span><div class="tag-list compact"><el-tag v-for="assignment in assignmentsFor(s.row,demand)" :key="assignment.employee_id" :type="assignment.locked?'warning':'primary'" effect="light">{{assignment.employee_name}}{{assignment.locked?' · 已锁定':''}}</el-tag><span v-if="!assignmentsFor(s.row,demand).length" class="muted">未安排</span></div></div></div></template></el-table-column><el-table-column label="覆盖" min-width="100"><template #default="s"><el-tag :type="shiftAssigned(s.row)===shiftRequired(s.row)?'success':'warning'" effect="plain">{{shiftAssigned(s.row)}}/{{shiftRequired(s.row)}}</el-tag></template></el-table-column><el-table-column label="操作" min-width="100"><template #default="s"><el-button link type="primary" @click="openWorkbenchShift(s.row)">调整人员</el-button></template></el-table-column></el-table>
   </section>
   <section v-if="workbenchValidation" class="panel validation-panel">
    <div class="section-heading"><h2>统一校验结果</h2><el-tag :type="workbenchValidation.valid?'success':'danger'">{{workbenchValidation.valid?'无硬冲突':'需要处理'}}</el-tag></div>
    <div class="metric-grid"><div class="metric-card"><span>岗位覆盖</span><strong>{{workbenchValidation.metrics.assignment_count}}/{{workbenchValidation.metrics.required_positions}}</strong><small>已安排 / 需求</small></div><div class="metric-card"><span>偏好满足率</span><strong>{{workbenchValidation.metrics.preference_rate===null?'—':workbenchValidation.metrics.preference_rate+'%'}}</strong><small>{{workbenchValidation.metrics.preference_rate===null?'未提交偏好':'已提交偏好'}}</small></div><div class="metric-card accent"><span>工时差</span><strong>{{((workbenchValidation.metrics.max_minutes-workbenchValidation.metrics.min_minutes)/60).toFixed(1)}}</strong><small>员工计划工时极差（小时）</small></div></div>
    <div v-if="workbenchValidation.hard_conflicts.length" class="conflict-list"><h3>硬冲突</h3><el-alert v-for="(conflict,index) in workbenchValidation.hard_conflicts" :key="index" :title="conflict.message" :description="`${conflict.date||''} ${conflict.shift_key||''} ${conflict.position_id||''}`" type="error" :closable="false" show-icon/></div>
    <div v-if="workbenchValidation.soft_warnings.length" class="conflict-list"><h3>偏好与公平提示</h3><el-alert v-for="(warning,index) in workbenchValidation.soft_warnings" :key="index" :title="warning.message" :description="`${warning.date||''}`" type="warning" :closable="false" show-icon/></div>
   </section>
  </template>
 </template>
 <template v-else-if="route.path==='/versions'">
  <div class="page-heading"><div><span class="eyebrow">发布与追溯</span><h1>版本与发布</h1><p class="muted">发布前重新读取当前人员、可用时间、偏好和规则并强制校验；已发布版本只读保留。</p></div></div>
  <section class="panel solver-toolbar"><div><span class="field-label">选择排班周</span><el-select v-model="versionPeriodId" class="filter-select wide" @change="changeVersionPeriod"><el-option v-for="period in versionPeriods" :key="period.id" :label="`${period.week_start} 周一`" :value="period.id"/></el-select></div><el-tag v-if="versionPeriod?.current_version_id" type="success">已发布</el-tag><el-tag v-else type="info">尚未发布</el-tag></section>
  <section v-if="versionPeriod" class="panel table-panel"><div class="section-heading"><h2>版本时间线</h2><span class="muted">周期 revision {{versionPeriod.revision}}</span></div><el-table :data="versionList" @row-click="selectVersion" highlight-current-row><el-table-column prop="version_no" label="版本" min-width="80"/><el-table-column label="状态" min-width="110"><template #default="s"><el-tag :type="s.row.status==='PUBLISHED'?'success':s.row.status==='DRAFT'?'warning':'info'" effect="light">{{versionStatusLabel(s.row.status)}}</el-tag></template></el-table-column><el-table-column prop="revision" label="revision" min-width="90"/><el-table-column label="创建时间" min-width="170"><template #default="s">{{formatTime(s.row.created_at)}}</template></el-table-column><el-table-column label="发布时间" min-width="170"><template #default="s">{{formatTime(s.row.published_at)}}</template></el-table-column><el-table-column prop="published_by_name" label="发布人" min-width="100"/></el-table></section>
  <section v-if="selectedVersion" class="panel version-detail">
   <div class="section-heading"><h2>版本 {{selectedVersion.version_no}} · {{versionStatusLabel(selectedVersion.status)}}</h2><div class="workbench-actions"><el-button @click="loadVersionDiff">与当前发布版本比较</el-button><el-button v-if="selectedVersion.status==='DRAFT'" @click="validateSelectedVersion">重新校验</el-button><el-button v-if="selectedVersion.status==='DRAFT'" type="primary" :loading="busy" @click="publishSelectedVersion">发布</el-button><el-button @click="copySelectedVersion">复制为新草稿</el-button><el-button v-if="selectedVersion.status==='DRAFT'" type="danger" plain @click="discardSelectedVersion">废弃草稿</el-button></div></div>
   <div class="metric-grid"><div class="metric-card"><span>岗位需求</span><strong>{{selectedVersion.metrics.total_positions}}</strong><small>岗位数量</small></div><div class="metric-card"><span>安排人员</span><strong>{{selectedVersion.assignments.length}}</strong><small>条分配</small></div><div class="metric-card accent"><span>需求工时</span><strong>{{selectedVersion.metrics.required_hours}}</strong><small>小时</small></div></div>
   <div v-if="versionPublishValidation" class="publish-validation"><el-tag :type="versionPublishValidation.valid?'success':'danger'">{{versionPublishValidation.valid?'发布校验通过':'存在硬冲突'}}</el-tag><span class="muted">input revision {{versionPublishValidation.input_revision}}</span><el-alert v-for="(conflict,index) in versionPublishValidation.hard_conflicts" :key="index" :title="conflict.message" type="error" :closable="false" show-icon/></div>
   <div v-if="versionDiff" class="diff-panel"><div class="section-heading"><h2>版本差异</h2><span class="muted">新增班次 {{versionDiff.summary.shifts_added}} · 移除 {{versionDiff.summary.shifts_removed}} · 变更 {{versionDiff.summary.shifts_changed}} · 新增安排 {{versionDiff.summary.assignments_added}} · 移除安排 {{versionDiff.summary.assignments_removed}}</span></div><el-table :data="versionDiff.assignments_added" max-height="220"><el-table-column prop="employee_id" label="新增安排员工" min-width="120"/><el-table-column prop="position_id" label="岗位" min-width="100"/><el-table-column prop="shift_key" label="班次键" min-width="260"/></el-table><el-table :data="versionDiff.assignments_removed" max-height="220"><el-table-column prop="employee_id" label="移除安排员工" min-width="120"/><el-table-column prop="position_id" label="岗位" min-width="100"/><el-table-column prop="shift_key" label="班次键" min-width="260"/></el-table></div>
  </section>
 </template>
 <template v-else-if="route.path==='/my-schedule'">
  <div class="page-heading"><div><span class="eyebrow">当前发布班表</span><h1>我的班表</h1><p class="muted">仅显示当前已发布版本中的本人安排；历史替代版本不会继续展示。</p></div></div>
  <section class="panel table-panel"><div class="table-toolbar"><el-date-picker v-model="myScheduleFrom" type="date" value-format="YYYY-MM-DD" :clearable="false"/><span>至</span><el-date-picker v-model="myScheduleTo" type="date" value-format="YYYY-MM-DD" :clearable="false"/><el-button type="primary" @click="loadMySchedule">查询</el-button></div><el-table :data="myScheduleItems" v-loading="busy" empty-text="所选日期没有已发布安排"><el-table-column label="日期" min-width="160"><template #default="s">{{weekDateLabel(s.row.work_date)}}</template></el-table-column><el-table-column prop="shift_name" label="班次" min-width="110"/><el-table-column label="时间" min-width="120"><template #default="s">{{s.row.start_time}}—{{s.row.end_time}}</template></el-table-column><el-table-column prop="position_name" label="岗位" min-width="120"/><el-table-column label="发布版本" min-width="100"><template #default="s">第 {{s.row.version_no}} 版</template></el-table-column></el-table></section>
 </template>
 <template v-else-if="route.path==='/rules'">
  <div class="page-heading"><div><span class="eyebrow">约束与优化</span><h1>排班规则</h1><p class="muted">硬约束保障基本可行性；软约束权重用于在多个可行方案之间优化偏好与公平性。</p></div><el-button v-if="isManager" type="primary" :icon="Plus" @click="openRuleDialog">创建新规则版本</el-button></div>
  <section class="panel rule-panel">
   <div class="rule-week-row"><div><span class="field-label">查看生效周</span><el-date-picker v-model="ruleWeek" type="date" value-format="YYYY-MM-DD" :clearable="false" @change="changeRuleWeek"/></div><el-tag v-if="effectiveRule" type="success" effect="light">版本 {{effectiveRule.version_no}}</el-tag></div>
   <template v-if="effectiveRule">
    <div class="rule-card-grid"><div class="rule-card"><span>每人每天班次上限</span><strong>{{effectiveRule.daily_shift_limit}}</strong><small>个班次</small></div><div class="rule-card"><span>每周工时上限</span><strong>{{formatHourValue(effectiveRule.weekly_minutes_limit)}}</strong><small>小时</small></div><div class="rule-card"><span>连续工作上限</span><strong>{{effectiveRule.consecutive_days_limit}}</strong><small>天</small></div><div class="rule-card"><span>班间最短休息</span><strong>{{effectiveRule.min_rest_minutes}}</strong><small>分钟</small></div></div>
    <div class="weight-row"><div><span>偏好满足</span><el-progress :percentage="effectiveRule.weights.preference" :show-text="false"/><strong>{{effectiveRule.weights.preference}}</strong></div><div><span>工时均衡</span><el-progress :percentage="effectiveRule.weights.hours_balance" :show-text="false" color="#14b8a6"/><strong>{{effectiveRule.weights.hours_balance}}</strong></div><div><span>晚班均衡</span><el-progress :percentage="effectiveRule.weights.evening_balance" :show-text="false" color="#8b5cf6"/><strong>{{effectiveRule.weights.evening_balance}}</strong></div></div>
    <el-alert title="时间重叠、员工在岗状态、岗位技能和已批准不可用时段属于不可关闭的基础约束。" type="info" :closable="false" show-icon/>
   </template>
   <el-alert v-else title="该周之前还没有生效的排班规则。请管理员先创建规则版本。" type="warning" :closable="false" show-icon/>
  </section>
  <section v-if="isManager" class="panel table-panel rule-history">
   <div class="section-heading"><h2>版本历史</h2><span class="muted">规则版本创建后不可修改</span></div>
   <el-table :data="ruleVersions" v-loading="busy" empty-text="尚未创建规则版本"><el-table-column prop="version_no" label="版本" min-width="80"/><el-table-column label="生效周" min-width="130"><template #default="s">{{weekDateLabel(s.row.effective_week)}}</template></el-table-column><el-table-column label="硬约束" min-width="300"><template #default="s">每天 {{s.row.daily_shift_limit}} 班 · 每周 {{formatHourValue(s.row.weekly_minutes_limit)}} 小时 · 连续 {{s.row.consecutive_days_limit}} 天 · 休息 {{s.row.min_rest_minutes}} 分钟</template></el-table-column><el-table-column label="软约束权重" min-width="220"><template #default="s">偏好 {{s.row.weights.preference}} · 工时 {{s.row.weights.hours_balance}} · 晚班 {{s.row.weights.evening_balance}}</template></el-table-column><el-table-column prop="created_by_name" label="创建人" min-width="100"/><el-table-column label="创建时间" min-width="170"><template #default="s">{{formatTime(s.row.created_at)}}</template></el-table-column></el-table>
  </section>
 </template>
 <template v-else-if="route.path==='/qualifications'">
  <div class="page-heading">
   <div><span class="eyebrow">人员资格基础</span><h1>岗位与技能</h1><p class="muted">岗位要求员工同时具备全部指定技能；停用只关闭后续使用，不删除历史关联。</p></div>
   <el-button type="primary" :icon="Plus" @click="qualificationTab==='positions'?openPositionDialog():openSkillDialog()">新增{{qualificationTab==='positions'?'岗位':'技能'}}</el-button>
  </div>
  <section class="panel table-panel qualification-panel">
   <el-tabs v-model="qualificationTab">
    <el-tab-pane label="岗位" name="positions">
     <el-table :data="positions" v-loading="busy" empty-text="尚未创建岗位">
      <el-table-column prop="name" label="岗位名称" min-width="140"/>
      <el-table-column prop="code" label="编码" min-width="110"/>
      <el-table-column label="所需技能" min-width="260"><template #default="s"><div class="tag-list compact"><el-tag v-for="skill in s.row.required_skills" :key="skill.id" size="small" :type="skill.active?'primary':'info'" effect="light">{{skill.name}}</el-tag><span v-if="!s.row.required_skills.length" class="muted">通用岗位</span></div></template></el-table-column>
      <el-table-column label="状态" min-width="90"><template #default="s"><el-tag :type="s.row.active?'success':'info'" effect="light">{{s.row.active?'启用':'停用'}}</el-tag></template></el-table-column>
      <el-table-column label="操作" min-width="140"><template #default="s"><el-button link type="primary" @click="openPositionDialog(s.row)">编辑</el-button><el-button link :type="s.row.active?'danger':'primary'" @click="togglePosition(s.row)">{{s.row.active?'停用':'启用'}}</el-button></template></el-table-column>
     </el-table>
    </el-tab-pane>
    <el-tab-pane label="技能" name="skills">
     <el-table :data="skills" v-loading="busy" empty-text="尚未创建技能">
      <el-table-column prop="name" label="技能名称" min-width="180"/>
      <el-table-column prop="code" label="编码" min-width="130"/>
      <el-table-column label="状态" min-width="90"><template #default="s"><el-tag :type="s.row.active?'success':'info'" effect="light">{{s.row.active?'启用':'停用'}}</el-tag></template></el-table-column>
      <el-table-column label="操作" min-width="140"><template #default="s"><el-button link type="primary" @click="openSkillDialog(s.row)">编辑</el-button><el-button link :type="s.row.active?'danger':'primary'" @click="toggleSkill(s.row)">{{s.row.active?'停用':'启用'}}</el-button></template></el-table-column>
     </el-table>
    </el-tab-pane>
   </el-tabs>
  </section>
 </template>
 <template v-else-if="route.path==='/password-resets'">
  <div class="page-heading"><div><span class="eyebrow">账号安全</span><h1>密码重置审批</h1><p class="muted">仅在核实账号本人身份后处理，不通过消息公开或长期保存临时密码。</p></div></div>
  <section class="panel table-panel">
   <div class="table-toolbar">
    <el-select v-model="resetFilter" class="filter-select" @change="page=1;load()">
     <el-option label="待处理申请" value="PENDING"/><el-option label="已处理申请" value="PROCESSED"/>
    </el-select>
    <el-button @click="page=1;load()">刷新列表</el-button>
    <span class="muted">共 {{total}} 条记录</span>
   </div>
   <el-table :data="rows" v-loading="busy" empty-text="暂无重置申请">
    <el-table-column prop="name" label="申请人" min-width="130"/>
    <el-table-column prop="username" label="账号" min-width="120"/>
    <el-table-column label="账号状态" min-width="100"><template #default="s"><el-tag :type="s.row.account_status==='ACTIVE'?'success':'warning'" effect="light">{{statuses[s.row.account_status]||s.row.account_status}}</el-tag></template></el-table-column>
    <el-table-column label="申请时间" min-width="170"><template #default="s">{{formatTime(s.row.requested_at)}}</template></el-table-column>
    <el-table-column label="处理状态" min-width="100"><template #default="s"><el-tag :type="s.row.status==='PROCESSED'?'success':'warning'" effect="plain">{{resetStatuses[s.row.status]||s.row.status}}</el-tag></template></el-table-column>
    <el-table-column v-if="resetFilter==='PROCESSED'" label="处理信息" min-width="200"><template #default="s"><span>{{s.row.processed_by_name||'管理员'}} · {{formatTime(s.row.processed_at)}}</span><small class="cell-note">{{s.row.note}}</small></template></el-table-column>
    <el-table-column label="操作" min-width="110"><template #default="s"><el-button v-if="s.row.status==='PENDING'" link type="primary" @click="openReset(s.row)">处理申请</el-button><span v-else class="muted">已完成</span></template></el-table-column>
   </el-table>
   <el-pagination class="pagination" v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load"/>
  </section>
 </template>
 <template v-else-if="route.path==='/leave'">
  <LeavePanel/>
 </template>
 <template v-else-if="route.path==='/swaps'">
  <SwapPanel/>
 </template>
 <template v-else-if="route.path==='/notifications'">
  <NotificationPanel/>
 </template>
 <template v-else-if="route.path==='/dynamic-adjustment'">
  <AdjustmentPanel/>
 </template>
 <template v-else-if="route.path==='/statistics'">
  <StatisticsPanel/>
 </template>
 <template v-else-if="route.path==='/ai-requirements'">
  <AIParsePanel/>
 </template>
 <template v-else-if="route.path==='/ai-explanations'">
  <AIExplanationPanel/>
 </template>
 <template v-else-if="route.path==='/system-audit'">
  <SystemPanel @settings-updated="loadStoreSettings"/>
 </template>
 <template v-else>
  <div class="page-heading">
   <div><span class="eyebrow">团队管理</span><h1>{{heading}}</h1><p class="muted">{{route.path==='/employees'?'统一维护团队成员的基础信息。':'审核员工注册申请，也可直接创建员工账号并绑定未使用的员工档案。'}}</p></div>
   <el-button v-if="route.path==='/employees'" type="primary" :icon="Plus" @click="Object.assign(employee,{employee_no:'',name:'',employment_type:'FULL_TIME',weekly_limit_minutes:2400});dialog=true">新增员工</el-button>
   <el-button v-else-if="route.path==='/accounts'" type="primary" :icon="Plus" @click="openCreateAccount">创建员工账号</el-button>
  </div>
  <section class="panel table-panel">
   <div class="table-toolbar">
    <el-input v-if="route.path==='/employees'" v-model="search" :prefix-icon="Search" placeholder="搜索姓名或员工编号" clearable @keyup.enter="page=1;load()" @clear="page=1;load()"/>
    <el-select v-if="route.path==='/employees'" v-model="employeeStatusFilter" class="filter-select" @change="page=1;load()"><el-option label="全部状态" value=""/><el-option label="在岗" value="ACTIVE"/><el-option label="已停用" value="INACTIVE"/></el-select>
    <el-select v-if="route.path==='/employees'" v-model="employeePositionFilter" class="filter-select wide" @change="page=1;load()"><el-option label="全部岗位" value=""/><el-option v-for="p in positionOptions" :key="p.id" :label="p.name" :value="p.id"/></el-select>
    <el-select v-if="route.path==='/accounts'" v-model="accountFilter" class="filter-select" @change="page=1;load()">
     <el-option label="全部账号" value=""/><el-option label="待审核" value="PENDING"/><el-option label="已启用" value="ACTIVE"/><el-option label="已停用" value="DISABLED"/><el-option label="未通过" value="REJECTED"/>
    </el-select>
    <el-button @click="page=1;load()">刷新列表</el-button>
    <span class="muted">共 {{total}} 条记录</span>
   </div>
   <el-table :data="rows" v-loading="busy" empty-text="暂无记录">
    <el-table-column prop="name" label="姓名" min-width="120"/>
    <el-table-column v-if="route.path==='/employees'" prop="employee_no" label="员工编号" min-width="120"/>
    <el-table-column v-else prop="username" label="账号" min-width="120"/>
    <el-table-column v-if="route.path==='/accounts'" label="角色" min-width="90"><template #default="s">{{s.row.role==='MANAGER'?'管理员':'员工'}}</template></el-table-column>
    <el-table-column label="状态" min-width="110"><template #default="s"><el-tag :type="s.row.status==='ACTIVE'?'success':s.row.status==='DISABLED'?'info':'warning'" effect="light">{{statuses[s.row.status]||s.row.status}}</el-tag></template></el-table-column>
    <el-table-column v-if="route.path==='/employees'" label="每周工时上限" min-width="130"><template #default="s">{{formatHours(s.row.weekly_limit_minutes)}}</template></el-table-column>
    <el-table-column v-if="route.path==='/employees'" label="账号绑定" min-width="120"><template #default="s">{{s.row.bound?'已绑定':'待绑定'}}</template></el-table-column>
    <el-table-column v-if="route.path==='/employees'" label="操作" min-width="150"><template #default="s"><el-button link type="primary" @click="openEditEmployee(s.row)">编辑资料</el-button><el-button link :type="s.row.status==='ACTIVE'?'danger':'primary'" @click="changeEmployeeStatus(s.row,s.row.status==='ACTIVE'?'INACTIVE':'ACTIVE')">{{s.row.status==='ACTIVE'?'停用':'启用'}}</el-button></template></el-table-column>
    <el-table-column v-if="route.path==='/accounts'" label="操作" min-width="150">
     <template #default="s">
      <el-button v-if="s.row.status==='PENDING'" link type="primary" @click="openReview(s.row)">审核申请</el-button>
      <el-button v-else-if="s.row.status==='ACTIVE'" link type="danger" @click="changeAccountStatus(s.row,'DISABLED')">停用</el-button>
      <el-button v-else-if="s.row.status==='DISABLED'" link type="primary" @click="changeAccountStatus(s.row,'ACTIVE')">启用</el-button>
      <span v-else class="muted">—</span>
     </template>
    </el-table-column>
   </el-table>
   <el-pagination class="pagination" v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load"/>
  </section>
 </template>
 </main></div>
 <el-dialog v-model="dialog" title="新增员工档案" width="min(480px, 94vw)"><el-form label-position="top" @submit.prevent="saveEmployee"><el-form-item label="员工编号"><el-input v-model="employee.employee_no" placeholder="例如 E001" required/></el-form-item><el-form-item label="姓名"><el-input v-model="employee.name" required/></el-form-item><el-form-item label="用工类型"><el-select v-model="employee.employment_type"><el-option label="全职" value="FULL_TIME"/><el-option label="兼职" value="PART_TIME"/></el-select></el-form-item><el-form-item label="每周工时上限（小时）"><el-input-number v-model="employeeWeeklyHours" :min="0.1" :max="168" :step="0.1" :precision="1"/></el-form-item><el-alert v-if="error" :title="error" type="error" :closable="false"/><el-button type="primary" native-type="submit" :loading="busy">创建档案</el-button></el-form></el-dialog>
 <el-dialog :model-value="!!employeeEditTarget" title="编辑员工资料" width="min(560px, 94vw)" @close="employeeEditTarget=null">
  <template v-if="employeeEditTarget">
   <el-form label-position="top" @submit.prevent="saveEmployeeEdit">
    <div class="form-grid"><el-form-item label="员工编号"><el-input v-model="employeeEditForm.employee_no" maxlength="32" required/></el-form-item><el-form-item label="姓名"><el-input v-model="employeeEditForm.name" maxlength="64" required/></el-form-item></div>
    <div class="form-grid"><el-form-item label="用工类型"><el-select v-model="employeeEditForm.employment_type"><el-option label="全职" value="FULL_TIME"/><el-option label="兼职" value="PART_TIME"/></el-select></el-form-item><el-form-item label="每周工时上限（小时）"><el-input-number v-model="employeeEditWeeklyHours" :min="0.1" :max="168" :step="0.1" :precision="1"/></el-form-item></div>
    <el-form-item label="员工技能"><el-select v-model="employeeEditSkills" multiple filterable placeholder="选择员工已具备的技能"><el-option v-for="s in employeeEditActiveSkills" :key="s.id" :label="s.name" :value="Number(s.id)"/></el-select></el-form-item>
    <el-alert v-if="employeeHasInactiveSkills" title="资料中存在已停用的技能，保存后将不再保留这些技能关联。" type="info" :closable="false" show-icon/>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
    <div class="dialog-actions"><el-button @click="employeeEditTarget=null">取消</el-button><el-button type="primary" native-type="submit" :loading="busy">保存资料</el-button></div>
   </el-form>
  </template>
 </el-dialog>
 <el-dialog v-model="accountDialog" title="创建员工账号" width="min(500px, 94vw)">
  <el-form label-position="top" @submit.prevent="createAccount">
   <el-form-item label="登录账号"><el-input v-model="accountForm.username" placeholder="4—32 位字母、数字或下划线" maxlength="32" autocomplete="off" required/></el-form-item>
   <el-form-item label="员工姓名"><el-input v-model="accountForm.name" placeholder="用于工作空间显示" maxlength="64" required/></el-form-item>
   <el-form-item label="绑定员工档案（可选）">
    <el-select v-model="accountForm.employee_id" clearable placeholder="暂不绑定，稍后处理"><el-option v-for="e in accountEmployees" :key="e.id" :label="e.employee_no+' · '+e.name" :value="e.id"/></el-select>
   </el-form-item>
   <p class="muted">创建后账号立即启用，系统只显示一次随机临时密码，首次登录必须修改。</p>
   <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
   <div class="dialog-actions"><el-button @click="accountDialog=false">取消</el-button><el-button type="primary" native-type="submit" :loading="busy">创建账号</el-button></div>
  </el-form>
 </el-dialog>
 <el-dialog v-model="skillDialog" :title="skillEditTarget?'编辑技能':'新增技能'" width="min(450px, 94vw)">
  <el-form label-position="top" @submit.prevent="saveSkill"><el-form-item label="技能编码"><el-input v-model="skillForm.code" :disabled="!!skillEditTarget" placeholder="例如 latte_art" maxlength="32" required/></el-form-item><el-form-item label="技能名称"><el-input v-model="skillForm.name" placeholder="例如 拉花" maxlength="64" required/></el-form-item><el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/><div class="dialog-actions"><el-button @click="skillDialog=false">取消</el-button><el-button type="primary" native-type="submit" :loading="busy">{{skillEditTarget?'保存':'创建'}}</el-button></div></el-form>
 </el-dialog>
 <el-dialog v-model="positionDialog" :title="positionEditTarget?'编辑岗位':'新增岗位'" width="min(500px, 94vw)">
  <el-form label-position="top" @submit.prevent="savePosition"><el-form-item label="岗位编码"><el-input v-model="positionForm.code" :disabled="!!positionEditTarget" placeholder="例如 barista" maxlength="32" required/></el-form-item><el-form-item label="岗位名称"><el-input v-model="positionForm.name" placeholder="例如 咖啡师" maxlength="64" required/></el-form-item><el-form-item label="所需技能"><el-select v-model="positionSkillIds" multiple filterable placeholder="不选择表示通用岗位"><el-option v-for="s in activeSkills" :key="s.id" :label="s.name" :value="Number(s.id)"/></el-select></el-form-item><p class="muted">员工需要同时具备这里选择的全部技能，才能胜任该岗位。</p><el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/><div class="dialog-actions"><el-button @click="positionDialog=false">取消</el-button><el-button type="primary" native-type="submit" :loading="busy">{{positionEditTarget?'保存':'创建'}}</el-button></div></el-form>
 </el-dialog>
 <el-dialog v-model="templateDialog" :title="templateEditTarget?'编辑班次模板':'新增班次模板'" width="min(620px, 94vw)">
  <el-form label-position="top" @submit.prevent="saveTemplate">
   <div class="form-grid"><el-form-item label="班次编码"><el-input v-model="templateForm.code" placeholder="例如 morning" maxlength="32" required/></el-form-item><el-form-item label="班次名称"><el-input v-model="templateForm.name" placeholder="例如 早班" maxlength="32" required/></el-form-item></div>
   <div class="form-grid"><el-form-item label="开始时间"><el-time-picker v-model="templateForm.start_time" value-format="HH:mm" format="HH:mm" :clearable="false"/></el-form-item><el-form-item label="结束时间"><el-time-picker v-model="templateForm.end_time" value-format="HH:mm" format="HH:mm" :clearable="false"/></el-form-item></div>
   <div class="demand-editor"><div class="section-heading"><h2>默认岗位人数</h2><span class="muted">人数为0表示该岗位默认不配置</span></div><div v-for="position in activeDemandPositions" :key="position.id" class="demand-row"><span>{{position.name}}</span><el-input-number v-model="templateDemandMap[position.id]" :min="0" :max="100"/></div><el-alert v-if="!activeDemandPositions.length" title="请先在“岗位与技能”中启用至少一个岗位。" type="warning" :closable="false" show-icon/></div>
   <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
   <div class="dialog-actions"><el-button @click="templateDialog=false">取消</el-button><el-button type="primary" native-type="submit" :loading="busy">保存模板</el-button></div>
  </el-form>
 </el-dialog>
 <el-dialog v-model="shiftDialog" title="调整本周班次需求" width="min(580px, 94vw)">
  <template v-if="shiftEditTarget">
   <div class="shift-summary"><strong>{{weekDateLabel(shiftEditTarget.work_date)}} · {{shiftEditTarget.name}}</strong><span>{{shiftEditTarget.start_time}}—{{shiftEditTarget.end_time}}</span></div>
   <el-form label-position="top"><el-form-item label="本周是否开放"><el-switch v-model="shiftEditTarget.enabled" active-text="开放" inactive-text="关闭"/></el-form-item><div class="demand-editor"><div class="section-heading"><h2>岗位人数</h2><span class="muted">只修改当前周草稿</span></div><div v-for="position in activeDemandPositions" :key="position.id" class="demand-row"><span>{{position.name}}</span><el-input-number v-model="shiftDemandMap[position.id]" :min="0" :max="100"/></div></div></el-form>
   <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
   <div class="dialog-actions"><el-button @click="shiftDialog=false">取消</el-button><el-button type="primary" :loading="busy" @click="saveShift">保存当前班次</el-button></div>
  </template>
 </el-dialog>
 <el-dialog :model-value="!!workbenchShiftTarget" title="调整班次人员" width="min(680px, 94vw)" @close="workbenchShiftTarget=null">
  <template v-if="workbenchShiftTarget">
   <div class="shift-summary"><strong>{{weekDateLabel(workbenchShiftTarget.work_date)}} · {{workbenchShiftTarget.name}}</strong><span>{{workbenchShiftTarget.start_time}}—{{workbenchShiftTarget.end_time}}</span></div>
   <div v-for="demand in workbenchShiftTarget.demands" :key="demand.position_id" class="workbench-demand-editor">
    <div class="section-heading"><h2>{{demand.position_name}}（{{assignmentsFor(workbenchShiftTarget,demand).length}}/{{demand.required_count}}）</h2></div>
    <div class="assigned-workers"><div v-for="assignment in assignmentsFor(workbenchShiftTarget,demand)" :key="assignment.employee_id" class="assigned-worker"><span>{{assignment.employee_name}}</span><el-switch v-model="assignment.locked" size="small" active-text="锁定" @change="markWorkbenchDirty"/><el-button link type="danger" @click="removeWorkbenchAssignment(assignment)">移除</el-button></div><span v-if="!assignmentsFor(workbenchShiftTarget,demand).length" class="muted">尚未安排人员</span></div>
    <div class="preference-add compact-assign"><el-select v-model="workbenchSelections[demand.position_id]" filterable placeholder="选择员工"><el-option v-for="candidate in workbenchCandidates[demand.position_id]||[]" :key="candidate.employee_id" :label="candidateLabel(candidate)" :value="candidate.employee_id" :disabled="!candidate.eligible"/></el-select><el-button @click="addWorkbenchAssignment(demand)">添加人员</el-button></div>
   </div>
   <p class="muted">锁定表示重新生成时必须保留该人员与岗位；若员工技能或可用时间已变化，求解会明确报告锁定安排不可用。</p>
   <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
   <div class="dialog-actions"><el-button @click="workbenchShiftTarget=null">取消</el-button><el-button type="primary" :loading="busy" @click="saveAndCloseWorkbenchShift">保存并校验</el-button></div>
  </template>
 </el-dialog>
 <el-dialog v-model="overrideDialog" title="设置日期例外" width="min(560px, 94vw)">
  <template v-if="overrideTarget">
   <div class="shift-summary"><strong>{{weekDateLabel(overrideTarget.date)}}</strong><span>当前：{{overrideTargetSummary}}</span></div>
   <el-form label-position="top"><el-form-item label="例外方式"><el-radio-group v-model="overrideMode"><el-radio-button value="REPLACE">替换当天时间</el-radio-button><el-radio-button value="BLOCK">从常规时间扣除</el-radio-button></el-radio-group></el-form-item><div class="window-editor"><div v-for="(window,index) in overrideWindows" :key="index" class="time-window-row"><el-time-picker v-model="window.start_time" value-format="HH:mm" format="HH:mm" :clearable="false"/><span>至</span><el-time-picker v-model="window.end_time" value-format="HH:mm" format="HH:mm" :clearable="false"/><el-button link type="danger" @click="removeOverrideWindow(index)">删除</el-button></div><el-button link type="primary" @click="addOverrideWindow">添加时段</el-button><p class="muted">{{overrideMode==='REPLACE'?'不添加时段表示当天全天不可用。':'扣除模式至少需要一个不可用时段。'}}</p></div></el-form>
   <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
   <div class="dialog-actions"><el-button v-if="hasOverrideForTarget" type="danger" plain :loading="busy" @click="deleteOverride">删除例外</el-button><el-button @click="overrideDialog=false">取消</el-button><el-button type="primary" :loading="busy" @click="saveOverride">保存例外</el-button></div>
  </template>
 </el-dialog>
 <el-dialog v-model="managerAvailabilityVisible" title="员工实际可用时间" width="min(760px, 94vw)">
  <el-table v-if="managerAvailability" :data="managerAvailability.days" empty-text="暂无可用时间"><el-table-column label="日期" min-width="150"><template #default="s">{{weekDateLabel(s.row.date)}}</template></el-table-column><el-table-column label="实际可用时间" min-width="300"><template #default="s"><div class="tag-list compact"><el-tag v-for="window in s.row.windows" :key="window.start_time+window.end_time" size="small" effect="light">{{window.start_time}}—{{window.end_time}}</el-tag><span v-if="!s.row.windows.length" class="muted">不可用</span></div></template></el-table-column><el-table-column label="来源" min-width="100"><template #default="s">{{s.row.source==='OVERRIDE'?'日期例外':s.row.source==='REGULAR'?'常规时间':'未配置'}}</template></el-table-column></el-table>
 </el-dialog>
 <el-dialog v-model="ruleDialog" title="创建排班规则版本" width="min(640px, 94vw)">
  <el-form label-position="top" @submit.prevent="saveRuleVersion">
   <el-form-item label="生效周（必须为周一）"><el-date-picker v-model="ruleForm.effective_week" type="date" value-format="YYYY-MM-DD" :clearable="false"/></el-form-item>
   <div class="form-grid"><el-form-item label="每人每天最多班次"><el-input-number v-model="ruleForm.daily_shift_limit" :min="1" :max="10"/></el-form-item><el-form-item label="每周工时上限（小时）"><el-input-number v-model="ruleWeeklyHours" :min="0.1" :max="168" :step="0.1" :precision="1"/></el-form-item></div>
   <div class="form-grid"><el-form-item label="连续工作天数上限"><el-input-number v-model="ruleForm.consecutive_days_limit" :min="1" :max="14"/></el-form-item><el-form-item label="班间最短休息（分钟）"><el-input-number v-model="ruleForm.min_rest_minutes" :min="0" :max="1440" :step="30"/></el-form-item></div>
   <div class="section-heading rule-weight-heading"><h2>软约束权重</h2><span class="muted">0—100，数值越高越优先</span></div>
   <div class="form-grid three"><el-form-item label="偏好满足"><el-input-number v-model="ruleForm.preference" :min="0" :max="100"/></el-form-item><el-form-item label="工时均衡"><el-input-number v-model="ruleForm.hours_balance" :min="0" :max="100"/></el-form-item><el-form-item label="晚班均衡"><el-input-number v-model="ruleForm.evening_balance" :min="0" :max="100"/></el-form-item></div>
   <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
   <div class="dialog-actions"><el-button @click="ruleDialog=false">取消</el-button><el-button type="primary" native-type="submit" :loading="busy">创建新版本</el-button></div>
  </el-form>
 </el-dialog>
 <el-dialog :model-value="!!reviewTarget" title="审核员工注册" width="min(520px, 94vw)" @close="reviewTarget=null"><template v-if="reviewTarget"><p>{{reviewTarget.name}} · {{reviewTarget.username}}</p><el-radio-group v-model="reviewMode"><el-radio-button value="new">新建员工档案</el-radio-button><el-radio-button value="existing">绑定已有档案</el-radio-button></el-radio-group><el-form label-position="top" class="review-form"><template v-if="reviewMode==='new'"><el-form-item label="员工编号"><el-input v-model="employee.employee_no"/></el-form-item><el-form-item label="姓名"><el-input v-model="employee.name"/></el-form-item></template><el-form-item v-else label="选择未绑定的员工"><el-select v-model="existingId"><el-option v-for="e in bindingOptions" :key="e.id" :label="e.employee_no+' · '+e.name" :value="e.id"/></el-select></el-form-item><el-form-item label="审核说明"><el-input v-model="note" type="textarea" maxlength="255"/></el-form-item></el-form><el-alert v-if="error" :title="error" type="error" :closable="false"/><div class="dialog-actions"><el-button :loading="busy" @click="review('REJECT')">不予通过</el-button><el-button type="primary" :loading="busy" @click="review('APPROVE')">通过并绑定</el-button></div></template></el-dialog>
 <el-dialog :model-value="!!resetTarget" title="核实并重置密码" width="min(500px, 94vw)" @close="resetTarget=null">
  <template v-if="resetTarget">
   <div class="reset-target"><span class="reset-avatar">{{resetTarget.name.slice(0,1)}}</span><div><strong>{{resetTarget.name}}</strong><small>{{resetTarget.username}} · {{formatTime(resetTarget.requested_at)}}</small></div></div>
   <el-alert title="请先通过线下方式确认对方身份。生成后，该账号的全部旧会话会立即失效。" type="warning" :closable="false" show-icon/>
   <el-form label-position="top" class="review-form"><el-form-item label="身份核实说明"><el-input v-model="resetNote" type="textarea" :rows="3" maxlength="255" show-word-limit placeholder="例如：已在门店当面核对员工编号与姓名"/></el-form-item></el-form>
   <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
   <div class="dialog-actions"><el-button @click="resetTarget=null">取消</el-button><el-button type="primary" :loading="busy" @click="submitReset">生成临时密码</el-button></div>
  </template>
 </el-dialog>
 <el-dialog v-model="resetResultVisible" title="临时密码已生成" width="min(520px, 94vw)" :close-on-click-modal="false" @closed="resetResult=null">
  <template v-if="resetResult">
   <p class="reset-success">请立即通过已核实的线下渠道交给 <strong>{{resetResult.username}}</strong>。此密码只显示一次，系统不会再次提供。</p>
   <div class="temporary-password"><code>{{resetResult.temporary_password}}</code><el-button :icon="DocumentCopy" @click="copyPassword">{{copied?'已复制':'复制'}}</el-button></div>
   <p class="muted">首次登录必须修改密码；临时密码有效至 {{formatTime(resetResult.expires_at)}}。</p>
   <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
  </template>
 </el-dialog>
</div>
</template>
