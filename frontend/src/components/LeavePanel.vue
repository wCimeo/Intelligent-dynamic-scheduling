<script setup lang="ts">
import { computed, reactive, ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api, session } from '../api'

const isManager = computed(() => session.user?.role === 'MANAGER')
const busy = ref(false)
const error = ref('')
const rows = ref<any[]>([])
const filterStatus = ref('')
const search = ref('')
const dateFrom = ref('')
const dateTo = ref('')
const form = reactive({ start_date: '', start_time: '08:00', end_date: '', end_time: '14:00', reason: '' })
const previewShifts = ref<any[]>([])
const selected = ref<any>(null)
const reviewNote = ref('')
const detailVisible = ref(false)

const statuses: Record<string, string> = { PENDING: '待审批', APPROVED: '已批准', REJECTED: '已拒绝', WITHDRAWN: '已撤回' }
const statusType: Record<string, string> = { PENDING: 'warning', APPROVED: 'success', REJECTED: 'danger', WITHDRAWN: 'info' }
const shiftStatuses: Record<string, string> = { PREVIEW: '影响预览', OPEN: '待补岗', RESOLVED: '已解决', SUPERSEDED: '已失效' }

async function load() {
  error.value = ''
  busy.value = true
  try {
    const params = new URLSearchParams()
    if (filterStatus.value) params.set('status', filterStatus.value)
    if (isManager.value) {
      if (search.value) params.set('search', search.value)
      if (dateFrom.value) params.set('date_from', dateFrom.value)
      if (dateTo.value) params.set('date_to', dateTo.value)
      const data = await api(`/leave-requests?${params}`)
      rows.value = data.items
    } else {
      const data = await api(`/me/leave-requests?${params}`)
      rows.value = data.items
    }
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function preview() {
  error.value = ''
  if (!form.start_date || !form.end_date) { error.value = '请选择完整的请假日期'; return }
  busy.value = true
  try {
    const data = await api('/me/leave-requests/preview', 'POST', {
      start_date: form.start_date, start_time: form.start_time,
      end_date: form.end_date, end_time: form.end_time
    })
    previewShifts.value = data.affected_shifts
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function submit() {
  error.value = ''
  if (!form.reason.trim()) { error.value = '请填写请假原因'; return }
  busy.value = true
  try {
    const data = await api('/me/leave-requests', 'POST', { ...form, reason: form.reason.trim() }, crypto.randomUUID())
    previewShifts.value = data.affected_shifts
    form.reason = ''
    ElMessage.success('请假申请已提交')
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
    await api(`/me/leave-requests/${row.id}/withdraw`, 'POST', { expected_revision: row.revision })
    ElMessage.success('申请已撤回')
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
  detailVisible.value = true
}

async function review(decision: 'APPROVE' | 'REJECT') {
  error.value = ''
  if (decision === 'REJECT' && !reviewNote.value.trim()) { error.value = '拒绝时请填写审批说明'; return }
  busy.value = true
  try {
    await api(`/leave-requests/${selected.value.id}/review`, 'POST', {
      decision, expected_revision: selected.value.revision, note: reviewNote.value.trim()
    }, crypto.randomUUID())
    detailVisible.value = false
    ElMessage.success(decision === 'APPROVE' ? '请假已批准' : '请假已拒绝')
    await load()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-heading">
    <div><span class="eyebrow">申请与协作 · F09</span><h1>{{ isManager ? '请假审批' : '请假申请' }}</h1><p class="muted">{{ isManager ? '核实请假时间与受影响班次；批准后形成真实缺岗事件，等待调班处理。' : '提交后仅进入待审批状态；批准前不会改变班表，也不能覆盖已批准的重叠请假。' }}</p></div>
    <el-tag type="success" effect="plain">{{ isManager ? '管理员审批' : '员工自助' }}</el-tag>
  </div>

  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="leave-error"/>

  <template v-if="!isManager">
    <div class="leave-grid">
      <section class="panel">
        <div class="section-heading"><h2>提交请假申请</h2><el-tag effect="plain">待审批</el-tag></div>
        <el-form label-position="top">
          <div class="leave-time-grid">
            <el-form-item label="开始日期"><el-date-picker v-model="form.start_date" type="date" value-format="YYYY-MM-DD" :clearable="false"/></el-form-item>
            <el-form-item label="开始时间"><el-time-picker v-model="form.start_time" value-format="HH:mm" format="HH:mm" :clearable="false"/></el-form-item>
            <el-form-item label="结束日期"><el-date-picker v-model="form.end_date" type="date" value-format="YYYY-MM-DD" :clearable="false"/></el-form-item>
            <el-form-item label="结束时间"><el-time-picker v-model="form.end_time" value-format="HH:mm" format="HH:mm" :clearable="false"/></el-form-item>
          </div>
          <el-form-item label="请假原因"><el-input v-model="form.reason" type="textarea" :rows="3" maxlength="500" show-word-limit placeholder="请说明需要请假的原因"/></el-form-item>
          <div class="dialog-actions">
            <el-button :loading="busy" @click="preview">检查影响班次</el-button>
            <el-button type="primary" :loading="busy" @click="submit">提交申请</el-button>
          </div>
        </el-form>
      </section>
      <section class="panel">
        <div class="section-heading"><h2>受影响的已发布班次</h2><el-tag type="warning" effect="light">{{ previewShifts.length }} 个</el-tag></div>
        <div v-if="previewShifts.length" class="leave-shifts">
          <div v-for="shift in previewShifts" :key="shift.version_shift_id + shift.position_id" class="leave-shift">
            <strong>{{ shift.work_date }} · {{ shift.shift_name }}</strong>
            <span>{{ shift.start_time }}—{{ shift.end_time }} · {{ shift.position_name }}</span>
          </div>
        </div>
        <p v-else class="muted">选择时间后可先检查影响班次。请假批准前，这些班次不会发生变化。</p>
      </section>
    </div>
    <section class="panel leave-list">
      <div class="section-heading"><h2>我的请假记录</h2><el-select v-model="filterStatus" clearable placeholder="全部状态" @change="load"><el-option v-for="(label,key) in statuses" :key="key" :label="label" :value="key"/></el-select></div>
      <el-table :data="rows" v-loading="busy" empty-text="暂无请假记录">
        <el-table-column label="请假时间" min-width="230"><template #default="s">{{ s.row.start_date }} {{ s.row.start_time }}<br>至 {{ s.row.end_date }} {{ s.row.end_time }}</template></el-table-column>
        <el-table-column prop="reason" label="原因" min-width="220" show-overflow-tooltip/>
        <el-table-column label="状态" min-width="100"><template #default="s"><el-tag :type="statusType[s.row.status]" effect="light">{{ statuses[s.row.status] }}</el-tag></template></el-table-column>
        <el-table-column label="影响" min-width="100"><template #default="s">{{ s.row.affected_shifts?.length || 0 }} 个班次</template></el-table-column>
        <el-table-column label="操作" min-width="150"><template #default="s"><el-button link type="primary" @click="openDetail(s.row)">查看</el-button><el-button v-if="s.row.status==='PENDING'" link type="danger" @click="withdraw(s.row)">撤回</el-button></template></el-table-column>
      </el-table>
    </section>
  </template>

  <template v-else>
    <section class="panel leave-filter">
      <el-select v-model="filterStatus" clearable placeholder="全部状态" @change="load"><el-option v-for="(label,key) in statuses" :key="key" :label="label" :value="key"/></el-select>
      <el-input v-model="search" clearable placeholder="员工姓名或编号" @keyup.enter="load"/>
      <el-date-picker v-model="dateFrom" type="date" value-format="YYYY-MM-DD" placeholder="起始日期"/>
      <el-date-picker v-model="dateTo" type="date" value-format="YYYY-MM-DD" placeholder="结束日期"/>
      <el-button @click="load">筛选</el-button>
    </section>
    <section class="panel table-panel">
      <el-table :data="rows" v-loading="busy" empty-text="暂无请假申请">
        <el-table-column prop="employee_no" label="员工编号" min-width="110"/>
        <el-table-column prop="employee_name" label="姓名" min-width="100"/>
        <el-table-column label="请假时间" min-width="220"><template #default="s">{{ s.row.start_date }} {{ s.row.start_time }}<br>至 {{ s.row.end_date }} {{ s.row.end_time }}</template></el-table-column>
        <el-table-column prop="reason" label="原因" min-width="220" show-overflow-tooltip/>
        <el-table-column label="状态" min-width="100"><template #default="s"><el-tag :type="statusType[s.row.status]" effect="light">{{ statuses[s.row.status] }}</el-tag></template></el-table-column>
        <el-table-column label="缺岗" min-width="90"><template #default="s"><el-tag v-if="s.row.open_gap_count" type="warning">{{ s.row.open_gap_count }}</el-tag><span v-else class="muted">—</span></template></el-table-column>
        <el-table-column label="操作" min-width="120"><template #default="s"><el-button link type="primary" @click="openDetail(s.row)">{{ s.row.status === 'PENDING' ? '审批' : '查看' }}</el-button></template></el-table-column>
      </el-table>
    </section>
  </template>

  <el-dialog v-model="detailVisible" title="请假申请详情" width="min(650px, 94vw)">
    <template v-if="selected">
      <div class="leave-detail-head"><div><strong>{{ selected.employee_name }}</strong><span>{{ selected.employee_no }}</span></div><el-tag :type="statusType[selected.status]">{{ statuses[selected.status] }}</el-tag></div>
      <dl class="leave-detail-grid"><dt>请假时间</dt><dd>{{ selected.start_date }} {{ selected.start_time }} — {{ selected.end_date }} {{ selected.end_time }}</dd><dt>请假原因</dt><dd>{{ selected.reason }}</dd><dt v-if="selected.review_note">审批说明</dt><dd v-if="selected.review_note">{{ selected.review_note }}</dd></dl>
      <h3>受影响班次</h3>
      <div v-if="selected.affected_shifts?.length" class="leave-shifts"><div v-for="shift in selected.affected_shifts" :key="shift.version_shift_id+shift.position_id" class="leave-shift"><strong>{{ shift.work_date }} · {{ shift.shift_name }}</strong><span>{{ shift.start_time }}—{{ shift.end_time }} · {{ shift.position_name }} · {{ shiftStatuses[shift.status] || shift.status }}</span></div></div>
      <p v-else class="muted">该时间范围内没有当前发布班次安排。</p>
      <template v-if="isManager && selected.status==='PENDING'">
        <el-form-item label="审批说明"><el-input v-model="reviewNote" type="textarea" :rows="3" maxlength="500" show-word-limit placeholder="批准可选填；拒绝时必须填写"/></el-form-item>
        <div class="dialog-actions"><el-button :loading="busy" @click="review('REJECT')">拒绝</el-button><el-button type="primary" :loading="busy" @click="review('APPROVE')">批准</el-button></div>
      </template>
    </template>
  </el-dialog>
</template>

<style scoped>
.leave-grid{display:grid;grid-template-columns:1.1fr .9fr;gap:22px}.leave-time-grid{display:grid;grid-template-columns:1.2fr .8fr;gap:0 14px}.leave-error{margin-bottom:18px}.leave-shifts{display:grid;gap:8px}.leave-shift{display:flex;justify-content:space-between;gap:16px;background:#f8fafc;border:1px solid #edf1f6;border-radius:8px;padding:11px 13px;font-size:13px}.leave-shift span{color:#64748b}.leave-list{margin-top:22px}.leave-filter{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}.leave-filter .el-select,.leave-filter .el-input{width:180px}.leave-detail-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}.leave-detail-head strong{display:block;font-size:18px}.leave-detail-head span{display:block;color:#8491a5;font-size:12px;margin-top:4px}.leave-detail-grid{display:grid;grid-template-columns:90px 1fr;gap:10px 16px;background:#f8fafc;border-radius:10px;padding:15px}.leave-detail-grid dt{color:#8491a5}.leave-detail-grid dd{margin:0;color:#334155}@media(max-width:900px){.leave-grid{grid-template-columns:1fr}.leave-shift{align-items:flex-start;flex-direction:column;gap:5px}.leave-filter>*{width:100%!important}}
</style>
