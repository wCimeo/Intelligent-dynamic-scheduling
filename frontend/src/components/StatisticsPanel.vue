<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { session } from '../api'
import { api } from '../api'

const isManager = computed(() => session.user?.role === 'MANAGER')
const busy = ref(false)
const error = ref('')
const periods = ref<any[]>([])
const periodId = ref('')
const employeeId = ref('')
const positionId = ref('')
const stats = ref<any>(null)

function queryString() {
  const params = new URLSearchParams({ period_id: periodId.value })
  if (isManager.value && employeeId.value) params.set('employee_id', employeeId.value)
  if (isManager.value && positionId.value) params.set('position_id', positionId.value)
  return params.toString()
}

async function loadStats() {
  if (!periodId.value) return
  error.value = ''
  busy.value = true
  try {
    stats.value = await api(`${isManager.value ? '/statistics' : '/me/statistics'}?${queryString()}`)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

function applyFilters() {
  loadStats()
}

function downloadSchedule() {
  const base = isManager.value ? '/api/v1/exports/schedule.csv' : '/api/v1/me/exports/schedule.csv'
  window.open(`${base}?${queryString()}`, '_blank')
}

function downloadStatistics() {
  window.open(`/api/v1/exports/statistics.csv?${queryString()}`, '_blank')
}

onMounted(async () => {
  busy.value = true
  try {
    periods.value = (await api('/period-options')).items
    if (periods.value.length) periodId.value = periods.value[0].id
    await loadStats()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
})
</script>

<template>
  <div class="page-heading">
    <div><span class="eyebrow">智能与数据 · F15</span><h1>统计与导出</h1><p class="muted">{{ isManager ? '按当前发布版本统计计划工时、班次、缺岗、偏好和确认情况。' : '查看本人计划工时、班次和晚班分布。统计不表示实际出勤或薪资。' }}</p></div>
    <div class="stat-actions"><el-button @click="downloadSchedule">导出班表CSV</el-button><el-button v-if="isManager" type="primary" @click="downloadStatistics">导出统计CSV</el-button></div>
  </div>
  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="stats-error"/>
  <section class="panel stats-filter">
    <el-select v-model="periodId" placeholder="选择排班周" @change="applyFilters"><el-option v-for="period in periods" :key="period.id" :label="`${period.week_start} 周一`" :value="period.id"/></el-select>
    <el-select v-if="isManager" v-model="employeeId" clearable placeholder="全部员工" @change="applyFilters"><el-option v-for="employee in stats?.employees || []" :key="employee.employee_id" :label="`${employee.employee_no} · ${employee.employee_name}`" :value="employee.employee_id"/></el-select>
    <el-select v-if="isManager" v-model="positionId" clearable placeholder="全部岗位" @change="applyFilters"><el-option v-for="position in stats?.positions || []" :key="position.position_id" :label="position.position_name" :value="position.position_id"/></el-select>
    <el-button @click="applyFilters">刷新统计</el-button>
    <el-tag v-if="stats" effect="plain">当前版本 {{ stats.version.version_no }}</el-tag>
  </section>

  <template v-if="stats">
    <div class="metric-grid stats-metrics">
      <div class="metric-card"><span>计划工时</span><strong>{{ stats.summary.planned_hours }}</strong><small>小时</small></div>
      <div class="metric-card"><span>计划班次</span><strong>{{ stats.summary.shift_count }}</strong><small>人次班次</small></div>
      <div class="metric-card"><span>晚班次数</span><strong>{{ stats.summary.evening_count }}</strong><small>结束时间不早于22:00</small></div>
      <div class="metric-card accent"><span>偏好满足率</span><strong>{{ stats.summary.preference_rate === null ? '—' : stats.summary.preference_rate + '%' }}</strong><small>{{ stats.summary.preference_rate === null ? '未提交偏好' : `${stats.summary.preference_satisfied}/${stats.summary.preference_total}` }}</small></div>
      <div class="metric-card"><span>当前缺岗</span><strong>{{ stats.summary.open_gap_count }}</strong><small>待处理缺口</small></div>
      <div class="metric-card"><span>确认进度</span><strong>{{ stats.summary.confirmation_rate === null ? '—' : stats.summary.confirmation_rate + '%' }}</strong><small>{{ stats.summary.confirmation_confirmed }}/{{ stats.summary.confirmation_total }}</small></div>
    </div>

    <section class="panel table-panel">
      <div class="section-heading"><h2>{{ isManager ? '员工统计' : '我的计划安排' }}</h2><span class="muted">{{ stats.note }}</span></div>
      <el-table :data="stats.employees" v-loading="busy" empty-text="当前筛选没有人员安排">
        <el-table-column prop="employee_no" label="员工编号" min-width="110"/>
        <el-table-column prop="employee_name" label="姓名" min-width="110"/>
        <el-table-column prop="shift_count" label="班次数" min-width="85"/>
        <el-table-column prop="planned_hours" label="计划工时" min-width="100"><template #default="s">{{ s.row.planned_hours }} 小时</template></el-table-column>
        <el-table-column prop="evening_count" label="晚班" min-width="75"/>
        <el-table-column prop="position_count" label="岗位数" min-width="80"/>
        <el-table-column label="偏好满足" min-width="110"><template #default="s">{{ s.row.preference_rate === null ? '未提交' : `${s.row.preference_satisfied}/${s.row.preference_total}` }}</template></el-table-column>
        <el-table-column prop="open_gap_count" label="当前缺岗" min-width="95"/>
        <el-table-column v-if="isManager" prop="confirmation_status" label="确认状态" min-width="100"><template #default="s">{{ s.row.confirmation_status==='CONFIRMED'?'已确认':s.row.confirmation_status==='PENDING'?'待确认':'无需确认' }}</template></el-table-column>
      </el-table>
    </section>

    <section v-if="isManager" class="panel table-panel position-stats">
      <div class="section-heading"><h2>岗位统计</h2><span class="muted">{{ stats.summary.position_count }} 个岗位</span></div>
      <el-table :data="stats.positions"><el-table-column prop="position_name" label="岗位" min-width="140"/><el-table-column prop="employee_count" label="安排人数" min-width="100"/><el-table-column prop="shift_count" label="班次数" min-width="90"/><el-table-column label="计划工时" min-width="110"><template #default="s">{{ (s.row.planned_minutes/60).toFixed(1) }} 小时</template></el-table-column></el-table>
    </section>

    <section class="panel summary-strip"><span>当前发布版本：第 {{ stats.version.version_no }} 版</span><span>员工 {{ stats.summary.employee_count }} 人</span><span>已批准换班 {{ stats.summary.swap_count }} 次</span><span>已解决调班 {{ stats.summary.adjustment_count }} 次</span></section>
  </template>
</template>

<style scoped>
.stats-error{margin-bottom:18px}.stat-actions{display:flex;gap:8px}.stats-filter{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:22px}.stats-filter .el-select{width:190px}.stats-metrics{grid-template-columns:repeat(3,1fr);margin-bottom:22px}.position-stats{margin-top:22px}.summary-strip{display:flex;gap:24px;flex-wrap:wrap;margin-top:22px;color:#64748b;font-size:12px}
@media(max-width:900px){.stats-metrics{grid-template-columns:1fr 1fr}}@media(max-width:600px){.stats-metrics{grid-template-columns:1fr}.stats-filter>*{width:100%!important}.stat-actions{flex-wrap:wrap}}
</style>
