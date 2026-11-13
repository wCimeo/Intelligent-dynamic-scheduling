<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

const busy = ref(false)
const error = ref('')
const events = ref<any[]>([])
const selectedEvent = ref<any>(null)
const baseVersion = ref<any>(null)
const assignments = ref<any[]>([])
const candidates = ref<any[]>([])
const generationIssues = ref<any[]>([])
const selectedCandidate = ref<any>(null)

async function loadEvents() {
  error.value = ''
  busy.value = true
  try {
    events.value = (await api('/adjustment-events?status=OPEN')).items
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function chooseEvent(item: any) {
  selectedEvent.value = item
  selectedCandidate.value = null
  candidates.value = []
  generationIssues.value = []
  busy.value = true
  try {
    const [version, existing] = await Promise.all([
      api(`/versions/${item.version_id}`),
      api(`/adjustment-events/${item.id}/candidates?status=PROPOSED`)
    ])
    baseVersion.value = version
    const affected = new Set(version.assignments
      .filter((assignment: any) => assignment.employee_id === item.employee_id && assignment.shift_key === item.shift_key && assignment.position_id === item.position_id)
      .map((assignment: any) => `${assignment.shift_key}:${assignment.employee_id}:${assignment.position_id}`))
    assignments.value = version.assignments.map((assignment: any) => ({
      ...assignment,
      lockable: !affected.has(`${assignment.shift_key}:${assignment.employee_id}:${assignment.position_id}`),
      selectedLock: !!assignment.locked
    }))
    candidates.value = existing.items
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function generate() {
  if (!selectedEvent.value) return
  error.value = ''
  busy.value = true
  try {
    const locked = assignments.value.filter(item => item.selectedLock).map(item => ({
      shift_key: item.shift_key, employee_id: Number(item.employee_id),
      position_id: Number(item.position_id), locked: true
    }))
    const data = await api('/adjustment-candidates/generate', 'POST', {
      event_ids: [Number(selectedEvent.value.id)], locked_assignments: locked, time_limit_seconds: 20
    })
    candidates.value = data.candidates
    generationIssues.value = data.issues
    if (!data.candidates.length) error.value = '没有找到满足硬约束的调班方案'
    else ElMessage.success(`已生成 ${data.candidates.length} 个候选方案`)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function applyCandidate(candidate: any) {
  try {
    await ElMessageBox.confirm('应用后将生成并发布新的班表版本，同时关闭当前缺岗事件。', '应用调班方案', {
      confirmButtonText: '应用并发布', cancelButtonText: '取消', type: 'warning'
    })
  } catch { return }
  busy.value = true
  error.value = ''
  try {
    await api(`/adjustment-candidates/${candidate.id}/apply`, 'POST', {
      expected_base_version_id: Number(candidate.base_version_id),
      expected_input_revision: candidate.input_revision
    }, crypto.randomUUID())
    ElMessage.success('调班方案已应用并发布新版本')
    selectedEvent.value = null
    selectedCandidate.value = null
    await loadEvents()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function discard(candidate: any) {
  busy.value = true
  try {
    await api(`/adjustment-candidates/${candidate.id}/discard`, 'POST', { expected_revision: candidate.revision })
    candidates.value = candidates.value.filter(item => item.id !== candidate.id)
    if (selectedCandidate.value?.id === candidate.id) selectedCandidate.value = null
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

function employeeName(edge: any) {
  return assignments.value.find(item => item.shift_key === edge.shift_key && item.employee_id === edge.employee_id)?.employee_name || edge.employee_id
}

function shiftLabel(edge: any, version: any = baseVersion.value) {
  const shift = version?.shifts?.find((item: any) => item.shift_key === edge.shift_key)
  return shift ? `${shift.work_date} ${shift.name}` : edge.shift_key
}

onMounted(loadEvents)
</script>

<template>
  <div class="page-heading">
    <div><span class="eyebrow">申请与协作 · F11</span><h1>动态调班</h1><p class="muted">从真实缺岗事件生成最多3个方案，优先减少已发布安排的改动，再比较偏好、工时和晚班均衡。</p></div>
    <el-tag type="warning" effect="light">{{ events.length }} 个待处理缺岗</el-tag>
  </div>
  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="adjustment-error"/>

  <div class="adjustment-layout">
    <section class="panel event-list">
      <div class="section-heading"><h2>待处理缺岗</h2><el-button link @click="loadEvents">刷新</el-button></div>
      <button v-for="item in events" :key="item.id" :class="['event-card',{active:selectedEvent?.id===item.id}]" @click="chooseEvent(item)">
        <div><strong>{{ item.work_date }} · {{ item.shift_name }}</strong><span>{{ item.position_name }} · 原安排 {{ item.employee_name }}</span></div>
        <el-tag type="danger" effect="light">缺岗</el-tag>
      </button>
      <p v-if="!events.length" class="muted">当前没有待处理缺岗。</p>
    </section>

    <section v-if="selectedEvent" class="panel adjustment-workbench">
      <div class="section-heading"><h2>调班工作台</h2><el-button type="primary" :loading="busy" @click="generate">生成候选方案</el-button></div>
      <div class="gap-banner"><div><span>缺岗班次</span><strong>{{ selectedEvent.work_date }} · {{ selectedEvent.shift_name }}</strong></div><div><span>缺口岗位</span><strong>{{ selectedEvent.position_name }}</strong></div><div><span>原安排</span><strong>{{ selectedEvent.employee_name }}</strong></div></div>
      <el-collapse class="lock-panel"><el-collapse-item title="需要锁定的已有安排" name="locks"><p class="muted">锁定的员工和岗位在生成方案时不会被改动；缺岗原安排本身不可锁定。</p><div class="lock-grid"><label v-for="item in assignments.filter(i=>i.lockable)" :key="`${item.shift_key}:${item.employee_id}`" class="lock-item"><el-checkbox v-model="item.selectedLock"/><span><strong>{{ item.employee_name }}</strong><small>{{ shiftLabel(item) }} · {{ item.position_name }}</small></span></label></div></el-collapse-item></el-collapse>
      <el-alert v-for="(issue,index) in generationIssues" :key="index" :title="issue.message || issue.code" type="warning" :closable="false" show-icon/>
      <div v-if="candidates.length" class="candidate-grid">
        <article v-for="candidate in candidates" :key="candidate.id" :class="['candidate-plan',{selected:selectedCandidate?.id===candidate.id}]" @click="selectedCandidate=candidate">
          <div class="plan-heading"><el-tag :type="candidate.sequence===1?'success':'info'" effect="dark">方案 {{ candidate.sequence }}</el-tag><span>改动 {{ candidate.metrics.changed_count }} 人 / {{ candidate.metrics.changed_shift_count }} 班</span></div>
          <div class="plan-metrics"><div><span>偏好满足</span><strong>{{ candidate.metrics.preference_satisfied }}/{{ candidate.metrics.preference_total }}</strong></div><div><span>工时极差</span><strong>{{ ((candidate.metrics.max_minutes-candidate.metrics.min_minutes)/60).toFixed(1) }}h</strong></div></div>
          <div class="plan-actions"><el-button type="primary" :loading="busy" @click.stop="applyCandidate(candidate)">应用方案</el-button><el-button link @click.stop="discard(candidate)">弃用</el-button></div>
        </article>
      </div>
      <div v-if="selectedCandidate" class="change-panel"><h3>方案变化</h3><div class="change-columns"><div><h4>新增安排</h4><p v-for="item in selectedCandidate.change_summary.added" :key="item.shift_key+item.employee_id">{{ shiftLabel(item) }} · {{ employeeName(item) }}</p><span v-if="!selectedCandidate.change_summary.added.length" class="muted">无</span></div><div><h4>移除安排</h4><p v-for="item in selectedCandidate.change_summary.removed" :key="item.shift_key+item.employee_id">{{ shiftLabel(item) }} · {{ employeeName(item) }}</p><span v-if="!selectedCandidate.change_summary.removed.length" class="muted">无</span></div></div></div>
    </section>
    <section v-else class="panel empty-workbench"><span class="large-symbol">↺</span><h2>选择一个缺岗事件</h2><p class="muted">系统会基于当前发布版本生成最小改动方案。</p></section>
  </div>
</template>

<style scoped>
.adjustment-error{margin-bottom:18px}.adjustment-layout{display:grid;grid-template-columns:280px 1fr;gap:22px;align-items:start}.event-list{display:grid;gap:9px}.event-card{display:flex;justify-content:space-between;align-items:center;gap:10px;border:1px solid #edf1f6;background:white;border-radius:10px;padding:12px;text-align:left;cursor:pointer;color:inherit}.event-card:hover,.event-card.active{border-color:#9dbdff;background:#f4f8ff}.event-card strong{display:block;font-size:13px}.event-card span{display:block;color:#8491a5;font-size:11px;margin-top:5px}.gap-banner{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;background:#fff7ed;border:1px solid #fed7aa;border-radius:10px;padding:15px;margin-bottom:16px}.gap-banner span{display:block;color:#9a6a32;font-size:11px}.gap-banner strong{display:block;margin-top:4px}.lock-panel{margin-bottom:18px}.lock-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px;max-height:260px;overflow:auto}.lock-item{display:flex;align-items:flex-start;gap:8px;background:#f8fafc;border-radius:7px;padding:8px}.lock-item strong{display:block;font-size:12px}.lock-item small{display:block;color:#8491a5;font-size:10px;margin-top:3px}.candidate-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:13px;margin-top:18px}.candidate-plan{border:1px solid #e2e8f0;border-radius:11px;padding:15px;background:white;cursor:pointer}.candidate-plan.selected{border-color:#2563eb;box-shadow:0 0 0 3px #dbeafe}.plan-heading{display:flex;align-items:center;justify-content:space-between}.plan-heading>span{font-size:11px;color:#64748b}.plan-metrics{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:15px 0}.plan-metrics span{display:block;color:#8491a5;font-size:10px}.plan-metrics strong{display:block;margin-top:4px}.plan-actions{display:flex;justify-content:space-between;align-items:center}.change-panel{border-top:1px solid #edf1f6;margin-top:20px;padding-top:18px}.change-panel h3{font-size:15px}.change-columns{display:grid;grid-template-columns:1fr 1fr;gap:20px}.change-columns h4{font-size:12px;color:#64748b}.change-columns p{font-size:12px;background:#f8fafc;border-radius:6px;padding:8px;margin:6px 0}.empty-workbench{min-height:420px;text-align:center;padding-top:100px}
@media(max-width:1000px){.adjustment-layout{grid-template-columns:1fr}.event-list{grid-template-columns:repeat(2,1fr)}.candidate-grid{grid-template-columns:1fr}.lock-grid{grid-template-columns:1fr}}@media(max-width:700px){.event-list,.gap-banner,.change-columns{grid-template-columns:1fr}}
</style>
