<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, session } from '../api'

const isManager = computed(() => session.user?.role === 'MANAGER')
const busy = ref(false)
const error = ref('')
const rows = ref<any[]>([])
const schedule = ref<any[]>([])
const candidates = ref<any[]>([])
const myEmployeeId = ref('')
const filterStatus = ref('')
const search = ref('')
const selected = ref<any>(null)
const detailVisible = ref(false)
const reviewNote = ref('')
const responseNote = ref('')
const form = reactive({ mode: 'TRANSFER', source: '', target_employee_id: '', target_key: '', note: '' })

const statuses: Record<string, string> = {
  PENDING_TARGET: '待接收人确认', PENDING_MANAGER: '待管理员审批', APPROVED: '已批准',
  REJECTED: '已拒绝', WITHDRAWN: '已撤回', TARGET_REJECTED: '接收人已拒绝', INVALID: '已失效'
}
const statusType: Record<string, string> = {
  PENDING_TARGET: 'warning', PENDING_MANAGER: 'warning', APPROVED: 'success',
  REJECTED: 'danger', WITHDRAWN: 'info', TARGET_REJECTED: 'danger', INVALID: 'info'
}

function localDate(value: Date) {
  const year = value.getFullYear(), month = String(value.getMonth() + 1).padStart(2, '0'), day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

async function load() {
  error.value = ''
  busy.value = true
  try {
    if (isManager.value) {
      const params = new URLSearchParams()
      if (filterStatus.value) params.set('status', filterStatus.value)
      if (search.value) params.set('search', search.value)
      rows.value = (await api(`/swap-requests?${params}`)).items
    } else {
      const statusQuery = filterStatus.value ? `?status=${filterStatus.value}` : ''
      const now = new Date()
      const start = new Date(now.getFullYear(), now.getMonth(), now.getDate())
      const end = new Date(start); end.setDate(end.getDate() + 27)
      const [swaps, scheduleData, profile] = await Promise.all([
        api(`/me/swap-requests${statusQuery}`),
        api(`/me/schedules?from=${localDate(start)}&to=${localDate(end)}`),
        api('/me/profile')
      ])
      rows.value = swaps.items
      schedule.value = scheduleData.items
      myEmployeeId.value = profile.id
    }
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

function selectedSource() {
  return schedule.value.find(item => item.shift_key === form.source)
}

async function loadCandidates() {
  candidates.value = []
  form.target_employee_id = ''
  form.target_key = ''
  const source = selectedSource()
  if (!source) return
  busy.value = true
  try {
    candidates.value = (await api(`/me/swap-candidates?source_shift_key=${source.shift_key}&source_position_id=${source.position_id}`)).items
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

function selectedCandidate() {
  return candidates.value.find(item => item.employee_id === form.target_employee_id)
}

function candidateReasonText(candidate: any) {
  return (candidate.reasons || []).map((reason: any) => reason.message).join('、')
}

async function submit() {
  error.value = ''
  const source = selectedSource()
  if (!source || !form.target_employee_id) { error.value = '请选择自己的班次和接收人'; return }
  const payload: any = { mode: form.mode, target_employee_id: Number(form.target_employee_id),
    source_shift_key: source.shift_key, source_position_id: Number(source.position_id), note: form.note.trim() }
  if (form.mode === 'EXCHANGE') {
    if (!form.target_key) { error.value = '双向换班需要选择对方班次'; return }
    const exchange = selectedCandidate()?.exchange_assignments?.find((item: any) => item.shift_key === form.target_key)
    payload.target_shift_key = form.target_key
    payload.target_position_id = Number(exchange.position_id)
  }
  busy.value = true
  try {
    await api('/me/swap-requests', 'POST', payload, crypto.randomUUID())
    ElMessage.success('换班申请已发送')
    Object.assign(form, { source: '', target_employee_id: '', target_key: '', note: '' })
    candidates.value = []
    await load()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function respond(row: any, decision: 'ACCEPT' | 'REJECT') {
  busy.value = true
  try {
    await api(`/me/swap-requests/${row.id}/respond`, 'POST', { decision, expected_revision: row.revision, note: responseNote.value.trim() })
    ElMessage.success(decision === 'ACCEPT' ? '已接受换班邀请' : '已拒绝换班邀请')
    detailVisible.value = false
    responseNote.value = ''
    await load()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function withdraw(row: any) {
  busy.value = true
  try {
    await api(`/me/swap-requests/${row.id}/withdraw`, 'POST', { expected_revision: row.revision })
    ElMessage.success('换班申请已撤回')
    await load()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

function openDetail(row: any) {
  selected.value = row
  reviewNote.value = ''
  responseNote.value = ''
  detailVisible.value = true
}

async function review(decision: 'APPROVE' | 'REJECT') {
  error.value = ''
  if (decision === 'REJECT' && !reviewNote.value.trim()) { error.value = '拒绝时请填写审批说明'; return }
  busy.value = true
  try {
    await api(`/swap-requests/${selected.value.id}/review`, 'POST', { decision, expected_revision: selected.value.revision, note: reviewNote.value.trim() }, crypto.randomUUID())
    detailVisible.value = false
    ElMessage.success(decision === 'APPROVE' ? '换班已批准并发布新版本' : '换班已拒绝')
    await load()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

function isMyInvitation(row: any) {
  return row.target_employee_id === myEmployeeId.value && row.status === 'PENDING_TARGET'
}

onMounted(load)
</script>

<template>
  <div class="page-heading">
    <div><span class="eyebrow">申请与协作 · F10</span><h1>{{ isManager ? '换班审批' : '换班申请' }}</h1><p class="muted">{{ isManager ? '接收方确认后，重新校验资格、时间、工时和版本；批准时原子发布新版本。' : '发起单方转交或双向交换；接收人确认后进入管理员审批。' }}</p></div>
    <el-tag type="success" effect="plain">{{ isManager ? '管理员审批' : '员工协作' }}</el-tag>
  </div>
  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="swap-error"/>

  <template v-if="!isManager">
    <div class="swap-create-grid">
      <section class="panel">
        <div class="section-heading"><h2>发起换班</h2><el-tag effect="plain">当前发布班表</el-tag></div>
        <el-form label-position="top">
          <el-form-item label="换班方式"><el-radio-group v-model="form.mode"><el-radio-button value="TRANSFER">转交给他人</el-radio-button><el-radio-button value="EXCHANGE">双向交换</el-radio-button></el-radio-group></el-form-item>
          <el-form-item label="我的班次"><el-select v-model="form.source" filterable placeholder="选择本人当前班次" @change="loadCandidates"><el-option v-for="shift in schedule" :key="shift.shift_key" :label="`${shift.work_date} · ${shift.shift_name} · ${shift.position_name}`" :value="shift.shift_key"/></el-select></el-form-item>
          <el-form-item label="接收人"><el-select v-model="form.target_employee_id" filterable placeholder="选择接收员工"><el-option v-for="candidate in candidates" :key="candidate.employee_id" :label="candidate.name" :value="candidate.employee_id" :disabled="!candidate.eligible"/></el-select></el-form-item>
          <el-form-item v-if="form.mode==='EXCHANGE'" label="对方用于交换的班次"><el-select v-model="form.target_key" placeholder="选择对方班次"><el-option v-for="shift in selectedCandidate()?.exchange_assignments || []" :key="shift.shift_key" :label="`${shift.work_date} · ${shift.shift_name} · ${shift.position_name}`" :value="shift.shift_key"/></el-select></el-form-item>
          <el-form-item label="说明"><el-input v-model="form.note" type="textarea" :rows="2" maxlength="500" placeholder="例如：当天有课程冲突"/></el-form-item>
          <el-button type="primary" :loading="busy" @click="submit">发送换班申请</el-button>
        </el-form>
      </section>
      <section class="panel">
        <div class="section-heading"><h2>候选接收人</h2><el-tag type="warning" effect="light">{{ candidates.filter(c=>c.eligible).length }} 人可选</el-tag></div>
        <div v-if="candidates.length" class="candidate-list">
          <div v-for="candidate in candidates" :key="candidate.employee_id" :class="['candidate-card', { disabled: !candidate.eligible }]"><div><strong>{{ candidate.name }}</strong><span>{{ candidate.employee_no }}</span></div><el-tag :type="candidate.eligible?'success':'info'" effect="light">{{ candidate.eligible ? '可接收' : '存在限制' }}</el-tag><p v-if="candidate.reasons?.length">{{ candidateReasonText(candidate) }}</p></div>
        </div>
        <p v-else class="muted">选择本人班次后加载候选员工。</p>
      </section>
    </div>
  </template>

  <section class="panel swap-filter">
    <el-select v-model="filterStatus" clearable placeholder="全部状态" @change="load"><el-option v-for="(label,key) in statuses" :key="key" :label="label" :value="key"/></el-select>
    <el-input v-if="isManager" v-model="search" clearable placeholder="员工姓名或编号" @keyup.enter="load"/>
    <el-button @click="load">刷新</el-button>
  </section>

  <section class="panel table-panel">
    <el-table :data="rows" v-loading="busy" empty-text="暂无换班申请">
      <el-table-column v-if="isManager" prop="initiator_name" label="发起人" min-width="100"/>
      <el-table-column prop="target_name" label="接收人" min-width="100"/>
      <el-table-column label="方式" min-width="90"><template #default="s">{{ s.row.mode === 'TRANSFER' ? '转交' : '交换' }}</template></el-table-column>
      <el-table-column label="原班次" min-width="180"><template #default="s">{{ s.row.source?.work_date }}<br>{{ s.row.source?.shift_name }} · {{ s.row.source?.position_name }}</template></el-table-column>
      <el-table-column label="状态" min-width="120"><template #default="s"><el-tag :type="statusType[s.row.status]" effect="light">{{ statuses[s.row.status] }}</el-tag></template></el-table-column>
      <el-table-column label="操作" min-width="150"><template #default="s"><el-button link type="primary" @click="openDetail(s.row)">{{ isManager && s.row.status==='PENDING_MANAGER' ? '审批' : '查看' }}</el-button><el-button v-if="!isManager && s.row.initiator_employee_id===myEmployeeId && ['PENDING_TARGET','PENDING_MANAGER'].includes(s.row.status)" link type="danger" @click="withdraw(s.row)">撤回</el-button></template></el-table-column>
    </el-table>
  </section>

  <el-dialog v-model="detailVisible" title="换班申请详情" width="min(650px, 94vw)">
    <template v-if="selected">
      <div class="swap-party-grid"><div><span>发起人</span><strong>{{ selected.initiator_name }}</strong></div><div class="swap-arrow">⇄</div><div><span>接收人</span><strong>{{ selected.target_name }}</strong></div></div>
      <div class="leave-shifts"><div class="leave-shift"><strong>{{ selected.source?.work_date }} · {{ selected.source?.shift_name }}</strong><span>{{ selected.source?.start_time }}—{{ selected.source?.end_time }} · {{ selected.source?.position_name }}</span></div><div v-if="selected.target" class="leave-shift"><strong>{{ selected.target.work_date }} · {{ selected.target.shift_name }}</strong><span>{{ selected.target.start_time }}—{{ selected.target.end_time }} · {{ selected.target.position_name }}</span></div></div>
      <p v-if="selected.initiator_note" class="muted">发起说明：{{ selected.initiator_note }}</p><p v-if="selected.target_note" class="muted">接收说明：{{ selected.target_note }}</p><p v-if="selected.review_note" class="muted">审批说明：{{ selected.review_note }}</p>
      <template v-if="!isManager && isMyInvitation(selected)">
        <el-form-item label="回复说明"><el-input v-model="responseNote" type="textarea" :rows="2" maxlength="500"/></el-form-item>
        <div class="dialog-actions"><el-button :loading="busy" @click="respond(selected,'REJECT')">拒绝</el-button><el-button type="primary" :loading="busy" @click="respond(selected,'ACCEPT')">接受</el-button></div>
      </template>
      <template v-if="isManager && selected.status==='PENDING_MANAGER'">
        <el-form-item label="审批说明"><el-input v-model="reviewNote" type="textarea" :rows="3" maxlength="500" placeholder="拒绝时必须填写"/></el-form-item>
        <div class="dialog-actions"><el-button :loading="busy" @click="review('REJECT')">拒绝</el-button><el-button type="primary" :loading="busy" @click="review('APPROVE')">批准并发布</el-button></div>
      </template>
    </template>
  </el-dialog>
</template>

<style scoped>
.swap-error{margin-bottom:18px}.swap-create-grid{display:grid;grid-template-columns:1.1fr .9fr;gap:22px;margin-bottom:22px}.candidate-list{display:grid;gap:9px}.candidate-card{display:grid;grid-template-columns:1fr auto;gap:5px 12px;background:#f8fafc;border:1px solid #edf1f6;border-radius:9px;padding:12px}.candidate-card strong{display:block}.candidate-card span{display:block;color:#8491a5;font-size:11px;margin-top:3px}.candidate-card p{grid-column:1/-1;margin:3px 0 0;color:#b45309;font-size:12px}.candidate-card.disabled{background:#fafafa}.swap-filter{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}.swap-filter .el-select,.swap-filter .el-input{width:190px}.swap-party-grid{display:grid;grid-template-columns:1fr auto 1fr;gap:18px;align-items:center;background:#f8fafc;border-radius:10px;padding:16px;margin-bottom:16px}.swap-party-grid span{display:block;color:#8491a5;font-size:11px}.swap-party-grid strong{font-size:16px}.swap-arrow{font-size:26px;color:#2563eb}.leave-shifts{display:grid;gap:8px}.leave-shift{display:flex;justify-content:space-between;background:#f8fafc;border:1px solid #edf1f6;border-radius:8px;padding:11px}.leave-shift span{color:#64748b}.user-select{color:#2563eb}@media(max-width:900px){.swap-create-grid{grid-template-columns:1fr}.swap-party-grid{grid-template-columns:1fr;text-align:center}.swap-filter>*{width:100%!important}.leave-shift{flex-direction:column;gap:5px}}
</style>
