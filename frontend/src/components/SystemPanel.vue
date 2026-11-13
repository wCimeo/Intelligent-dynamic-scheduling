<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const emit = defineEmits<{ settingsUpdated: [] }>()
const busy = ref(false)
const error = ref('')
const settings = ref<any>(null)
const form = reactive({ store_name: '', demo_mode: false, solver_time_limit_seconds: 30 })
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 30
const category = ref('')
const actorSearch = ref('')
const dateFrom = ref('')
const dateTo = ref('')

const categories = [
  ['account','账号'],['employee','员工'],['skill','技能'],['position','岗位'],
  ['shift_template','班次模板'],['schedule_period','排班周期'],['schedule_draft','排班草稿'],
  ['assignments','人员安排'],['rule_version','排班规则'],['solver_task','求解任务'],
  ['schedule','班表发布'],['leave','请假'],['swap','换班'],['adjustment','动态调班'],
  ['publication','版本确认'],['settings','基础设置']
]

function formatTime(value: string) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'medium', timeZone: 'Asia/Shanghai' }).format(new Date(value))
}

function summaryText(summary: any) {
  if (!summary || !Object.keys(summary).length) return '—'
  return JSON.stringify(summary, null, 2)
}

async function loadSettings() {
  settings.value = await api('/settings')
  Object.assign(form, {
    store_name: settings.value.store_name,
    demo_mode: settings.value.demo_mode,
    solver_time_limit_seconds: settings.value.solver_time_limit_seconds
  })
}

async function saveSettings() {
  error.value = ''
  busy.value = true
  try {
    settings.value = await api('/settings', 'PATCH', { ...form, expected_revision: settings.value.revision })
    ElMessage.success('基础设置已保存')
    emit('settingsUpdated')
    await loadAudit()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function loadAudit() {
  const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize) })
  if (category.value) params.set('category', category.value)
  if (actorSearch.value) params.set('actor_search', actorSearch.value)
  if (dateFrom.value) params.set('date_from', dateFrom.value)
  if (dateTo.value) params.set('date_to', dateTo.value)
  const data = await api(`/audit-events?${params}`)
  rows.value = data.items
  total.value = data.total
}

async function refreshAudit() {
  error.value = ''
  busy.value = true
  page.value = 1
  try {
    await loadAudit()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  busy.value = true
  try {
    await Promise.all([loadSettings(), loadAudit()])
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
})
</script>

<template>
  <div class="page-heading">
    <div><span class="eyebrow">智能与数据 · F16</span><h1>操作记录与设置</h1><p class="muted">查看关键业务操作和版本关联，维护不影响历史事实的门店基础设置。</p></div>
    <el-tag type="success" effect="plain">管理员</el-tag>
  </div>
  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="system-error"/>

  <section v-if="settings" class="panel settings-card">
    <div class="section-heading"><h2>门店与演示设置</h2><span class="muted">时区固定为 Asia/Shanghai</span></div>
    <el-form label-position="top">
      <div class="settings-grid">
        <el-form-item label="门店名称"><el-input v-model="form.store_name" maxlength="100"/></el-form-item>
        <el-form-item label="默认求解时限（秒）"><el-input-number v-model="form.solver_time_limit_seconds" :min="1" :max="120"/></el-form-item>
        <el-form-item label="演示模式"><el-switch v-model="form.demo_mode" active-text="开启" inactive-text="关闭"/></el-form-item>
      </div>
      <p class="muted">默认求解时限用于没有显式指定时限的新任务；不会改写已完成求解任务的历史值。</p>
      <el-button type="primary" :loading="busy" @click="saveSettings">保存设置</el-button>
    </el-form>
  </section>

  <section class="panel audit-panel">
    <div class="section-heading"><h2>操作记录</h2><span class="muted">共 {{ total }} 条</span></div>
    <div class="audit-filters">
      <el-select v-model="category" clearable placeholder="全部操作类别" @change="refreshAudit"><el-option v-for="[value,label] in categories" :key="value" :label="label" :value="value"/></el-select>
      <el-input v-model="actorSearch" clearable placeholder="操作人账号或姓名" @keyup.enter="refreshAudit"/>
      <el-date-picker v-model="dateFrom" type="date" value-format="YYYY-MM-DD" placeholder="开始日期"/>
      <el-date-picker v-model="dateTo" type="date" value-format="YYYY-MM-DD" placeholder="结束日期"/>
      <el-button @click="refreshAudit">筛选</el-button>
    </div>
    <el-table :data="rows" v-loading="busy" empty-text="没有符合条件的操作记录">
      <el-table-column label="时间" min-width="180"><template #default="s">{{ formatTime(s.row.created_at) }}</template></el-table-column>
      <el-table-column label="操作人" min-width="130"><template #default="s">{{ s.row.actor_name || '系统' }}<small class="actor-account">{{ s.row.actor_username }}</small></template></el-table-column>
      <el-table-column prop="action_label" label="操作" min-width="140"/>
      <el-table-column prop="category" label="类别" min-width="100"/>
      <el-table-column label="对象" min-width="100"><template #default="s">{{ s.row.entity_id || '—' }}</template></el-table-column>
      <el-table-column label="摘要" min-width="320"><template #default="s"><el-popover v-if="Object.keys(s.row.summary || {}).length" placement="left" width="420" trigger="click"><template #reference><el-button link type="primary">查看摘要</el-button></template><pre class="audit-json">{{ summaryText(s.row.summary) }}</pre></el-popover><span v-else class="muted">—</span></template></el-table-column>
    </el-table>
    <el-pagination class="pagination" v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next" @current-change="loadAudit"/>
  </section>
</template>

<style scoped>
.system-error{margin-bottom:18px}.settings-card{margin-bottom:22px}.settings-grid{display:grid;grid-template-columns:2fr 1fr 1fr;gap:16px}.audit-filters{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}.audit-filters .el-select,.audit-filters .el-input{width:190px}.actor-account{display:block;color:#94a3b8;font-size:10px;margin-top:3px}.audit-json{white-space:pre-wrap;word-break:break-word;max-height:320px;overflow:auto;font-size:12px;background:#f8fafc;padding:12px;margin:0}
@media(max-width:900px){.settings-grid{grid-template-columns:1fr}.audit-filters>*{width:100%!important}}
</style>
